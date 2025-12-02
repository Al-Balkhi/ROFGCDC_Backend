from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import OneTimePassword, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "username", "role", "is_active", "is_staff")
    search_fields = ("email", "username", "phone")
    list_filter = ("role", "is_active", "is_staff")
    readonly_fields = (
        "last_login_at",
        "last_logout_at",
        "last_password_change_at",
        "last_password_change_reason",
        "date_joined",
    )

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("username", "phone", "image_profile", "role")}),
        (
            "Security",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Activity",
            {
                "fields": (
                    "last_login_at",
                    "last_logout_at",
                    "last_password_change_at",
                    "last_password_change_reason",
                    "date_joined",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "username", "password1", "password2", "role", "is_active"),
            },
        ),
    )


@admin.register(OneTimePassword)
class OneTimePasswordAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "code", "created_at", "expires_at", "is_used")
    list_filter = ("purpose", "is_used", "created_at")
    search_fields = ("user__email", "code")
