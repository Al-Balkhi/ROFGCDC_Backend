from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class UserListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing users with limited fields.
    Used in the list action of UserViewSet.
    """

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "role",
            "is_active",
            "is_archived",
        ]
        read_only_fields = ["id", "email"]


class UserDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for full user profile details.
    Used in the retrieve action of UserViewSet.
    Excludes password fields.
    """

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "phone",
            "image_profile",
            "role",
            "is_active",
            "is_archived",
            "is_staff",
            "date_joined",
            "last_login_at",
            "last_logout_at",
            "last_password_change_at",
            "last_password_change_reason",
        ]
        read_only_fields = [
            "id",
            "email",
            "is_staff",
            "date_joined",
            "last_login_at",
            "last_logout_at",
            "last_password_change_at",
            "last_password_change_reason",
        ]


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating new users.
    Admin provides: email, username, role, phone (optional), image_profile (optional).
    """

    class Meta:
        model = User
        fields = [
            "email",
            "username",
            "role",
            "phone",
            "image_profile",
        ]

    def validate_email(self, value):
        """Ensure email is unique."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating users.
    Admin can edit: username, role, phone, image_profile.
    Email is not editable.
    """

    class Meta:
        model = User
        fields = [
            "username",
            "role",
            "phone",
            "image_profile",
        ]

