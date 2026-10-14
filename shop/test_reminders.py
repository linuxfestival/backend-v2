from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core import mail, signing
from django.core.management import call_command
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SkyroomCredential, User
from shop.models import Participation, Presentation, PresentationReminder
from shop.reminders import confirmation_token, queue_reminders, reminder_batch, reminder_content, TOKEN_SALT


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SKYROOM_ENCRYPTION_KEY='',
                   STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                             'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PresentationReminderTests(TestCase):
    def setUp(self):
        self.admin = self.user('admin', '09123456001', is_staff=True, is_superuser=True)
        self.attendee = self.user('attendee', '09123456002')
        self.pending = self.user('pending', '09123456003')
        self.other = self.user('other', '09123456004')
        start = timezone.now() + timedelta(days=1)
        self.presentation = Presentation.objects.create(
            en_title='Reminder workshop', fa_title='کارگاه یادآوری', cost='10000', capacity=10,
            service_type='WORKSHOP', start=start, end=start + timedelta(hours=1),
            en_description='Test', fa_description='Test', is_skyroom=False,
        )
        self.confirmed = Participation.objects.create(
            user=self.attendee, presentation=self.presentation, payment_state='COMPLETED', is_capacity_exempt=True)
        Participation.objects.create(user=self.pending, presentation=self.presentation, payment_state='PENDING')
        self.url = reverse('admin:shop_presentation_notify_participants', args=[self.presentation.pk])
        self.change_url = reverse('admin:shop_presentation_change', args=[self.presentation.pk])
        self.client.force_login(self.admin)

    def user(self, name, phone, **extra):
        return User.objects.create_user(email=f'{name}@example.com', phone_number=phone,
                                        first_name=name, last_name='Tester', is_active=True, **extra)

    def confirm(self, token=None, client=None):
        return (client or self.client).post(self.url, {
            'confirm': 'yes', 'confirmation_token': token or confirmation_token(self.presentation),
        })

    def queue(self):
        batch = reminder_batch(confirmation_token(self.presentation), self.presentation)
        return queue_reminders(self.presentation, batch, self.admin)

    def work(self, limit=25):
        call_command('send_presentation_reminders', limit=limit, stdout=StringIO())

    def test_edit_page_has_button_and_get_only_previews_count_and_message(self):
        self.assertContains(self.client.get(self.change_url), 'Send reminder email')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['recipient_count'], 1)
        self.assertContains(response, self.presentation.fa_title)
        self.assertContains(response, 'Confirm and queue reminder emails')
        self.assertFalse(PresentationReminder.objects.exists())
        self.assertFalse(SkyroomCredential.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_confirmation_queues_only_completed_active_users_without_sending_yet(self):
        inactive = self.user('inactive', '09123456005')
        inactive.is_active = False
        inactive.save()
        Participation.objects.create(user=inactive, presentation=self.presentation, payment_state='COMPLETED')
        failed = self.user('failed', '09123456006')
        Participation.objects.create(user=failed, presentation=self.presentation, payment_state='FAILED')
        self.assertRedirects(self.confirm(), self.change_url)
        job = PresentationReminder.objects.get()
        self.assertEqual(job.user, self.attendee)
        self.assertEqual(job.presentation, self.presentation)
        self.assertEqual(job.recipient, self.attendee.email)
        self.assertEqual(job.queued_by, self.admin)
        self.assertEqual(len(mail.outbox), 0)

    def test_repeated_confirmation_does_not_duplicate_even_after_new_registration(self):
        token = confirmation_token(self.presentation)
        self.confirm(token)
        self.pending.participations.filter(presentation=self.presentation).update(payment_state='COMPLETED')
        self.confirm(token)
        self.assertEqual(PresentationReminder.objects.count(), 1)

    def test_new_confirmation_can_intentionally_send_another_reminder(self):
        self.confirm()
        self.confirm()
        self.assertEqual(PresentationReminder.objects.count(), 2)

    def test_invalid_unconfirmed_expired_or_wrong_presentation_post_never_queues(self):
        token = signing.dumps({'presentation': self.presentation.pk + 1, 'batch': 'invalid'}, salt=TOKEN_SALT)
        self.assertEqual(self.confirm(token).status_code, 400)
        self.assertEqual(self.confirm('tampered-token').status_code, 400)
        self.assertEqual(self.client.post(self.url, {}).status_code, 400)
        with patch('django.core.signing.time.time', return_value=0):
            expired = confirmation_token(self.presentation)
        self.assertEqual(self.confirm(expired).status_code, 400)
        self.assertFalse(PresentationReminder.objects.exists())

    def test_staff_with_change_only_cannot_send_or_see_button(self):
        self.other.is_staff = True
        self.other.save()
        self.other.user_permissions.add(Permission.objects.get(codename='change_presentation'))
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.change_url), 'Send reminder email')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.confirm().status_code, 403)
        self.assertFalse(PresentationReminder.objects.exists())

    def test_explicit_sender_also_requires_presentation_view_permission(self):
        self.other.is_staff = True
        self.other.save()
        self.other.user_permissions.add(Permission.objects.get(codename='send_presentation_reminders'))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.other.user_permissions.add(Permission.objects.get(codename='view_presentation'))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertRedirects(self.confirm(), self.change_url)

    def test_csrf_is_required_on_confirmation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(self.confirm(client=client).status_code, 403)
        self.assertFalse(PresentationReminder.objects.exists())
        preview = client.get(self.url)
        response = client.post(self.url, {'confirm': 'yes',
            'confirmation_token': preview.context['confirmation_token'],
            'csrfmiddlewaretoken': client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PresentationReminder.objects.count(), 1)

    def test_invalid_methods_and_missing_presentation(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)
        self.assertEqual(self.client.get(reverse('admin:shop_presentation_notify_participants', args=[99999])).status_code, 404)

    def test_worker_sends_private_reminder_once_without_credentials_or_encryption_key(self):
        self.assertEqual(self.queue(), 1)
        self.work()
        self.work()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.attendee.email])
        self.assertFalse(message.cc)
        self.assertFalse(message.bcc)
        self.assertIn(self.presentation.fa_title, message.subject)
        self.assertIn(self.attendee.get_full_name(), message.body)
        self.assertIn('به وقت تهران', message.body)
        self.assertIn('https://linuxfest.ir/profile/workshops', message.body)
        self.assertNotIn(self.attendee.phone_number, message.body)
        self.assertFalse(SkyroomCredential.objects.exists())
        self.assertEqual(PresentationReminder.objects.get().status, 'SENT')

    def test_each_recipient_gets_an_individual_email(self):
        Participation.objects.create(user=self.other, presentation=self.presentation, payment_state='COMPLETED')
        self.queue()
        self.work()
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual({tuple(message.to) for message in mail.outbox}, {(self.attendee.email,), (self.other.email,)})

    def test_worker_uses_latest_presentation_time_and_room_url(self):
        self.queue()
        self.presentation.is_skyroom = True
        self.presentation.skyroom_room_url = 'https://www.skyroom.online/ch/test/current'
        self.presentation.start += timedelta(hours=1)
        self.presentation.save()
        self.work()
        self.assertIn(self.presentation.skyroom_room_url, mail.outbox[0].body)
        self.assertIn(timezone.localtime(self.presentation.start).strftime('%Y-%m-%d %H:%M'), mail.outbox[0].body)

    def test_room_link_is_not_in_reminder_when_skyroom_is_disabled(self):
        self.presentation.skyroom_room_url = 'https://www.skyroom.online/ch/test/not-published'
        _, body = reminder_content(self.presentation, 'Test')
        self.assertNotIn(self.presentation.skyroom_room_url, body)

    @override_settings(PUBLIC_SITE_URL='linuxfest.ir')
    def test_bare_compose_site_address_produces_absolute_https_panel_link(self):
        _, body = reminder_content(self.presentation, 'Test')
        self.assertIn('https://linuxfest.ir/profile/workshops', body)

    def test_revoked_registration_is_not_emailed(self):
        self.queue()
        self.confirmed.delete()
        self.work()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(PresentationReminder.objects.get().last_error, 'NoCompletedRegistration')

    def test_changed_email_or_inactive_account_is_not_emailed(self):
        self.queue()
        self.attendee.email = 'changed@example.com'
        self.attendee.save()
        self.work()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(PresentationReminder.objects.get().last_error, 'RecipientChangedOrInactive')
        self.attendee.is_active = False
        self.attendee.save()
        self.assertEqual(self.queue(), 0)

    @patch('shop.management.commands.send_presentation_reminders.send_mail', side_effect=RuntimeError('Sensitive SMTP body'))
    def test_delivery_failures_retry_then_stop_without_recording_sensitive_error(self, send):
        self.queue()
        for _ in range(5):
            PresentationReminder.objects.update(available_at=timezone.now() - timedelta(seconds=1))
            self.work()
        job = PresentationReminder.objects.get()
        self.assertEqual(job.status, 'FAILED')
        self.assertEqual(job.attempts, 5)
        self.assertEqual(job.last_error, 'RuntimeError')
        self.work()
        self.assertEqual(send.call_count, 5)

    @patch('shop.management.commands.send_presentation_reminders.send_mail', return_value=0)
    def test_mail_backend_rejecting_message_is_retried(self, send):
        self.queue()
        self.work()
        job = PresentationReminder.objects.get()
        self.assertEqual(job.status, 'PENDING')
        self.assertEqual(job.attempts, 1)
        self.assertGreater(job.available_at, timezone.now())

    def test_worker_limit_and_admin_retry_only_failed(self):
        from shop.admin import PresentationReminderAdmin
        from django.contrib import admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        self.queue()
        self.work(limit=0)
        self.assertEqual(len(mail.outbox), 0)
        self.work()
        request = RequestFactory().post('/admin/shop/presentationreminder/')
        request.user, request.session = self.admin, {}
        request._messages = FallbackStorage(request)
        model_admin = PresentationReminderAdmin(PresentationReminder, admin.site)
        model_admin.retry_failed(request, PresentationReminder.objects.all())
        self.assertEqual(PresentationReminder.objects.get().status, 'SENT')
        PresentationReminder.objects.update(status='FAILED', attempts=5)
        model_admin.retry_failed(request, PresentationReminder.objects.all())
        job = PresentationReminder.objects.get()
        self.assertEqual((job.status, job.attempts), ('PENDING', 0))


