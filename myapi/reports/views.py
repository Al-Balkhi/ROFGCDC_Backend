import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from .models import Report, BinRequest, DeviceFingerprint, ReportMedia
from .serializers import ReportSerializer, BinRequestSerializer
from .services import create_immediate_plan
from .throttles import DeviceAndIPRateThrottle
from accounts.models import Notification, User
from accounts.serializers import NotificationSerializer
from optimization.models import Scenario, Bin
from datetime import date

logger = logging.getLogger(__name__)


class CitizenReportViewSet(viewsets.GenericViewSet):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = ReportSerializer
    throttle_classes = [DeviceAndIPRateThrottle]

    def create(self, request):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            logger.warning("CitizenReportViewSet: serializer validation failed: %s", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        report = serializer.save()

        # Handle photos (ReportMedia) files
        photos = request.FILES.getlist('photos')
        device_id = request.data.get('device_id', 'unknown')
        device = DeviceFingerprint.objects.filter(device_id=device_id).first()
        
        for photo in photos:
            ReportMedia.objects.create(
                report=report,
                device=device,
                image=photo
            )

        if report.municipality:
            planners = []
            if report.municipality.planner:
                planners.append(report.municipality.planner)
            
            fallback_planners = User.objects.filter(role=User.Roles.PLANNER, municipality=report.municipality)
            for p in fallback_planners:
                if p not in planners:
                    planners.append(p)

            for planner in planners:
                Notification.objects.create(
                    user=planner,
                    title=_("بلاغ جديد"),
                    message=f"تم استلام بلاغ جديد ({report.get_issue_type_display()}) في منطقتك.",
                    type="citizen_report",
                    related_id=report.id
                )

        return Response(
            {"message": "Report submitted successfully.", "report_id": report.id},
            status=status.HTTP_201_CREATED
        )


class PlannerReportViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ReportSerializer
    queryset = Report.objects.all().order_by('-urgency_score', '-created_at')

    def get_queryset(self):
        user = self.request.user
        if user.role != User.Roles.PLANNER:
            return Report.objects.none()

        # Prefer explicit municipality->planner assignment when available
        from optimization.models import Municipality  # local import to avoid circular

        assigned_municipalities = Municipality.objects.filter(planner=user)
        if assigned_municipalities.exists():
            return Report.objects.filter(municipality__in=assigned_municipalities)

        # Fallback to legacy single municipality on the user, if set
        if user.municipality:
            return Report.objects.filter(municipality=user.municipality)

        return Report.objects.none()

    @action(detail=True, methods=['post'], url_path='plan')
    def create_plan(self, request, pk=None):
        """
        Create an immediate same-day collection scenario for a pending report.
        """
        report = self.get_object()
        user = request.user

        if report.status != Report.Status.PENDING:
            return Response(
                {"error": "Report is not pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            scenario = create_immediate_plan(report, created_by=user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        report.assigned_scenario = scenario
        report.status = Report.Status.PROCESSING
        report.save(update_fields=["assigned_scenario", "status"])

        return Response(
            {"message": "Plan created and route generated successfully.", "scenario_id": scenario.id}
        )

    @action(detail=True, methods=['post'], url_path='request-bin')
    def request_bin(self, request, pk=None):
        """
        Submit a bin request (new bin or resize) for a pending/processing report.
        Notifies the admin who created this planner.
        """
        report = self.get_object()
        user = request.user
        request_type = request.data.get('request_type')  # 'new_bin' or 'resize_bin'
        note = request.data.get('note', '')
        requested_capacity = request.data.get('capacity')

        if request_type not in [BinRequest.RequestType.NEW_BIN, BinRequest.RequestType.RESIZE_BIN]:
            return Response({"error": "Invalid request_type"}, status=status.HTTP_400_BAD_REQUEST)

        municipality = report.municipality
        if not municipality:
            return Response({"error": "No municipality assigned to this report."}, status=status.HTTP_400_BAD_REQUEST)

        target_bin = None
        if request_type == BinRequest.RequestType.RESIZE_BIN:
            if not requested_capacity:
                return Response(
                    {"error": "Capacity is required for resize bin request"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from django.contrib.gis.measure import D
            target_bin = Bin.objects.filter(
                municipality=municipality,
                location__distance_lte=(report.location, D(m=10))
            ).first()

            if not target_bin:
                return Response(
                    {"error": "No bin found within 10 meters of the report."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        bin_req = BinRequest.objects.create(
            planner=user,
            report=report,
            request_type=request_type,
            target_bin=target_bin,
            requested_capacity=requested_capacity,
            note=note,
        )

        report.status = Report.Status.PROCESSING
        report.save(update_fields=["status"])

        # Notify the admin who created this planner.
        admin = user.created_by
        if admin and admin.role == User.Roles.ADMIN:
            Notification.objects.create(
                user=admin,
                title=_("طلب حاوية جديد"),
                message=(
                    f"قام المخطط {user.username} بطلب "
                    f"{bin_req.get_request_type_display()} للبلاغ {report.id}."
                ),
                type="container_request",
                related_id=bin_req.id,
            )

        return Response({"message": "Bin request submitted and Admin notified.", "bin_request_id": bin_req.id})


class AdminBinRequestViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """
    Admin-only ViewSet for bin requests submitted by planners.

    Intentionally exposes ONLY list and retrieve — create/update/delete
    are not valid operations here. Mutations happen through the dedicated
    /approve/ and /reject/ action endpoints.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = BinRequestSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role != User.Roles.ADMIN:
            return BinRequest.objects.none()

        return BinRequest.objects.filter(planner__created_by=user).order_by('-created_at')

    @action(detail=True, methods=['post'], url_path='approve')
    def approve_request(self, request, pk=None):
        """
        Approve a pending bin request.
        - NEW_BIN: creates a Bin near the report location (averaged over nearby reports).
        - RESIZE_BIN: updates the target bin's capacity.
        Marks the related report as PROCESSED and notifies the planner.
        """
        bin_req = self.get_object()
        user = request.user

        if bin_req.status != BinRequest.Status.PENDING:
            return Response({"error": "Request already processed."}, status=status.HTTP_400_BAD_REQUEST)

        if bin_req.request_type == BinRequest.RequestType.NEW_BIN:
            new_capacity = request.data.get('capacity') or bin_req.requested_capacity or 1100
            new_name = request.data.get('name', f"New Bin {bin_req.report.id}")
            new_address = request.data.get('address', '')

            from django.contrib.gis.measure import D
            from django.contrib.gis.geos import Point

            # Use the spatial average of nearby reports as the bin location.
            nearby = Report.objects.filter(
                municipality=bin_req.report.municipality,
                location__distance_lte=(bin_req.report.location, D(m=10)),
            )
            
            nearby_locations = [r.location for r in nearby if r.location]
            if nearby_locations:
                avg_lon = sum(loc.x for loc in nearby_locations) / len(nearby_locations)
                avg_lat = sum(loc.y for loc in nearby_locations) / len(nearby_locations)
                location = Point(avg_lon, avg_lat, srid=4326)
            else:
                location = bin_req.report.location

            new_bin = Bin.objects.create(
                name=new_name,
                location=location,
                capacity=int(new_capacity),
                municipality=bin_req.report.municipality,
                created_by=user,
                address=new_address,
            )

        elif bin_req.request_type == BinRequest.RequestType.RESIZE_BIN:
            new_capacity = request.data.get('capacity') or bin_req.requested_capacity
            if new_capacity and bin_req.target_bin:
                bin_req.target_bin.capacity = int(new_capacity)
                bin_req.target_bin.save(update_fields=['capacity'])

        bin_req.status = BinRequest.Status.APPROVED
        bin_req.admin = user
        bin_req.save(update_fields=['status', 'admin'])

        report = bin_req.report
        report.status = Report.Status.PROCESSED
        report.save(update_fields=['status'])

        Notification.objects.create(
            user=bin_req.planner,
            title=_("الموافقة على طلب الحاوية"),
            message=(
                f"تمت الموافقة على طلب '{bin_req.get_request_type_display()}' "
                f"الخاص بك من قبل المسؤول {user.username}."
            ),
        )

        return Response({"message": "Bin request approved."})

    @action(detail=True, methods=['post'], url_path='reject')
    def reject_request(self, request, pk=None):
        """
        Reject a pending bin request.
        Automatically creates an immediate collection plan as a fallback
        and notifies the planner of both the rejection and the new plan.
        """
        bin_req = self.get_object()
        user = request.user
        reason = request.data.get("reason", "No reason provided.")

        if bin_req.status != BinRequest.Status.PENDING:
            return Response({"error": "Request already processed."}, status=status.HTTP_400_BAD_REQUEST)

        bin_req.status = BinRequest.Status.REJECTED
        bin_req.admin = user
        bin_req.note = reason
        bin_req.save(update_fields=['status', 'admin', 'note'])

        # Fall back to an immediate collection plan.
        report = bin_req.report

        # If the request had a target_bin, pre-add it to the scenario via
        # the service (closest-bin logic runs inside; target_bin is already
        # the closest, so it will be selected).
        try:
            scenario = create_immediate_plan(
                report,
                created_by=user,
                name_prefix="Immediate Plan (Rejected Bin)",
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        report.assigned_scenario = scenario
        report.status = Report.Status.PROCESSING
        report.save(update_fields=["assigned_scenario", "status"])

        Notification.objects.create(
            user=bin_req.planner,
            title=_("رفض طلب الحاوية"),
            message=(
                f"تم رفض طلب '{bin_req.get_request_type_display()}' الخاص بك "
                f"من قبل المسؤول {user.username}. "
                f"تمت جدولة خطة جمع فورية تلقائيًا. السبب: {reason}"
            ),
            type="plan_created",
            related_id=scenario.id,
        )

        return Response({"message": "Bin request rejected and converted to plan."})

