from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from .models import (
    Bin,
    Vehicle,
    Scenario,
    RouteSolution,
    Municipality,
    Landfill,
    ScenarioTemplate,
)
from .validators import (
    DAMASCUS_LAT_MIN, DAMASCUS_LAT_MAX,
    DAMASCUS_LON_MIN, DAMASCUS_LON_MAX
)


class DamascusLocationMixin:
    def _validate_coord(self, value, min_val, max_val, coord_name):
        if value is not None and (value < min_val or value > max_val):
            raise serializers.ValidationError(
                f'الإحداثيات خارج حدود مدينة دمشق. {coord_name} يجب أن يكون بين {min_val} و {max_val}'
            )
        return value

    def validate_latitude(self, value):
        return self._validate_coord(value, DAMASCUS_LAT_MIN, DAMASCUS_LAT_MAX, "خط العرض")

    def validate_longitude(self, value):
        return self._validate_coord(value, DAMASCUS_LON_MIN, DAMASCUS_LON_MAX, "خط الطول")

    def validate_hq_latitude(self, value):
        return self.validate_latitude(value)

    def validate_hq_longitude(self, value):
        return self.validate_longitude(value)

    def validate_start_latitude(self, value):
        return self.validate_latitude(value)

    def validate_start_longitude(self, value):
        return self.validate_longitude(value)


class MunicipalitySerializer(DamascusLocationMixin, serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Municipality
        fields = ['id', 'name', 'hq_latitude', 'hq_longitude', 'created_by']
        read_only_fields = ['id', 'created_by']


class LandfillSerializer(DamascusLocationMixin, serializers.ModelSerializer):
    municipalities = MunicipalitySerializer(many=True, read_only=True)
    municipality_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Municipality.objects.all(), source='municipalities',
        write_only=True, required=False,
    )

    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Landfill
        fields = ['id', 'name', 'latitude', 'longitude', 'municipalities', 'municipality_ids', 'created_by']
        read_only_fields = ['id', 'created_by']


