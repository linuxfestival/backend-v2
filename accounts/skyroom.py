from io import BytesIO

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook

from .models import SkyroomCredential, SkyroomEmail, User


HEADERS = ['email', 'phone_number', 'full_name', 'sky_username', 'sky_password', 'presentations', 'rooms']


def cipher():
    try:
        return Fernet(settings.SKYROOM_ENCRYPTION_KEY.encode('ascii'))
    except (ValueError, TypeError, UnicodeError) as error:
        raise ImproperlyConfigured('A valid SKYROOM_ENCRYPTION_KEY is required.') from error


def credential_password(credential):
    try:
        return cipher().decrypt(credential.encrypted_password.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError) as error:
        raise ImproperlyConfigured('Skyroom credentials cannot be decrypted with the configured key.') from error


def ensure_credential(user):
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        existing = SkyroomCredential.objects.filter(user=user).first()
        if existing:
            return existing
        password = user.phone_number.strip().removeprefix('+98')
        encrypted = cipher().encrypt(password.encode('utf-8')).decode('ascii')
        base = user.email.lower().split('@', 1)[0][:240]
        # Different domains can share the same email prefix. Unique
        # constraints and savepoints also handle simultaneous first exports.
        for username in [base, f'{base}-{user.pk}']:
            try:
                with transaction.atomic():
                    return SkyroomCredential.objects.create(user=user, username=username, encrypted_password=encrypted)
            except IntegrityError:
                continue
        raise ImproperlyConfigured('Could not allocate a unique Skyroom username.')


def user_presentations(user, selected_ids=None):
    from shop.models import Presentation
    items = Presentation.objects.filter(
        participations__user=user, participations__payment_state='COMPLETED', is_skyroom=True,
    ).distinct().order_by('pk')
    if selected_ids is not None:
        items = items.filter(pk__in=selected_ids)
    return items


def room_data(items):
    return [{'id': item.pk, 'name': item.fa_title or item.en_title,
             'room_url': item.skyroom_room_url, 'start': item.start.isoformat()} for item in items]


def export_users(users, selected_ids=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Participants'
    sheet.append(HEADERS)
    for user in users.order_by('pk'):
        credential = ensure_credential(user)
        rooms = room_data(user_presentations(user, selected_ids))
        values = [user.email, user.phone_number, user.get_full_name(), credential.username,
                  credential_password(credential), '\n'.join(r['name'] for r in rooms),
                  '\n'.join(dict.fromkeys(r['room_url'] for r in rooms if r['room_url']))]
        sheet.append(values)
        # User-controlled names/titles must remain text, never Excel formulas;
        # phone/password leading zeroes must also survive import.
        for cell in sheet[sheet.max_row]:
            cell.data_type = 's'
            cell.number_format = '@'
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in zip('ABCDEFG', [32, 20, 30, 35, 20, 55, 60]):
        sheet.column_dimensions[column].width = width
    data = BytesIO()
    workbook.save(data)
    response = HttpResponse(data.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = timezone.localtime().strftime('presentation_participants_%Y%m%d_%H%M%S.xlsx')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    return response


def queue_credential_emails(users, selected_ids):
    count = 0
    with transaction.atomic():
        for user in users.order_by('pk'):
            rooms = room_data(user_presentations(user, selected_ids))
            if not rooms:
                continue
            credential = ensure_credential(user)
            SkyroomEmail.objects.create(credential=credential, recipient=user.email, presentations=rooms)
            count += 1
    return count
