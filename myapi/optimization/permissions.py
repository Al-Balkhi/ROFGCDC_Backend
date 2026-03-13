from rest_framework import permissions
from accounts.models import User


class IsAdmin(permissions.BasePermission):
    """Allow only Admin role."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Roles.ADMIN
        )


class IsAdminOrPlanner(permissions.BasePermission):
    """Allow Admin or Planner roles."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role in {User.Roles.ADMIN, User.Roles.PLANNER}
        )


# Backward-compatible alias — both names were in use across the codebase.
# Prefer ``IsAdminOrPlanner`` for new code; ``IsPlannerOrAdmin`` will be
# removed in a future clean-up pass once all call sites are migrated.
IsPlannerOrAdmin = IsAdminOrPlanner


class IsPlanner(permissions.BasePermission):
    """Allow only Planner role."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Roles.PLANNER
        )
