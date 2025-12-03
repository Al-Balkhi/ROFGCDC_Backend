from rest_framework import permissions
from django.contrib.auth import get_user_model

User = get_user_model()


class IsAdminRole(permissions.BasePermission):
    """
    Permission class that checks if the user has admin role.
    Only users with role == "admin" can access the endpoints.
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Roles.ADMIN
        )

