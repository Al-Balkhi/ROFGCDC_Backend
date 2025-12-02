from django.urls import path

from .views import (
    ActivateAccountView,
    ActivityLogView,
    ChangePasswordView,
    InitialSetupConfirmView,
    InitialSetupRequestOTPView,
    LoginView,
    LogoutView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileView,
    RefreshTokenView,
)

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/refresh/", RefreshTokenView.as_view(), name="auth-refresh"),
    path("auth/activate/", ActivateAccountView.as_view(), name="auth-activate"),
    path(
        "auth/initial-setup/request-otp/",
        InitialSetupRequestOTPView.as_view(),
        name="auth-initial-setup-request-otp",
    ),
    path(
        "auth/initial-setup/confirm/",
        InitialSetupConfirmView.as_view(),
        name="auth-initial-setup-confirm",
    ),
    path(
        "auth/password/reset/request/",
        PasswordResetRequestView.as_view(),
        name="password-reset-request",
    ),
    path(
        "auth/password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/password/", ChangePasswordView.as_view(), name="profile-password"),
    path("admin/activity-log/", ActivityLogView.as_view(), name="activity-log"),
]
