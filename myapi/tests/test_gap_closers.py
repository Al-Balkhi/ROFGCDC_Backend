import pytest
from django.test import RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from unittest.mock import patch
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient
from django.urls import reverse
from datetime import timedelta
from django.utils import timezone

# استيراد ملفات المشروع
from accounts.admin import UserCreationNoPasswordForm, UserAdmin
from accounts.models import UserManager, OneTimePassword
from accounts.services import OTPService, EmailService
from optimization.admin import ScenarioAdmin, RouteSolutionAdmin
from optimization.models import Scenario, RouteSolution, Municipality, Vehicle, Bin, Landfill
from optimization.serializers import MunicipalitySerializer

User = get_user_model()

@pytest.mark.django_db
class TestGapClosers:
    def setup_method(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.client = APIClient()
        self.admin = User.objects.create_superuser(email="admin_gap@test.com", password="pw")

    # ========================== ACCOUNTS ADMIN ==========================
    def test_accounts_admin_form(self):
        """يغطي UserCreationNoPasswordForm في accounts/admin.py"""
        form_data = {
            'email': 'admin_test@example.com',
            'username': 'admintest',
            'role': 'driver',
        }
        form = UserCreationNoPasswordForm(data=form_data)
        assert form.is_valid()
        
        # اختبار save() الذي ينشئ مستخدم بدون كلمة مرور
        user = form.save(commit=True)
        assert user.email == 'admin_test@example.com'
        assert user.has_usable_password() is False
        
        # اختبار save_m2m
        form.save_m2m()

    # ========================== ACCOUNTS SERVICES ==========================
    def test_otp_service_mark_used_logic(self):
        """يغطي السطر الذي يقوم بوضع علامة used على OTP القديم إذا لم تنته صلاحيته"""
        user = User.objects.create_user(email="otp_gap@test.com", password="pw")
        
        # 1. إصدار OTP أول
        OTPService.issue(user, OneTimePassword.Purpose.INITIAL_SETUP)
        otp1 = OneTimePassword.objects.first()
        
        # 2. التلاعب بالوقت لتجاوز الـ Cooldown (دقيقة) ولكن قبل الانتهاء (5 دقائق)
        # نحتاج لمحاكاة مرور دقيقتين
        future = timezone.now() + timedelta(minutes=2)
        with patch('django.utils.timezone.now', return_value=future):
            # إصدار OTP ثاني
            OTPService.issue(user, OneTimePassword.Purpose.INITIAL_SETUP)
            
        otp1.refresh_from_db()
        assert otp1.is_used is True  # هذا يغطي السطر latest.mark_used()

    @patch('accounts.services.send_mail')
    def test_email_service_fallback_and_error(self, mock_send_mail):
        """يغطي حالات فشل الإيميل والحالات الافتراضية"""
        
        EmailService.send_otp_email("test@test.com", "12345", "UNKNOWN_PURPOSE")
        
        _, kwargs = mock_send_mail.call_args
        assert "Your verification code" in kwargs['subject']

        mock_send_mail.side_effect = Exception("SMTP Error")
        with pytest.raises(Exception):
            EmailService.send_otp_email("test@test.com", "12345", "INITIAL_SETUP")

    # ========================== OPTIMIZATION ADMIN ==========================
    def test_optimization_admin_querysets(self):
        """يغطي دوال get_queryset في optimization/admin.py"""
        mun = Municipality.objects.create(name="AdminMun")
        veh = Vehicle.objects.create(name="AdminVeh", capacity=5, start_latitude=33.5, start_longitude=36.2, municipality=mun)
        sc = Scenario.objects.create(name="AdminSc", municipality=mun, vehicle=veh, collection_date="2025-01-01", created_by=None)
        RouteSolution.objects.create(scenario=sc, total_distance=10, data={})

        request = self.factory.get('/')
        
        # ScenarioAdmin
        sc_admin = ScenarioAdmin(Scenario, self.site)
        assert sc_admin.get_queryset(request).count() == 1

        # RouteSolutionAdmin
        rs_admin = RouteSolutionAdmin(RouteSolution, self.site)
        assert rs_admin.get_queryset(request).count() == 1

    # ========================== MODELS __str__ ==========================
    def test_models_str_methods(self):
        """يغطي دوال الطباعة للموديلات"""
        mun = Municipality.objects.create(name="StrMun")
        assert str(mun) == "StrMun"
        
        landfill = Landfill.objects.create(name="StrLand", latitude=33.5, longitude=36.2)
        assert str(landfill) == "StrLand Landfill"
        
        bin_obj = Bin.objects.create(name="StrBin", latitude=33.5, longitude=36.2, capacity=5)
        assert str(bin_obj).startswith("StrBin")
        
        veh = Vehicle.objects.create(name="StrVeh", capacity=5, start_latitude=33.5, start_longitude=36.2)
        assert "Capacity: 5" in str(veh)
        
        # Scenario with unknown creator
        sc = Scenario.objects.create(name="StrSc", municipality=mun, vehicle=veh, collection_date="2025-01-01")
        assert "Unknown" in str(sc)

    # ========================== SERIALIZERS VALIDATION ==========================
    def test_damascus_coordinates_validation(self):
        """يغطي Mixin التحقق من الإحداثيات في optimization/serializers.py"""
        # محاولة إنشاء بلدية بإحداثيات خارج دمشق
        data = {
            "name": "BadMun",
            "hq_latitude": 40.0, # خارج الحدود
            "hq_longitude": 36.2
        }
        serializer = MunicipalitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'hq_latitude' in serializer.errors
        assert 'خارج حدود مدينة دمشق' in str(serializer.errors['hq_latitude'][0])

    # ========================== ACCOUNTS VIEWS EXCEPTIONS ==========================
    def test_logout_and_refresh_token_errors(self):
        """يغطي حالات التوكن الفاسد في Logout و Refresh"""
        self.client.force_authenticate(user=self.admin)
        
        # Logout with bad token
        self.client.cookies['refresh'] = 'bad_token'
        url_logout = reverse('auth-logout')
        resp = self.client.post(url_logout)
        assert resp.status_code == 204 # Should handle gracefully
        
        # Refresh with bad token
        url_refresh = reverse('auth-refresh')
        resp = self.client.post(url_refresh)
        assert resp.status_code == 401

    # ========================== USERS VIEWS ACTIONS ==========================
    def test_users_archive_restore_methods(self):
        """يغطي دوال archive و restore في UserViewSet بشكل مباشر"""
        self.client.force_authenticate(user=self.admin)
        user = User.objects.create_user(email="target@test.com", password="pw")
        
        # Archive
        url_archive = reverse('user-archive', args=[user.id])
        self.client.patch(url_archive)
        user.refresh_from_db()
        assert user.is_archived is True
        assert user.is_active is False
        
        # Restore
        url_restore = reverse('user-restore', args=[user.id])
        self.client.patch(url_restore)
        user.refresh_from_db()
        assert user.is_archived is False
        assert user.is_active is True