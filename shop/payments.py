import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode, urlparse

import requests
from django.conf import settings


class ZarrinPal:
    PAYMENT_DESCRIPTION = "Register Linux Festival workshops or talks"
    PAY_URL = "https://payment.zarinpal.com/pg/v4/payment/request.json"
    VERIFY_URL = "https://payment.zarinpal.com/pg/v4/payment/verify.json"
    START_PAY_URL = "https://payment.zarinpal.com/pg/StartPay/{authority}"

    STATUS_SUCCESS = 100
    STATUS_VERIFIED = 101

    def __init__(self):
        self.merchant_id = (settings.PAYMENT_API_KEY or "").strip()
        self.callback_url = (settings.PAYMENT_CALLBACK_URL or "").strip()
        self.start_url = (settings.PAYMENT_START_URL or "").strip()
        self.timeout = (
            settings.PAYMENT_HTTP_CONNECT_TIMEOUT,
            settings.PAYMENT_HTTP_READ_TIMEOUT,
        )

    @staticmethod
    def _gateway_amount(amount):
        """Convert a Toman amount to the integer Rial amount required by ZarinPal."""
        try:
            toman = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Payment amount is invalid.") from exc
        if not toman.is_finite() or toman <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        return int((toman * Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _error_message(body, fallback):
        errors = body.get("errors") or {}
        if isinstance(errors, dict):
            message = errors.get("message")
            code = errors.get("code")
            if message:
                return f"{code}: {message}" if code is not None else str(message)
        data = body.get("data") or {}
        return str(body.get("message") or data.get("message") or fallback)

    def _configuration_error(self):
        if not self.merchant_id or self.merchant_id == "auth":
            return "ZarinPal merchant ID is not configured."
        callback = urlparse(self.callback_url)
        if callback.scheme != "https" or not callback.netloc:
            return "Payment callback URL must be an absolute HTTPS URL."
        if not self.start_url:
            return None
        start = urlparse(self.start_url)
        if (
            start.scheme != "https"
            or not start.netloc
            or start.username
            or start.password
            or start.query
            or start.fragment
        ):
            return "Payment start URL must be an HTTPS URL without query parameters."
        return None

    def generate_link(self, authority):
        if not isinstance(authority, str) or not re.fullmatch(r"[A-Za-z0-9]{1,128}", authority):
            raise ValueError("ZarinPal returned an invalid authority.")
        gateway_url = self.START_PAY_URL.format(authority=authority)
        if not self.start_url:
            return gateway_url
        return f"{self.start_url}?{urlencode({'gateway': gateway_url})}"

    def create_payment(self, amount, mobile=None, email=None):
        configuration_error = self._configuration_error()
        if configuration_error:
            return {
                "status": "error",
                "authority": None,
                "error": configuration_error,
                "link": None,
            }
        try:
            amount_rial = self._gateway_amount(amount)
        except ValueError as exc:
            return {"status": "error", "authority": None, "error": str(exc), "link": None}

        metadata = {}
        if mobile:
            metadata["mobile"] = mobile
        if email:
            metadata["email"] = email
        payload = {
            "merchant_id": self.merchant_id,
            "amount": amount_rial,
            "callback_url": self.callback_url,
            "description": self.PAYMENT_DESCRIPTION,
            "metadata": metadata,
        }

        try:
            response = requests.post(
                self.PAY_URL,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=self.timeout,
            )
            body = response.json() if response.content else {}
        except requests.RequestException as exc:
            return {"status": "error", "authority": None, "error": str(exc), "link": None}
        except ValueError:
            return {
                "status": "error",
                "authority": None,
                "error": "ZarinPal returned an invalid response.",
                "link": None,
            }

        data = body.get("data") or {}
        authority = data.get("authority")
        if data.get("code") == self.STATUS_SUCCESS and authority:
            try:
                link = self.generate_link(authority)
            except ValueError as exc:
                return {"status": "error", "authority": None, "error": str(exc), "link": None}
            return {"status": "success", "authority": authority, "error": None, "link": link}
        return {
            "status": "failed",
            "authority": None,
            "error": self._error_message(body, f"Payment request failed (HTTP {response.status_code})."),
            "link": None,
        }

    def verify_payment(self, authority, amount):
        configuration_error = self._configuration_error()
        if configuration_error:
            return {
                "status": "unexpected",
                "ref_id": None,
                "error": configuration_error,
                "card_pan": None,
            }
        try:
            amount_rial = self._gateway_amount(amount)
        except ValueError as exc:
            return {
                "status": "unexpected",
                "ref_id": None,
                "error": str(exc),
                "card_pan": None,
            }

        payload = {
            "merchant_id": self.merchant_id,
            "amount": amount_rial,
            "authority": authority,
        }
        try:
            response = requests.post(
                self.VERIFY_URL,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=self.timeout,
            )
            body = response.json() if response.content else {}
        except requests.RequestException as exc:
            return {
                "status": "unexpected",
                "ref_id": None,
                "error": str(exc),
                "card_pan": None,
            }
        except ValueError:
            return {
                "status": "unexpected",
                "ref_id": None,
                "error": "ZarinPal returned an invalid response.",
                "card_pan": None,
            }

        data = body.get("data") or {}
        if data.get("code") in {self.STATUS_SUCCESS, self.STATUS_VERIFIED}:
            return {
                "status": "success",
                "ref_id": data.get("ref_id"),
                "error": None,
                "card_pan": data.get("card_pan"),
            }
        return {
            "status": "failed",
            "ref_id": None,
            "error": self._error_message(body, f"Payment verification failed (HTTP {response.status_code})."),
            "card_pan": None,
        }
