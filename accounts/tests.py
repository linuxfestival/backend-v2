import re
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from .models import User


TEST_EMAIL_SETTINGS = {
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "EMAIL_VERIFICATION_ENABLED": True,
    "EMAIL_OTP_RESEND_SECONDS": 0,
    "EMAIL_OTP_TTL_SECONDS": 600,
    "EMAIL_OTP_MAX_ATTEMPTS": 5,
}


@override_settings(**TEST_EMAIL_SETTINGS)
class UserAuthTestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_data = {
            "phone_number": "09337905450",
            "password": "A-strong-password-123",
            "email": "Test@Example.com",
            "first_name": "Test",
            "last_name": "User",
        }

    def signup(self):
        return self.client.post("/api/users/signup/", self.user_data, format="json")

    @staticmethod
    def latest_code():
        match = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
        if not match:
            raise AssertionError("OTP not found in email body")
        return match.group(1)

    def test_signup_requires_email_and_phone(self):
        payload = {**self.user_data}
        payload.pop("phone_number")
        response = self.client.post("/api/users/signup/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone_number", response.data)

        payload = {**self.user_data}
        payload.pop("email")
        response = self.client.post("/api/users/signup/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_signup_sends_email_code_and_activation_returns_tokens(self):
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["verification_required"])
        self.assertNotIn("tokens", response.data)
        user = User.objects.get(email="test@example.com")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)

        login = self.client.post("/api/token/access/", {
            "email": "TEST@example.com",
            "password": self.user_data["password"],
        }, format="json")
        self.assertEqual(login.status_code, 401)
        self.assertTrue(login.data["verification_required"])

        activation = self.client.post("/api/users/activate/", {
            "email": self.user_data["email"],
            "code": self.latest_code(),
        }, format="json")
        self.assertEqual(activation.status_code, 200)
        self.assertIn("access", activation.data["tokens"])
        self.assertTrue(User.objects.get(pk=user.pk).is_active)

    def test_unverified_signup_retry_resends_without_replacing_credentials(self):
        first = self.signup()
        self.assertEqual(first.status_code, 201)
        retry_payload = {
            **self.user_data,
            "first_name": "Attacker cannot replace this",
            "password": "A-different-password-456",
        }

        second = self.client.post("/api/users/signup/", retry_payload, format="json")

        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["verification_required"])
        self.assertEqual(User.objects.filter(email="test@example.com").count(), 1)
        user = User.objects.get(email="test@example.com")
        self.assertTrue(user.check_password(self.user_data["password"]))
        self.assertEqual(user.first_name, self.user_data["first_name"])
        self.assertEqual(len(mail.outbox), 2)

    def test_unverified_signup_retry_requires_same_phone(self):
        self.signup()
        response = self.client.post("/api/users/signup/", {
            **self.user_data,
            "phone_number": "09120000000",
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_failed_signup_email_does_not_throttle_retry(self):
        with patch("accounts.emailing.send_mail", side_effect=RuntimeError("SMTP unavailable")):
            response = self.signup()
        self.assertEqual(response.status_code, 503)
        user = User.objects.get(email="test@example.com")
        self.assertIsNone(user.last_otp_sent)
        self.assertIsNone(user.otp_code)

        retry = self.signup()
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_VERIFICATION_ENABLED=False)
    def test_disabled_verification_activates_immediately(self):
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["verification_required"])
        self.assertIn("access", response.data["tokens"])
        self.assertTrue(User.objects.get(email="test@example.com").is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_login_returns_profile_and_onboarding_state(self):
        User.objects.create_user(**self.user_data, is_active=True)
        response = self.client.post("/api/token/access/", {
            "email": "TEST@EXAMPLE.COM",
            "password": self.user_data["password"],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["phone_number"], self.user_data["phone_number"])
        self.assertTrue(response.data["is_first_login"])

    def test_password_reset_by_email_code(self):
        user = User.objects.create_user(**self.user_data, is_active=True)
        response = self.client.post("/api/users/password_reset_request/", {
            "email": self.user_data["email"],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post("/api/users/password_reset_confirm/", {
            "email": self.user_data["email"],
            "code": self.latest_code(),
            "new_password": "A-different-password-456",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("A-different-password-456"))

    def test_password_reset_request_does_not_reveal_missing_accounts(self):
        response = self.client.post("/api/users/password_reset_request/", {
            "email": "missing@example.com",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_authenticated_user_can_complete_onboarding(self):
        user = User.objects.create_user(**self.user_data, is_active=True)
        self.client.force_authenticate(user)

        before = self.client.get("/api/users/onboarding/")
        self.assertEqual(before.status_code, 200)
        self.assertTrue(before.data["is_first_login"])

        response = self.client.post("/api/users/onboarding/", {
            "heard_about_us": "university",
            "university": "Sharif University",
            "hamkaran_announcement_consent": True,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_first_login"])
        user.refresh_from_db()
        self.assertEqual(user.heard_about_us, "university")
        self.assertFalse(user.is_first_login)
