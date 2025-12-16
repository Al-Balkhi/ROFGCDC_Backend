from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BinViewSet,
    VehicleViewSet,
    ScenarioViewSet,
    SolveScenarioView,
    RouteSolutionDetailView,
    RouteSolutionListView,
    MunicipalityViewSet,
    LandfillViewSet,
    AvailableBinList,
)

router = DefaultRouter()
router.register(r'bins', BinViewSet, basename='bin')
router.register(r'vehicles', VehicleViewSet, basename='vehicle')
router.register(r'scenarios', ScenarioViewSet, basename='scenario')
router.register(r'municipalities', MunicipalityViewSet, basename='municipality')
router.register(r'landfills', LandfillViewSet, basename='landfill')

urlpatterns = [
    
    path('bins/available/', AvailableBinList.as_view(), name='available-bins'), 
    path('scenarios/<int:pk>/solve/', SolveScenarioView.as_view(), name='scenario-solve'),
    path('solutions/', RouteSolutionListView.as_view(), name='solution-list'),
    path('solutions/<int:pk>/', RouteSolutionDetailView.as_view(), name='solution-detail'),

    path('', include(router.urls)),
]