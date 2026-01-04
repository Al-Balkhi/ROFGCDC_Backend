import logging
from typing import List, Tuple, Dict, Any
import requests
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from .models import Scenario, RouteSolution

logger = logging.getLogger(__name__)


class OSRMService:
    """Handles communication with the OSRM backend."""
    
    BASE_URL = getattr(settings, 'OSRM_BASE_URL', 'http://localhost:5000')

    @classmethod
    def get_distance_matrix(cls, locations: List[Tuple[float, float]]) -> List[List[int]]:
        if not locations:
            return []

        coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
        url = f"{cls.BASE_URL}/table/v1/driving/{coordinates}"
        params = {"annotations": "distance"}

        try:
            # FIX: Add strict timeout (5 seconds)
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"OSRM Connection Error: {e}")
            raise ValidationError("فشل الاتصال بخدمة الخرائط.") from e

        if "distances" not in data:
            raise ValidationError("استجابة غير صالحة من خدمة الخرائط.")

        return cls._sanitize_matrix(data["distances"], len(locations))

    @staticmethod
    def _sanitize_matrix(raw_distances, expected_size) -> List[List[int]]:
        matrix = []
        for row in raw_distances:
            if len(row) != expected_size:
                raise ValidationError("عدم تطابق في أبعاد مصفوفة المسافات.")
            matrix.append([int(round(d)) for d in row])
        return matrix


class VRPSolver:
    """
    Solves the Vehicle Routing Problem using Google OR-Tools.
    """

    def __init__(self, scenario_id: int):
        self.scenario_id = scenario_id
        self.scenario = None
        self.bins = []
        self.vehicle = None
        self.depot_location = None
        self.locations = []
        self.distance_matrix = []
        
        self.manager = None
        self.routing = None
        self.solution = None

    def run(self) -> Dict[str, Any]:
        self._load_data()
        self._validate_requirements()
        self._prepare_locations()
        self._fetch_matrix()
        self._setup_routing_model()
        self._solve()
        return self._save_solution()

    def _load_data(self):
        try:
            self.scenario = Scenario.objects.select_related(
                'created_by', 'vehicle'
            ).prefetch_related('bins').get(pk=self.scenario_id)
        except Scenario.DoesNotExist:
            raise ObjectDoesNotExist(f"الخطة رقم {self.scenario_id} غير موجودة.")

        self.bins = list(self.scenario.bins.filter(is_active=True))
        self.vehicle = self.scenario.vehicle

    def _validate_requirements(self):
        if not self.bins:
            raise ValidationError("يجب أن تحتوي الخطة على حاوية واحدة نشطة على الأقل.")
        if not self.vehicle:
            raise ValidationError("لا توجد مركبة محددة للخطة.")

    def _prepare_locations(self):
        if self.scenario.start_latitude and self.scenario.start_longitude:
            self.depot_location = (self.scenario.start_latitude, self.scenario.start_longitude)
        elif self.vehicle.start_latitude and self.vehicle.start_longitude:
            self.depot_location = (self.vehicle.start_latitude, self.vehicle.start_longitude)
        else:
            raise ValidationError("لم يتم تحديد نقطة انطلاق صالحة (في الخطة أو المركبة).")

        self.locations = [self.depot_location] + [(b.latitude, b.longitude) for b in self.bins]

    def _fetch_matrix(self):
        self.distance_matrix = OSRMService.get_distance_matrix(self.locations)

    def _setup_routing_model(self):
        num_vehicles = 1
        depot_index = 0
        
        self.manager = pywrapcp.RoutingIndexManager(
            len(self.locations), num_vehicles, depot_index
        )
        self.routing = pywrapcp.RoutingModel(self.manager)

        def distance_callback(from_index: int, to_index: int) -> int:
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)
            return self.distance_matrix[from_node][to_node]

        transit_callback_index = self.routing.RegisterTransitCallback(distance_callback)
        self.routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        def demand_callback(from_index: int) -> int:
            from_node = self.manager.IndexToNode(from_index)
            return 0 if from_node == 0 else 1

        demand_callback_index = self.routing.RegisterUnaryTransitCallback(demand_callback)
        self.routing.AddDimension(
            demand_callback_index, 0, self.vehicle.capacity, True, 'Capacity'
        )

    def _solve(self):
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.seconds = 30
        
        self.solution = self.routing.SolveWithParameters(search_parameters)
        if not self.solution:
            raise ValidationError("لم يتم العثور على حل ممكن لهذه الخطة (قد تكون السعة غير كافية).")

    def _save_solution(self) -> Dict[str, Any]:
        total_distance = 0
        routes = []
        
        # FIX: Avoid hardcoded range(1). 
        # Although model only supports 1 vehicle now, this prevents logic errors if updated.
        num_vehicles = 1
        
        for vehicle_id in range(num_vehicles):
            index = self.routing.Start(vehicle_id)
            route_stops = []
            route_distance = 0
            
            while not self.routing.IsEnd(index):
                node = self.manager.IndexToNode(index)
                if node != 0: 
                    bin_index = node - 1
                    if 0 <= bin_index < len(self.bins):
                        route_stops.append(self.bins[bin_index].id)

                previous_index = index
                index = self.solution.Value(self.routing.NextVar(index))
                route_distance += self.routing.GetArcCostForVehicle(
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
        
        result_data = {
            'total_distance': total_distance_km,
            'routes': routes
        }

        solution_obj = RouteSolution.objects.create(
            scenario=self.scenario,
            total_distance=total_distance_km,
            data=result_data
        )
        result_data['solution_id'] = solution_obj.id
        
        return result_data


def solve_vrp(scenario_id: int) -> Dict[str, Any]:
    """Legacy entry point."""
    solver = VRPSolver(scenario_id)
    return solver.run()
