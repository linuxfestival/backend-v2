from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.db import connection, connections
from django.test import override_settings, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from accounts.models import User
from shop.admin import BundleAdminForm
from shop.models import Bundle, BundleSelection, Coupon, Participation, Payment, Presentation


@override_settings(PAYMENT_PENDING_TTL_SECONDS=1800)
class BundleTests(APITestCase):
    def setUp(self):
        self.user = self.make_user('bundle@example.com', '09120000031')
        self.client.force_authenticate(self.user)
        self.first = self.make_presentation('First', '100000')
        self.second = self.make_presentation('Second', '120000')
        self.bundle = Bundle.objects.create(name='Linux bundle', price='150000')
        self.bundle.presentations.set([self.first, self.second])
        self.add_url = reverse('bundle-add-to-cart', args=[self.bundle.pk])
        self.remove_url = reverse('bundle-remove-from-cart', args=[self.bundle.pk])
        self.pay_url = reverse('payment-pay-all')

    def make_user(self, email, phone):
        return User.objects.create_user(
            email=email, phone_number=phone, first_name='Bundle', last_name='Tester',
            password='test-password-123', is_active=True,
        )

    def make_presentation(self, title, cost):
        start = timezone.now() + timedelta(days=20)
        return Presentation.objects.create(
            en_title=title, fa_title=title, service_type='WORKSHOP',
            start=start, end=start + timedelta(hours=1), en_description='Test',
            fa_description='Test', cost=cost, capacity=3,
        )

    def gateway(self, create):
        create.return_value = {
            'status': 'success', 'authority': 'BUNDLE-AUTHORITY',
            'link': 'https://ceit-ssc.ir/payment/start?gateway=bundle',
        }

    def test_public_catalog_has_price_contents_and_availability(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('bundle-detail', args=[self.bundle.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data['price']), Decimal('150000.00'))
        self.assertEqual(Decimal(response.data['original_price']), Decimal('220000'))
        self.assertEqual(len(response.data['presentations']), 2)
        self.assertTrue(response.data['is_available'])
        self.assertEqual(response.data['remaining_capacity'], 3)

    def test_cart_mutations_and_cart_require_login(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(self.add_url).status_code, 401)
        self.assertEqual(self.client.delete(self.remove_url).status_code, 401)
        self.assertEqual(self.client.get(reverse('bundle-cart')).status_code, 401)
        self.assertFalse(BundleSelection.objects.exists())

    def test_add_replaces_individual_cart_items_and_remove_deletes_whole_bundle(self):
        individual = Participation.objects.create(user=self.user, presentation=self.first)
        response = self.client.post(self.add_url)
        self.assertEqual(response.status_code, 201)
        individual.refresh_from_db()
        self.assertEqual(individual.bundle_selection_id, response.data['id'])
        self.assertEqual(Participation.objects.count(), 2)
        cart = self.client.get(reverse('bundle-cart'))
        self.assertEqual(len(cart.data), 1)
        self.assertEqual(len(cart.data[0]['participation_ids']), 2)
        legacy_cart = self.client.get(reverse('presentation-cart'))
        self.assertTrue(all(item['bundle_selection'] for item in legacy_cart.data))
        remove_single = self.client.delete(reverse('presentation-remove-participation', args=[self.first.pk]))
        self.assertEqual(remove_single.status_code, 409)
        self.assertEqual(self.client.delete(self.remove_url).status_code, 204)
        self.assertFalse(Participation.objects.exists())
        self.assertFalse(BundleSelection.objects.exists())

    def test_duplicate_and_overlapping_bundles_are_rejected(self):
        self.assertEqual(self.client.post(self.add_url).status_code, 201)
        self.assertEqual(self.client.post(self.add_url).status_code, 409)
        another = Bundle.objects.create(name='Overlapping bundle', price='140000')
        another.presentations.set([self.first, self.second])
        response = self.client.post(reverse('bundle-add-to-cart', args=[another.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'bundle_overlap')
        self.assertEqual(BundleSelection.objects.count(), 1)

    def test_already_purchased_member_prevents_bundle_purchase(self):
        Participation.objects.create(user=self.user, presentation=self.first, payment_state='COMPLETED')
        response = self.client.post(self.add_url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['presentation_ids'], [self.first.pk])
        self.assertFalse(BundleSelection.objects.exists())

    def test_smallest_member_capacity_controls_availability(self):
        self.second.capacity = 1
        self.second.save()
        self.assertEqual(self.bundle.availability(), (1, None))
        other = self.make_user('other@example.com', '09120000032')
        Participation.objects.create(user=other, presentation=self.second, payment_state='COMPLETED')
        self.assertEqual(self.bundle.availability(), (0, 'sold_out'))
        self.assertEqual(self.client.post(self.add_url).status_code, 400)

    def test_started_closed_and_disabled_bundles_are_unavailable(self):
        self.bundle.is_active = False
        self.bundle.save()
        self.assertEqual(self.client.post(self.add_url).data['code'], 'inactive')
        self.bundle.is_active = True
        self.bundle.save()
        self.first.is_registration_active = False
        self.first.save()
        self.assertEqual(self.client.post(self.add_url).data['code'], 'registration_closed')
        self.first.is_registration_active = True
        self.first.start = timezone.now() - timedelta(hours=2)
        self.first.save()
        self.assertEqual(self.client.post(self.add_url).data['code'], 'started')

    @patch('shop.views.ZarrinPal.create_payment')
    @patch('shop.views.ZarrinPal.verify_payment')
    def test_checkout_charges_bundle_price_and_verifies_every_member(self, verify, create):
        self.gateway(create)
        self.client.post(self.add_url)
        self.assertEqual(self.client.post(self.pay_url, {}, format='json').status_code, 200)
        payment = Payment.objects.get()
        self.assertEqual(payment.total_price, Decimal('150000'))
        self.assertEqual(payment.participations.count(), 2)
        self.assertEqual(payment.bundle_snapshot[0]['presentation_ids'], [self.first.pk, self.second.pk])
        self.assertEqual(self.first.get_remained_capacity(), 2)
        self.assertEqual(self.second.get_remained_capacity(), 2)
        self.assertEqual(self.client.delete(self.remove_url).status_code, 409)
        self.bundle.price = Decimal('10000')
        self.bundle.presentations.clear()
        self.bundle.save()
        verify.return_value = {'status': 'success', 'ref_id': 'BUNDLE-REF', 'card_pan': '1234'}
        response = self.client.post(reverse('payment-verify'), {'authority': payment.authority})
        self.assertEqual(response.status_code, 200)
        verify.assert_called_once_with(authority=payment.authority, amount=Decimal('150000'))
        self.assertEqual(Participation.objects.filter(payment_state='COMPLETED').count(), 2)
        self.assertEqual(self.client.get(reverse('bundle-cart')).data, [])
        self.assertEqual(self.client.delete(self.remove_url).status_code, 409)

    @patch('shop.views.ZarrinPal.create_payment')
    def test_checkout_is_idempotent(self, create):
        self.gateway(create)
        self.client.post(self.add_url)
        first = self.client.post(self.pay_url, {}, format='json')
        second = self.client.post(self.pay_url, {}, format='json')
        self.assertEqual(first.data, second.data)
        self.assertEqual(Payment.objects.count(), 1)
        create.assert_called_once()

    @patch('shop.views.ZarrinPal.create_payment')
    def test_member_filling_up_after_cart_addition_blocks_checkout(self, create):
        self.client.post(self.add_url)
        self.second.capacity = 0
        self.second.save()
        self.assertEqual(self.client.post(self.pay_url, {}, format='json').status_code, 400)
        create.assert_not_called()
        self.assertFalse(Payment.objects.exists())

    @patch('shop.views.ZarrinPal.create_payment')
    def test_changed_bundle_membership_blocks_new_checkout(self, create):
        self.client.post(self.add_url)
        self.bundle.presentations.remove(self.second)
        response = self.client.post(self.pay_url, {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'bundle_changed')
        create.assert_not_called()

    @patch('shop.views.ZarrinPal.create_payment')
    def test_coupon_discounts_only_separate_items(self, create):
        self.gateway(create)
        self.client.post(self.add_url)
        third = self.make_presentation('Separate', '60000')
        Participation.objects.create(user=self.user, presentation=third)
        coupon = Coupon.objects.create(name='STANDALONE', count=5, percentage=50, preserve_capacity=True)
        response = self.client.post(self.pay_url, {'coupon': coupon.pk}, format='json')
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get()
        self.assertEqual(payment.total_price, Decimal('180000'))
        self.assertEqual(list(payment.coupon_participations.values_list('presentation_id', flat=True)), [third.pk])

    @patch('shop.views.ZarrinPal.create_payment')
    def test_bundle_only_cart_cannot_use_coupon(self, create):
        self.client.post(self.add_url)
        coupon = Coupon.objects.create(name='NO-STACK', count=5, percentage=100)
        self.assertFalse(self.client.get(reverse('coupon-detail', args=[coupon.pk])).data['is_valid'])
        response = self.client.post(self.pay_url, {'coupon': coupon.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()

    def test_free_bundle_completes_all_members_immediately(self):
        self.bundle.price = 0
        self.bundle.save()
        self.client.post(self.add_url)
        response = self.client.post(self.pay_url, {}, format='json')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Participation.objects.filter(payment_state='COMPLETED').count(), 2)

    @patch('shop.views.ZarrinPal.verify_payment')
    def test_expired_unpaid_bundle_can_be_removed(self, verify):
        self.client.post(self.add_url)
        payment = Payment.objects.create(user=self.user, total_price='150000', authority='EXPIRED')
        payment.participations.set(Participation.objects.all())
        Payment.objects.filter(pk=payment.pk).update(created_date=timezone.now() - timedelta(hours=1))
        verify.return_value = {'status': 'failed', 'error': 'Not paid'}
        self.assertEqual(self.client.delete(self.remove_url).status_code, 204)
        self.assertFalse(Participation.objects.exists())
        payment.refresh_from_db()
        self.assertEqual(payment.payment_state, 'FAILED')

    @patch('shop.views.ZarrinPal.verify_payment')
    def test_unreachable_gateway_preserves_expired_bundle(self, verify):
        self.client.post(self.add_url)
        payment = Payment.objects.create(user=self.user, total_price='150000', authority='RETRY')
        payment.participations.set(Participation.objects.all())
        Payment.objects.filter(pk=payment.pk).update(created_date=timezone.now() - timedelta(hours=1))
        verify.return_value = {'status': 'error', 'error': 'Timeout'}
        self.assertEqual(self.client.delete(self.remove_url).status_code, 503)
        self.assertEqual(Participation.objects.count(), 2)

    def test_user_cannot_access_other_users_bundle_cart(self):
        self.client.post(self.add_url)
        other = self.make_user('private@example.com', '09120000033')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(reverse('bundle-cart')).data, [])
        self.assertEqual(self.client.delete(self.remove_url).status_code, 404)
        self.assertEqual(Participation.objects.count(), 2)

    def test_admin_requires_two_presentations_and_nonnegative_price(self):
        data = {'name': 'Invalid', 'price': '-10', 'presentations': [self.first.pk], 'is_active': True}
        form = BundleAdminForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('price', form.errors)
        self.assertIn('presentations', form.errors)


@skipUnless(connection.vendor == 'postgresql', 'Row-lock concurrency requires PostgreSQL.')
class BundleConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.first = BundleTests.make_presentation(self, 'Last first seat', '100000')
        self.second = BundleTests.make_presentation(self, 'Last second seat', '120000')
        Presentation.objects.all().update(capacity=1)
        self.bundle = Bundle.objects.create(name='Last seats bundle', price='150000')
        self.bundle.presentations.set([self.first, self.second])
        self.users = [
            BundleTests.make_user(self, f'concurrent{i}@example.com', f'0912000004{i}')
            for i in range(2)
        ]

    def parallel_requests(self, users, endpoint):
        barrier = Barrier(2)

        def execute(user):
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                return client.post(endpoint, {}, format='json').status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(execute, users))

    @patch('shop.views.ZarrinPal.create_payment')
    def test_two_checkouts_cannot_purchase_same_final_seats(self, create):
        create.side_effect = lambda **kwargs: {
            'status': 'success', 'authority': str(uuid4()),
            'link': 'https://ceit-ssc.ir/payment/start?gateway=test',
        }
        for user in self.users:
            client = APIClient()
            client.force_authenticate(user)
            self.assertEqual(client.post(reverse('bundle-add-to-cart', args=[self.bundle.pk])).status_code, 201)
        responses = self.parallel_requests(self.users, reverse('payment-pay-all'))
        self.assertEqual(sorted(responses), [200, 400])
        self.assertEqual(Payment.objects.filter(payment_state='PENDING').count(), 1)
        self.assertEqual(Payment.objects.get().participations.count(), 2)

    def test_two_same_user_additions_cannot_duplicate_bundle(self):
        responses = self.parallel_requests(
            [self.users[0], self.users[0]], reverse('bundle-add-to-cart', args=[self.bundle.pk]),
        )
        self.assertEqual(sorted(responses), [201, 409])
        self.assertEqual(BundleSelection.objects.count(), 1)
        self.assertEqual(Participation.objects.count(), 2)
