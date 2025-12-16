from typing import List, Tuple, Dict, Any
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import requests 

from django.core.exceptions import ObjectDoesNotExist
from .models import Scenario, RouteSolution


def build_distance_matrix(locations: List[Tuple[float, float]]) -> List[List[int]]:
    """
    Build a symmetric distance matrix from a list of (latitude, longitude) tuples.
    Uses OSRM Table API for real road distances.
    
    Args:
        locations: List of (lat, lon) tuples
        
    Returns:
        Symmetric distance matrix as list of lists (integers in meters)
        
    Raises:
        requests.RequestException: If OSRM request fails
        ValueError: If OSRM response is invalid
    """
    num_locations = len(locations)
    
    if num_locations == 0:
        return []
    
    # Build OSRM coordinates string: lon,lat;lon,lat;...
    coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
    
    # OSRM Table API endpoint
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
    
    # Convert OSRM distances (meters) to integer matrix
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
    """
    Solve a Capacitated Vehicle Routing Problem for a given scenario.
    
    Args:
        scenario_id: ID of the Scenario to solve
        
    Returns:
        Dictionary with 'total_distance' and 'routes' (list of route dicts)
        
    Raises:
        ObjectDoesNotExist: If scenario doesn't exist
        ValueError: If scenario has no bins or vehicles
    """
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
    
    # Determine depot/start location (scenario override falls back to vehicle start)
    depot_location = (
        scenario.start_latitude or vehicle.start_latitude,
        scenario.start_longitude or vehicle.start_longitude
    )
    locations = [depot_location]
    
    # Add bin locations
    bin_locations = [(bin.latitude, bin.longitude) for bin in bins]
    locations.extend(bin_locations)
    
    # Build distance matrix
    distance_matrix = build_distance_matrix(locations)
    
    # Create routing index manager
    # Only one vehicle is used for the plan
    num_vehicles = 1
    depot = 0
    
    # Create routing model
    manager = pywrapcp.RoutingIndexManager(
        len(locations), num_vehicles, depot
    )
    routing = pywrapcp.RoutingModel(manager)
    
    def distance_callback(from_index: int, to_index: int) -> int:
        """Returns the distance between the two nodes."""
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]
    
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    # Add capacity constraint
    def demand_callback(from_index: int) -> int:
        """Returns the demand of the node."""
        from_node = manager.IndexToNode(from_index)
        if from_node == 0:  # Depot has no demand
            return 0
        # Each bin has demand of 1 unit (can be modified to use bin.capacity)
        return 1
    
    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    
    routing.AddDimension(
        demand_callback_index,
        0,  # null capacity slack
        vehicle.capacity,  # vehicle maximum capacity
        True,  # start cumul to zero
        'Capacity'
    )
    
    # Set search parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = 30
    
    # Solve the problem
    solution = routing.SolveWithParameters(search_parameters)
    
    if not solution:
        raise ValueError("No solution found for the given scenario")
    
    # Extract solution
    total_distance = 0
    routes = []
    
    for vehicle_id in range(num_vehicles):
        index = routing.Start(vehicle_id)
        route_stops = []
        route_distance = 0
        
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != depot:  # Skip depot in route stops
                # node - 1 because depot is at index 0, bins start at index 1
                bin_index = node - 1
                if 0 <= bin_index < len(bins):
                    route_stops.append(bins[bin_index].id)
            
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            route_distance += routing.GetArcCostForVehicle(
                previous_index, index, vehicle_id
            )
        
        total_distance += route_distance
        
        if route_stops:  # Only add routes with stops
            routes.append({
                'vehicle': vehicle.name,
                'vehicle_id': vehicle.id,
                'stops': route_stops
            })
    
    # Convert distance from integer meters to float kilometers
    total_distance_km = total_distance / 1000.0
    
    result = {
        'total_distance': total_distance_km,
        'routes': routes
    }
    
    # Store solution in database
    solution_obj = RouteSolution.objects.create(
        scenario=scenario,
        total_distance=total_distance_km,
        data=result
    )
    
    result['solution_id'] = solution_obj.id
    return result

