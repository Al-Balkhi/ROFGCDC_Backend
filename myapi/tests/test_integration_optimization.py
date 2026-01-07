import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model
from optimization.models import Municipality, Vehicle, Bin, Scenario
from django.utils import timezone

User = get_user_model()

@pytest.mark.django_db
class TestOptimizationIntegration:
    def setup_method(self):
        self.client = APIClient()
        self.planner = User.objects.create_user(email="planner@test.com", password="pw", role=User.Roles.PLANNER, is_active=True)
        self.client.force_authenticate(user=self.planner)
        
        # Setup Basic Data
        self.mun = Municipality.objects.create(name="Damascus HQ", hq_latitude=33.5, hq_longitude=36.3)
        self.vehicle = Vehicle.objects.create(name="Truck 1", capacity=10, start_latitude=33.51, start_longitude=36.29, municipality=self.mun)
        self.bin = Bin.objects.create(name="Bin 1", latitude=33.52, longitude=36.31, capacity=5, municipality=self.mun)

    def test_create_scenario(self):
        url = reverse('scenario-list')
        data = {
            "name": "Test Plan",
            "municipality_id": self.mun.id,
            "vehicle_id": self.vehicle.id,
            "bin_ids": [self.bin.id],
            "collection_date": str(timezone.localdate())
        }
        response = self.client.post(url, data, format='json')
        assert response.status_code == 201
        assert Scenario.objects.count() == 1

    def test_solve_scenario(self):
        # Create scenario first
        scenario = Scenario.objects.create(
            name="Solve Me", 
            municipality=self.mun, 
            vehicle=self.vehicle, 
            collection_date=timezone.localdate(),
            created_by=self.planner
        )
        scenario.bins.add(self.bin)

        # Mock OSRM call to avoid external request during test (Optional but recommended)
        # If you don't mock, ensure OSRM is running or expect failure
        
        url = reverse('scenario-solve', args=[scenario.id])
        # Note: This might fail if OSRM is not reachable in test environment
        # You might need to mock 'optimization.services.VRPSolver.run'