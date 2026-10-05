from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Accessory, User
from shop.models import Coupon, Payment, Presentation, Participation
from shop.serializers import CouponSerializer
from shop.payments import ZarrinPal


PAYMENT_SETTINGS = {
    "PAYMENT_API_KEY": "11111111-1111-1111-1111-111111111111",
    "PAYMENT_CALLBACK_URL": "https://ceit-ssc.ir/payment/linuxfest/zarinpal/callback",
    "PAYMENT_START_URL": "https://ceit-ssc.ir/payment/start",
    "PAYMENT_RETURN_URL": "https://linuxfest.ir/payment/perhaps",
    "PAYMENT_HTTP_CONNECT_TIMEOUT": 5.0,
    "PAYMENT_HTTP_READ_TIMEOUT": 15.0,
}


@override_settings(**PAYMENT_SETTINGS)
class ZarrinPalClientTests(TestCase):
    @patch("shop.payments.requests.post")
    def test_create_uses_integer_rial_amount_and_registered_domain_handoff(self, post):
        response = Mock(status_code=200, content=b"response")
        response.json.return_value = {"data": {"code": 100, "authority": "A123"}}
        post.return_value = response

        result = ZarrinPal().create_payment(
            amount=Decimal("12500.25"),
            mobile="09120000000",
            email="payer@example.com",
        )

        self.assertEqual(result["status"], "success")
        handoff = urlparse(result["link"])
        self.assertEqual(handoff.netloc, "ceit-ssc.ir")
        self.assertEqual(handoff.path, "/payment/start")
        self.assertEqual(
            parse_qs(handoff.query)["gateway"],
            ["https://payment.zarinpal.com/pg/StartPay/A123"],
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["amount"], 125003)
        self.assertIsInstance(payload["amount"], int)
        self.assertEqual(payload["callback_url"], PAYMENT_SETTINGS["PAYMENT_CALLBACK_URL"])
        self.assertEqual(post.call_args.kwargs["timeout"], (5.0, 15.0))


