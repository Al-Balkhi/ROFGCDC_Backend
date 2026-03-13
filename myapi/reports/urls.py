from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CitizenReportViewSet, PlannerReportViewSet, AdminBinRequestViewSet

router = DefaultRouter()
router.register(r'submit', CitizenReportViewSet, basename='citizen-report')
router.register(r'planner', PlannerReportViewSet, basename='planner-report')
router.register(r'bin-requests', AdminBinRequestViewSet, basename='admin-bin-request')

urlpatterns = [
    path('', include(router.urls)),
]
