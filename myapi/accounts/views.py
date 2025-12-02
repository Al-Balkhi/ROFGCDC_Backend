from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .authentication import CookieJWTAuthentication
from .models import OneTimePassword
from .serializers import (
    ActivationSerializer,
    ActivityLogSerializer,
    ChangePasswordSerializer,
    ConfirmInitialSetupSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileUpdateSerializer,
    RequestInitialSetupOTPSerializer,
    UserSerializer,
)
from .services import OTPService, OTPServiceError

User = get_user_model()


def _set_jwt_cookies(response: Response, refresh: RefreshToken):
    access = refresh.access_token
    access_exp = int(access.lifetime.total_seconds())
    refresh_exp = int(refresh.lifetime.total_seconds())
    common_args = {
        "httponly": True,
        "samesite": "Lax",
        "secure": getattr(settings, "SESSION_COOKIE_SECURE", False),
        "path": "/",
    }
    response.set_cookie("access", str(access), max_age=access_exp, **common_args)
    response.set_cookie("refresh", str(refresh), max_age=refresh_exp, **common_args)


def _clear_jwt_cookies(response: Response):
    response.delete_cookie("access", path="/")
    response.delete_cookie("refresh", path="/")


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        if not user.is_active:
            try:
                OTPService.issue(user, OneTimePassword.Purpose.ACTIVATION)
            except OTPServiceError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            return Response(
                {
                    "detail": "Account not active. OTP sent to email for activation.",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        refresh = RefreshToken.for_user(user)
        user.last_login_at = timezone.now()
        user.last_login = user.last_login_at
        user.save(update_fields=["last_login_at", "last_login"])
        response = Response({"user": UserSerializer(user).data})
        _set_jwt_cookies(response, refresh)
        return response


class LogoutView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.COOKIES.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except TokenError:
                pass
        user = request.user
        user.last_logout_at = timezone.now()
        user.save(update_fields=["last_logout_at"])
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_jwt_cookies(response)
        return response


class RefreshTokenView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get("refresh")
        if not refresh_token:
            return Response({"detail": "Refresh token missing."}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            token = RefreshToken(refresh_token)
            user = User.objects.get(id=token["user_id"])
            token.blacklist()
        except (TokenError, User.DoesNotExist):
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)

        new_refresh = RefreshToken.for_user(user)
        response = Response({"detail": "Token refreshed."})
        _set_jwt_cookies(response, new_refresh)
        return response


class ActivateAccountView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.get(email=serializer.validated_data["email"])
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.is_active:
            return Response({"detail": "Account already active."})

        try:
            OTPService.verify(
                user,
                OneTimePassword.Purpose.ACTIVATION,
                serializer.validated_data["otp"],
            )
        except OTPServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = True
        user.save(update_fields=["is_active"])
        return Response({"detail": "Account activated successfully."})


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.get(email=serializer.validated_data["email"])
        try:
            OTPService.issue(user, OneTimePassword.Purpose.PASSWORD_RESET)
        except OTPServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        return Response({"detail": "Password reset OTP sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.get(email=serializer.validated_data["email"])
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            OTPService.verify(
                user,
                OneTimePassword.Purpose.PASSWORD_RESET,
                serializer.validated_data["otp"],
            )
        except OTPServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data["new_password"])
        user.last_password_change_at = timezone.now()
        user.last_password_change_reason = user.PasswordChangeReason.FORGOT
        user.save(update_fields=["password", "last_password_change_at", "last_password_change_reason"])
        return Response({"detail": "Password reset successful."})


class InitialSetupRequestOTPView(APIView):
    """
    Request an OTP for initial password setup.
    This is used when the user has no usable password and is not active.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RequestInitialSetupOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = User.objects.get(email=email)

        try:
            OTPService.issue(user, OneTimePassword.Purpose.INITIAL_SETUP)
        except OTPServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        return Response({"detail": "OTP sent for initial setup."})


class InitialSetupConfirmView(APIView):
    """
    Confirm initial setup using OTP and set the user's password.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ConfirmInitialSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        otp_code = serializer.validated_data["otp"]
        password = serializer.validated_data["password"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            OTPService.verify(
                user,
                OneTimePassword.Purpose.INITIAL_SETUP,
                otp_code,
            )
        except OTPServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(password)
        user.is_active = True
        user.last_password_change_at = timezone.now()
        user.last_password_change_reason = user.PasswordChangeReason.INITIAL_SETUP
        user.save(
            update_fields=[
                "password",
                "is_active",
                "last_password_change_at",
                "last_password_change_reason",
            ]
        )

        return Response({"detail": "Initial setup completed successfully."})


class ProfileView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def put(self, request):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.last_password_change_at = timezone.now()
        user.last_password_change_reason = user.PasswordChangeReason.PROFILE
        user.save(update_fields=["password", "last_password_change_at", "last_password_change_reason"])
        return Response({"detail": "Password updated successfully."})


class ActivityLogView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        queryset = User.objects.all().order_by("-last_login_at")
        data = ActivityLogSerializer(queryset, many=True).data
        return Response(data)
