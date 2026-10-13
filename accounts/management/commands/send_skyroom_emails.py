from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import SkyroomEmail
from accounts.skyroom import credential_password, room_data, user_presentations


class Command(BaseCommand):
    help = 'Send queued Skyroom credential emails, with bounded retries.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=25)

    def handle(self, *args, **options):
        sent, failed = 0, 0
        for _ in range(max(options['limit'], 0)):
            with transaction.atomic():
                job = SkyroomEmail.objects.select_for_update(of=('self',), skip_locked=True).filter(
                    status='PENDING', available_at__lte=timezone.now(),
                ).select_related('credential', 'credential__user').order_by('created_at').first()
                if job is None:
                    break
                job.attempts += 1
                try:
                    credential = job.credential
                    if job.recipient != credential.user.email or not credential.user.is_active:
                        job.status = 'FAILED'
                        job.last_error = 'RecipientChangedOrInactive'
                        job.save(update_fields=['status', 'attempts', 'last_error'])
                        failed += 1
                        continue
                    rooms = room_data(user_presentations(credential.user, [r['id'] for r in job.presentations]))
                    if not rooms:
                        job.status = 'FAILED'
                        job.last_error = 'NoCompletedSkyroomRegistration'
                        job.save(update_fields=['status', 'attempts', 'last_error'])
                        failed += 1
                        continue
                    links = '\n\n'.join(f"{r['name']}\n{r['room_url'] or 'لینک اتاق پس از تنظیم در پنل کاربری نمایش داده می‌شود.'}" for r in rooms)
                    message = (
                        f"سلام {credential.user.get_full_name()}\n\n"
                        f"اطلاعات ورود شما به اسکای‌روم لینوکس‌فست:\n"
                        f"نام کاربری: {credential.username}\n"
                        f"رمز عبور اسکای‌روم: {credential_password(credential)}\n\n"
                        f"{links}\n\n"
                        "این رمز مربوط به اسکای‌روم است و رمز ورود سایت شما تغییر نکرده است."
                    )
                    delivered = send_mail('اطلاعات ورود اسکای‌روم لینوکس‌فست', message,
                                          settings.DEFAULT_FROM_EMAIL, [job.recipient], fail_silently=False)
                    if delivered != 1:
                        raise RuntimeError('Email was not accepted.')
                    job.status = 'SENT'
                    job.sent_at = timezone.now()
                    job.presentations = rooms
                    job.last_error = ''
                    sent += 1
                except Exception as error:
                    # Exception class is enough for diagnostics; SMTP exception
                    # bodies can contain personal data or message contents.
                    job.last_error = type(error).__name__
                    job.status = 'FAILED' if job.attempts >= 5 else 'PENDING'
                    job.available_at = timezone.now() + timedelta(minutes=2 ** job.attempts)
                    failed += 1
                job.save(update_fields=['status', 'attempts', 'sent_at', 'presentations', 'last_error', 'available_at'])
        self.stdout.write(f'sent={sent} failed={failed}')
