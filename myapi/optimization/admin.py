from django.contrib import admin
from .models import Bin, Vehicle, Scenario, RouteSolution, Municipality, Landfill


@admin.register(Bin)
class BinAdmin(admin.ModelAdmin):
    list_display = ['name', 'latitude', 'longitude', 'capacity', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['name', 'capacity', 'municipality', 'created_at']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Municipality)
class MunicipalityAdmin(admin.ModelAdmin):
    list_display = ['name', 'hq_latitude', 'hq_longitude']
    search_fields = ['name']


@admin.register(Landfill)
class LandfillAdmin(admin.ModelAdmin):
    list_display = ['name', 'latitude', 'longitude']
    search_fields = ['name']
    filter_horizontal = ['municipalities']


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ['name', 'municipality', 'vehicle', 'collection_date', 'created_by', 'created_at']
    list_filter = ['collection_date', 'created_at', 'municipality']
    search_fields = ['name', 'description']
    filter_horizontal = ['bins']
    readonly_fields = ['created_at', 'updated_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by', 'municipality', 'vehicle')


@admin.register(RouteSolution)
class RouteSolutionAdmin(admin.ModelAdmin):
    list_display = ['scenario', 'total_distance', 'created_at']
    list_filter = ['created_at']
    readonly_fields = ['created_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('scenario')
