import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import OneTimePassword, User

logger = logging.getLogger(__name__)


class OTPServiceError(Exception):
    pass


@dataclass
class OTPResult:
    code: str
    expires_at: datetime


class OTPService:
    OTP_LENGTH = 5
    EXPIRY = timedelta(minutes=5)
    COOLDOWN = timedelta(minutes=1)

    @classmethod
    def _latest_otp(cls, user: User, purpose: str) -> Optional[OneTimePassword]:
        return (
            OneTimePassword.objects.filter(user=user, purpose=purpose, is_used=False)
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def issue(cls, user: User, purpose: str) -> OTPResult:
        now = timezone.now()
        latest = cls._latest_otp(user, purpose)
        if latest and latest.created_at + cls.COOLDOWN > now:
            raise OTPServiceError("OTP recently sent. Please wait before requesting another.")

        if latest and not latest.is_expired():
            # Invalidate previous OTP so the newest one is the only valid option
            latest.mark_used()

        # Generate cryptographically secure 5-digit OTP code
        code = ''.join(secrets.choice('0123456789') for _ in range(cls.OTP_LENGTH))
        expires_at = now + cls.EXPIRY
        otp = OneTimePassword.objects.create(
            user=user,
            code=code,
            purpose=purpose,
            expires_at=expires_at,
        )
        EmailService.send_otp_email(user.email, code, purpose)
        return OTPResult(code=code, expires_at=otp.expires_at)

    @classmethod
    def verify(cls, user: User, purpose: str, code: str) -> bool:
        otp = cls._latest_otp(user, purpose)
        if not otp:
            raise OTPServiceError("No OTP request found. Please request a new code.")

        otp.attempt_count += 1
        otp.save(update_fields=["attempt_count"])

        if otp.is_expired():
            raise OTPServiceError("OTP expired. Please request a new code.")

        if otp.code != code:
            raise OTPServiceError("Invalid OTP. Please try again.")

        otp.mark_used()
        return True


class EmailService:
    @staticmethod
    def send_otp_email(email: str, code: str, purpose: str) -> None:
        if purpose == OneTimePassword.Purpose.INITIAL_SETUP:
            subject = "Set up your account password"
            body = f"Your initial setup code is {code}. It expires in 5 minutes."
        elif purpose == OneTimePassword.Purpose.PASSWORD_RESET:
            subject = "Reset your password"
            body = f"Your password reset code is {code}. It expires in 5 minutes."
        else:
            # Fallback for any unexpected purposes
            subject = "Your verification code"
            body = f"Your verification code is {code}. It expires in 5 minutes."

        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                recipient_list=[email],
                fail_silently=False,
            )
            logger.info(f"OTP email sent successfully to {email} for purpose: {purpose}")
        except Exception as e:
            logger.error(
                f"Failed to send OTP email to {email} for purpose {purpose}. "
                f"Error: {str(e)}. "
                f"Check EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env file."
            )
            raise