class BinSerializer(DamascusLocationMixin, serializers.ModelSerializer):
    municipality = MunicipalitySerializer(read_only=True)
    municipality_id = serializers.PrimaryKeyRelatedField(
        queryset=Municipality.objects.all(), source='municipality',
        write_only=True,
    )

    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Bin
        fields = ['id', 'name', 'latitude', 'longitude', 'capacity', 'is_active',
                  'municipality', 'municipality_id', 'created_at', 'updated_at', 'created_by']
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']


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

    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Vehicle
        fields = ['id', 'name', 'capacity', 'municipality', 'municipality_id', 'created_at', 'updated_at', 'created_by']
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']


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
    end_landfill = LandfillSerializer(read_only=True)
    end_landfill_id = serializers.PrimaryKeyRelatedField(queryset=Landfill.objects.all(), source='end_landfill', write_only=True)
    bins = BinSerializer(many=True, read_only=True)
    bin_ids = serializers.PrimaryKeyRelatedField(many=True, queryset=Bin.objects.all(), source='bins', write_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    solutions = RouteSolutionSlimSerializer(many=True, read_only=True)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Scenario
        fields = [
            'id', 'name', 'description', 'municipality', 'municipality_id',
            'start_latitude', 'start_longitude', 'collection_date', 'status',
            'vehicle', 'vehicle_id', 'end_landfill', 'end_landfill_id',
            'bins', 'bin_ids', 'created_by', 'solutions',
            'is_expired', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at', 'is_expired']

    def get_is_expired(self, obj):
        return obj.collection_date < timezone.localdate()

    def validate_collection_date(self, value):
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError('لا يمكن تحديد تاريخ في الماضي.')
        if value > today + timedelta(days=180):
            raise serializers.ValidationError('يمكن تحديد موعد ضمن ستة أشهر فقط.')
        return value

    def validate(self, attrs):
        vehicle = attrs.get('vehicle') or getattr(self.instance, 'vehicle', None)
        municipality = attrs.get('municipality') or getattr(self.instance, 'municipality', None)

        end_landfill = attrs.get('end_landfill') or getattr(self.instance, 'end_landfill', None)
        if not end_landfill:
            raise serializers.ValidationError({'end_landfill': 'يجب تحديد المدفن النهائي للخطة.'})

        if vehicle and municipality and vehicle.municipality_id != municipality.id:
            raise serializers.ValidationError({'vehicle': 'المركبة يجب أن تتبع لنفس البلدية.'})

        bins = attrs.get('bins')
        if bins is not None:
            if not bins:
                raise serializers.ValidationError({'bins': 'يجب اختيار حاوية واحدة على الأقل.'})
            inactive = [b.name for b in bins if not b.is_active]
            if inactive:
                raise serializers.ValidationError({'bins': f'الحاويات التالية غير نشطة: {", ".join(inactive)}'})

            if municipality and any(b.municipality_id != municipality.id for b in bins):
                raise serializers.ValidationError({'bins': 'كل الحاويات يجب أن تكون ضمن نفس البلدية.'})

        collection_date = attrs.get('collection_date') or getattr(self.instance, 'collection_date', None)
        if vehicle and collection_date:
            exclude_args = {'pk': self.instance.pk} if self.instance else {}
            in_use = Scenario.objects.filter(vehicle=vehicle, collection_date=collection_date).exclude(**exclude_args).exists()
            if in_use:
                raise serializers.ValidationError({'vehicle': 'المركبة مستخدمة في خطة أخرى في نفس التاريخ.'})

        start_lat = attrs.get('start_latitude')
        start_lon = attrs.get('start_longitude')
        if vehicle and start_lat is None:
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


class ScenarioTemplateSerializer(serializers.ModelSerializer):
    municipality = MunicipalitySerializer(read_only=True)
    municipality_id = serializers.PrimaryKeyRelatedField(queryset=Municipality.objects.all(), source='municipality', write_only=True)
    vehicle = VehicleSerializer(read_only=True)
    vehicle_id = serializers.PrimaryKeyRelatedField(queryset=Vehicle.objects.all(), source='vehicle', write_only=True)
    end_landfill = LandfillSerializer(read_only=True)
    end_landfill_id = serializers.PrimaryKeyRelatedField(queryset=Landfill.objects.all(), source='end_landfill', write_only=True)
    bins = BinSerializer(many=True, read_only=True)
    bin_ids = serializers.PrimaryKeyRelatedField(many=True, queryset=Bin.objects.all(), source='bins', write_only=True)

    class Meta:
        model = ScenarioTemplate
        fields = [
            'id', 'name', 'municipality', 'municipality_id', 'vehicle', 'vehicle_id',
            'end_landfill', 'end_landfill_id', 'bins', 'bin_ids', 'weekdays', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        municipality = attrs.get('municipality')
        vehicle = attrs.get('vehicle')
        bins = attrs.get('bins')

        if municipality and vehicle and vehicle.municipality_id != municipality.id:
            raise serializers.ValidationError({'vehicle': 'المركبة يجب أن تتبع نفس البلدية.'})
        if bins and municipality and any(b.municipality_id != municipality.id for b in bins):
            raise serializers.ValidationError({'bins': 'كل الحاويات يجب أن تكون من نفس البلدية.'})

        return attrs


class RouteSolutionSerializer(serializers.ModelSerializer):
    scenario = ScenarioSerializer(read_only=True)
    scenario_id = serializers.PrimaryKeyRelatedField(
        queryset=Scenario.objects.all(), source='scenario', write_only=True, required=False
    )

    class Meta:
        model = RouteSolution
        fields = ['id', 'scenario', 'scenario_id', 'created_at', 'total_distance', 'data']
        read_only_fields = ['id', 'created_at']
