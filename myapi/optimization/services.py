import logging
from typing import List, Tuple, Dict, Any
import requests
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from .models import Scenario, RouteSolution

logger = logging.getLogger(__name__)


class OSRMService:
    BASE_URL = getattr(settings, 'OSRM_BASE_URL', 'http://localhost:5000')

    @classmethod
    def get_distance_matrix(cls, locations: List[Tuple[float, float]]) -> List[List[int]]:
        if not locations:
            return []
        coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
        url = f"{cls.BASE_URL}/table/v1/driving/{coordinates}"
        try:
            response = requests.get(url, params={"annotations": "distance"}, timeout=5)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"OSRM Connection Error: {e}")
            raise ValidationError("فشل الاتصال بخدمة الخرائط.") from e

        if "distances" not in data:
            raise ValidationError("استجابة غير صالحة من خدمة الخرائط.")
        return cls._sanitize_matrix(data["distances"], len(locations))

    @classmethod
    def get_route_geometry(cls, locations: List[Tuple[float, float]]) -> str:
        if not locations:
            return ""
        coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
        url = f"{cls.BASE_URL}/route/v1/driving/{coordinates}"
        params = {"overview": "full", "geometries": "polyline", "steps": "false"}
        try:
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("routes"):
                    return data["routes"][0].get("geometry", "")
        except Exception as e:
            logger.error(f"Failed to fetch route geometry: {e}")
        return ""

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
    Hybrid TSP+VRP approach:
    - TSP-style initial route construction (PATH_CHEAPEST_ARC)
    - VRP local improvement (GUIDED_LOCAL_SEARCH)
    - Open route: starts at municipality HQ and ends at scenario end_landfill
    """

    def __init__(self, scenario_id: int):
        self.scenario_id = scenario_id
        self.scenario = None
        self.bins = []
        self.vehicle = None
        self.start_location = None
        self.end_location = None
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
                'vehicle', 'vehicle__municipality', 'end_landfill'
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
        if not self.scenario.end_landfill:
            raise ValidationError("يجب تحديد المدفن النهائي للخطة.")

    def _prepare_locations(self):
        if self.scenario.start_latitude is not None and self.scenario.start_longitude is not None:
            self.start_location = (self.scenario.start_latitude, self.scenario.start_longitude)
        elif (
            self.vehicle.municipality.hq_latitude is not None
            and self.vehicle.municipality.hq_longitude is not None
        ):
            self.start_location = (
                self.vehicle.municipality.hq_latitude,
                self.vehicle.municipality.hq_longitude,
            )
        else:
            raise ValidationError("لم يتم تحديد نقطة انطلاق صالحة (في الخطة أو بلدية المركبة).")

        self.end_location = (self.scenario.end_landfill.latitude, self.scenario.end_landfill.longitude)
        self.locations = [self.start_location] + [(b.latitude, b.longitude) for b in self.bins] + [self.end_location]

    def _fetch_matrix(self):
        self.distance_matrix = OSRMService.get_distance_matrix(self.locations)

    def _setup_routing_model(self):
        num_vehicles = 1
        start_idx = 0
        end_idx = len(self.locations) - 1

        self.manager = pywrapcp.RoutingIndexManager(
            len(self.locations), num_vehicles, [start_idx], [end_idx]
        )
        self.routing = pywrapcp.RoutingModel(self.manager)

        def distance_callback(from_index: int, to_index: int) -> int:
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)
            return self.distance_matrix[from_node][to_node]

        transit_index = self.routing.RegisterTransitCallback(distance_callback)
        self.routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

        def demand_callback(from_index: int) -> int:
            node = self.manager.IndexToNode(from_index)
            return 0 if node in (0, len(self.locations) - 1) else 1

        demand_index = self.routing.RegisterUnaryTransitCallback(demand_callback)
        self.routing.AddDimension(demand_index, 0, self.vehicle.capacity, True, 'Capacity')

    def _solve(self):
        p = pywrapcp.DefaultRoutingSearchParameters()
        p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        p.time_limit.seconds = 10

        self.solution = self.routing.SolveWithParameters(p)
        if not self.solution:
            raise ValidationError("لم يتم العثور على حل ممكن لهذه الخطة (قد تكون السعة غير كافية).")

    def _save_solution(self) -> Dict[str, Any]:
        route_stops, route_coords = [], [self.start_location]
        total_distance = 0

        index = self.routing.Start(0)
        while not self.routing.IsEnd(index):
            node = self.manager.IndexToNode(index)
            if 1 <= node <= len(self.bins):
                current_bin = self.bins[node - 1]
                route_stops.append(current_bin.id)
                route_coords.append((current_bin.latitude, current_bin.longitude))

            prev = index
            index = self.solution.Value(self.routing.NextVar(index))
            total_distance += self.routing.GetArcCostForVehicle(prev, index, 0)

        route_coords.append(self.end_location)

        geometry = OSRMService.get_route_geometry(route_coords) if route_stops else ""
        result_data = {
            'total_distance': total_distance / 1000.0,
            'routes': [{
                'vehicle': self.vehicle.name,
                'vehicle_id': self.vehicle.id,
                'start': self.start_location,
                'end_landfill': {
                    'id': self.scenario.end_landfill.id,
                    'name': self.scenario.end_landfill.name,
                },
                'stops': route_stops,
                'geometry': geometry,
            }],
            'solver_mode': 'hybrid_tsp_vrp',
            'time_limit_seconds': 10,
        }

        solution_obj = RouteSolution.objects.create(
            scenario=self.scenario,
            total_distance=result_data['total_distance'],
            data=result_data
        )
        result_data['solution_id'] = solution_obj.id
        return result_data


def solve_vrp(scenario_id: int) -> Dict[str, Any]:
    solver = VRPSolver(scenario_id)
    return solver.run()