@override_settings(**PAYMENT_SETTINGS)
class PaymentFlowTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone_number="09120000000",
            password="test-password-123",
            first_name="Payment",
            last_name="Tester",
            email="payment-tester@example.com",
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        start = timezone.now() + timedelta(days=30)
        self.presentation = Presentation.objects.create(
            service_type="WORKSHOP",
            en_title="Free payment flow test",
            fa_title="آزمایش پرداخت",
            start=start,
            end=start + timedelta(hours=1),
            en_description="Test",
            fa_description="آزمایش",
            capacity=10,
            cost=Decimal("0"),
        )
        self.participation = Participation.objects.create(
            user=self.user,
            presentation=self.presentation,
        )

    @patch("shop.views.ZarrinPal.create_payment")
    def test_paid_accessory_is_not_given_away_with_free_workshop(self, create_payment):
        accessory = Accessory.objects.create(
            name="Paid test accessory",
            description="Payment regression test",
            price=Decimal("12000.00"),
            img="test-accessory.png",
            is_active=True,
        )
        create_payment.return_value = {
            "status": "success",
            "authority": "A123",
            "link": "https://ceit-ssc.ir/payment/start?gateway=test",
        }

        response = self.client.post(
            reverse("payment-pay-all"),
            {"coupon": "", "accessories": [accessory.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        create_payment.assert_called_once_with(
            amount=Decimal("12000.00"),
            mobile=self.user.phone_number,
            email=self.user.email,
        )
        payment = Payment.objects.get(authority="A123")
        self.assertEqual(payment.total_price, Decimal("12000.00"))
        self.assertFalse(self.user.accessories.filter(pk=accessory.pk).exists())

    @patch("shop.views.ZarrinPal.verify_payment")
    def test_provider_callback_verifies_and_settles_before_frontend_redirect(self, verify_payment):
        payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="A-CALLBACK-123".replace("-", ""),
        )
        payment.participations.add(self.participation)
        verify_payment.return_value = {
            "status": "success",
            "ref_id": "REF123",
            "card_pan": "621986******1234",
            "error": None,
        }

        self.client.force_authenticate(user=None)
        response = self.client.get(
            reverse("payment-provider-callback"),
            {"Authority": payment.authority, "Status": "OK"},
        )

        self.assertEqual(response.status_code, 302)
        target = urlparse(response["Location"])
        self.assertEqual(target.netloc, "linuxfest.ir")
        self.assertEqual(target.path, "/payment/perhaps")
        self.assertEqual(parse_qs(target.query)["Status"], ["OK"])
        payment.refresh_from_db()
        self.participation.refresh_from_db()
        self.assertEqual(payment.payment_state, "COMPLETED")
        self.assertEqual(payment.ref_id, "REF123")
        self.assertEqual(self.participation.payment_state, "COMPLETED")

    def test_remove_accepts_presentation_id(self):
        self.participation.delete()
        participation = Participation.objects.create(
            user=self.user,
            presentation=self.presentation,
        )
        self.assertNotEqual(participation.pk, self.presentation.pk)

        response = self.client.delete(
            reverse("presentation-remove-participation", args=[self.presentation.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participation.objects.filter(pk=participation.pk).exists())

    def test_remove_accepts_legacy_participation_id(self):
        self.participation.delete()
        participation = Participation.objects.create(
            user=self.user,
            presentation=self.presentation,
        )

        response = self.client.delete(
            reverse("presentation-remove-participation", args=[participation.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participation.objects.filter(pk=participation.pk).exists())

    def test_remove_rejects_item_with_payment_in_progress(self):
        payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="REMOVELOCK123",
        )
        payment.participations.add(self.participation)

        response = self.client.delete(
            reverse("presentation-remove-participation", args=[self.presentation.pk])
        )

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Participation.objects.filter(pk=self.participation.pk).exists())

    @patch("shop.views.ZarrinPal.create_payment")
    def test_repeated_checkout_reuses_existing_payment(self, create_payment):
        self.presentation.cost = Decimal("10000.00")
        self.presentation.save(update_fields=["cost"])
        create_payment.return_value = {
            "status": "success",
            "authority": "REUSE123",
            "link": "https://ceit-ssc.ir/payment/start?gateway=test",
        }

        first = self.client.post(reverse("payment-pay-all"), {}, format="json")
        second = self.client.post(reverse("payment-pay-all"), {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["authority"], "REUSE123")
        self.assertEqual(create_payment.call_count, 1)
        self.assertEqual(Payment.objects.filter(user=self.user).count(), 1)

    def test_started_payment_reserves_capacity(self):
        self.presentation.capacity = 1
        self.presentation.save(update_fields=["capacity"])
        payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="RESERVED123",
        )
        payment.participations.add(self.participation)

        self.assertEqual(self.presentation.get_remained_capacity(), 0)


class ShopValidationTests(TestCase):
    def test_negative_capacity_is_rejected(self):
        start = timezone.now() + timedelta(days=1)
        presentation = Presentation(
            service_type="WORKSHOP",
            en_title="Invalid capacity",
            fa_title="ظرفیت نامعتبر",
            start=start,
            end=start + timedelta(hours=1),
            en_description="Test",
            fa_description="Test",
            capacity=-1,
            cost=Decimal("0"),
        )
        with self.assertRaises(ValidationError):
            presentation.full_clean()

    def test_coupon_validity_is_serialized_from_remaining_count(self):
        invalid = Coupon.objects.create(name="EMPTY", count=0, percentage=10)
        valid = Coupon.objects.create(name="VALID", count=1, percentage=10)

        self.assertFalse(CouponSerializer(invalid).data["is_valid"])
        self.assertTrue(CouponSerializer(valid).data["is_valid"])


class PaymentTestItemCommandTests(TestCase):
    def test_seed_command_is_repeatable(self):
        call_command("seed_payment_test_item", price="10000.00", verbosity=0)
        call_command("seed_payment_test_item", price="15000.00", verbosity=0)
        items = Presentation.objects.filter(en_title="Payment Gateway Test Workshop")
        self.assertEqual(items.count(), 1)
        self.assertEqual(items.get().cost, Decimal("15000.00"))
