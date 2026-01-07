import pytest
from accounts.serializers import LoginSerializer, PasswordResetRequestSerializer, RequestInitialSetupOTPSerializer
from django.contrib.auth import get_user_model

User = get_user_model()


def test_login_serializer_invalid_user(db):
    data = {"email": "noone@example.com", "password": "x"}
    s = LoginSerializer(data=data)
    with pytest.raises(Exception):
        s.is_valid(raise_exception=True)


def test_login_serializer_unusable_password(db):
    user = User.objects.create_user(email="e@example.com", password=None)
    data = {"email": user.email, "password": "anything"}
    s = LoginSerializer(data=data)
    with pytest.raises(Exception):
        s.is_valid(raise_exception=True)


def test_password_reset_request_serializer_requires_active(db):
    user = User.objects.create_user(email="f@example.com", password="pw")
    user.is_active = False
    user.save()
    s = PasswordResetRequestSerializer(data={"email": user.email})
    with pytest.raises(Exception):
        s.is_valid(raise_exception=True)


def test_request_initial_setup_serializer_requires_inactive(db):
    user = User.objects.create_user(email="g@example.com", password=None)
    # create_user sets is_active False by default; this should pass
    s = RequestInitialSetupOTPSerializer(data={"email": user.email})
    assert s.is_valid()
