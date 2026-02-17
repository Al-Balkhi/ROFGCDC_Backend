from rest_framework import permissions
from accounts.models import User


class IsAdmin(permissions.BasePermission):
    """Permission to allow only Admin role."""
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role == User.Roles.ADMIN
        )


class IsAdminOrPlanner(permissions.BasePermission):
    """Permission to allow Admin or Planner roles."""
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in [User.Roles.ADMIN, User.Roles.PLANNER]
        )


class IsPlannerOrAdmin(permissions.BasePermission):
    """Permission to allow only Planner or Admin roles."""
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in [User.Roles.PLANNER, User.Roles.ADMIN]
        )


class IsPlanner(permissions.BasePermission):
    """Permission to allow only Planner role."""
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role == User.Roles.PLANNER
        )
