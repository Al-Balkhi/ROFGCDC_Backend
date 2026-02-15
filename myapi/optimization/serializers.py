from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from .models import Bin, Vehicle, Scenario, RouteSolution, Municipality, Landfill
from .validators import (
    DAMASCUS_LAT_MIN, DAMASCUS_LAT_MAX,
    DAMASCUS_LON_MIN, DAMASCUS_LON_MAX
)


class DamascusLocationMixin:
    """Mixin to centralize coordinate validation for Damascus."""
    
    def _validate_coord(self, value, min_val, max_val, coord_name):
        if value is not None:
            if value < min_val or value > max_val:
                raise serializers.ValidationError(
                    f'الإحداثيات خارج حدود مدينة دمشق. {coord_name} يجب أن يكون بين {min_val} و {max_val}'
                )
        return value

    def validate_latitude(self, value):
        return self._validate_coord(value, DAMASCUS_LAT_MIN, DAMASCUS_LAT_MAX, "خط العرض")

    def validate_longitude(self, value):
        return self._validate_coord(value, DAMASCUS_LON_MIN, DAMASCUS_LON_MAX, "خط الطول")
    
    # Aliases for models using specific field names
    def validate_hq_latitude(self, value):
        return self.validate_latitude(value)

    def validate_hq_longitude(self, value):
        return self.validate_longitude(value)
    
    def validate_start_latitude(self, value):
        return self.validate_latitude(value)

    def validate_start_longitude(self, value):
        return self.validate_longitude(value)


class MunicipalitySerializer(DamascusLocationMixin, serializers.ModelSerializer):
    class Meta:
        model = Municipality
        fields = ['id', 'name', 'hq_latitude', 'hq_longitude', 'description']
        read_only_fields = ['id']


class LandfillSerializer(DamascusLocationMixin, serializers.ModelSerializer):
    municipalities = MunicipalitySerializer(many=True, read_only=True)
    municipality_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Municipality.objects.all(), source='municipalities',
        write_only=True, required=False,
    )

    class Meta:
        model = Landfill
        fields = ['id', 'name', 'latitude', 'longitude', 'description', 'municipalities', 'municipality_ids']
        read_only_fields = ['id']


