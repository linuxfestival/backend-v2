from datetime import timedelta
from unittest.mock import patch

from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from shop.admin import CouponAdmin, PresentationAdmin
from shop.models import Coupon, CouponRedemption, Participation, Payment, Presentation
from shop.serializers import PresentationSerializer
from shop.bundles import BundleSerializer
from shop.models import Bundle


class RegistrationAndCouponAuditTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='audit@example.com', phone_number='09120000091', first_name='Coupon',
            last_name='Audit', password='test-password-123', is_active=True,
        )
        self.client.force_authenticate(self.user)
        self.first = self.presentation('First')
        self.second = self.presentation('Second')
        self.coupon_admin = CouponAdmin(Coupon, admin.site)

    def presentation(self, title):
        start = timezone.now() + timedelta(days=10)
        return Presentation.objects.create(
            en_title=title, fa_title=title, service_type='WORKSHOP', cost='10000',
            capacity=10, start=start, end=start + timedelta(hours=1),
            en_description='Test', fa_description='Test',
        )

    def populate_cart(self):
        return [Participation.objects.create(user=self.user, presentation=p) for p in [self.first, self.second]]

    def test_free_coupon_checkout_records_one_order_and_two_registrations(self):
        self.populate_cart()
        coupon = Coupon.objects.create(name='FREE-AUDIT', count=4, percentage=100, preserve_capacity=True)
        response = self.client.post(reverse('payment-pay-all'), {'coupon': coupon.pk}, format='json')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(CouponRedemption.objects.count(), 1)
        redemption = CouponRedemption.objects.get()
        self.assertIsNone(redemption.payment_id)
        self.assertEqual(redemption.participations.count(), 2)
        self.assertTrue(redemption.snapshot['preserve_capacity'])
        self.assertEqual(self.coupon_admin.used(coupon), 1)
        self.assertEqual(self.coupon_admin.discounted_registrations(coupon), 2)
        self.assertEqual(self.first.get_remained_capacity(), 10)
        coupon.refresh_from_db()
        self.assertEqual(coupon.count, 3)
        self.assertEqual(self.client.post(reverse('payment-pay-all'), {'coupon': coupon.pk}, format='json').status_code, 400)
        self.assertEqual(CouponRedemption.objects.count(), 1)

    @patch('shop.views.ZarrinPal.create_payment')
    @patch('shop.views.ZarrinPal.verify_payment')
    def test_paid_coupon_is_recorded_once_without_double_counting_payment(self, verify, create):
        self.populate_cart()
        coupon = Coupon.objects.create(name='PAID-AUDIT', count=4, percentage=50)
        create.return_value = {'status': 'success', 'authority': 'AUDIT-PAID', 'link': 'https://ceit-ssc.ir/payment/start'}
        verify.return_value = {'status': 'success', 'ref_id': 'AUDIT-REF', 'card_pan': '1234'}
        self.assertEqual(self.client.post(reverse('payment-pay-all'), {'coupon': coupon.pk}, format='json').status_code, 200)
        self.assertEqual(CouponRedemption.objects.count(), 0)
        coupon.percentage = 75
        coupon.preserve_capacity = True
        coupon.save()
        for _ in range(2):
            self.assertEqual(self.client.post(reverse('payment-verify'), {'authority': 'AUDIT-PAID'}, format='json').status_code, 200)
        self.assertEqual(CouponRedemption.objects.count(), 1)
        self.assertEqual(CouponRedemption.objects.get().snapshot['percentage'], 50)
        self.assertFalse(CouponRedemption.objects.get().snapshot['preserve_capacity'])
        self.assertEqual(self.coupon_admin.used(coupon), 1)
        self.assertEqual(self.coupon_admin.discounted_registrations(coupon), 2)

    def test_legacy_gateway_orders_still_count_and_review_payments_do_not(self):
        items = self.populate_cart()
        Participation.objects.filter(pk__in=[p.pk for p in items]).update(payment_state='COMPLETED')
        coupon = Coupon.objects.create(name='LEGACY', count=3, percentage=50)
        old = Payment.objects.create(user=self.user, coupon=coupon, payment_state='COMPLETED', total_price='10000')
        old.coupon_participations.set(items)
        Payment.objects.create(user=self.user, coupon=coupon, payment_state='COMPLETED', total_price='10000', requires_manual_review=True)
        self.assertEqual(self.coupon_admin.used(coupon), 1)
        self.assertEqual(self.coupon_admin.discounted_registrations(coupon), 2)

    @patch('shop.views.ZarrinPal.create_payment')
    @patch('shop.views.ZarrinPal.verify_payment')
    def test_retired_paid_link_does_not_create_a_coupon_redemption(self, verify, create):
        self.populate_cart()
        coupon = Coupon.objects.create(name='RETIRED', count=3, percentage=50)
        create.return_value = {'status': 'success', 'authority': 'RETIRED-AUDIT', 'link': 'https://ceit-ssc.ir/payment/start'}
        self.client.post(reverse('payment-pay-all'), {'coupon': coupon.pk}, format='json')
        self.client.delete(reverse('presentation-remove-participation', args=[self.first.pk]))
        verify.return_value = {'status': 'success', 'ref_id': 'RETIRED-REF', 'card_pan': '1234'}
        self.assertEqual(self.client.post(reverse('payment-verify'), {'authority': 'RETIRED-AUDIT'}).status_code, 409)
        self.assertFalse(CouponRedemption.objects.exists())
        self.assertEqual(self.coupon_admin.used(coupon), 0)

    def test_presentation_counts_include_completed_exempt_but_not_cart_items(self):
        Participation.objects.create(user=self.user, presentation=self.first, payment_state='COMPLETED', is_capacity_exempt=True)
        Participation.objects.create(user=self.user, presentation=self.second)
        model_admin = PresentationAdmin(Presentation, admin.site)
        queryset = model_admin.get_queryset(RequestFactory().get('/admin/shop/presentation/'))
        first, second = queryset.get(pk=self.first.pk), queryset.get(pk=self.second.pk)
        self.assertEqual(model_admin.completed_registrations(first), 1)
        self.assertEqual(model_admin.capacity_exempt_registrations(first), 1)
        self.assertEqual(model_admin.completed_registrations(second), 0)

    def test_display_counts_exempt_registrations_but_checkout_does_not(self):
        self.first.capacity = 1
        self.first.save()
        Participation.objects.create(user=self.user, presentation=self.first, payment_state='COMPLETED', is_capacity_exempt=True)
        data = PresentationSerializer(self.first).data
        self.assertEqual(data['remained_capacity'], 0)
        self.assertEqual(data['checkout_remaining_capacity'], 1)
        self.assertEqual(self.first.get_remained_capacity(), 1)
        bundle = Bundle.objects.create(name='Capacity display', price='10000')
        bundle.presentations.set([self.first, self.second])
        data = BundleSerializer(bundle).data
        self.assertEqual(data['remaining_capacity'], 0)
        self.assertEqual(data['checkout_remaining_capacity'], 1)
        self.assertTrue(data['is_available'])

    def test_display_keeps_gateway_reservations_and_ignores_retired_links(self):
        item = Participation.objects.create(user=self.user, presentation=self.first)
        payment = Payment.objects.create(user=self.user, total_price='10000', authority='DISPLAY-RESERVED')
        payment.participations.add(item)
        self.assertEqual(PresentationSerializer(self.first).data['remained_capacity'], 9)
        payment.superseded_at = timezone.now()
        payment.save()
        self.assertEqual(PresentationSerializer(self.first).data['remained_capacity'], 10)

    @patch('shop.views.ZarrinPal.create_payment')
    def test_scoped_coupon_logs_only_discounted_members_of_mixed_cart(self, create):
        self.populate_cart()
        coupon = Coupon.objects.create(name='SCOPED-AUDIT', count=3, percentage=100, preserve_capacity=True)
        coupon.eligible_presentations.add(self.first)
        create.return_value = {'status': 'success', 'authority': 'SCOPED-PAID', 'link': 'https://ceit-ssc.ir/payment/start'}
        self.client.post(reverse('payment-pay-all'), {'coupon': coupon.pk}, format='json')
        with patch('shop.views.ZarrinPal.verify_payment', return_value={'status': 'success', 'ref_id': 'SCOPED-REF', 'card_pan': '1234'}):
            self.client.post(reverse('payment-verify'), {'authority': 'SCOPED-PAID'})
        self.assertEqual(list(CouponRedemption.objects.get().participations.values_list('presentation_id', flat=True)), [self.first.pk])
        self.assertEqual(self.coupon_admin.discounted_registrations(coupon), 1)
