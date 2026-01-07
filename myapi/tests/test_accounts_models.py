import pytest
from django.utils import timezone

from accounts.models import OneTimePassword


def test_create_user_requires_email(db):
    from accounts.models import UserManager
    um = UserManager()
    with pytest.raises(ValueError):
        um.create_user(email=None)


def test_one_time_password_methods(db, django_user_model):
    user = django_user_model.objects.create_user(email="a@example.com", password="testpass")
    expires = timezone.now() + timezone.timedelta(minutes=1)
    otp = OneTimePassword.objects.create(user=user, code="12345", purpose=OneTimePassword.Purpose.PASSWORD_RESET, expires_at=expires)
    assert otp.is_expired() is False
    otp.expires_at = timezone.now() - timezone.timedelta(minutes=1)
    otp.save()
    assert otp.is_expired() is True
    otp.is_used = False
    otp.mark_used()
    assert otp.is_used is True
