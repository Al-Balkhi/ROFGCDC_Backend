from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django import forms

from .models import OneTimePassword, User


class UserCreationNoPasswordForm(forms.ModelForm):
    """
    Custom creation form that does not allow setting a password.
    The user will receive an initial-setup OTP to set their own password.
    """

    class Meta:
        model = User
        fields = ("email", "username", "phone", "image_profile", "role")

    def save(self, commit=True):
        """
        Use the custom manager's create_user(password=None), and make sure
        admin can still call save_m2m() without errors.
        """
        email = self.cleaned_data["email"]
        username = self.cleaned_data.get("username") or email.split("@")[0]
        phone = self.cleaned_data.get("phone", "")
        image_profile = self.cleaned_data.get("image_profile")
        role = self.cleaned_data.get("role", User.Roles.DRIVER)

        # create_user will set unusable password, inactive, and send INITIAL_SETUP OTP
        user = User.objects.create_user(
            email=email,
            password=None,
            username=username,
            phone=phone,
            image_profile=image_profile,
            role=role,
        )

        # No many-to-many fields on this form, so this is safe
        self._save_m2m = lambda: None
        return user

    def save_m2m(self):
        # Called by admin after save(commit=True)
        self._save_m2m()


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationNoPasswordForm

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
                "fields": ("email", "username", "phone", "image_profile", "role"),
            },
        ),
    )


@admin.register(OneTimePassword)
class OneTimePasswordAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "code", "created_at", "expires_at", "is_used")
    list_filter = ("purpose", "is_used", "created_at")
    search_fields = ("user__email", "code")