@skipUnless(connection.vendor == 'postgresql', 'Reminder locking requires PostgreSQL.')
class PresentationReminderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='reminder-concurrent@example.com', phone_number='09123456050',
                                            first_name='Concurrent', last_name='Attendee', is_active=True)
        start = timezone.now() + timedelta(days=1)
        self.presentation = Presentation.objects.create(en_title='Concurrent reminder', fa_title='Test',
            cost='10000', capacity=10, service_type='WORKSHOP', start=start, end=start + timedelta(hours=1),
            en_description='Test', fa_description='Test')
        Participation.objects.create(user=self.user, presentation=self.presentation, payment_state='COMPLETED')

    def test_simultaneous_confirmations_queue_only_once(self):
        batch = reminder_batch(confirmation_token(self.presentation), self.presentation)
        barrier = Barrier(2)
        def confirm(_):
            connections.close_all()
            try:
                presentation = Presentation.objects.get(pk=self.presentation.pk)
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                return queue_reminders(presentation, batch, user)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(confirm, range(2))), [0, 1])
        self.assertEqual(PresentationReminder.objects.count(), 1)

    @patch('shop.management.commands.send_presentation_reminders.send_mail', return_value=1)
    def test_simultaneous_workers_deliver_one_job_once(self, send):
        batch = reminder_batch(confirmation_token(self.presentation), self.presentation)
        queue_reminders(self.presentation, batch, self.user)
        barrier = Barrier(2)
        def work(_):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                call_command('send_presentation_reminders', limit=1, stdout=StringIO())
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(work, range(2)))
        self.assertEqual(send.call_count, 1)
        job = PresentationReminder.objects.get()
        self.assertEqual((job.status, job.attempts), ('SENT', 1))
