import sys
import pytest
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

# استيراد الكلاسات المراد اختبارها مباشرة
from optimization.services import OSRMService, VRPSolver
from optimization.models import Scenario, Municipality, Vehicle, Bin
from accounts.serializers import LoginSerializer, RequestInitialSetupOTPSerializer

User = get_user_model()

@pytest.mark.django_db
class TestFinalGapCloser:
    def setup_method(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(email="super_gap@test.com", password="StrongPass1!")
        self.planner = User.objects.create_user(email="planner_gap@test.com", password="StrongPass1!", role=User.Roles.PLANNER, is_active=True)

    # --- 1. تغطية حالات ImportError في AdminStatsView ---
    def test_admin_stats_import_errors(self):
        """
        يقوم هذا الاختبار بإخفاء موديول optimization.models مؤقتاً
        لمحاكاة فشل الاستيراد واختبار بلوك except ImportError
        """
        self.client.force_authenticate(user=self.admin)
        url = reverse('admin-stats')
        
        # نخفي الموديول عن النظام
        with patch.dict(sys.modules, {'optimization.models': None}):
            resp = self.client.get(url)
            assert resp.status_code == 200
            # يجب أن تعود القيم أصفاراً لأن الاستيراد فشل
            assert resp.data['vehicles_total'] == 0
            assert resp.data['bins_active'] == 0

    # --- 2. تغطية حالات التحقق في Serializers ---
    def test_login_serializer_user_does_not_exist(self):
        """اختبار محاولة الدخول بمستخدم غير موجود (يغطي User.DoesNotExist)"""
        data = {'email': 'ghost@test.com', 'password': 'pw'}
        ser = LoginSerializer(data=data)
        with pytest.raises(DRFValidationError) as exc:
            ser.is_valid(raise_exception=True)
        assert "Unable to log in" in str(exc.value)

    def test_initial_setup_serializer_edge_cases(self):
        """اختبار حالات الحافة في RequestInitialSetupOTPSerializer"""
        # حالة 1: المستخدم غير موجود
        data = {'email': 'ghost@test.com'}
        ser = RequestInitialSetupOTPSerializer(data=data)
        with pytest.raises(DRFValidationError) as exc:
            ser.is_valid(raise_exception=True)
        assert "does not exist" in str(exc.value)

        # حالة 2: المستخدم موجود لكنه لا يحتاج إعداد (لديه كلمة مرور)
        u = User.objects.create_user(email="ready@test.com", password="StrongPass1!")
        data = {'email': u.email}
        ser = RequestInitialSetupOTPSerializer(data=data)
        with pytest.raises(DRFValidationError) as exc:
            ser.is_valid(raise_exception=True)
        assert "does not require initial setup" in str(exc.value)

    # --- 3. تغطية خطأ TokenError في Logout ---
    def test_logout_token_error(self):
        """محاكاة توكن فاسد أثناء تسجيل الخروج"""
        self.client.force_authenticate(user=self.admin)
        self.client.cookies['refresh'] = 'invalid_token'
        
        # نجبر RefreshToken على رمي خطأ عند محاولة قراءة التوكن
        with patch('accounts.views.RefreshToken', side_effect=TokenError("Bad token")):
            url = reverse('auth-logout')
            resp = self.client.post(url)
            assert resp.status_code == 204  # يجب أن يتجاهل الخطأ ويكمل الخروج

    # --- 4. تغطية خطأ التاريخ في VehicleViewSet ---
    def test_vehicle_viewset_bad_date(self):
        """إرسال تاريخ خاطئ للفلتر لاختبار الـ fallback"""
        self.client.force_authenticate(user=self.planner)
        url = reverse('vehicle-list')
        # نرسل نصاً بدلاً من تاريخ، مما يفعل except ValueError
        resp = self.client.get(url, {'collection_date': 'invalid-date-format'})
        assert resp.status_code == 200

    # --- 5. تغطية أخطاء OSRMService ---
    def test_osrm_service_missing_key(self):
        """محاكاة استجابة من الخرائط لا تحتوي على مفتاح distances"""
        locations = [(33.5, 36.2), (33.6, 36.3)]
        fake_response = MagicMock()
        fake_response.json.return_value = {} # استجابة فارغة
        fake_response.status_code = 200
        
        with patch('requests.get', return_value=fake_response):
            with pytest.raises(DjangoValidationError) as exc:
                OSRMService.get_distance_matrix(locations)
            assert "استجابة غير صالحة" in str(exc.value)

    # --- 6. تغطية شروط VRPSolver ---
    def test_vrp_solver_requirements(self):
        """اختبار تشغيل الحل على سيناريو بدون حاويات"""
        mun = Municipality.objects.create(name="SolverMun")
        veh = Vehicle.objects.create(name="V", capacity=5, start_latitude=33.5, start_longitude=36.2, municipality=mun)
        # سيناريو بدون حاويات
        sc_no_bins = Scenario.objects.create(name="NoBins", municipality=mun, collection_date="2025-01-01", vehicle=veh)
        
        solver = VRPSolver(sc_no_bins.id)
        with pytest.raises(DjangoValidationError) as exc:
            solver.run()
        assert "حاوية واحدة نشطة على الأقل" in str(exc.value)

    def test_vrp_solver_scenario_not_found(self):
        """اختبار طلب حل لسيناريو غير موجود"""
        solver = VRPSolver(99999)
        from django.core.exceptions import ObjectDoesNotExist
        with pytest.raises(ObjectDoesNotExist):
            solver.run()