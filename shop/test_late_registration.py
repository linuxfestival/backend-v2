from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from shop.models import Bundle, Participation, Payment, Presentation
from shop.serializers import PresentationSerializer


class LateRegistrationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='late@example.com', phone_number='09120000880',
            first_name='Late', last_name='Registrant', is_active=True)
        self.client.force_authenticate(self.user)
        self.presentation = self.make_presentation('Community day')
        self.add_url = reverse('presentation-add-participation', args=[self.presentation.pk])
        self.pay_url = reverse('payment-pay-all')

    def make_presentation(self, title):
        start = timezone.now() - timedelta(hours=1)
        return Presentation.objects.create(en_title=title, fa_title=title, service_type='WORKSHOP',
            start=start, end=start + timedelta(hours=6), en_description='Test', fa_description='Test',
            cost='10000', capacity=10)

    def allow_late(self):
        self.presentation.allow_registration_after_start = True
        self.presentation.save()

    def gateway(self, create):
        create.return_value = {'status': 'success', 'authority': 'LATE-REGISTRATION',
                              'link': 'https://example.com/payment'}

    def test_other_started_presentations_remain_blocked_by_default(self):
        self.assertTrue(self.presentation.is_registration_time_closed())
        self.assertEqual(self.client.post(self.add_url).status_code, 400)
        self.assertFalse(Participation.objects.exists())

    @patch('shop.views.ZarrinPal.verify_payment')
    @patch('shop.views.ZarrinPal.create_payment')
    def test_explicit_override_allows_add_checkout_and_payment_completion(self, create, verify):
        self.allow_late()
        self.gateway(create)
        self.assertFalse(self.presentation.is_registration_time_closed())
        self.assertEqual(self.client.post(self.add_url).status_code, 201)
        response = self.client.post(self.pay_url, {}, format='json')
        self.assertEqual(response.status_code, 200)
        create.assert_called_once_with(amount=Decimal('10000.00'), mobile=self.user.phone_number, email=self.user.email)
        verify.return_value = {'status': 'success', 'ref_id': 'LATE-REF', 'card_pan': '1234'}
        response = self.client.post(reverse('payment-verify'), {'authority': 'LATE-REGISTRATION'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Participation.objects.get().payment_state, 'COMPLETED')

    def test_late_registration_still_requires_open_registration(self):
        self.allow_late()
        self.presentation.is_registration_active = False
        self.presentation.save()
        self.assertEqual(self.client.post(self.add_url).status_code, 400)
        self.assertFalse(Participation.objects.exists())

    @patch('shop.views.ZarrinPal.create_payment')
    def test_existing_cart_cannot_checkout_when_registration_is_closed(self, create):
        self.allow_late()
        Participation.objects.create(user=self.user, presentation=self.presentation)
        self.presentation.is_registration_active = False
        self.presentation.save()
        self.assertEqual(self.client.post(self.pay_url, {}, format='json').status_code, 400)
        create.assert_not_called()

    @patch('shop.views.ZarrinPal.create_payment')
    def test_existing_cart_cannot_bypass_start_without_override(self, create):
        Participation.objects.create(user=self.user, presentation=self.presentation)
        self.assertEqual(self.client.post(self.pay_url, {}, format='json').status_code, 400)
        create.assert_not_called()

    @patch('shop.views.ZarrinPal.create_payment')
    def test_late_registration_still_checks_capacity_at_add_and_checkout(self, create):
        self.allow_late()
        self.presentation.capacity = 0
        self.presentation.save()
        self.assertEqual(self.client.post(self.add_url).status_code, 400)
        Participation.objects.create(user=self.user, presentation=self.presentation)
        self.assertEqual(self.client.post(self.pay_url, {}, format='json').status_code, 400)
        create.assert_not_called()

    def test_free_late_registration_can_complete_without_gateway(self):
        self.allow_late()
        self.presentation.cost = 0
        self.presentation.save()
        self.assertEqual(self.client.post(self.add_url).status_code, 201)
        self.assertEqual(self.client.post(self.pay_url, {}, format='json').status_code, 204)
        self.assertEqual(Participation.objects.get().payment_state, 'COMPLETED')

    @patch('shop.views.ZarrinPal.create_payment')
    def test_override_cannot_bypass_another_closed_item_in_same_cart(self, create):
        self.allow_late()
        other = self.make_presentation('Closed workshop')
        other.start = timezone.now() + timedelta(hours=1)
        other.is_registration_active = False
        other.save()
        Participation.objects.create(user=self.user, presentation=self.presentation)
        Participation.objects.create(user=self.user, presentation=other)
        self.assertEqual(self.client.post(self.pay_url, {}, format='json').status_code, 400)
        self.assertFalse(Payment.objects.exists())
        create.assert_not_called()

    def test_api_exposes_override(self):
        self.assertFalse(PresentationSerializer(self.presentation).data['allow_registration_after_start'])
        self.allow_late()
        self.assertTrue(PresentationSerializer(self.presentation).data['allow_registration_after_start'])

    def test_bundle_requires_each_started_member_to_explicitly_allow_late_registration(self):
        other = self.make_presentation('Other workshop')
        bundle = Bundle.objects.create(name='Late bundle', price='15000')
        bundle.presentations.set([self.presentation, other])
        self.allow_late()
        self.assertEqual(bundle.availability(), (0, 'started'))
        other.allow_registration_after_start = True
        other.save()
        self.assertEqual(bundle.availability(), (10, None))
        other.is_registration_active = False
        other.save()
        self.assertEqual(bundle.availability(), (0, 'registration_closed'))

    def test_paid_or_duplicate_registration_stays_protected(self):
        self.allow_late()
        Participation.objects.create(user=self.user, presentation=self.presentation, payment_state='COMPLETED')
        self.assertEqual(self.client.post(self.add_url).status_code, 400)
        self.assertEqual(Participation.objects.count(), 1)
