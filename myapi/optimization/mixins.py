"""
optimization/mixins.py
~~~~~~~~~~~~~~~~~~~~~~

Reusable mixins for the optimization app.

  GeoPointSerializerMixin   — Centralises the lat/lon float → GeoDjango
                               Point conversion that was copy-pasted across
                               every geo-serializer (Bin, Landfill, Municipality,
                               Scenario).  Subclasses override three class
                               attributes to match their model's field names.

  CreatorScopedViewSetMixin  — Wraps the creator-based multi-tenancy scoping
                               logic into a reusable ViewSet mixin so the rule
                               "who can see what" lives in exactly one place.
"""
from __future__ import annotations

from django.contrib.gis.geos import Point
from django.db.models import Q


# ---------------------------------------------------------------------------
# Serializer mixin
# ---------------------------------------------------------------------------

class GeoPointSerializerMixin:
    """
    DRF serializer mixin that converts a ``latitude`` + ``longitude`` pair
    into a single GeoDjango ``Point`` field on create and update.

    Subclasses may override the three class attributes to match their model::

        class MySerializer(GeoPointSerializerMixin, ModelSerializer):
            _lat_field   = 'latitude'    # readable float field
            _lon_field   = 'longitude'   # readable float field
            _point_field = 'location'    # model PointField

    Serializers with additional create/update logic (e.g. ScenarioSerializer)
    should call ``self._build_point(validated_data)`` explicitly instead of
    relying on the mixin's auto-applied create() / update().
    """

    _lat_field: str = 'latitude'
    _lon_field: str = 'longitude'
    _point_field: str = 'location'

    def _build_point(self, validated_data: dict) -> dict:
        """
        Pop lat/lon from *validated_data*, build a Point, and insert it under
        *_point_field*.  Mutates in-place **and** returns the dict so callers
        can chain: ``validated_data = self._build_point(validated_data)``.
        """
        lat = validated_data.pop(self._lat_field, None)
        lon = validated_data.pop(self._lon_field, None)
        if lat is not None and lon is not None:
            validated_data[self._point_field] = Point(lon, lat, srid=4326)
        return validated_data

    def create(self, validated_data):
        self._build_point(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._build_point(validated_data)
        # Explicitly set the point on the instance so partial updates work
        # even when the underlying super().update() doesn't iterate over every
        # field.
        if self._point_field in validated_data:
            setattr(instance, self._point_field, validated_data.pop(self._point_field))
        return super().update(instance, validated_data)


# ---------------------------------------------------------------------------
# ViewSet mixin
# ---------------------------------------------------------------------------

class CreatorScopedViewSetMixin:
    """
    ViewSet mixin that restricts querysets to objects the requesting user is
    entitled to see, based on their role:

    ==============================  ===========================================
    Role                            Visible objects
    ==============================  ===========================================
    Superuser                       Everything — no restriction.
    Admin                           Objects they created **or** objects created
                                     by planners that they created (one level of
                                     delegation).
    Planner                         Objects they created **or** objects created
                                     by the admin who created them (shared
                                     intra-admin visibility).
    Any other authenticated role    Empty queryset.
    ==============================  ===========================================

    Usage::

        class MyViewSet(CreatorScopedViewSetMixin, viewsets.ModelViewSet):
            def get_queryset(self):
                qs = super().get_queryset()
                return self.scope_by_creator(qs)
    """

    def scope_by_creator(self, qs):
        """Return *qs* filtered to objects the current user may see."""
        user = self.request.user

        if user.is_superuser:
            return qs

        if user.role == user.Roles.ADMIN:
            # Admin sees objects they created OR objects by their planners.
            return qs.filter(
                Q(created_by=user) | Q(created_by__created_by=user)
            )

        if user.role == user.Roles.PLANNER:
            # Planner sees their own objects OR objects by the same admin.
            if user.created_by_id:
                return qs.filter(
                    Q(created_by=user) | Q(created_by_id=user.created_by_id)
                )
            return qs.filter(created_by=user)

        return qs.none()
