from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Accessory, User
from shop.models import Bundle, Coupon, Participation, Payment, Presentation


class EditableCheckoutTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='editable@example.com', phone_number='09120000081',
            first_name='Editable', last_name='Checkout', password='test-password-123', is_active=True,
        )
        self.client.force_authenticate(self.user)
        start = timezone.now() + timedelta(days=10)
        self.presentation = Presentation.objects.create(
            service_type='WORKSHOP', en_title='Original workshop', fa_title='کارگاه',
            en_description='Test', fa_description='Test', start=start,
            end=start + timedelta(hours=1), capacity=1, cost='10000',
        )
        self.item = Participation.objects.create(user=self.user, presentation=self.presentation)
        self.old = Payment.objects.create(user=self.user, authority='OLD-LINK', total_price='10000')
        self.old.participations.add(self.item)
        self.checkout_url = reverse('payment-pay-all')

    def gateway(self, create):
        create.return_value = {
            'status': 'success', 'authority': 'NEW-LINK',
            'link': 'https://ceit-ssc.ir/payment/start?gateway=new',
        }

    def verify(self, authority):
        return self.client.post(reverse('payment-verify'), {'authority': authority}, format='json')

    @patch('shop.views.ZarrinPal.create_payment')
    def test_restart_on_last_seat_releases_own_old_reservation(self, create):
        self.gateway(create)
        self.assertEqual(self.presentation.get_remained_capacity(), 0)
        response = self.client.post(self.checkout_url, {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.presentation.get_remained_capacity(), 0)
        self.old.refresh_from_db()
        self.assertIsNotNone(self.old.superseded_at)
        self.assertIsNone(Payment.objects.get(authority='NEW-LINK').superseded_at)

    @patch('shop.views.ZarrinPal.create_payment')
    def test_failed_gateway_creation_preserves_old_link_and_reservation(self, create):
        create.return_value = {'status': 'error', 'error': 'Provider unavailable'}
        response = self.client.post(self.checkout_url, {}, format='json')
        self.assertEqual(response.status_code, 502)
        self.old.refresh_from_db()
        self.assertIsNone(self.old.superseded_at)
        self.assertEqual(self.presentation.get_remained_capacity(), 0)
        self.assertEqual(Payment.objects.count(), 1)

    def test_invalid_checkout_does_not_retire_old_payment(self):
        response = self.client.post(self.checkout_url, {'coupon': 'DOES-NOT-EXIST'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.old.refresh_from_db()
        self.assertIsNone(self.old.superseded_at)

    @patch('shop.views.ZarrinPal.create_payment')
    @patch('shop.views.ZarrinPal.verify_payment')
    def test_old_and_new_paid_links_only_fulfil_latest_order_once(self, verify, create):
        self.gateway(create)
        coupon = Coupon.objects.create(name='COUPON', count=3, percentage=10)
        self.old.coupon = coupon
        self.old.save()
        accessory = Accessory.objects.create(name='Extra', description='Test', price='2000', img='test.png')
        self.old.accessories.add(accessory)
        self.assertEqual(self.client.post(self.checkout_url, {}, format='json').status_code, 200)
        verify.return_value = {'status': 'success', 'ref_id': 'OLD-PAID-REF', 'card_pan': '1234'}
        result = self.verify(self.old.authority)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.data['code'], 'payment_requires_review')
        self.item.refresh_from_db()
        self.assertEqual(self.item.payment_state, 'PENDING')
        self.assertFalse(self.user.accessories.exists())
        coupon.refresh_from_db()
        self.assertEqual(coupon.count, 3)
        verify.return_value = {'status': 'success', 'ref_id': 'NEW-PAID-REF', 'card_pan': '5678'}
        self.assertEqual(self.verify('NEW-LINK').status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.payment_state, 'COMPLETED')
        verify.reset_mock()
        self.assertEqual(self.verify(self.old.authority).status_code, 409)
        verify.assert_not_called()
        self.assertEqual(Participation.objects.filter(payment_state='COMPLETED').count(), 1)

    def test_cart_deletion_keeps_original_order_snapshot_and_releases_capacity(self):
        response = self.client.delete(reverse('presentation-remove-participation', args=[self.presentation.pk]))
        self.assertEqual(response.status_code, 200)
        self.old.refresh_from_db()
        self.assertEqual(self.old.checkout_snapshot['presentations'][0]['name'], 'Original workshop')
        self.assertEqual(self.old.checkout_snapshot['amount'], '10000.00')
        self.assertEqual(self.presentation.get_remained_capacity(), 1)
        self.assertEqual(self.old.participations.count(), 0)

    @patch('shop.views.ZarrinPal.verify_payment')
    def test_cron_rechecks_rejected_old_links_and_flags_later_payment(self, verify):
        self.client.delete(reverse('presentation-remove-participation', args=[self.presentation.pk]))
        verify.return_value = {'status': 'failed', 'error': 'Not yet paid'}
        call_command('reconcile_pending_payments', stdout=StringIO())
        self.old.refresh_from_db()
        self.assertEqual(self.old.payment_state, 'FAILED')
        self.assertIsNotNone(self.old.last_reconciled_at)
        verify.reset_mock()
        call_command('reconcile_pending_payments', stdout=StringIO())
        verify.assert_not_called()
        Payment.objects.filter(pk=self.old.pk).update(last_reconciled_at=timezone.now() - timedelta(minutes=6))
        verify.return_value = {'status': 'success', 'ref_id': 'LATE-REF', 'card_pan': '1234'}
        output = StringIO()
        call_command('reconcile_pending_payments', stdout=output)
        self.assertIn('manual_review=1', output.getvalue())
        self.old.refresh_from_db()
        self.assertTrue(self.old.requires_manual_review)
        self.assertEqual(self.old.payment_state, 'COMPLETED')
        self.assertEqual(self.old.ref_id, 'LATE-REF')
        self.assertFalse(Participation.objects.exists())

    @patch('shop.views.ZarrinPal.verify_payment')
    def test_old_link_callback_identifies_support_review(self, verify):
        self.client.delete(reverse('presentation-remove-participation', args=[self.presentation.pk]))
        verify.return_value = {'status': 'success', 'ref_id': 'CALLBACK-REF', 'card_pan': '1234'}
        response = self.client.get(reverse('payment-provider-callback'), {'Authority': self.old.authority, 'Status': 'OK'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('ReviewRequired=1', response['Location'])
        self.assertIn('RefID=CALLBACK-REF', response['Location'])

    def test_bundle_conversion_retires_original_single_item_payment(self):
        second = Presentation.objects.get(pk=self.presentation.pk)
        second.pk = None
        second.en_title = 'Second workshop'
        second.save()
        bundle = Bundle.objects.create(name='Bundle', price='15000')
        bundle.presentations.set([self.presentation, second])
        response = self.client.post(reverse('bundle-add-to-cart', args=[bundle.pk]))
        self.assertEqual(response.status_code, 201)
        self.old.refresh_from_db()
        self.assertIsNotNone(self.old.superseded_at)
        self.assertEqual(self.presentation.get_remained_capacity(), 1)

    @patch('shop.views.ZarrinPal.create_payment')
    def test_removed_readded_item_is_never_fulfilled_by_old_payment(self, create):
        self.client.delete(reverse('presentation-remove-participation', args=[self.presentation.pk]))
        self.assertEqual(self.client.post(reverse('presentation-add-participation', args=[self.presentation.pk])).status_code, 201)
        self.gateway(create)
        self.assertEqual(self.client.post(self.checkout_url, {}, format='json').status_code, 200)
        with patch('shop.views.ZarrinPal.verify_payment', return_value={'status': 'success', 'ref_id': 'LATE', 'card_pan': '1234'}):
            self.assertEqual(self.verify(self.old.authority).status_code, 409)
        self.assertEqual(Participation.objects.get().payment_state, 'PENDING')
