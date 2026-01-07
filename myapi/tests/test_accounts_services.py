import pytest
from django.utils import timezone
from django.core.mail import send_mail

from accounts.models import OneTimePassword
from accounts.services import OTPService, OTPServiceError, EmailService


def test_issue_creates_otp_and_sends_email(db, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(email="b@example.com", password=None)
    sent = {}

    def fake_send(email, code, purpose):
        sent['called'] = True

    # Patch EmailService.send_otp_email to capture calls
    monkeypatch.setattr("accounts.services.EmailService.send_otp_email", lambda e, c, p: fake_send(e, c, p))

    res = OTPService.issue(user, OneTimePassword.Purpose.INITIAL_SETUP)
    assert len(res.code) == OTPService.OTP_LENGTH
    assert 'called' in sent


def test_issue_respects_cooldown(db, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(email="c@example.com", password=None)
    # Issue first
    OTPService.issue(user, OneTimePassword.Purpose.INITIAL_SETUP)
    # Immediately issuing should raise cooldown error
    with pytest.raises(OTPServiceError):
        OTPService.issue(user, OneTimePassword.Purpose.INITIAL_SETUP)


def test_verify_behaviour(db, django_user_model):
    user = django_user_model.objects.create_user(email="d@example.com", password=None)
    otp = OneTimePassword.objects.create(user=user, code="99999", purpose=OneTimePassword.Purpose.PASSWORD_RESET, expires_at=timezone.now() + timezone.timedelta(minutes=5))
    assert OTPService.verify(user, OneTimePassword.Purpose.PASSWORD_RESET, "99999") is True

    # Wrong code
    otp2 = OneTimePassword.objects.create(user=user, code="11111", purpose=OneTimePassword.Purpose.PASSWORD_RESET, expires_at=timezone.now() + timezone.timedelta(minutes=5))
    with pytest.raises(OTPServiceError):
        OTPService.verify(user, OneTimePassword.Purpose.PASSWORD_RESET, "00000")

    # Expired
    otp3 = OneTimePassword.objects.create(user=user, code="22222", purpose=OneTimePassword.Purpose.PASSWORD_RESET, expires_at=timezone.now() - timezone.timedelta(minutes=1))
    with pytest.raises(OTPServiceError):
        OTPService.verify(user, OneTimePassword.Purpose.PASSWORD_RESET, "22222")
