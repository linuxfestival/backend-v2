from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from shop.models import Presentation


class Command(BaseCommand):
    help = "Create or refresh a low-cost workshop used for a real payment smoke test."

    def add_arguments(self, parser):
        parser.add_argument(
            "--price",
            default="10000.00",
            help="Test price in Toman (default: 10000.00).",
        )

    def handle(self, *args, **options):
        try:
            price = Decimal(options["price"])
        except InvalidOperation as exc:
            raise CommandError("--price must be a decimal amount in Toman.") from exc
        if not price.is_finite() or price <= 0:
            raise CommandError("--price must be greater than zero.")

        start = timezone.now() + timedelta(days=30)
        presentation, created = Presentation.objects.update_or_create(
            en_title="Payment Gateway Test Workshop",
            defaults={
                "fa_title": "کارگاه آزمایشی پرداخت",
                "service_type": "WORKSHOP",
                "start": start,
                "end": start + timedelta(hours=1),
                "en_description": "Temporary item for testing the production payment flow.",
                "fa_description": "آیتم موقت برای آزمایش فرایند پرداخت واقعی.",
                "capacity": 20,
                "is_registration_active": True,
                "presentation_link": "",
                "morkopoloyor": "",
                "cost": price.quantize(Decimal("0.01")),
            },
        )
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} payment test workshop id={presentation.pk} price={presentation.cost} Toman"
        ))
