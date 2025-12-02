from django.contrib.auth import password_validation
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import OneTimePassword, User


class UserSerializer(serializers.ModelSerializer):
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
            "last_login_at",
            "last_logout_at",
            "last_password_change_at",
            "last_password_change_reason",
        ]
        read_only_fields = [
            "id",
            "email",
            "is_active",
            "last_login_at",
            "last_logout_at",
            "last_password_change_at",
            "last_password_change_reason",
        ]


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(_("Unable to log in with provided credentials."))

        if not user.check_password(password):
            raise serializers.ValidationError(_("Unable to log in with provided credentials."))

        attrs["user"] = user
        return attrs


class ActivationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=5, max_length=5)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value, is_active=True).exists():
            raise serializers.ValidationError(_("Active account with this email was not found."))
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=5, max_length=5)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["username", "phone", "image_profile"]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": _("Incorrect password.")})
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": _("Passwords do not match.")})
        password_validation.validate_password(attrs["new_password"], user)
        return attrs


class ActivityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "email",
            "role",
            "is_active",
            "last_login_at",
            "last_logout_at",
            "last_password_change_at",
            "last_password_change_reason",
        ]

