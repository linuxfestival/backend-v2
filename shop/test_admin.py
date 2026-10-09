from decimal import Decimal

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from shop.admin import PaymentAdmin
from shop.models import Payment


class PaymentAdminSummaryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email='admin-summary@example.com',
            phone_number='09120000010',
            first_name='Payment',
            last_name='Admin',
            password='test-password-123',
        )
        self.payer = User.objects.create_user(
            email='payer-summary@example.com',
            phone_number='09120000011',
            first_name='Payment',
            last_name='Payer',
            password='test-password-123',
            is_active=True,
        )
        Payment.objects.create(
            user=self.payer,
            total_price=Decimal('120000.00'),
            payment_state='COMPLETED',
            authority='SUMMARY-COMPLETED-1',
        )
        Payment.objects.create(
            user=self.payer,
            total_price=Decimal('80000.00'),
            payment_state='COMPLETED',
            authority='SUMMARY-COMPLETED-2',
        )
        Payment.objects.create(
            user=self.payer,
            total_price=Decimal('900000.00'),
            payment_state='PENDING',
            authority='SUMMARY-PENDING',
        )
        self.url = reverse('admin:shop_payment_changelist')
        self.request_factory = RequestFactory()
        self.payment_admin = PaymentAdmin(Payment, admin.site)

    def get_changelist(self, query=None):
        request = self.request_factory.get(self.url, query or {})
        request.user = self.admin
        return self.payment_admin.changelist_view(request)

    def test_changelist_shows_completed_count_and_revenue(self):
        response = self.get_changelist()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context_data['completed_payment_summary'],
            {'count': 2, 'total': Decimal('200000')},
        )
        self.assertEqual(
            response.template_name,
            'admin/shop/payment/change_list.html',
        )

    def test_summary_respects_changelist_filters(self):
        response = self.get_changelist(
            {'payment_state__exact': 'PENDING'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context_data['completed_payment_summary'],
            {'count': 0, 'total': Decimal('0')},
        )
