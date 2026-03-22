from rest_framework import serializers
from .models import Report, ReportMedia, BinRequest, DeviceFingerprint
from optimization.serializers import MunicipalitySerializer, BinSerializer
from optimization.models import Municipality
from accounts.models import User
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance




class ReportMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportMedia
        fields = ['id', 'image', 'description', 'created_at']


class ReportSerializer(serializers.ModelSerializer):
    media = ReportMediaSerializer(many=True, read_only=True)
    municipality_name = serializers.CharField(source='municipality.name', read_only=True)
    latitude = serializers.FloatField(write_only=True)
    longitude = serializers.FloatField(write_only=True)

    class Meta:
        model = Report
        fields = [
            'id', 'municipality', 'municipality_name', 'latitude', 'longitude', 
            'description', 'issue_type', 'urgency_score', 'status', 'created_at', 'updated_at', 'media'
        ]
        read_only_fields = ['id', 'municipality', 'urgency_score', 'status', 'created_at', 'updated_at']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.location:
            ret['latitude'] = instance.location.y
            ret['longitude'] = instance.location.x
        return ret

    def create(self, validated_data):
        request = self.context.get('request')
        device_id = request.data.get('device_id', 'unknown')
        ip_address = self._get_client_ip(request)

        device, _ = DeviceFingerprint.objects.get_or_create(
            device_id=device_id,
            defaults={'ip_address': ip_address}
        )

        if device.is_blocked:
            raise serializers.ValidationError("This device is blocked from submitting reports.")

        # Find closest municipality
        lat = validated_data.pop('latitude', None)
        lon = validated_data.pop('longitude', None)
        
        if lat is None or lon is None:
            raise serializers.ValidationError("Latitude and longitude are required.")
            
        point = Point(lon, lat, srid=4326)
        validated_data['location'] = point
        
        # Native PostGIS distance search
        closest_muni = Municipality.objects.filter(hq_location__isnull=False).annotate(
            distance=Distance('hq_location', point)
        ).order_by('distance').first()

        if not closest_muni:
            # Fallback if no HQ locations
            closest_muni = Municipality.objects.first()
            if not closest_muni:
                raise serializers.ValidationError("No municipalities exist in the system.")
            
        validated_data['municipality'] = closest_muni

        # Check for existing reports within 10 meters using DWithin
        existing_report = Report.objects.filter(
            status=Report.Status.PENDING,
            municipality=closest_muni,
            location__distance_lte=(point, D(m=10))
        ).first()

        NO_CONTAINER_BONUS = 3
        issue_type = validated_data.get('issue_type') or Report.IssueType.CONTAINER_FULL

        # IMPORTANT: Don't merge a "container full" submission into an existing
        # "no container" report. Otherwise the location becomes permanently
        # stuck as "no container" once such a report exists within the merge radius,
        # which makes clients appear to always submit "no bin".
        if (
            existing_report
            and existing_report.issue_type == Report.IssueType.NO_CONTAINER
            and issue_type == Report.IssueType.CONTAINER_FULL
        ):
            existing_report = None
                
        if existing_report:
            existing_report.urgency_score += 1

            # Escalate priority/type if a "no container" report is merged into an existing one
            if issue_type == Report.IssueType.NO_CONTAINER and existing_report.issue_type != Report.IssueType.NO_CONTAINER:
                existing_report.issue_type = Report.IssueType.NO_CONTAINER
                existing_report.urgency_score += NO_CONTAINER_BONUS

            if 'description' in validated_data and validated_data['description']:
                if existing_report.description:
                    existing_report.description += f"\n---\n{validated_data['description']}"
                else:
                    existing_report.description = validated_data['description']
            existing_report.save()
            existing_report.devices.add(device)
            return existing_report
        else:
            # Boost baseline urgency for "no container" reports
            if issue_type == Report.IssueType.NO_CONTAINER:
                validated_data['urgency_score'] = int(validated_data.get('urgency_score') or 1) + NO_CONTAINER_BONUS
            report = Report.objects.create(**validated_data)
            report.devices.add(device)
            return report

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class BinRequestSerializer(serializers.ModelSerializer):
    report_details = ReportSerializer(source='report', read_only=True)
    planner_name = serializers.CharField(source='planner.username', read_only=True)
    admin_name = serializers.CharField(source='admin.username', read_only=True)
    target_bin_details = BinSerializer(source='target_bin', read_only=True)

    class Meta:
        model = BinRequest
        fields = [
            'id', 'planner', 'planner_name', 'admin', 'admin_name', 'report', 
            'report_details', 'request_type', 'target_bin', 'target_bin_details', 
            'status', 'note', 'requested_capacity', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'planner', 'admin', 'status', 'created_at', 'updated_at']

