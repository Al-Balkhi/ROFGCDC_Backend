from datetime import timedelta

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q

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


class BinViewSet(viewsets.ModelViewSet):
    queryset = Bin.objects.all()
    serializer_class = BinSerializer
    permission_classes = [IsAdmin]

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


class MunicipalityViewSet(viewsets.ModelViewSet):
    queryset = Municipality.objects.all().prefetch_related('landfills')
    serializer_class = MunicipalitySerializer
    permission_classes = [IsAdmin]

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


class LandfillViewSet(viewsets.ModelViewSet):
    queryset = Landfill.objects.all().prefetch_related('municipalities')
    serializer_class = LandfillSerializer
    permission_classes = [IsAdmin]

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


class VehicleViewSet(viewsets.ModelViewSet):
    """
    Viewset for Vehicle operations.
    Planner: See vehicles NOT assigned to any ACTIVE scenario (today or future).
    """
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        municipality_id = self.request.query_params.get('municipality')

        if user.is_authenticated and hasattr(user, 'role'):
            if user.role == user.Roles.PLANNER:
                scenario_id = self.request.query_params.get('scenario_id')
                today = timezone.localdate()

                # المنطق الجديد: استبعاد المركبات المشغولة في خطط اليوم أو المستقبل فقط
                # 1. تحديد المركبات المشغولة (في خطط نشطة)
                busy_vehicles_query = Scenario.objects.filter(
                    collection_date__gte=today
                )
                
                # إذا كنا نعدل خطة، لا نعتبر مركبتها مشغولة (لكي تظهر في القائمة)
                if scenario_id:
                    busy_vehicles_query = busy_vehicles_query.exclude(id=scenario_id)
                
                busy_vehicle_ids = busy_vehicles_query.values_list('vehicle_id', flat=True)

                # 2. استبعاد هذه المركبات من القائمة النهائية
                qs = qs.exclude(id__in=busy_vehicle_ids)

                if municipality_id:
                    qs = qs.filter(municipality_id=municipality_id)
                
                return qs.distinct()

        if municipality_id:
            qs = qs.filter(municipality_id=municipality_id)
        return qs

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrPlanner()]
        return super().get_permissions()


class ScenarioViewSet(viewsets.ModelViewSet):
    """
    Viewset for Scenarios. 
    Supports auto-archiving logic via filtering (Active vs Archived based on Date).
    """
    serializer_class = ScenarioSerializer
    
    def get_queryset(self):
        queryset = Scenario.objects.select_related(
            'created_by',
            'vehicle',
            'municipality',
        ).prefetch_related('bins').all()

        search = self.request.query_params.get('search')
        is_archived = self.request.query_params.get('is_archived')
        municipality_id = self.request.query_params.get('municipality')
        collection_date = self.request.query_params.get('collection_date')

        today = timezone.localdate()

        if search:
            queryset = queryset.filter(name__icontains=search)

        # منطق الأرشفة التلقائية
        if is_archived == 'true':
            queryset = queryset.filter(collection_date__lt=today)
        elif is_archived == 'false':
            queryset = queryset.filter(collection_date__gte=today)

        if municipality_id:
            queryset = queryset.filter(municipality_id=municipality_id)

        if collection_date:
            queryset = queryset.filter(collection_date=collection_date)

        return queryset.order_by('-collection_date', '-created_at')

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsPlannerOrAdmin]
        else:
            permission_classes = [permissions.IsAuthenticated]
        return [permission() for permission in permission_classes]


class SolveScenarioView(APIView):
    permission_classes = [IsAdminOrPlanner]
    
    def post(self, request, pk):
        scenario = get_object_or_404(Scenario, pk=pk)
        try:
            result = solve_vrp(scenario.id)
            return Response(result, status=status.HTTP_200_OK)
        except ObjectDoesNotExist as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Server Error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AvailableBinList(APIView):
    """
    Returns active bins NOT linked to any ACTIVE Scenario (Today or Future).
    Resources from past scenarios are freed.
    """
    permission_classes = [IsPlannerOrAdmin]

    def get(self, request):
        scenario_id = request.query_params.get('scenario_id')
        municipality_id = request.query_params.get('municipality')
        today = timezone.localdate()

        # 1. تحديد الحاويات المحجوزة في خطط نشطة (اليوم أو المستقبل)
        busy_scenarios = Scenario.objects.filter(collection_date__gte=today)
        
        # استثناء الخطة الحالية عند التعديل
        if scenario_id:
            busy_scenarios = busy_scenarios.exclude(id=scenario_id)
            
        busy_bin_ids = busy_scenarios.values_list('bins__id', flat=True)

        # 2. جلب الحاويات النشطة واستبعاد المحجوزة
        qs = Bin.objects.filter(is_active=True).exclude(id__in=busy_bin_ids)

        if municipality_id:
            try:
                m_id = int(municipality_id)
                qs = qs.filter(municipality_id=m_id)
            except ValueError:
                pass

        bins = qs.distinct()
        serializer = BinAvailableSerializer(bins, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RouteSolutionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, pk):
        solution = get_object_or_404(
            RouteSolution.objects.select_related('scenario'),
            pk=pk
        )
        serializer = RouteSolutionSerializer(solution)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RouteSolutionListView(APIView):
    permission_classes = [IsPlannerOrAdmin]

    def get(self, request):
        qs = RouteSolution.objects.select_related(
            'scenario',
            'scenario__vehicle',
            'scenario__municipality',
            'scenario__created_by'
        ).prefetch_related('scenario__bins').all()

        range_filter = request.query_params.get('range')
        today = timezone.localdate()

        if range_filter == 'today':
            qs = qs.filter(scenario__collection_date=today)
        elif range_filter == 'week':
            week_end = today + timedelta(days=7)
            qs = qs.filter(scenario__collection_date__gte=today, scenario__collection_date__lte=week_end)
        elif range_filter == 'month':
            month_end = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            qs = qs.filter(scenario__collection_date__gte=today.replace(day=1), scenario__collection_date__lte=month_end)

        serializer = RouteSolutionSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)