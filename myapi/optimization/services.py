from typing import List, Tuple, Dict, Any
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import requests

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from .models import Scenario, RouteSolution


class OSRMClientError(Exception):
    """Base exception for OSRM client errors."""
    pass


class OSRMClient:
    """
    Client for interacting with OSRM (Open Source Routing Machine) service.
    
    Encapsulates HTTP logic for distance matrix calculation, including URL length
    validation and comprehensive error handling for network issues.
    """
    
    # HTTP GET URLs are typically limited to ~2000 characters (varies by server/browser)
    MAX_URL_LENGTH = 2000
    DEFAULT_TIMEOUT = 30
    DEFAULT_BASE_URL = "http://localhost:5000"
    
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = DEFAULT_TIMEOUT):
        """
        Initialize OSRM client.
        
        Args:
            base_url: Base URL for OSRM service
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
    
    def get_distance_matrix(self, locations: List[Tuple[float, float]]) -> List[List[int]]:
        """
        Calculate distance matrix using OSRM table service.
        
        Args:
            locations: List of (latitude, longitude) tuples. First location is the depot.
            
        Returns:
            Distance matrix as a list of lists of integers (distances in meters).
            
        Raises:
            OSRMClientError: For URL length violations, network errors, or invalid responses.
            ValueError: For invalid response data structure.
        """
        num_locations = len(locations)
        if num_locations == 0:
            return []
        
        # Build coordinates string: "lon,lat;lon,lat;..."
        coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
        
        # Construct full URL
        osrm_url = f"{self.base_url}/table/v1/driving/{coordinates}"
        params = {"annotations": "distance"}
        
        # Validate URL length to prevent issues with large datasets
        full_url = f"{osrm_url}?annotations=distance"
        if len(full_url) > self.MAX_URL_LENGTH:
            raise OSRMClientError(
                f"OSRM request URL exceeds maximum length ({self.MAX_URL_LENGTH} chars). "
                f"Current length: {len(full_url)}. "
                f"Consider reducing the number of locations or using a different approach."
            )
        
        try:
            response = requests.get(osrm_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.Timeout as e:
            raise OSRMClientError(
                f"OSRM request timed out after {self.timeout} seconds. "
                f"The service may be overloaded or unreachable."
            ) from e
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 'unknown'
            raise OSRMClientError(
                f"OSRM service returned HTTP error {status_code}: {str(e)}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise OSRMClientError(
                f"OSRM request failed: {str(e)}. "
                f"Check if OSRM service is running at {self.base_url}"
            ) from e
        
        # Validate response structure
        if "distances" not in data:
            raise ValueError("OSRM response missing 'distances' field")
        
        osrm_distances = data["distances"]
        
        if len(osrm_distances) != num_locations:
            raise ValueError(
                f"OSRM returned {len(osrm_distances)} rows, expected {num_locations}"
            )
        
        # Build distance matrix with validation
        distance_matrix = []
        for i in range(num_locations):
            if len(osrm_distances[i]) != num_locations:
                raise ValueError(
                    f"OSRM row {i} has {len(osrm_distances[i])} columns, expected {num_locations}"
                )
            row = [int(round(dist)) for dist in osrm_distances[i]]
            distance_matrix.append(row)
        
        return distance_matrix


class VRPSolver:
    """
    Vehicle Routing Problem (VRP) solver using Google OR-Tools.
    
    Encapsulates OR-Tools routing logic, separating validation from solving
    to improve maintainability and testability.
    """
    
    def __init__(self, scenario: Scenario, osrm_client: OSRMClient = None):
        """
        Initialize VRP solver with a scenario.
        
        Args:
            scenario: Scenario instance containing bins, vehicle, and routing parameters
            osrm_client: Optional OSRMClient instance. If None, creates a default one.
        """
        self.scenario = scenario
        self.osrm_client = osrm_client or OSRMClient()
        self.bins = None
        self.vehicle = None
        self.depot_location = None
    
    def _validate_scenario(self) -> None:
        """
        Validate that scenario has required data for solving.
        
        Raises:
            ValueError: If scenario is missing required data (bins or vehicle).
        """
        self.bins = list(self.scenario.bins.filter(is_active=True))
        self.vehicle = self.scenario.vehicle
        
        if not self.bins:
            raise ValueError("Scenario must have at least one active bin")
        if not self.vehicle:
            raise ValueError("Scenario must have at least one vehicle")
    
    def _get_depot_location(self) -> Tuple[float, float]:
        """
        Determine depot location from scenario or vehicle.
        
        Returns:
            Tuple of (latitude, longitude) for the depot.
            
        Raises:
            ValueError: If no valid start location is found.
        """
        # Priority: scenario start location > vehicle start location
        if self.scenario.start_latitude is not None and self.scenario.start_longitude is not None:
            return (self.scenario.start_latitude, self.scenario.start_longitude)
        elif (
            self.vehicle.start_latitude is not None
            and self.vehicle.start_longitude is not None
        ):
            return (self.vehicle.start_latitude, self.vehicle.start_longitude)
        else:
            raise ValueError("No valid start location found (scenario or vehicle)")
    
    def _build_routing_model(
        self, 
        distance_matrix: List[List[int]]
    ) -> Tuple[pywrapcp.RoutingIndexManager, pywrapcp.RoutingModel]:
        """
        Build OR-Tools routing model with distance and capacity constraints.
        
        Args:
            distance_matrix: Distance matrix between all locations (including depot).
            
        Returns:
            Tuple of (RoutingIndexManager, RoutingModel) instances.
        """
        num_vehicles = 1
        depot = 0
        
        manager = pywrapcp.RoutingIndexManager(
            len(distance_matrix), num_vehicles, depot
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
            if from_node == 0:  # Depot has no demand
                return 0
            return 1  # Each bin has demand of 1
        
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        
        routing.AddDimension(
            demand_callback_index,
            0,  # null capacity slack
            self.vehicle.capacity,  # vehicle maximum capacity
            True,  # start cumul to zero
            'Capacity'
        )
        
        return manager, routing
    
    def solve(self) -> Dict[str, Any]:
        """
        Solve the VRP for the scenario.
        
        Returns:
            Dictionary containing:
            - total_distance: Total route distance in kilometers
            - routes: List of route dictionaries with vehicle info and stops
            - solution_id: ID of the saved RouteSolution instance
            
        Raises:
            ValueError: If scenario validation fails or no solution is found.
            OSRMClientError: If OSRM service fails.
        """
        # Validate scenario
        self._validate_scenario()
        
        # Get depot location
        self.depot_location = self._get_depot_location()
        
        # Build locations list: depot first, then bins
        locations = [self.depot_location]
        bin_locations = [(bin.latitude, bin.longitude) for bin in self.bins]
        locations.extend(bin_locations)
        
        # Get distance matrix from OSRM
        distance_matrix = self.osrm_client.get_distance_matrix(locations)
        
        # Build routing model
        manager, routing = self._build_routing_model(distance_matrix)
        
        # Configure search parameters
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.seconds = 30
        
        # Solve
        solution = routing.SolveWithParameters(search_parameters)
        
        if not solution:
            raise ValueError("No solution found for the given scenario")
        
        # Extract routes
        num_vehicles = 1
        depot = 0
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
                    if 0 <= bin_index < len(self.bins):
                        route_stops.append(self.bins[bin_index].id)
                
                previous_index = index
                index = solution.Value(routing.NextVar(index))
                route_distance += routing.GetArcCostForVehicle(
                    previous_index, index, vehicle_id
                )
            
            total_distance += route_distance
            
            if route_stops:
                routes.append({
                    'vehicle': self.vehicle.name,
                    'vehicle_id': self.vehicle.id,
                    'stops': route_stops
                })
        
        total_distance_km = total_distance / 1000.0
        
        result = {
            'total_distance': total_distance_km,
            'routes': routes
        }
        
        # Save solution
        solution_obj = RouteSolution.objects.create(
            scenario=self.scenario,
            total_distance=total_distance_km,
            data=result
        )
        
        result['solution_id'] = solution_obj.id
        return result


def solve_vrp(scenario_id: int) -> Dict[str, Any]:
    """
    Solve VRP for a scenario (backwards-compatible entry point).
    
    This function maintains the original API while using the refactored
    VRPSolver class internally.
    
    Args:
        scenario_id: ID of the scenario to solve.
        
    Returns:
        Dictionary containing total_distance, routes, and solution_id.
        
    Raises:
        ObjectDoesNotExist: If scenario with given ID doesn't exist.
        ValueError: If scenario validation fails or solving fails.
        OSRMClientError: If OSRM service fails.
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
    
    solver = VRPSolver(scenario)
    return solver.solve()
