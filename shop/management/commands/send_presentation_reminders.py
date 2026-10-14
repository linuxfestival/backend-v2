from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from shop.models import Participation, PresentationReminder
from shop.reminders import reminder_content


class Command(BaseCommand):
    help = 'Deliver queued presentation reminder emails, with bounded retries.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=25)

    def handle(self, *args, **options):
        sent, failed = 0, 0
        for _ in range(max(options['limit'], 0)):
            with transaction.atomic():
                job = PresentationReminder.objects.select_for_update(of=('self',), skip_locked=True).filter(
                    status='PENDING', available_at__lte=timezone.now(),
                ).select_related('user', 'presentation').order_by('created_at', 'pk').first()
                if job is None:
                    break
                job.attempts += 1
                if job.recipient != job.user.email or not job.user.is_active:
                    job.status, job.last_error = 'FAILED', 'RecipientChangedOrInactive'
                elif not Participation.objects.filter(user=job.user, presentation=job.presentation,
                                                      payment_state='COMPLETED').exists():
                    job.status, job.last_error = 'FAILED', 'NoCompletedRegistration'
                else:
                    try:
                        subject, body = reminder_content(job.presentation, job.user.get_full_name())
                        delivered = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                                              [job.recipient], fail_silently=False)
                        if delivered != 1:
                            raise RuntimeError('Email was not accepted.')
                        job.status, job.last_error = 'SENT', ''
                        job.sent_at = timezone.now()
                        sent += 1
                    except Exception as error:
                        # Never persist SMTP exception bodies or recipient data.
                        job.last_error = type(error).__name__
                        job.status = 'FAILED' if job.attempts >= 5 else 'PENDING'
                        job.available_at = timezone.now() + timedelta(minutes=2 ** job.attempts)
                if job.status != 'SENT':
                    failed += 1
                job.save(update_fields=['status', 'attempts', 'sent_at', 'last_error', 'available_at'])
        self.stdout.write(f'sent={sent} failed={failed}')
