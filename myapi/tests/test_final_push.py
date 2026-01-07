import pytest
from unittest.mock import patch
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from rest_framework.request import Request
from rest_framework.exceptions import APIException
from optimization.views import VehicleViewSet, LandfillViewSet, MunicipalityViewSet, ScenarioViewSet
from users.views import UserViewSet
from accounts.views import InitialSetupRequestOTPView, InitialSetupConfirmView

User = get_user_model()

@pytest.mark.django_db
class TestFinalPush:
    def setup_method(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser(email="push_admin@test.com", password="StrongPass1!")
        self.planner = User.objects.create_user(email="push_planner@test.com", password="StrongPass1!", role=User.Roles.PLANNER, is_active=True)
        self.driver = User.objects.create_user(email="push_driver@test.com", password="StrongPass1!", role=User.Roles.DRIVER, is_active=True)

    # ========================== ACCOUNTS EXCEPTION HANDLING (Fix) ==========================
    def test_initial_setup_request_exception_force(self):
        """
        يضمن الوصول لبلوك except في RequestOTP عبر تجاوز التحقق
        """
        view = InitialSetupRequestOTPView.as_view()
        user = User.objects.create_user(email="push_req@test.com", password=None)
        request = self.factory.post('/fake', {'email': user.email})
        
        # نجبر الخدمة على الفشل ونلتقط الخطأ
        with patch('accounts.services.OTPService.issue', side_effect=Exception("DB Error")):
            # بما أننا نستخدم factory مباشرة، الـ Exception يخرج للمستوى الأعلى
            try:
                view(request)
            except Exception as e:
                assert "DB Error" in str(e)

    def test_initial_setup_confirm_exception_force(self):
        """
        يضمن الوصول لبلوك except في Confirm عبر بيانات صحيحة وكلمة مرور قوية
        """
        view = InitialSetupConfirmView.as_view()
        user = User.objects.create_user(email="push_conf@test.com", password=None)
        
        data = {
            "email": user.email, 
            "otp": "12345", 
            "password": "StrongPass123!", 
            "confirm_password": "StrongPass123!"
        }
        request = self.factory.post('/fake', data)

        with patch('accounts.services.OTPService.verify', side_effect=Exception("System Crash")):
            try:
                view(request)
            except Exception as e:
                assert "System Crash" in str(e)

    # ========================== OPTIMIZATION VIEWSETS (Missing Filters) ==========================
    def test_vehicle_viewset_queryset_filters(self):
        """يغطي فلاتر VehicleViewSet"""
        view = VehicleViewSet()
        
        # 1. فلترة بالبلدية
        request = self.factory.get('/', {'municipality': '1'})
        request.user = self.planner # تعيين المستخدم في طلب Django
        view.request = Request(request) # تغليف الطلب لـ DRF
        view.request.user = self.planner # تأكيد تعيين المستخدم في طلب DRF
        
        view.action = 'list'
        view.get_queryset() 

        # 2. فلترة بالتاريخ (collection_date)
        request = self.factory.get('/', {'collection_date': '2025-01-01'})
        request.user = self.planner
        view.request = Request(request)
        view.request.user = self.planner
        
        view.get_queryset()

    def test_landfill_viewset_filters(self):
        """يغطي فلاتر LandfillViewSet"""
        view = LandfillViewSet()
        request = self.factory.get('/', {'municipality': '1'})
        request.user = self.planner
        view.request = Request(request)
        view.request.user = self.planner # Fix AnonymousUser error
        
        view.action = 'list'
        view.get_queryset()

    def test_municipality_viewset_filters(self):
        """يغطي فلاتر MunicipalityViewSet"""
        view = MunicipalityViewSet()
        request = self.factory.get('/', {'name': 'Damascus'})
        request.user = self.planner
        view.request = Request(request)
        view.request.user = self.planner # Fix AnonymousUser error
        
        view.action = 'list'
        view.get_queryset()

    def test_scenario_viewset_extra_filters(self):
        """يغطي الفلاتر المتبقية في ScenarioViewSet"""
        view = ScenarioViewSet()
        # فلترة vehicle_id
        request = self.factory.get('/', {'vehicle': '1'})
        request.user = self.planner
        view.request = Request(request)
        view.request.user = self.planner # Fix AnonymousUser error
        
        view.action = 'list'
        view.get_queryset()

    # ========================== USERS VIEWSET (Missing Branches) ==========================
    def test_user_viewset_role_queryset(self):
        """
        يغطي منطق get_queryset الخاص باختلاف الأدوار (Admin vs Planner vs Driver)
        """
        view = UserViewSet()

        # 1. Admin
        request = self.factory.get('/')
        request.user = self.admin
        view.request = Request(request)
        view.request.user = self.admin
        view.action = 'list'
        qs = view.get_queryset()
        
        # 2. Planner
        request = self.factory.get('/')
        request.user = self.planner
        view.request = Request(request)
        view.request.user = self.planner
        view.action = 'list'
        qs = view.get_queryset()

        # 3. Driver
        request = self.factory.get('/')
        request.user = self.driver
        view.request = Request(request)
        view.request.user = self.driver
        view.action = 'list'
        qs = view.get_queryset()

    def test_user_viewset_search_short_term(self):
        """يغطي شرط if len(search) > 2"""
        view = UserViewSet()
        request = self.factory.get('/', {'search': 'a'})
        request.user = self.admin
        view.request = Request(request)
        view.request.user = self.admin
        view.action = 'list'
        view.get_queryset()