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
from shop.models import Coupon, Payment, Presentation, PresentationTag, Participation
from shop.serializers import CouponSerializer, PresentationTagSerializer
from shop.payments import ZarrinPal


PAYMENT_SETTINGS = {
    "PAYMENT_API_KEY": "11111111-1111-1111-1111-111111111111",
    "PAYMENT_CALLBACK_URL": "https://ceit-ssc.ir/payment/linuxfest/zarinpal/callback",
    "PAYMENT_START_URL": "https://ceit-ssc.ir/payment/start",
    "PAYMENT_RETURN_URL": "https://linuxfest.ir/payment/perhaps",
    "PAYMENT_HTTP_CONNECT_TIMEOUT": 5.0,
    "PAYMENT_HTTP_READ_TIMEOUT": 15.0,
    "PAYMENT_PENDING_TTL_SECONDS": 1800,
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

        verify_response = self.client.post(
            reverse("payment-verify"),
            {"authority": payment.authority},
            format="json",
        )
        self.assertEqual(verify_response.status_code, 200)
        self.assertEqual(verify_response.data["status"], "success")
        self.assertEqual(verify_response.data["ref_id"], "REF123")

    @patch("shop.views.ZarrinPal.verify_payment")
    def test_callback_preserves_gateway_ok_for_retryable_verification(self, verify_payment):
        payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="RETRYABLE123",
        )
        payment.participations.add(self.participation)
        verify_payment.return_value = {
            "status": "unexpected",
            "ref_id": None,
            "card_pan": None,
            "error": "Temporary provider timeout",
        }

        self.client.force_authenticate(user=None)
        response = self.client.get(
            reverse("payment-provider-callback"),
            {"Authority": payment.authority, "Status": "OK"},
        )

        self.assertEqual(response.status_code, 302)
        target = urlparse(response["Location"])
        self.assertEqual(parse_qs(target.query)["Status"], ["OK"])
        payment.refresh_from_db()
        self.assertEqual(payment.payment_state, "PENDING")

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

    @patch("shop.views.ZarrinPal.verify_payment")
    def test_remove_rejects_item_with_recent_payment_in_progress(self, verify_payment):
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
        self.assertGreater(response.data["retry_after_seconds"], 0)
        verify_payment.assert_not_called()
        self.assertTrue(Participation.objects.filter(pk=self.participation.pk).exists())

    @patch("shop.views.ZarrinPal.verify_payment")
    def test_remove_reconciles_failed_stale_payment_then_deletes_item(self, verify_payment):
        payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="REMOVEFAILED123",
        )
        payment.participations.add(self.participation)
        Payment.objects.filter(pk=payment.pk).update(
            created_date=timezone.now() - timedelta(minutes=31),
        )
        verify_payment.return_value = {
            "status": "failed",
            "ref_id": None,
            "card_pan": None,
            "error": "Payment was not completed",
        }

        response = self.client.delete(
            reverse("presentation-remove-participation", args=[self.presentation.pk])
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_state, "FAILED")
        self.assertFalse(Participation.objects.filter(pk=self.participation.pk).exists())

    @patch("shop.views.ZarrinPal.verify_payment")
    def test_remove_keeps_item_when_stale_payment_was_successful(self, verify_payment):
        payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="REMOVESUCCESS123",
        )
        payment.participations.add(self.participation)
        Payment.objects.filter(pk=payment.pk).update(
            created_date=timezone.now() - timedelta(minutes=31),
        )
        verify_payment.return_value = {
            "status": "success",
            "ref_id": "PAID-REF-123",
            "card_pan": "621986******1234",
            "error": None,
        }

        response = self.client.delete(
            reverse("presentation-remove-participation", args=[self.presentation.pk])
        )

        self.assertEqual(response.status_code, 409)
        payment.refresh_from_db()
        self.participation.refresh_from_db()
        self.assertEqual(payment.payment_state, "COMPLETED")
        self.assertEqual(self.participation.payment_state, "COMPLETED")
        self.assertTrue(Participation.objects.filter(pk=self.participation.pk).exists())

    @patch("shop.views.ZarrinPal.verify_payment")
    def test_remove_keeps_item_when_provider_is_temporarily_unavailable(self, verify_payment):
        payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="REMOVEUNKNOWN123",
        )
        payment.participations.add(self.participation)
        Payment.objects.filter(pk=payment.pk).update(
            created_date=timezone.now() - timedelta(minutes=31),
        )
        verify_payment.return_value = {
            "status": "unexpected",
            "ref_id": None,
            "card_pan": None,
            "error": "Temporary provider timeout",
        }

        response = self.client.delete(
            reverse("presentation-remove-participation", args=[self.presentation.pk])
        )

        self.assertEqual(response.status_code, 503)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_state, "PENDING")
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

    @patch("shop.views.ZarrinPal.create_payment")
    @patch("shop.views.ZarrinPal.verify_payment")
    def test_checkout_reconciles_failed_stale_payment_before_creating_another(
        self,
        verify_payment,
        create_payment,
    ):
        self.presentation.cost = Decimal("10000.00")
        self.presentation.save(update_fields=["cost"])
        old_payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="OLDCHECKOUT123",
            pay_link="https://ceit-ssc.ir/payment/start?gateway=old",
        )
        old_payment.participations.add(self.participation)
        Payment.objects.filter(pk=old_payment.pk).update(
            created_date=timezone.now() - timedelta(minutes=31),
        )
        verify_payment.return_value = {
            "status": "failed",
            "ref_id": None,
            "card_pan": None,
            "error": "Payment was not completed",
        }
        create_payment.return_value = {
            "status": "success",
            "authority": "NEWCHECKOUT123",
            "link": "https://ceit-ssc.ir/payment/start?gateway=new",
        }

        response = self.client.post(reverse("payment-pay-all"), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["authority"], "NEWCHECKOUT123")
        old_payment.refresh_from_db()
        self.assertEqual(old_payment.payment_state, "FAILED")
        self.assertTrue(Payment.objects.filter(authority="NEWCHECKOUT123").exists())

    @patch("shop.views.ZarrinPal.create_payment")
    @patch("shop.views.ZarrinPal.verify_payment")
    def test_checkout_does_not_double_charge_a_successful_stale_payment(
        self,
        verify_payment,
        create_payment,
    ):
        self.presentation.cost = Decimal("10000.00")
        self.presentation.save(update_fields=["cost"])
        old_payment = Payment.objects.create(
            user=self.user,
            total_price=Decimal("10000.00"),
            authority="PAIDCHECKOUT123",
        )
        old_payment.participations.add(self.participation)
        Payment.objects.filter(pk=old_payment.pk).update(
            created_date=timezone.now() - timedelta(minutes=31),
        )
        verify_payment.return_value = {
            "status": "success",
            "ref_id": "PAID-CHECKOUT-REF",
            "card_pan": "621986******1234",
            "error": None,
        }

        response = self.client.post(reverse("payment-pay-all"), {}, format="json")

        self.assertEqual(response.status_code, 409)
        create_payment.assert_not_called()
        old_payment.refresh_from_db()
        self.participation.refresh_from_db()
        self.assertEqual(old_payment.payment_state, "COMPLETED")
        self.assertEqual(self.participation.payment_state, "COMPLETED")

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

    @patch("shop.views.ZarrinPal.create_payment")
    def test_scoped_coupon_discounts_only_selected_presentations(self, create_payment):
        self.presentation.cost = Decimal("10000.00")
        self.presentation.save(update_fields=["cost"])
        start = timezone.now() + timedelta(days=30)
        other_presentation = Presentation.objects.create(
            service_type="WORKSHOP",
            en_title="Unrelated workshop",
            fa_title="کارگاه نامرتبط",
            start=start,
            end=start + timedelta(hours=1),
            en_description="Test",
            fa_description="Test",
            capacity=10,
            cost=Decimal("20000.00"),
        )
        other_participation = Participation.objects.create(
            user=self.user,
            presentation=other_presentation,
        )
        accessory = Accessory.objects.create(
            name="Unrelated accessory",
            description="Must not receive the scoped discount",
            price=Decimal("3000.00"),
            img="unrelated-accessory.png",
            is_active=True,
        )
        coupon = Coupon.objects.create(name="TARGET50", count=5, percentage=50)
        coupon.eligible_presentations.add(self.presentation)
        create_payment.return_value = {
            "status": "success",
            "authority": "SCOPED123",
            "link": "https://ceit-ssc.ir/payment/start?gateway=scoped",
        }

        response = self.client.post(
            reverse("payment-pay-all"),
            {"coupon": coupon.pk, "accessories": [accessory.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        create_payment.assert_called_once_with(
            amount=Decimal("28000.00"),
            mobile=self.user.phone_number,
            email=self.user.email,
        )
        payment = Payment.objects.get(authority="SCOPED123")
        self.assertEqual(payment.total_price, Decimal("28000.00"))
        self.assertSetEqual(
            set(payment.coupon_participations.all()),
            {self.participation},
        )
        self.assertNotIn(other_participation, payment.coupon_participations.all())

    def test_scoped_coupon_is_rejected_without_an_eligible_cart_item(self):
        start = timezone.now() + timedelta(days=30)
        other_presentation = Presentation.objects.create(
            service_type="WORKSHOP",
            en_title="Coupon-only workshop",
            fa_title="کارگاه مخصوص کد",
            start=start,
            end=start + timedelta(hours=1),
            en_description="Test",
            fa_description="Test",
            capacity=10,
            cost=Decimal("10000.00"),
        )
        coupon = Coupon.objects.create(name="OTHERONLY", count=5, percentage=50)
        coupon.eligible_presentations.add(other_presentation)

        response = self.client.post(
            reverse("payment-pay-all"),
            {"coupon": coupon.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not apply", response.data["detail"])
        self.assertFalse(Payment.objects.exists())

    @patch('shop.views.ZarrinPal.create_payment')
    def test_coupon_minimum_rejects_small_cart_without_starting_payment(self, create_payment):
        coupon = Coupon.objects.create(
            name='MINTHREE', count=5, percentage=50, minimum_items=3,
        )
        validation = self.client.get(reverse('coupon-detail', args=[coupon.pk]))
        self.assertFalse(validation.data['is_valid'])
        self.assertEqual(validation.data['minimum_items'], 3)

        response = self.client.post(
            reverse('payment-pay-all'), {'coupon': coupon.pk}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'coupon_minimum_items')
        self.assertEqual(response.data['cart_items'], 1)
        self.assertFalse(Payment.objects.exists())
        create_payment.assert_not_called()
        coupon.refresh_from_db()
        self.assertEqual(coupon.count, 5)

    @patch('shop.views.ZarrinPal.create_payment')
    def test_coupon_minimum_counts_mixed_cart_and_discounts_only_scoped_items(self, create_payment):
        self.presentation.cost = Decimal('10000')
        self.presentation.save(update_fields=['cost'])
        coupon = Coupon.objects.create(
            name='MIXEDTHREE', count=5, percentage=50, minimum_items=3,
        )
        coupon.eligible_presentations.add(self.presentation)
        for index in range(2):
            other = Presentation.objects.get(pk=self.presentation.pk)
            other.pk = None
            other.en_title = f'Other workshop {index}'
            other.save()
            Participation.objects.create(user=self.user, presentation=other)
        create_payment.return_value = {
            'status': 'success', 'authority': 'MINIMUM-THREE',
            'link': 'https://ceit-ssc.ir/payment/start?gateway=test',
        }
        validation = self.client.get(reverse('coupon-detail', args=[coupon.pk]))
        self.assertTrue(validation.data['is_valid'])
        response = self.client.post(
            reverse('payment-pay-all'), {'coupon': coupon.pk}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.get().total_price, Decimal('25000'))
        self.assertEqual(Payment.objects.get().coupon_participations.count(), 1)

    def test_completed_items_do_not_count_toward_coupon_minimum(self):
        self.participation.payment_state = 'COMPLETED'
        self.participation.save(update_fields=['payment_state'])
        coupon = Coupon.objects.create(
            name='PASTITEMS', count=5, percentage=50, minimum_items=2,
        )
        response = self.client.get(reverse('coupon-detail', args=[coupon.pk]))
        self.assertFalse(response.data['is_valid'])

    def test_scoped_coupon_validation_requires_an_eligible_cart_item(self):
        start = timezone.now() + timedelta(days=30)
        other_presentation = Presentation.objects.create(
            service_type="WORKSHOP",
            en_title="Coupon validation workshop",
            fa_title="کارگاه اعتبارسنجی کد",
            start=start,
            end=start + timedelta(hours=1),
            en_description="Test",
            fa_description="Test",
            capacity=10,
            cost=Decimal("10000.00"),
        )
        coupon = Coupon.objects.create(name="VALIDATECART", count=5, percentage=50)
        coupon.eligible_presentations.add(other_presentation)

        without_item = self.client.get(reverse("coupon-detail", args=[coupon.pk]))

        self.assertEqual(without_item.status_code, 200)
        self.assertFalse(without_item.data["is_valid"])

        Participation.objects.create(
            user=self.user,
            presentation=other_presentation,
        )
        with_item = self.client.get(reverse("coupon-detail", args=[coupon.pk]))

        self.assertEqual(with_item.status_code, 200)
        self.assertTrue(with_item.data["is_valid"])

    def test_anonymous_user_cannot_validate_a_scoped_coupon(self):
        coupon = Coupon.objects.create(name="PRIVATECART", count=5, percentage=50)
        coupon.eligible_presentations.add(self.presentation)
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("coupon-detail", args=[coupon.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_valid"])

    @patch("shop.views.ZarrinPal.create_payment")
    @patch("shop.views.ZarrinPal.verify_payment")
    def test_capacity_preserving_coupon_does_not_consume_a_seat(
        self,
        verify_payment,
        create_payment,
    ):
        self.presentation.capacity = 1
        self.presentation.cost = Decimal("10000.00")
        self.presentation.save(update_fields=["capacity", "cost"])
        coupon = Coupon.objects.create(
            name="GUEST50",
            count=1,
            percentage=50,
            preserve_capacity=True,
        )
        coupon.eligible_presentations.add(self.presentation)
        create_payment.return_value = {
            "status": "success",
            "authority": "GUEST123",
            "link": "https://ceit-ssc.ir/payment/start?gateway=guest",
        }
        verify_payment.return_value = {
            "status": "success",
            "ref_id": "GUEST-REF",
            "card_pan": "621986******1234",
            "error": None,
        }

        checkout_response = self.client.post(
            reverse("payment-pay-all"),
            {"coupon": coupon.pk},
            format="json",
        )
        payment = Payment.objects.get(authority="GUEST123")

        self.assertEqual(checkout_response.status_code, 200)
        self.assertTrue(payment.coupon_preserves_capacity)
        self.assertEqual(self.presentation.get_remained_capacity(), 0)

        verify_response = self.client.post(
            reverse("payment-verify"),
            {"authority": payment.authority},
            format="json",
        )

        self.assertEqual(verify_response.status_code, 200)
        self.participation.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(self.participation.payment_state, "COMPLETED")
        self.assertTrue(self.participation.is_capacity_exempt)
        self.assertEqual(self.presentation.get_remained_capacity(), 1)
        self.assertEqual(coupon.count, 0)

    def test_free_capacity_preserving_coupon_is_settled_immediately(self):
        original_remaining = self.presentation.get_remained_capacity()
        start = timezone.now() + timedelta(days=30)
        other_presentation = Presentation.objects.create(
            service_type="WORKSHOP",
            en_title="Regular free workshop",
            fa_title="کارگاه رایگان عادی",
            start=start,
            end=start + timedelta(hours=1),
            en_description="Test",
            fa_description="Test",
            capacity=2,
            cost=Decimal("0"),
        )
        other_participation = Participation.objects.create(
            user=self.user,
            presentation=other_presentation,
        )
        coupon = Coupon.objects.create(
            name="FREEGUEST",
            count=1,
            percentage=100,
            preserve_capacity=True,
        )
        coupon.eligible_presentations.add(self.presentation)

        response = self.client.post(
            reverse("payment-pay-all"),
            {"coupon": coupon.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 204)
        self.participation.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(self.participation.payment_state, "COMPLETED")
        self.assertTrue(self.participation.is_capacity_exempt)
        self.assertEqual(self.presentation.get_remained_capacity(), original_remaining)
        other_participation.refresh_from_db()
        self.assertEqual(other_participation.payment_state, "COMPLETED")
        self.assertFalse(other_participation.is_capacity_exempt)
        self.assertEqual(other_presentation.get_remained_capacity(), 1)
        self.assertEqual(coupon.count, 0)


class ShopValidationTests(TestCase):
    def test_presentation_tag_exposes_both_languages_and_legacy_name(self):
        tag = PresentationTag.objects.create(
            en_name="Beginner",
            fa_name="مبتدی",
            color="#9B85FA",
        )

        data = PresentationTagSerializer(tag).data

        self.assertEqual(data["name"], "Beginner")
        self.assertEqual(data["en_name"], "Beginner")
        self.assertEqual(data["fa_name"], "مبتدی")

    def test_presentation_tag_requires_both_languages(self):
        tag = PresentationTag(en_name="Beginner", fa_name="")
        with self.assertRaises(ValidationError):
            tag.full_clean()

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

    def test_negative_cost_uses_django_model_validation(self):
        start = timezone.now() + timedelta(days=1)
        presentation = Presentation(
            service_type="WORKSHOP",
            en_title="Invalid cost",
            fa_title="هزینه نامعتبر",
            start=start,
            end=start + timedelta(hours=1),
            en_description="Test",
            fa_description="Test",
            capacity=1,
            cost=Decimal("-1"),
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


@override_settings(**PAYMENT_SETTINGS)
class ReconcilePendingPaymentsCommandTests(TestCase):
    @patch("shop.management.commands.reconcile_pending_payments.PaymentViewSet._verify_authority")
    def test_only_stale_pending_payments_are_reconciled(self, verify_authority):
        user = User.objects.create_user(
            phone_number="09121111111",
            password="test-password-123",
            email="reconcile@example.com",
            first_name="Reconcile",
            last_name="Tester",
        )
        stale = Payment.objects.create(
            user=user,
            total_price=Decimal("10000.00"),
            authority="STALECOMMAND123",
        )
        Payment.objects.filter(pk=stale.pk).update(
            created_date=timezone.now() - timedelta(minutes=31),
        )
        Payment.objects.create(
            user=user,
            total_price=Decimal("10000.00"),
            authority="RECENTCOMMAND123",
        )
        verify_authority.return_value = (
            stale,
            {"status": "failed"},
            400,
        )

        call_command("reconcile_pending_payments", verbosity=0)

        verify_authority.assert_called_once_with("STALECOMMAND123")
