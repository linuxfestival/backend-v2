from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework import status

from shop.models import Payment
from shop.views import PaymentViewSet


class Command(BaseCommand):
    help = "Verify stale pending payments with the provider and persist their real state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of stale payments to verify (default: 100).",
        )

    def handle(self, *args, **options):
        limit = max(options["limit"], 0)
        cutoff = timezone.now() - timedelta(
            seconds=settings.PAYMENT_PENDING_TTL_SECONDS,
        )
        payments = list(
            Payment.objects.filter(
                payment_state="PENDING",
                authority__isnull=False,
                created_date__lte=cutoff,
            ).order_by("created_date")[:limit]
        )
        result = {
            "checked": 0,
            "completed": 0,
            "failed": 0,
            "retryable": 0,
        }
        for payment in payments:
            _payment, _payload, response_status = PaymentViewSet._verify_authority(
                payment.authority,
            )
            result["checked"] += 1
            if response_status == status.HTTP_200_OK:
                result["completed"] += 1
            elif response_status == status.HTTP_400_BAD_REQUEST:
                result["failed"] += 1
            else:
                result["retryable"] += 1

        self.stdout.write(" ".join(f"{key}={value}" for key, value in result.items()))
