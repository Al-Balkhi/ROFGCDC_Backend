import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from optimization.models import Municipality, Vehicle, Bin, Scenario
from unittest.mock import patch
from django.core.exceptions import ValidationError

User = get_user_model()

@pytest.mark.django_db
class TestOptimizationAdvanced:
    def setup_method(self):
        self.client = APIClient()
        self.planner = User.objects.create_user(email="planner1@test.com", password="pw", role=User.Roles.PLANNER, is_active=True)
        self.planner2 = User.objects.create_user(email="planner2@test.com", password="pw", role=User.Roles.PLANNER, is_active=True)
        self.admin = User.objects.create_superuser(email="admin@test.com", password="pw")
        
        self.mun = Municipality.objects.create(name="M1", hq_latitude=33.51, hq_longitude=36.29)
        self.vehicle = Vehicle.objects.create(name="V1", capacity=100, start_latitude=33.51, start_longitude=36.29, municipality=self.mun)
        self.bin = Bin.objects.create(name="B1", latitude=33.52, longitude=36.30, capacity=10, municipality=self.mun, is_active=True)

    def test_scenario_creation_past_date(self):
        """Test creating scenario in the past"""
        self.client.force_authenticate(user=self.planner)
        url = reverse('scenario-list')
        past_date = timezone.localdate() - timedelta(days=1)
        data = {
            "name": "Past Plan",
            "municipality_id": self.mun.id,
            "vehicle_id": self.vehicle.id,
            "bin_ids": [self.bin.id],
            "collection_date": str(past_date)
        }
        response = self.client.post(url, data, format='json')
        assert response.status_code == 400
        assert "collection_date" in response.data

    def test_scenario_update_clears_solutions(self):
        """Test that updating bins/vehicle deletes existing solutions"""
        self.client.force_authenticate(user=self.planner)
        scenario = Scenario.objects.create(
            name="Original", municipality=self.mun, vehicle=self.vehicle, 
            collection_date=timezone.localdate() + timedelta(days=1),
            created_by=self.planner
        )
        scenario.bins.add(self.bin)
        # Create a dummy solution
        scenario.solutions.create(total_distance=10, data={})

        url = reverse('scenario-detail', args=[scenario.id])
        # Update vehicle
        v2 = Vehicle.objects.create(name="V2", capacity=50, start_latitude=33.5, start_longitude=36.3, municipality=self.mun)
        data = {
            "vehicle_id": v2.id,
            "bin_ids": [self.bin.id] # keep bins same
        }
        response = self.client.patch(url, data, format='json')
        assert response.status_code == 200
        assert scenario.solutions.count() == 0  # Should be deleted

    def test_solve_permission_denied(self):
        """Planner 2 cannot solve Planner 1's scenario"""
        self.client.force_authenticate(user=self.planner2)
        scenario = Scenario.objects.create(
            name="P1 Plan", municipality=self.mun, vehicle=self.vehicle, 
            collection_date=timezone.localdate(), created_by=self.planner
        )
        url = reverse('scenario-solve', args=[scenario.id])
        response = self.client.post(url)
        assert response.status_code == 403

    @patch('optimization.views.VRPSolver')
    def test_solve_validation_error(self, mock_solver_cls):
        """Test solver raising ValidationError (e.g. no solution found)"""
        self.client.force_authenticate(user=self.planner)
        scenario = Scenario.objects.create(
            name="Fail Plan", municipality=self.mun, vehicle=self.vehicle, 
            collection_date=timezone.localdate(), created_by=self.planner
        )
        
        # Mock the instance.run() method to raise ValidationError
        mock_instance = mock_solver_cls.return_value
        mock_instance.run.side_effect = ValidationError("No solution found")

        url = reverse('scenario-solve', args=[scenario.id])
        response = self.client.post(url)
        assert response.status_code == 400
        assert "No solution found" in str(response.data)

    @patch('optimization.views.VRPSolver')
    def test_solve_unexpected_error(self, mock_solver_cls):
        """Test solver raising generic Exception"""
        self.client.force_authenticate(user=self.planner)
        scenario = Scenario.objects.create(
            name="Crash Plan", municipality=self.mun, vehicle=self.vehicle, 
            collection_date=timezone.localdate(), created_by=self.planner
        )
        
        mock_instance = mock_solver_cls.return_value
        mock_instance.run.side_effect = Exception("Boom")

        url = reverse('scenario-solve', args=[scenario.id])
        response = self.client.post(url)
        assert response.status_code == 500

    def test_vehicle_list_filtering(self):
        """Test that vehicle list excludes busy vehicles for Planners"""
        self.client.force_authenticate(user=self.planner)
        today = timezone.localdate()
        
        # Scenario using V1 today
        s = Scenario.objects.create(
            municipality=self.mun, vehicle=self.vehicle, 
            collection_date=today, created_by=self.planner
        )
        s.bins.add(self.bin)

        url = reverse('vehicle-list')
        # Filter for today
        response = self.client.get(url, {'collection_date': str(today)})
        ids = [v['id'] for v in response.data['results']]
        assert self.vehicle.id not in ids # Should be excluded

        # Filter for tomorrow (should show up)
        response = self.client.get(url, {'collection_date': str(today + timedelta(days=1))})
        ids = [v['id'] for v in response.data['results']]
        assert self.vehicle.id in ids

    def test_scenario_list_filtering(self):
        """Test filtering scenarios by archive status"""
        self.client.force_authenticate(user=self.planner)
        today = timezone.localdate()
        past = today - timedelta(days=5)
        
        s_future = Scenario.objects.create(municipality=self.mun, vehicle=self.vehicle, collection_date=today, created_by=self.planner)
        s_past = Scenario.objects.create(municipality=self.mun, vehicle=self.vehicle, collection_date=past, created_by=self.planner) # Archived

        url = reverse('scenario-list')
        
        # is_archived = false (Future/Today only)
        response = self.client.get(url, {'is_archived': 'false'})
        ids = [s['id'] for s in response.data['results']]
        assert s_future.id in ids
        assert s_past.id not in ids

        # is_archived = true (Past only)
        response = self.client.get(url, {'is_archived': 'true'})
        ids = [s['id'] for s in response.data['results']]
        assert s_past.id in ids
        assert s_future.id not in ids

    def test_route_solution_list_ranges(self):
        """Test filtering solutions by date range"""
        self.client.force_authenticate(user=self.planner)
        today = timezone.localdate()
        
        scenario = Scenario.objects.create(
            municipality=self.mun, vehicle=self.vehicle, 
            collection_date=today, created_by=self.planner
        )
        scenario.solutions.create(total_distance=10, data={})

        url = reverse('solution-list')
        
        # Test 'today' range
        response = self.client.get(url, {'range': 'today'})
        assert len(response.data) == 1
        
        # Test 'month' range
        response = self.client.get(url, {'range': 'month'})
        assert len(response.data) == 1