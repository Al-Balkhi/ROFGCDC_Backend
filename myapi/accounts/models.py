from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.conf import settings
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must provide an email address")
        email = self.normalize_email(email)
        extra_fields.setdefault("username", email.split("@")[0])
        user = self.model(email=email, **extra_fields)

        # Determine whether this user is being created with a real password
        has_password = bool(password)
        if has_password:
            user.set_password(password)
        else:
            # Create user with an unusable password so they must complete initial setup.
            user.set_unusable_password()

        # For normal users, ensure they are inactive until they complete initial setup.
        # (Superusers explicitly pass is_active=True via create_superuser.)
        if "is_active" not in extra_fields:
            user.is_active = False

        user.save(using=self._db)

        # If the user was created without a password, automatically send an
        # INITIAL_SETUP OTP to kick off onboarding. We reference OneTimePassword
        # at runtime to avoid circular imports.
        if not has_password:
            try:
                from .services import OTPService  # type: ignore

                OTPService.issue(user, OneTimePassword.Purpose.INITIAL_SETUP)
            except Exception:
                # Swallow any OTP-related errors so user creation is not blocked.
                # Logging can be added here if desired.
                pass

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", self.model.Roles.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Roles(models.TextChoices):
        DRIVER = "driver", "Driver"
#       ANALYST = "analyst", "Analyst"
        PLANNER = "planner", "Planner"
        ADMIN = "admin", "Admin"

    class PasswordChangeReason(models.TextChoices):
        FORGOT = "forgot", "Forgot"
        PROFILE = "profile", "Profile"
        INITIAL_SETUP = "initial_setup", "Initial Setup"

    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    image_profile = models.ImageField(upload_to="profiles/", blank=True, null=True)
    role = models.CharField(
        max_length=20, choices=Roles.choices, default=Roles.DRIVER
    )
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_logout_at = models.DateTimeField(null=True, blank=True)
    last_password_change_at = models.DateTimeField(null=True, blank=True)
    last_password_change_reason = models.CharField(
        max_length=20,
        choices=PasswordChangeReason.choices,
        blank=True,
        null=True,
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email


class OneTimePassword(models.Model):
    class Purpose(models.TextChoices):
        PASSWORD_RESET = "password_reset", "Password Reset"
        INITIAL_SETUP = "initial_setup", "Initial Setup"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="otps", on_delete=models.CASCADE
    )
    code = models.CharField(max_length=5)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    attempt_count = models.PositiveIntegerField(default=0)
    is_used = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["user", "purpose"]),
            models.Index(fields=["expires_at"]),
        ]

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def mark_used(self):
        self.is_used = True
        self.save(update_fields=["is_used"])
