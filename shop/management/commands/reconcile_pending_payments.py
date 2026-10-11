from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q, F
from django.utils import timezone
from rest_framework import status

from shop.models import Payment
from shop.views import PaymentViewSet


class Command(BaseCommand):
    help = 'Verify stale active payments and retired links; flag late payments for support.'

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of payments to reconcile (default: 100).",
        )

    def handle(self, *args, **options):
        limit = max(options["limit"], 0)
        cutoff = timezone.now() - timedelta(
            seconds=settings.PAYMENT_PENDING_TTL_SECONDS,
        )
        recheck_cutoff = timezone.now() - timedelta(minutes=5)
        payments = list(Payment.objects.filter(authority__isnull=False).filter(
            Q(payment_state='PENDING', superseded_at__isnull=True, created_date__lte=cutoff)
            | Q(superseded_at__isnull=False, payment_state__in=['PENDING', 'FAILED']),
        ).filter(
            Q(last_reconciled_at__isnull=True) | Q(last_reconciled_at__lte=recheck_cutoff),
        ).order_by(F('last_reconciled_at').asc(nulls_first=True), 'created_date')[:limit])
        result = {
            "checked": 0,
            "completed": 0,
            "failed": 0,
            "retryable": 0,
            'manual_review': 0,
        }
        for payment in payments:
            _payment, _payload, response_status = PaymentViewSet._verify_authority(
                payment.authority,
            )
            result["checked"] += 1
            if response_status == status.HTTP_200_OK:
                result["completed"] += 1
            elif response_status == status.HTTP_409_CONFLICT and _payment and _payment.requires_manual_review:
                result['manual_review'] += 1
            elif response_status == status.HTTP_400_BAD_REQUEST:
                result["failed"] += 1
            else:
                result["retryable"] += 1

        self.stdout.write(" ".join(f"{key}={value}" for key, value in result.items()))
