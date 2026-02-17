from datetime import timedelta, datetime
import logging

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    Bin,
    Vehicle,
    Scenario,
    RouteSolution,
    Municipality,
    Landfill,
    ScenarioTemplate,
)
from .serializers import (
    BinSerializer,
    VehicleSerializer,
    ScenarioSerializer,
    RouteSolutionSerializer,
    MunicipalitySerializer,
    LandfillSerializer,
    BinAvailableSerializer,
    ScenarioTemplateSerializer,
)
from .services import VRPSolver

logger = logging.getLogger(__name__)
from .permissions import IsAdmin, IsAdminOrPlanner, IsPlannerOrAdmin
from .pagination import OptimizationPagination


def _scope_by_creator(qs, request):
    user = request.user
    if user.is_superuser:
        return qs
    if user.role == user.Roles.ADMIN:
        return qs.filter(created_by=user)
    if user.role == user.Roles.PLANNER and user.created_by_id:
        return qs.filter(created_by_id=user.created_by_id)
    return qs.none()


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
        is_map_view = self.request.query_params.get('map_view') == 'true'
        user = self.request.user
        
        # If map view and user is admin/superuser, show all assets
        if is_map_view and (user.is_superuser or user.role == user.Roles.ADMIN):
             qs = self.queryset
        else:
             qs = _scope_by_creator(super().get_queryset(), self.request)
             
        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


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
        is_map_view = self.request.query_params.get('map_view') == 'true'
        user = self.request.user

        if is_map_view and (user.is_superuser or user.role == user.Roles.ADMIN):
             qs = self.queryset
        else:
             qs = _scope_by_creator(super().get_queryset(), self.request)

        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(id=municipality_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


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
        is_map_view = self.request.query_params.get('map_view') == 'true'
        user = self.request.user

        if is_map_view and (user.is_superuser or user.role == user.Roles.ADMIN):
             qs = self.queryset
        else:
             qs = _scope_by_creator(super().get_queryset(), self.request)

        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(municipalities__id=municipality_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


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
        qs = _scope_by_creator(super().get_queryset(), self.request)
        user = self.request.user
        municipality_id = self.request.query_params.get('municipality')

        if user.role == user.Roles.PLANNER:
            scenario_id = self.request.query_params.get('scenario_id')
            date_str = self.request.query_params.get('collection_date')
            target_date = timezone.localdate()
            if date_str:
                try:
                    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    pass

            busy_qs = Scenario.objects.filter(collection_date=target_date)
            if scenario_id:
                busy_qs = busy_qs.exclude(id=scenario_id)
            qs = qs.exclude(id__in=busy_qs.values_list('vehicle_id', flat=True))

        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)

        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ScenarioTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = ScenarioTemplateSerializer
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return [IsAdmin()]

    def get_queryset(self):
        qs = ScenarioTemplate.objects.select_related('municipality', 'vehicle', 'end_landfill')
        qs = _scope_by_creator(qs, self.request)
        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ScenarioViewSet(viewsets.ModelViewSet):
    serializer_class = ScenarioSerializer
    pagination_class = OptimizationPagination

    def get_permissions(self):
        return [IsPlannerOrAdmin()]

    def get_queryset(self):
        user = self.request.user
        today = timezone.localdate()

        qs = Scenario.objects.select_related(
            'created_by', 'vehicle', 'municipality', 'end_landfill'
        ).prefetch_related('bins')

        if user.role == user.Roles.PLANNER:
            qs = qs.filter(created_by=user)
        elif user.role == user.Roles.ADMIN and not user.is_superuser:
            qs = qs.filter(created_by__created_by=user)
        elif user.role not in [user.Roles.ADMIN, user.Roles.PLANNER]:
            qs = qs.none()

        search = self.request.query_params.get('search')
        is_archived = self.request.query_params.get('is_archived')
        municipality_id = self.request.query_params.get('municipality')
        collection_date = self.request.query_params.get('collection_date')
        status_filter = self.request.query_params.get('status')

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
        if status_filter:
            qs = qs.filter(status=status_filter)

        week_day = self.request.query_params.get('week_day')
        if week_day is not None and week_day.strip():
            try:
                # Mapping from JS getDay() style (if used) or just 0=Mon, 6=Sun
                # JS 0=Sun, 1=Mon...
                # My frontend uses ['Mon', 'Tue'...] mapped to index 0..6?
                # In PlanSideBar: `['الإثنين', ...].map((day, index) => ...)`
                # So 0=Monday, 1=Tuesday, ..., 6=Sunday.
                # Django __week_day: 1=Sunday, 2=Monday, ..., 7=Saturday.
                # Map: 0->2, 1->3, ..., 4->6, 5->7, 6->1.
                wd = int(week_day)
                django_wd = {
                    0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 1
                }.get(wd)
                if django_wd:
                    qs = qs.filter(collection_date__week_day=django_wd)
            except ValueError:
                pass

        return qs.order_by('-collection_date', '-created_at')

    def perform_create(self, serializer):
        if self.request.user.role != self.request.user.Roles.PLANNER:
            raise ValidationError('فقط المخطط يمكنه إنشاء الخطط.')
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        if self.request.user.role != self.request.user.Roles.PLANNER:
            raise ValidationError('فقط المخطط يمكنه تعديل الخطط.')
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role != self.request.user.Roles.PLANNER:
            raise ValidationError('فقط المخطط يمكنه حذف الخطط.')
        instance.delete()


class SolveScenarioView(APIView):
    permission_classes = [IsAdminOrPlanner]

    def post(self, request, pk):
        scenario = get_object_or_404(Scenario, pk=pk)

        if request.user.role == request.user.Roles.PLANNER and scenario.created_by != request.user:
            return Response({"detail": "لا تملك صلاحية تعديل هذه الخطة."}, status=status.HTTP_403_FORBIDDEN)

        try:
            scenario.status = Scenario.Status.IN_PROGRESS
            scenario.save(update_fields=['status'])
            result = VRPSolver(scenario.id).run()
            return Response(result, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error solving scenario {scenario.id}: {str(e)}", exc_info=True)
            return Response({"detail": "حدث خطأ غير متوقع أثناء المعالجة."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        return Response(BinAvailableSerializer(qs.distinct(), many=True).data)


class RouteSolutionListView(APIView):
    permission_classes = [IsPlannerOrAdmin]

    def get(self, request):
        user = request.user
        today = timezone.localdate()

        qs = RouteSolution.objects.select_related(
            'scenario', 'scenario__vehicle', 'scenario__municipality', 'scenario__created_by',
        ).prefetch_related('scenario__bins')

        if user.role == user.Roles.PLANNER:
            qs = qs.filter(scenario__created_by=user)

        range_filter = request.query_params.get('range')
        if range_filter == 'today':
            qs = qs.filter(scenario__collection_date=today)
        elif range_filter == 'week':
            qs = qs.filter(scenario__collection_date__gte=today, scenario__collection_date__lte=today + timedelta(days=7))
        elif range_filter == 'month':
            start = today.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            qs = qs.filter(scenario__collection_date__gte=start, scenario__collection_date__lte=end)

        return Response(RouteSolutionSerializer(qs, many=True).data)


class RouteSolutionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        qs = RouteSolution.objects.select_related('scenario')
        if request.user.role == request.user.Roles.PLANNER:
            qs = qs.filter(scenario__created_by=request.user)

        solution = get_object_or_404(qs, pk=pk)
        return Response(RouteSolutionSerializer(solution).data)


class PlannerStatsView(APIView):
    permission_classes = [IsPlannerOrAdmin]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        qs = Scenario.objects.filter(created_by=user)

        return Response({
            "total_plans": qs.count(),
            "plans_this_month": qs.filter(collection_date__month=today.month, collection_date__year=today.year).count(),
            "plans_today": qs.filter(collection_date=today).count(),
        })