class BinSerializer(DamascusLocationMixin, serializers.ModelSerializer):
    municipality = MunicipalitySerializer(read_only=True)
    municipality_id = serializers.PrimaryKeyRelatedField(
        queryset=Municipality.objects.all(), source='municipality',
        write_only=True,
    )

    class Meta:
        model = Bin
        fields = ['id', 'name', 'latitude', 'longitude', 'capacity', 'is_active', 
                  'municipality', 'municipality_id', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BinAvailableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bin
        fields = ['id', 'name', 'latitude', 'longitude', 'capacity']
        read_only_fields = ['id']


class VehicleSerializer(serializers.ModelSerializer):
    municipality = MunicipalitySerializer(read_only=True)
    municipality_id = serializers.PrimaryKeyRelatedField(
        queryset=Municipality.objects.all(), source='municipality',
        write_only=True,
    )

    class Meta:
        model = Vehicle
        fields = ['id', 'name', 'capacity', 'municipality', 'municipality_id', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class RouteSolutionSlimSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouteSolution
        fields = ['id', 'total_distance', 'created_at']
        read_only_fields = ['id', 'created_at']


class ScenarioSerializer(serializers.ModelSerializer):
    municipality = MunicipalitySerializer(read_only=True)
    municipality_id = serializers.PrimaryKeyRelatedField(queryset=Municipality.objects.all(), source='municipality', write_only=True)
    vehicle = VehicleSerializer(read_only=True)
    vehicle_id = serializers.PrimaryKeyRelatedField(queryset=Vehicle.objects.all(), source='vehicle', write_only=True)
    start_landfill_id = serializers.PrimaryKeyRelatedField(queryset=Landfill.objects.all(), source='start_landfill', write_only=True, required=False, allow_null=True)
    bins = BinSerializer(many=True, read_only=True)
    bin_ids = serializers.PrimaryKeyRelatedField(many=True, queryset=Bin.objects.all(), source='bins', write_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    solutions = RouteSolutionSlimSerializer(many=True, read_only=True)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Scenario
        fields = [
            'id', 'name', 'description', 'municipality', 'municipality_id',
            'start_latitude', 'start_longitude', 'collection_date',
            'vehicle', 'vehicle_id', 'bins', 'bin_ids', 'created_by',
            'solutions', 'start_landfill_id', 'is_expired', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at', 'is_expired']

    def get_is_expired(self, obj):
        today = timezone.localdate()
        return obj.collection_date < today

    def validate_collection_date(self, value):
        today = timezone.localdate()
        max_date = today + timedelta(days=180)
        if value < today:
            raise serializers.ValidationError('لا يمكن تحديد تاريخ في الماضي.')
        if value > max_date:
            raise serializers.ValidationError('يمكن تحديد موعد ضمن ستة أشهر فقط.')
        return value

    def validate(self, attrs):
        # 1. Resolve Basic Fields
        vehicle = attrs.get('vehicle') or getattr(self.instance, 'vehicle', None)
        start_landfill = attrs.pop('start_landfill', None)
        start_lat = attrs.get('start_latitude')
        start_lon = attrs.get('start_longitude')
        
        # Resolve Date (New vs Update)
        collection_date = attrs.get('collection_date')
        if not collection_date and self.instance:
            collection_date = self.instance.collection_date
            
        # 2. Validate Bins
        bins = attrs.get('bins')
        if bins is not None:  # Only validate if bins are being set/changed
            if not bins:
                raise serializers.ValidationError({'bins': 'يجب اختيار حاوية واحدة على الأقل.'})
            
            inactive = [b.name for b in bins if not b.is_active]
            if inactive:
                raise serializers.ValidationError({'bins': f'الحاويات التالية غير نشطة: {", ".join(inactive)}'})
            
            # Logic Fix: Check Availability Scoped by Date
            if collection_date:  # Only check if we have a date
                exclude_args = {'pk': self.instance.pk} if self.instance else {}
                conflicting = Scenario.objects.filter(
                    bins__in=bins,
                    collection_date=collection_date
                ).exclude(**exclude_args).distinct()
                
                if conflicting.exists():
                    raise serializers.ValidationError({'bins': 'بعض الحاويات مستخدمة في خطة أخرى في نفس التاريخ.'})

        # 3. Check Vehicle Availability (scoped by date)
        if vehicle and collection_date:
            exclude_args = {'pk': self.instance.pk} if self.instance else {}
            in_use = Scenario.objects.filter(
                vehicle=vehicle, 
                collection_date=collection_date
            ).exclude(**exclude_args).exists()
            
            if in_use:
                raise serializers.ValidationError({'vehicle': 'المركبة مستخدمة في خطة أخرى في نفس التاريخ.'})

        # 4. Handle Start Location (Keep existing logic)
        if start_landfill:
            start_lat, start_lon = start_landfill.latitude, start_landfill.longitude
        elif vehicle and start_lat is None:
            start_lat, start_lon = vehicle.municipality.hq_latitude, vehicle.municipality.hq_longitude
            if start_lat is None or start_lon is None:
                raise serializers.ValidationError({'vehicle': 'بلدية المركبة لا تملك إحداثيات مركز (HQ).'})

        attrs['start_latitude'] = start_lat
        attrs['start_longitude'] = start_lon
        return attrs

    def _auto_name(self, municipality, provided_name: str) -> str:
        if provided_name:
            return provided_name
        count = Scenario.objects.filter(municipality=municipality).count() + 1
        return f"خطة {count} – منطقة {municipality.name}"

    def create(self, validated_data):
        bins = validated_data.pop('bins')
        municipality = validated_data.get('municipality')
        validated_data['name'] = self._auto_name(municipality, validated_data.get('name', ''))
        validated_data['created_by'] = self.context['request'].user
        scenario = Scenario.objects.create(**validated_data)
        scenario.bins.set(bins)
        return scenario

    def update(self, instance, validated_data):
        bins = validated_data.pop('bins', None)
        incoming_vehicle = validated_data.get('vehicle')
        
        bins_changed = bins is not None
        vehicle_changed = incoming_vehicle is not None and incoming_vehicle != instance.vehicle
        start_changed = any(f in validated_data for f in ['start_latitude', 'start_longitude'])

        if 'name' in validated_data:
            validated_data['name'] = self._auto_name(
                validated_data.get('municipality', instance.municipality),
                validated_data.get('name', '')
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if bins is not None:
            instance.bins.set(bins)

        if bins_changed or vehicle_changed or start_changed:
            instance.solutions.all().delete()

        return instance


class RouteSolutionSerializer(serializers.ModelSerializer):
    scenario = ScenarioSerializer(read_only=True)
    scenario_id = serializers.PrimaryKeyRelatedField(
        queryset=Scenario.objects.all(), source='scenario', write_only=True, required=False
    )
    class Meta:
        model = RouteSolution
        fields = ['id', 'scenario', 'scenario_id', 'created_at', 'total_distance', 'data']
        read_only_fields = ['id', 'created_at']
