from datetime import timedelta, datetime
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets, status, permissions
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Bin,
    Vehicle,
    Scenario,
    RouteSolution,
    Municipality,
    Landfill,
    ScenarioTemplate,
)
from .mixins import CreatorScopedViewSetMixin
from .pagination import OptimizationPagination
from .permissions import IsAdmin, IsAdminOrPlanner, IsPlannerOrAdmin, IsPlanner
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


class BinViewSet(CreatorScopedViewSetMixin, viewsets.ModelViewSet):
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
            qs = self.scope_by_creator(super().get_queryset())

        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class MunicipalityViewSet(CreatorScopedViewSetMixin, viewsets.ModelViewSet):
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
            qs = self.scope_by_creator(super().get_queryset())

            # Further scope for planners: only municipalities they are assigned to
            if user.role == user.Roles.PLANNER:
                qs = qs.filter(planner=user)

        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(id=municipality_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class LandfillViewSet(CreatorScopedViewSetMixin, viewsets.ModelViewSet):
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
            qs = self.scope_by_creator(super().get_queryset())

        municipality_id = self.request.query_params.get('municipality')
        if municipality_id:
            qs = qs.filter(municipalities__id=municipality_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class VehicleViewSet(CreatorScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer
    permission_classes = [IsAdmin]
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return super().get_permissions()

    def get_queryset(self):
        qs = self.scope_by_creator(super().get_queryset())
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


class ScenarioTemplateViewSet(CreatorScopedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ScenarioTemplateSerializer
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return [IsPlanner()] # Admin is Read-Only for plans

    def get_queryset(self):
        qs = ScenarioTemplate.objects.select_related('municipality', 'vehicle', 'end_landfill')
        qs = self.scope_by_creator(qs)

        # For planners, restrict to their assigned municipalities
        user = self.request.user
        if user.role == user.Roles.PLANNER:
            qs = qs.filter(municipality__planner=user)

        search = self.request.query_params.get('search')
        municipality_id = self.request.query_params.get('municipality')
        week_day = self.request.query_params.get('week_day')

        if search:
            qs = qs.filter(name__icontains=search)
        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)
        if week_day is not None and week_day.strip():
            qs = qs.filter(weekdays__icontains=week_day)
        return qs

    def perform_create(self, serializer):
        serializer.save()


class ScenarioViewSet(CreatorScopedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ScenarioSerializer
    pagination_class = OptimizationPagination

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsPlannerOrAdmin()]
        return [IsPlanner()] # Admin is Read-Only for plans

    def get_queryset(self):
        user = self.request.user
        today = timezone.localdate()

        qs = Scenario.objects.select_related(
            'created_by', 'vehicle', 'municipality', 'end_landfill'
        ).prefetch_related('bins')

        qs = self.scope_by_creator(qs)

        # For planners, restrict to their assigned municipalities
        if user.role == user.Roles.PLANNER:
            qs = qs.filter(municipality__planner=user)

        search = self.request.query_params.get('search')
        is_archived = self.request.query_params.get('is_archived')
        municipality_id = self.request.query_params.get('municipality')
        status_filter = self.request.query_params.get('status')

        if search:
            qs = qs.filter(name__icontains=search)
        if is_archived == 'true':
            qs = qs.filter(status=Scenario.Status.COMPLETED)
        elif is_archived == 'false':
            qs = qs.exclude(status=Scenario.Status.COMPLETED)
        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)
        if status_filter:
            qs = qs.filter(status=status_filter)

        week_day = self.request.query_params.get('week_day')
        if week_day is not None and week_day.strip():
            try:
                # Saturday Start: 0=Sat, 1=Sun, 2=Mon...
                # Django __week_day: 1=Sun, 2=Mon, 3=Tue, 4=Wed, 5=Thu, 6=Fri, 7=Sat.
                wd = int(week_day)
                django_wd = {
                    0: 7, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6
                }.get(wd)
                if django_wd:
                    qs = qs.filter(collection_date__week_day=django_wd)
            except ValueError:
                pass

        return qs.order_by('-collection_date', '-created_at')

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        # Use DRF's ValidationError (not Django's) so DRF catches it
        # and returns HTTP 400 with a JSON body instead of a 500.
        if self.request.user.role != self.request.user.Roles.PLANNER:
            raise DRFValidationError(_('فقط المخطط يمكنه تعديل الخطط.'))
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role != self.request.user.Roles.PLANNER:
            raise DRFValidationError(_('فقط المخطط يمكنه حذف الخطط.'))
        instance.delete()


class SolveScenarioView(APIView):
    permission_classes = [IsAdminOrPlanner]

    def post(self, request, pk):
        scenario = get_object_or_404(Scenario, pk=pk)

        if request.user.role == request.user.Roles.PLANNER and scenario.created_by != request.user:
            return Response({"detail": _("لا تملك صلاحية تعديل هذه الخطة.")}, status=status.HTTP_403_FORBIDDEN)

        try:
            scenario.status = Scenario.Status.IN_PROGRESS
            scenario.save(update_fields=['status'])
            result = VRPSolver(scenario.id).run()
            return Response(result, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error solving scenario {scenario.id}: {str(e)}", exc_info=True)
            return Response({"detail": _("حدث خطأ غير متوقع أثناء المعالجة.")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
