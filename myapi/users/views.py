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
        By default, excludes archived users unless explicitly requested.
        For the 'restore' action, include archived users so they can be restored.
        Optimized search: only applies search for queries with at least 2 characters.
        """
        queryset = User.objects.filter(is_staff=False)
        requester = self.request.user

        if not requester.is_superuser:
            queryset = queryset.filter(created_by=requester)

        # Apply search filter first, before other filters
        # Minimum 2 characters to prevent expensive queries on short inputs
        search = self.request.query_params.get("search", "").strip()
        if search and len(search) >= 2:
            queryset = queryset.filter(username__icontains=search)

        # For restore, don't apply the default is_archived=False filter
        if getattr(self, "action", None) == "restore":
            # Still allow explicit query param filters if you want
            roles = self.request.query_params.getlist("role")
            if roles:
                queryset = queryset.filter(role__in=roles)

            status_list = self.request.query_params.getlist("is_active")
            if status_list:
                bool_map = {"true": True, "1": True, "false": False, "0": False}
                parsed = [bool_map.get(s.lower()) for s in status_list if s.lower() in bool_map]
                if parsed:
                    queryset = queryset.filter(is_active__in=parsed)

            # IMPORTANT: no default is_archived filter here
            return queryset.order_by("-date_joined")

        # Existing logic for all other actions
        roles = self.request.query_params.getlist("role")
        if roles:
            queryset = queryset.filter(role__in=roles)

        status_list = self.request.query_params.getlist("is_active")
        if status_list:
            bool_map = {"true": True, "1": True, "false": False, "0": False}
            parsed = [bool_map.get(s.lower()) for s in status_list if s.lower() in bool_map]
            if parsed:
                queryset = queryset.filter(is_active__in=parsed)

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

        # Create user with unusable password and inactive status
        user = User.objects.create_user(
            email=serializer.validated_data["email"],
            password=None,  # This triggers set_unusable_password() and is_active=False
            username=serializer.validated_data["username"],
            role=role,
            phone=serializer.validated_data.get("phone", ""),
            image_profile=serializer.validated_data.get("image_profile"),
            created_by=request.user,
        )

        # Ensure is_active is False (should already be set by create_user)
        user.is_active = False
        user.save(update_fields=["is_active"])



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
