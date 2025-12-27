from datetime import timedelta

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Bin, Vehicle, Scenario, RouteSolution, Municipality, Landfill
from .serializers import (
    BinSerializer,
    VehicleSerializer,
    ScenarioSerializer,
    RouteSolutionSerializer,
    MunicipalitySerializer,
    LandfillSerializer,
    BinAvailableSerializer,
)
from .services import solve_vrp
from .permissions import IsAdmin, IsAdminOrPlanner, IsPlannerOrAdmin
from .pagination import OptimizationPagination


# ======================= BINS =======================

class BinViewSet(viewsets.ModelViewSet):
    queryset = Bin.objects.all()
    serializer_class = BinSerializer
    permission_classes = [IsAdmin]
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)
        return qs


# ======================= MUNICIPALITIES =======================

class MunicipalityViewSet(viewsets.ModelViewSet):
    queryset = Municipality.objects.all().prefetch_related('landfills')
    serializer_class = MunicipalitySerializer
    permission_classes = [IsAdmin]
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(id=municipality_id)
        return qs


# ======================= LANDFILLS =======================

class LandfillViewSet(viewsets.ModelViewSet):
    queryset = Landfill.objects.all().prefetch_related('municipalities')
    serializer_class = LandfillSerializer
    permission_classes = [IsAdmin]
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(municipalities__id=municipality_id)
        return qs


# ======================= VEHICLES =======================

class VehicleViewSet(viewsets.ModelViewSet):
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer
    permission_classes = [IsAdmin]
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        municipality_id = self.request.query_params.get('municipality')

        if user.role == user.Roles.PLANNER:
            scenario_id = self.request.query_params.get('scenario_id')
            today = timezone.localdate()

            busy_qs = Scenario.objects.filter(collection_date__gte=today)
            if scenario_id:
                busy_qs = busy_qs.exclude(id=scenario_id)

            busy_ids = busy_qs.values_list('vehicle_id', flat=True)
            qs = qs.exclude(id__in=busy_ids)

        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)

        return qs.distinct()


# ======================= SCENARIOS =======================

class ScenarioViewSet(viewsets.ModelViewSet):
    serializer_class = ScenarioSerializer
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsPlannerOrAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        today = timezone.localdate()

        qs = Scenario.objects.select_related(
            'created_by',
            'vehicle',
            'municipality',
        ).prefetch_related('bins')

        # 🔴 عزل الـ Planners
        if user.role == user.Roles.PLANNER:
            qs = qs.filter(created_by=user)

        search = self.request.query_params.get('search')
        is_archived = self.request.query_params.get('is_archived')
        municipality_id = self.request.query_params.get('municipality')
        collection_date = self.request.query_params.get('collection_date')

        if search:
            qs = qs.filter(name__icontains=search)

        if is_archived == 'true':
            qs = qs.filter(collection_date__lt=today)
        elif is_archived == 'false':
            qs = qs.filter(collection_date__gte=today)

        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)

        if collection_date:
            qs = qs.filter(collection_date=collection_date)

        return qs.order_by('-collection_date', '-created_at')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ======================= SOLVE =======================

class SolveScenarioView(APIView):
    permission_classes = [IsAdminOrPlanner]

    def post(self, request, pk):
        scenario = get_object_or_404(Scenario, pk=pk)

        if (
            request.user.role == request.user.Roles.PLANNER
            and scenario.created_by != request.user
        ):
            return Response(
                {"detail": "غير مسموح"},
                status=status.HTTP_403_FORBIDDEN
            )

        result = solve_vrp(scenario.id)
        return Response(result, status=status.HTTP_200_OK)


# ======================= AVAILABLE BINS =======================

class AvailableBinList(APIView):
    permission_classes = [IsPlannerOrAdmin]

    def get(self, request):
        scenario_id = request.query_params.get('scenario_id')
        municipality_id = request.query_params.get('municipality')
        today = timezone.localdate()

        busy_qs = Scenario.objects.filter(collection_date__gte=today)
        if scenario_id:
            busy_qs = busy_qs.exclude(id=scenario_id)

        busy_bin_ids = busy_qs.values_list('bins__id', flat=True)
        qs = Bin.objects.filter(is_active=True).exclude(id__in=busy_bin_ids)

        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)

        serializer = BinAvailableSerializer(qs.distinct(), many=True)
        return Response(serializer.data)


# ======================= ROUTE SOLUTIONS =======================

class RouteSolutionListView(APIView):
    permission_classes = [IsPlannerOrAdmin]

    def get(self, request):
        user = request.user
        today = timezone.localdate()

        qs = RouteSolution.objects.select_related(
            'scenario',
            'scenario__vehicle',
            'scenario__municipality',
            'scenario__created_by'
        ).prefetch_related('scenario__bins')

        # 🔴 عزل الـ Planners
        if user.role == user.Roles.PLANNER:
            qs = qs.filter(scenario__created_by=user)

        range_filter = request.query_params.get('range')

        if range_filter == 'today':
            qs = qs.filter(scenario__collection_date=today)
        elif range_filter == 'week':
            qs = qs.filter(scenario__collection_date__gte=today,
                           scenario__collection_date__lte=today + timedelta(days=7))
        elif range_filter == 'month':
            start = today.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            qs = qs.filter(scenario__collection_date__gte=start,
                           scenario__collection_date__lte=end)

        serializer = RouteSolutionSerializer(qs, many=True)
        return Response(serializer.data)


class RouteSolutionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        qs = RouteSolution.objects.select_related('scenario')

        if request.user.role == request.user.Roles.PLANNER:
            qs = qs.filter(scenario__created_by=request.user)

        solution = get_object_or_404(qs, pk=pk)
        serializer = RouteSolutionSerializer(solution)
        return Response(serializer.data)


# ======================= PLANNER STATS =======================

class PlannerStatsView(APIView):
    permission_classes = [IsPlannerOrAdmin]

    def get(self, request):
        user = request.user
        today = timezone.localdate()

        qs = Scenario.objects.filter(created_by=user)

        return Response({
            "total_plans": qs.count(),
            "plans_this_month": qs.filter(
                collection_date__month=today.month,
                collection_date__year=today.year
            ).count(),
            "plans_today": qs.filter(collection_date=today).count(),
        })
