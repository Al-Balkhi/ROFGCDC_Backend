import logging
import math
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
    def get_distance_matrix(cls, locations: List[Tuple[float, float]], profile: str = 'driving', exclude: str = '') -> List[List[int]]:
        if not locations:
            return []
        coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
        url = f"{cls.BASE_URL}/table/v1/{profile}/{coordinates}"
        params = {"annotations": "distance"}
        if exclude:
            params['exclude'] = exclude
        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"OSRM Connection Error: {e}")
            raise ValidationError("فشل الاتصال بخدمة الخرائط.") from e

        if "distances" not in data:
            raise ValidationError("استجابة غير صالحة من خدمة الخرائط.")
        return cls._sanitize_matrix(data["distances"], len(locations))

    @classmethod
    def get_duration_matrix(cls, locations: List[Tuple[float, float]], profile: str = 'driving', exclude: str = '') -> List[List[int]]:
        if not locations:
            return []
        coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
        url = f"{cls.BASE_URL}/table/v1/{profile}/{coordinates}"
        params = {"annotations": "duration"}
        if exclude:
            params['exclude'] = exclude
        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"OSRM Connection Error: {e}")
            raise ValidationError("فشل الاتصال بخدمة الخرائط.") from e

        if "durations" not in data:
            raise ValidationError("استجابة غير صالحة من خدمة الخرائط.")
        return cls._sanitize_matrix(data["durations"], len(locations))

    @classmethod
    def get_route_geometry(cls, locations: List[Tuple[float, float]], profile: str = 'driving', exclude: str = '') -> str:
        if not locations:
            return ""
        coordinates = ";".join([f"{lon},{lat}" for lat, lon in locations])
        url = f"{cls.BASE_URL}/route/v1/{profile}/{coordinates}"
        params = {"overview": "full", "geometries": "polyline", "steps": "false"}
        if exclude:
            params['exclude'] = exclude
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
        self.duration_matrix = []

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
        profile = 'driving-traffic' if self.scenario.use_traffic_profile else 'driving'
        exclude = self.scenario.avoid_streets
        self.distance_matrix = OSRMService.get_distance_matrix(self.locations, profile=profile, exclude=exclude)
        self.duration_matrix = OSRMService.get_duration_matrix(self.locations, profile=profile, exclude=exclude)

    def _setup_routing_model(self):
        total_bin_demand = sum(b.capacity for b in self.bins)
        num_vehicles = max(1, math.ceil(total_bin_demand / self.vehicle.capacity))
        start_idx = 0
        end_idx = len(self.locations) - 1

        self.manager = pywrapcp.RoutingIndexManager(
            len(self.locations), num_vehicles, [start_idx] * num_vehicles, [end_idx] * num_vehicles
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
            if node in (0, len(self.locations) - 1):
                return 0
            return self.bins[node - 1].capacity

        demand_index = self.routing.RegisterUnaryTransitCallback(demand_callback)
        self.routing.AddDimension(demand_index, 0, self.vehicle.capacity, True, 'Capacity')

        def time_callback(from_index: int, to_index: int) -> int:
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)
            service_time = 180 if from_node != 0 and from_node != len(self.locations) - 1 else 0
            return int(self.duration_matrix[from_node][to_node]) + service_time

        time_callback_index = self.routing.RegisterTransitCallback(time_callback)
        self.routing.AddDimension(
            time_callback_index,
            3600,
            86400,
            False,
            'Time'
        )
        time_dimension = self.routing.GetDimensionOrDie('Time')

        for i, bin_obj in enumerate(self.bins):
            if bin_obj.pickup_window_start and bin_obj.pickup_window_end:
                node_idx = i + 1
                index = self.manager.NodeToIndex(node_idx)
                start_sec = bin_obj.pickup_window_start.hour * 3600 + bin_obj.pickup_window_start.minute * 60
                end_sec = bin_obj.pickup_window_end.hour * 3600 + bin_obj.pickup_window_end.minute * 60
                time_dimension.CumulVar(index).SetRange(start_sec, end_sec)

        for i in range(num_vehicles):
            self.routing.AddVariableMinimizedByFinalizer(
                time_dimension.CumulVar(self.routing.Start(i)))
            self.routing.AddVariableMinimizedByFinalizer(
                time_dimension.CumulVar(self.routing.End(i)))

    def _solve(self):
        p = pywrapcp.DefaultRoutingSearchParameters()
        p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        p.time_limit.seconds = 10

        self.solution = self.routing.SolveWithParameters(p)
        if not self.solution:
            raise ValidationError("لم يتم العثور على حل ممكن لهذه الخطة (قد تكون السعة غير كافية).")

    def _save_solution(self) -> Dict[str, Any]:
        routes_data = []
        total_distance = 0
        total_time_seconds = 0
        total_bins = len(self.bins)
        on_time_count = 0

        time_dimension = self.routing.GetDimensionOrDie('Time')

        for vehicle_id in range(self.manager.GetNumberOfVehicles()):
            index = self.routing.Start(vehicle_id)
            if self.routing.IsEnd(index):
                continue
                
            route_distance = 0
            route_stops = []
            route_coords = [self.start_location]
            has_bins = False
            
            while not self.routing.IsEnd(index):
                node = self.manager.IndexToNode(index)
                if 1 <= node <= len(self.bins):
                    has_bins = True
                    current_bin = self.bins[node - 1]
                    route_stops.append(current_bin.id)
                    route_coords.append((current_bin.latitude, current_bin.longitude))
                    
                    arrival_time = self.solution.Min(time_dimension.CumulVar(index))
                    if current_bin.pickup_window_start and current_bin.pickup_window_end:
                        start_sec = current_bin.pickup_window_start.hour * 3600 + current_bin.pickup_window_start.minute * 60
                        end_sec = current_bin.pickup_window_end.hour * 3600 + current_bin.pickup_window_end.minute * 60
                        if start_sec <= arrival_time <= end_sec:
                            on_time_count += 1
                    else:
                        on_time_count += 1
                
                prev = index
                index = self.solution.Value(self.routing.NextVar(index))
                route_distance += self.routing.GetArcCostForVehicle(prev, index, 0)
            
            if not has_bins:
                continue
                
            route_coords.append(self.end_location)
            
            profile = 'driving-traffic' if self.scenario.use_traffic_profile else 'driving'
            exclude = self.scenario.avoid_streets
            geometry = OSRMService.get_route_geometry(route_coords, profile=profile, exclude=exclude) if route_stops else ""
            
            total_distance += route_distance
            route_time = self.solution.Min(time_dimension.CumulVar(self.routing.End(vehicle_id)))
            total_time_seconds += route_time
            
            routes_data.append({
                'vehicle': self.vehicle.name,
                'vehicle_id': self.vehicle.id,
                'start': self.start_location,
                'end_landfill': {
                    'id': self.scenario.end_landfill.id,
                    'name': self.scenario.end_landfill.name,
                },
                'stops': route_stops,
                'geometry': geometry,
                'distance': route_distance / 1000.0,
                'time_seconds': route_time,
            })

        if not routes_data:
            raise ValidationError("لم يتم إنشاء مسارات صالحة (قد تكون المشكلة في سعة المركبة).")

        total_km = total_distance / 1000.0
        FUEL_LITRES_PER_KM = 0.30
        CO2_KG_PER_LITRE = 2.68
        
        fuel_litres = total_km * FUEL_LITRES_PER_KM
        co2_kg = fuel_litres * CO2_KG_PER_LITRE
        on_time_rate = (on_time_count / total_bins * 100) if total_bins > 0 else 100.0

        result_data = {
            'total_distance': total_km,
            'routes': routes_data,
            'solver_mode': 'hybrid_tsp_vrp',
            'time_limit_seconds': 10,
            'kpis': {
                'total_km': round(total_km, 2),
                'total_time_seconds': round(total_time_seconds, 2),
                'fuel_litres': round(fuel_litres, 2),
                'co2_kg': round(co2_kg, 2),
                'on_time_pickups': on_time_count,
                'on_time_rate': round(on_time_rate, 2),
            }
        }

        solution_obj = RouteSolution.objects.create(
            scenario=self.scenario,
            total_distance=total_km,
            total_time=total_time_seconds,
            co2_kg=co2_kg,
            data=result_data
        )
        result_data['solution_id'] = solution_obj.id
        return result_data


def solve_vrp(scenario_id: int) -> Dict[str, Any]:
    solver = VRPSolver(scenario_id)
    return solver.run()
