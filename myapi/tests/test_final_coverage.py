import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from optimization.models import Municipality, Bin, Vehicle, Landfill, Scenario

User = get_user_model()

@pytest.mark.django_db
class TestFinalCoverage:
    def setup_method(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(email="admin_cov@test.com", password="pw")
        self.planner = User.objects.create_user(email="planner_cov@test.com", password="pw", role=User.Roles.PLANNER, is_active=True)
        self.driver = User.objects.create_user(email="driver_cov@test.com", password="pw", role=User.Roles.DRIVER, is_active=True)

    # ========================== ACCOUNTS COVERAGE ==========================

    def test_initial_setup_confirm_failures(self):
        """Covers failure branches in InitialSetupConfirmView"""
        url = reverse('auth-initial-setup-confirm')
        
        resp = self.client.post(url, {
            "email": "fake@test.com", 
            "otp": "12345", 
            "password": "StrongPass123!", 
            "confirm_password": "StrongPass123!"
        })
        assert resp.status_code == 404 

        # Password mismatch
        user = User.objects.create_user(email="mismatch@test.com", password=None)
        resp = self.client.post(url, {
            "email": user.email, "otp": "00000", 
            "password": "Pass1", "confirm_password": "Pass2"
        })
        assert resp.status_code == 400
        
        user.refresh_from_db()
        assert user.is_active is True
        assert user.has_usable_password() is True

    def test_initial_setup_confirm_failures(self):
        """Covers failure branches in InitialSetupConfirmView"""
        url = reverse('auth-initial-setup-confirm')
        
        # User not found
        resp = self.client.post(url, {"email": "fake@test.com", "otp": "12345", "password": "StrongPass123!", "confirm_password": "StrongPass123!"})
        assert resp.status_code == 404

        # Password mismatch
        user = User.objects.create_user(email="mismatch@test.com", password=None)
        resp = self.client.post(url, {
            "email": user.email, "otp": "00000", 
            "password": "Pass1", "confirm_password": "Pass2"
        })
        assert resp.status_code == 400

    # ========================== USERS VIEWSET FILTERS ==========================

    def test_users_filtering_options(self):
        """
        Covers filter branches in UserViewSet.get_queryset (role, is_active)
        """
        self.client.force_authenticate(user=self.admin)
        url = reverse('user-list')

        # Filter by role
        resp = self.client.get(url, {'role': 'driver'})
        assert resp.status_code == 200
        # Should find self.driver but not self.planner
        ids = [u['id'] for u in resp.data['results']]
        assert self.driver.id in ids
        assert self.planner.id not in ids

        # Filter by is_active boolean (true/false strings)
        User.objects.create_user(email="lazy@test.com", password="pw", is_active=False)
        resp = self.client.get(url, {'is_active': 'false'})
        assert len(resp.data['results']) >= 1

    def test_users_restore_action_filters(self):
        """Covers the specific filtering logic inside 'restore' action"""
        self.client.force_authenticate(user=self.admin)
        archived_user = User.objects.create_user(email="old@test.com", password="pw", is_archived=True, is_active=False)
        
        # We access the viewset method manually or via action url if routed?
        # Since restore is detail=True, we usually call it on ID.
        # But the code has get_queryset logic for restore action specifically?
        # Let's try to trigger get_queryset context by calling the detail endpoint
        
        url = reverse('user-restore', args=[archived_user.id])
        # Just calling this triggers get_queryset with action='restore'
        resp = self.client.patch(url) 
        assert resp.status_code == 200

    # ========================== OPTIMIZATION VIEWSETS ==========================

    def test_optimization_viewsets_filtering_and_permissions(self):
        """
        Covers get_queryset and get_permissions for Bin, Landfill, Municipality
        """
        self.client.force_authenticate(user=self.planner) # Planner hits specific permission branch
        
        mun = Municipality.objects.create(name="MunTest", hq_latitude=33.5, hq_longitude=36.3)
        bin_obj = Bin.objects.create(name="BinTest", latitude=33.51, longitude=36.31, capacity=5, municipality=mun)
        landfill = Landfill.objects.create(name="LandfillTest", latitude=33.55, longitude=36.35)
        landfill.municipalities.add(mun)

        # 1. Test Bin Filtering by Municipality
        url_bin = reverse('bin-list')
        resp = self.client.get(url_bin, {'municipality': mun.id})
        assert resp.status_code == 200
        assert len(resp.data['results']) == 1

        # 2. Test Landfill Filtering by Municipality
        url_landfill = reverse('landfill-list')
        resp = self.client.get(url_landfill, {'municipality': mun.id})
        assert resp.status_code == 200
        assert len(resp.data['results']) == 1

        # 3. Test Municipality Filtering by ID
        url_mun = reverse('municipality-list')
        resp = self.client.get(url_mun, {'municipality': mun.id})
        assert resp.status_code == 200
        assert len(resp.data['results']) == 1

    def test_available_bins_logic(self):
        """Covers AvailableBinList logic with exclusion"""
        self.client.force_authenticate(user=self.planner)
        mun = Municipality.objects.create(name="MunAvail", hq_latitude=33.5, hq_longitude=36.3)
        
        b1 = Bin.objects.create(name="Free", latitude=33.51, longitude=36.31, capacity=5, municipality=mun)
        b2 = Bin.objects.create(name="Busy", latitude=33.52, longitude=36.32, capacity=5, municipality=mun)
        
        # Make b2 busy in a scenario
        v = Vehicle.objects.create(name="V_Avail", capacity=10, start_latitude=33.5, start_longitude=36.3, municipality=mun)
        s = Scenario.objects.create(
            municipality=mun, vehicle=v, collection_date=timezone.localdate(), created_by=self.planner
        )
        s.bins.add(b2)

        url = reverse('available-bins')
        
        # Should see b1, but NOT b2
        resp = self.client.get(url, {'municipality': mun.id})
        ids = [b['id'] for b in resp.data]
        assert b1.id in ids
        assert b2.id not in ids

        # Test excluding current scenario (edit mode logic)
        resp2 = self.client.get(url, {'municipality': mun.id, 'scenario_id': s.id})
        ids2 = [b['id'] for b in resp2.data]
        # Now b2 should be available because we are editing ITS scenario
        assert b2.id in ids2

    def test_planner_stats_view(self):
        """Covers PlannerStatsView"""
        self.client.force_authenticate(user=self.planner)
        mun = Municipality.objects.create(name="MunStats")
        v = Vehicle.objects.create(name="V_Stats", capacity=10, start_latitude=33.5, start_longitude=36.3, municipality=mun)
        
        # Create a scenario today
        Scenario.objects.create(municipality=mun, vehicle=v, collection_date=timezone.localdate(), created_by=self.planner)
        
        url = reverse('planner-stats')
        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.data['plans_today'] == 1
        assert resp.data['total_plans'] >= 1