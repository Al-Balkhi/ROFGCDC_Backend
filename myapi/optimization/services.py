from typing import List, Tuple, Dict, Any
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import requests 

from django.core.exceptions import ObjectDoesNotExist
from .models import Scenario, RouteSolution


def build_distance_matrix(locations: List[Tuple[float, float]]) -> List[List[int]]:
    num_locations = len(locations)
    if num_locations == 0:
        return []

    coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
    osrm_url = f"http://localhost:5000/table/v1/driving/{coordinates}"
    params = {"annotations": "distance"}

    try:
        response = requests.get(osrm_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        raise requests.exceptions.RequestException(
            f"OSRM request failed: {str(e)}"
        ) from e

    if "distances" not in data:
        raise ValueError("OSRM response missing 'distances' field")

    osrm_distances = data["distances"]

    if len(osrm_distances) != num_locations:
        raise ValueError(
            f"OSRM returned {len(osrm_distances)} rows, expected {num_locations}"
        )

    distance_matrix = []
    for i in range(num_locations):
        if len(osrm_distances[i]) != num_locations:
            raise ValueError(
                f"OSRM row {i} has {len(osrm_distances[i])} columns, expected {num_locations}"
            )
        row = [int(round(dist)) for dist in osrm_distances[i]]
        distance_matrix.append(row)

    return distance_matrix


def solve_vrp(scenario_id: int) -> Dict[str, Any]:
    try:
        scenario = Scenario.objects.select_related(
            'created_by',
            'vehicle',
        ).prefetch_related(
            'bins'
        ).get(pk=scenario_id)
    except Scenario.DoesNotExist:
        raise ObjectDoesNotExist(f"Scenario with id {scenario_id} does not exist")

    bins = list(scenario.bins.filter(is_active=True))
    vehicle = scenario.vehicle

    if not bins:
        raise ValueError("Scenario must have at least one active bin")
    if not vehicle:
        raise ValueError("Scenario must have at least one vehicle")

    # ===================== تحديد نقطة البداية (التعديل هنا) =====================

    if scenario.start_latitude is not None and scenario.start_longitude is not None:
        depot_location = (
            scenario.start_latitude,
            scenario.start_longitude
        )
    elif (
        vehicle.start_latitude is not None
        and vehicle.start_longitude is not None
    ):
        depot_location = (
            vehicle.start_latitude,
            vehicle.start_longitude
        )
    else:
        raise ValueError("No valid start location found (scenario or vehicle)")

    # ============================================================================

    locations = [depot_location]

    bin_locations = [(bin.latitude, bin.longitude) for bin in bins]
    locations.extend(bin_locations)

    distance_matrix = build_distance_matrix(locations)

    num_vehicles = 1
    depot = 0

    manager = pywrapcp.RoutingIndexManager(
        len(locations), num_vehicles, depot
    )
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    def demand_callback(from_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        if from_node == 0:
            return 0
        return 1

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)

    routing.AddDimension(
        demand_callback_index,
        0,
        vehicle.capacity,
        True,
        'Capacity'
    )

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = 30

    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        raise ValueError("No solution found for the given scenario")

    total_distance = 0
    routes = []

    for vehicle_id in range(num_vehicles):
        index = routing.Start(vehicle_id)
        route_stops = []
        route_distance = 0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != depot:
                bin_index = node - 1
                if 0 <= bin_index < len(bins):
                    route_stops.append(bins[bin_index].id)

            previous_index = index
            index = solution.Value(routing.NextVar(index))
            route_distance += routing.GetArcCostForVehicle(
                previous_index, index, vehicle_id
            )

        total_distance += route_distance

        if route_stops:
            routes.append({
                'vehicle': vehicle.name,
                'vehicle_id': vehicle.id,
                'stops': route_stops
            })

    total_distance_km = total_distance / 1000.0

    result = {
        'total_distance': total_distance_km,
        'routes': routes
    }

    solution_obj = RouteSolution.objects.create(
        scenario=scenario,
        total_distance=total_distance_km,
        data=result
    )

    result['solution_id'] = solution_obj.id
    return result
