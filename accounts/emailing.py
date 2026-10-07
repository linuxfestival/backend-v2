import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.utils import timezone

from .models import OTPPurpose, User


logger = logging.getLogger(__name__)


class OTPError(Exception):
    pass


class OTPThrottled(OTPError):
    pass


def _generate_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def clear_otp(user):
    user.otp_code = None
    user.otp_purpose = ""
    user.otp_expires_at = None
    user.otp_attempts = 0
    user.save(update_fields=[
        "otp_code", "otp_purpose", "otp_expires_at", "otp_attempts"
    ])


def send_otp(user: User, purpose: str):
    now = timezone.now()
    if user.last_otp_sent:
        elapsed = (now - user.last_otp_sent).total_seconds()
        if elapsed < settings.EMAIL_OTP_RESEND_SECONDS:
            retry_after = max(1, int(settings.EMAIL_OTP_RESEND_SECONDS - elapsed))
            raise OTPThrottled(f"Please wait {retry_after} seconds before requesting another code.")

    previous_state = {
        "otp_code": user.otp_code,
        "otp_purpose": user.otp_purpose,
        "otp_expires_at": user.otp_expires_at,
        "otp_attempts": user.otp_attempts,
        "last_otp_sent": user.last_otp_sent,
    }
    code = _generate_code()
    user.otp_code = make_password(code)
    user.otp_purpose = purpose
    user.otp_expires_at = now + timedelta(seconds=settings.EMAIL_OTP_TTL_SECONDS)
    user.otp_attempts = 0
    user.last_otp_sent = now
    user.save(update_fields=[
        "otp_code", "otp_purpose", "otp_expires_at", "otp_attempts",
        "last_otp_sent",
    ])

    if purpose == OTPPurpose.PASSWORD_RESET:
        subject = "LinuxFest password reset code"
        message = f"Your LinuxFest password reset code is: {code}"
    else:
        subject = "LinuxFest email verification code"
        message = f"Your LinuxFest email verification code is: {code}"

    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    except Exception:
        # Do not throttle a retry for a code the mail server did not accept.
        for field, value in previous_state.items():
            setattr(user, field, value)
        user.save(update_fields=list(previous_state))
        raise


def validate_otp(user: User, code: str, purpose: str):
    now = timezone.now()
    if not user.otp_code or user.otp_purpose != purpose:
        raise OTPError("No valid code has been requested.")

    if not user.otp_expires_at or user.otp_expires_at <= now:
        clear_otp(user)
        raise OTPError("The code has expired. Please request a new one.")

    if user.otp_attempts >= settings.EMAIL_OTP_MAX_ATTEMPTS:
        clear_otp(user)
        raise OTPError("Too many incorrect attempts. Please request a new code.")

    if not check_password(code, user.otp_code):
        user.otp_attempts += 1
        user.save(update_fields=["otp_attempts"])
        raise OTPError("Invalid code.")

    clear_otp(user)
