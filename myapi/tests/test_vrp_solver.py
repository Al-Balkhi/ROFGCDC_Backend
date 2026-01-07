import pytest

from optimization.models import Municipality, Vehicle, Bin, Scenario, RouteSolution
from optimization.services import VRPSolver, OSRMService, solve_vrp


@pytest.mark.django_db
def test_vrp_solver_creates_solution(monkeypatch):
    # Create municipality, vehicle, bins, scenario
    m = Municipality.objects.create(name="M1")
    vehicle = Vehicle.objects.create(name="V1", capacity=10, start_latitude=33.45, start_longitude=36.2, municipality=m)
    b1 = Bin.objects.create(name="B1", latitude=33.451, longitude=36.201, capacity=10, municipality=m)
    b2 = Bin.objects.create(name="B2", latitude=33.452, longitude=36.202, capacity=10, municipality=m)
    scenario = Scenario.objects.create(name="S1", municipality=m, collection_date="2025-01-01", vehicle=vehicle)
    scenario.bins.set([b1, b2])

    # Provide deterministic distance matrix for depot + 2 bins
    # distances in meters
    fake_matrix = [
        [0, 1000, 2000],
        [1000, 0, 1500],
        [2000, 1500, 0],
    ]

    monkeypatch.setattr(OSRMService, "get_distance_matrix", classmethod(lambda cls, locs: fake_matrix))

    result = solve_vrp(scenario.id)
    assert "total_distance" in result
    assert "routes" in result
    assert RouteSolution.objects.filter(scenario=scenario).exists()
