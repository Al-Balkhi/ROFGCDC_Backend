"""
accounts/notification_views.py

Notification management views — separated from auth views (accounts/views.py)
because notifications are orthogonal to the authentication domain.
"""
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .authentication import CookieJWTAuthentication
from .models import Notification
from .serializers import NotificationSerializer


class NotificationPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class NotificationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for the authenticated user's notifications.

    Supported actions:
        list            GET  /notifications/
        retrieve        GET  /notifications/<pk>/
        mark_read       POST /notifications/<pk>/read/
        mark_all_read   POST /notifications/read-all/
        clear_all       DEL  /notifications/clear-all/

    Filtering:
        ?is_read=true  — return only read notifications
        ?is_read=false — return only unread notifications
    """
    serializer_class = NotificationSerializer
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = NotificationPagination
    # Disable create / update / partial_update / destroy from the default
    # ModelViewSet surface; mutations go through dedicated @action endpoints.
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        queryset = (
            Notification.objects
            .filter(user=self.request.user)
            .order_by('-created_at')
        )
        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            is_read_lower = is_read.lower()
            if is_read_lower == 'true':
                queryset = queryset.filter(is_read=True)
            elif is_read_lower == 'false':
                queryset = queryset.filter(is_read=False)
        return queryset

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        """Mark a single notification as read."""
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response({"message": "Notification marked as read."})

    @action(detail=False, methods=['post'], url_path='read-all')
    def mark_all_read(self, request):
        """Mark all of the current user's unread notifications as read."""
        count = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"message": f"{count} notifications marked as read."})

    @action(detail=False, methods=['delete'], url_path='clear-all')
    def clear_all(self, request):
        """Permanently delete all of the current user's notifications."""
        self.get_queryset().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
