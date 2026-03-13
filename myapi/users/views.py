from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.authentication import CookieJWTAuthentication
from accounts.models import OneTimePassword
from accounts.services import OTPService, OTPServiceError
from .permissions import IsAdminRole
from .serializers import (
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
)
from .pagination import UserPagination

User = get_user_model()

# Mapping for query-param boolean strings, shared by the filter helper below.
_BOOL_MAP = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}


def _apply_common_filters(queryset, request):
    """
    Apply role and is_active list-filters from query params to a user queryset.
    Both params accept multiple values:
        ?role=driver&role=planner
        ?is_active=true&is_active=false
    """
    roles = request.query_params.getlist("role")
    if roles:
        queryset = queryset.filter(role__in=roles)

    status_list = request.query_params.getlist("is_active")
    if status_list:
        parsed = [_BOOL_MAP[s.lower()] for s in status_list if s.lower() in _BOOL_MAP]
        if parsed:
            queryset = queryset.filter(is_active__in=parsed)

    return queryset


class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for admin-only user management operations.
    Supports CRUD operations with soft-delete (archiving), pagination, filtering, and search.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminRole]
    pagination_class = UserPagination
    filter_backends = [SearchFilter]
    search_fields = ["username"]

    def get_queryset(self):
        """
        Return queryset filtered by request parameters.
        By default excludes archived users unless explicitly requested.
        For the 'restore' action, archived users are included so they can be
        found and restored.  Search is only applied for queries >= 2 chars.
        """
        queryset = User.objects.filter(is_staff=False)
        requester = self.request.user

        if not requester.is_superuser:
            queryset = queryset.filter(created_by=requester)

        # Minimum 2 characters to avoid expensive queries on very short inputs.
        search = self.request.query_params.get("search", "").strip()
        if search and len(search) >= 2:
            queryset = queryset.filter(username__icontains=search)

        # For restore: include archived users; skip the default is_archived=False.
        if getattr(self, "action", None) == "restore":
            queryset = _apply_common_filters(queryset, self.request)
            # IMPORTANT: no default is_archived filter for the restore action.
            return queryset.order_by("-date_joined")

        # All other actions: apply role/status filters then archived default.
        queryset = _apply_common_filters(queryset, self.request)

        is_archived = self.request.query_params.get("is_archived", None)
        if is_archived is not None:
            is_archived_bool = is_archived.lower() in ("true", "1", "yes")
            queryset = queryset.filter(is_archived=is_archived_bool)
        else:
            queryset = queryset.filter(is_archived=False)

        return queryset.order_by("-date_joined")

    def get_serializer_class(self):
        """
        Return appropriate serializer class based on action.
        """
        if self.action == "list":
            return UserListSerializer
        elif self.action == "create":
            return UserCreateSerializer
        elif self.action == "update" or self.action == "partial_update":
            return UserUpdateSerializer
        return UserDetailSerializer

    def create(self, request, *args, **kwargs):
        """
        Create a new user without a password.
        Sets is_active=False and triggers INITIAL_SETUP OTP.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        role = serializer.validated_data.get("role", User.Roles.DRIVER)

        if role == User.Roles.ADMIN and not request.user.is_superuser:
            return Response(
                {"detail": "Only superuser can create admin users."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Create user with unusable password and inactive status.
        # create_user(password=None) calls set_unusable_password() and sets
        # is_active=False automatically via UserManager — no extra save needed.
        user = User.objects.create_user(
            email=serializer.validated_data["email"],
            password=None,
            username=serializer.validated_data["username"],
            role=role,
            phone=serializer.validated_data.get("phone", ""),
            image_profile=serializer.validated_data.get("image_profile"),
            created_by=request.user,
        )

        # Return created user details
        response_serializer = UserDetailSerializer(user)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"])
    def archive(self, request, pk=None):
        """
        Archive a user (soft delete).
        Sets is_archived=True and is_active=False.
        """
        user = self.get_object()
        user.is_archived = True
        user.is_active = False
        user.save(update_fields=["is_archived", "is_active"])

        serializer = UserDetailSerializer(user)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"])
    def restore(self, request, pk=None):
        """
        Restore an archived user.
        Sets is_archived=False and is_active=True.
        """
        user = self.get_object()
        user.is_archived = False
        user.is_active = True
        user.save(update_fields=["is_archived", "is_active"])

        serializer = UserDetailSerializer(user)
        return Response(serializer.data)
