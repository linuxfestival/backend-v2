from uuid import UUID, uuid4

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from .models import Presentation, PresentationReminder


TOKEN_SALT = 'shop.presentation-reminder'


def reminder_recipients(presentation):
    return User.objects.filter(
        is_active=True, participations__presentation=presentation,
        participations__payment_state='COMPLETED',
    ).exclude(email='').distinct().order_by('pk')


def confirmation_token(presentation):
    return signing.dumps({'presentation': presentation.pk, 'batch': str(uuid4())}, salt=TOKEN_SALT)


def reminder_batch(token, presentation):
    try:
        data = signing.loads(token, salt=TOKEN_SALT, max_age=3600)
        if data['presentation'] != presentation.pk:
            raise ValueError
        return UUID(data['batch'])
    except (signing.BadSignature, ValueError, KeyError, TypeError) as error:
        raise ValueError('Confirmation expired or invalid. Open the reminder page again.') from error


@transaction.atomic
def queue_reminders(presentation, batch_id, queued_by):
    presentation = Presentation.objects.select_for_update().get(pk=presentation.pk)
    # Serialize confirmations for this presentation. Replaying the same POST
    # must not send another batch, even if registrations changed in between.
    if PresentationReminder.objects.filter(batch_id=batch_id).exists():
        return 0
    jobs = [PresentationReminder(presentation=presentation, user=user, recipient=user.email,
                                  batch_id=batch_id, queued_by=queued_by)
            for user in reminder_recipients(presentation)]
    PresentationReminder.objects.bulk_create(jobs)
    return len(jobs)


def reminder_content(presentation, full_name):
    title = presentation.fa_title or presentation.en_title
    start = timezone.localtime(presentation.start)
    end = timezone.localtime(presentation.end)
    message = (
        f'سلام {full_name}\n\n'
        f'یادآوری حضور شما در «{title}» از برنامه‌های لینوکس‌فست.\n'
        f'شروع: {start:%Y-%m-%d %H:%M}\n'
        f'پایان: {end:%Y-%m-%d %H:%M}\n'
        'تاریخ‌ها میلادی و ساعت‌ها به وقت تهران هستند.\n\n'
    )
    if presentation.is_skyroom and presentation.skyroom_room_url:
        message += f'لینک ورود به اتاق:\n{presentation.skyroom_room_url}\n\n'
    site_url = settings.PUBLIC_SITE_URL.strip().rstrip('/') or 'https://linuxfest.ir'
    # SITE_ADDRESS in compose may be a bare hostname (Caddy accepts both).
    if not site_url.startswith(('https://', 'http://')):
        site_url = 'https://' + site_url
    panel_url = site_url + '/profile/workshops'
    message += f'جزئیات برنامه و ارائه‌های ثبت‌نام‌شده را در پنل کاربری بررسی کنید:\n{panel_url}\n\nمنتظر حضور شما هستیم.\nتیم لینوکس‌فست'
    return f'یادآوری لینوکس‌فست: {title}', message
