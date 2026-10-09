from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import PresentationProposal


class PresentationProposalApiTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        storage_settings = override_settings(
            MEDIA_ROOT=self.media_directory.name,
            STORAGES={
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {
                    'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
                },
            },
        )
        storage_settings.enable()
        self.addCleanup(storage_settings.disable)
        self.client.defaults['REMOTE_ADDR'] = (
            f'192.0.2.{sum(map(ord, self._testMethodName)) % 250 + 1}'
        )
        self.url = reverse('presentation-proposal-create')

    def make_payload(self, slides_name='slides.pdf', slides_content=b'%PDF-1.4 proposal slides'):
        return {
            'full_name': 'Taylor Example',
            'biography': 'A short biography.',
            'organization': 'Example Organization',
            'phone_number': '+15551234567',
            'topic': 'Building reliable APIs',
            'abstract': 'A presentation about practical API design.',
            'slides': SimpleUploadedFile(slides_name, slides_content),
        }

    def test_anonymous_submission_returns_shop_success_response(self):
        response = self.client.post(self.url, self.make_payload(), format='multipart')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {'detail': 'Proposal submitted successfully.'})
        self.assertEqual(PresentationProposal.objects.count(), 1)

    def test_organization_is_optional(self):
        payload = self.make_payload()
        del payload['organization']

        response = self.client.post(self.url, payload, format='multipart')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(PresentationProposal.objects.get().organization, '')

    def test_slides_are_optional(self):
        payload = self.make_payload()
        del payload['slides']

        response = self.client.post(self.url, payload, format='multipart')

        self.assertEqual(response.status_code, 201)
        proposal = PresentationProposal.objects.get()
        self.assertFalse(proposal.slides)

    def test_proposal_without_slides_accepts_json(self):
        payload = self.make_payload()
        del payload['slides']

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertFalse(PresentationProposal.objects.get().slides)

    def test_each_other_field_is_required(self):
        required_fields = (
            'full_name',
            'biography',
            'phone_number',
            'topic',
            'abstract',
        )

        for field in required_fields:
            with self.subTest(field=field):
                payload = self.make_payload()
                del payload[field]

                response = self.client.post(self.url, payload, format='multipart')

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        self.assertEqual(PresentationProposal.objects.count(), 0)

    def test_unsupported_slide_extension_returns_field_error(self):
        response = self.client.post(
            self.url,
            self.make_payload(slides_name='slides.txt'),
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('slides', response.data)

    def test_slide_content_must_match_its_extension(self):
        response = self.client.post(
            self.url,
            self.make_payload(slides_name='not-really-a-pdf.pdf', slides_content=b'not a pdf'),
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('slides', response.data)

    def test_slide_larger_than_20_mb_returns_field_error(self):
        oversized_file = b'x' * (20 * 1024 * 1024 + 1)
        response = self.client.post(
            self.url,
            self.make_payload(slides_content=oversized_file),
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('slides', response.data)

    def test_staff_can_review_proposal_and_download_slides(self):
        self.client.post(self.url, self.make_payload(), format='multipart')
        proposal = PresentationProposal.objects.get()
        admin_user = get_user_model().objects.create_superuser(
            phone_number='09000000001',
            password='test-password',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse('admin:shop_presentationproposal_change', args=[proposal.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Taylor Example')
        self.assertContains(response, 'Download slides')
        self.assertNotContains(response, '/media/presentation_proposals/')

        download_url = reverse(
            'admin:shop_presentationproposal_download',
            args=[proposal.pk],
        )
        download_response = self.client.get(download_url)
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            b''.join(download_response.streaming_content),
            b'%PDF-1.4 proposal slides',
        )

        self.client.logout()
        anonymous_response = self.client.get(download_url)
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn('/admin/login/', anonymous_response['Location'])

        staff_without_permission = get_user_model().objects.create_user(
            phone_number='09000000003',
            password='test-password',
            first_name='Restricted',
            last_name='Staff',
            email='restricted@example.com',
            is_staff=True,
        )
        self.client.force_login(staff_without_permission)
        forbidden_response = self.client.get(download_url)
        self.assertEqual(forbidden_response.status_code, 403)

    def test_anonymous_throttle_limits_submissions(self):
        self.client.defaults['REMOTE_ADDR'] = '198.51.100.10'

        for _ in range(10):
            response = self.client.post(self.url, self.make_payload(), format='multipart')
            self.assertEqual(response.status_code, 201)

        response = self.client.post(self.url, self.make_payload(), format='multipart')

        self.assertEqual(response.status_code, 429)

    def test_authenticated_user_cannot_bypass_submission_throttle(self):
        user = get_user_model().objects.create_user(
            phone_number='09000000002',
            password='test-password',
            first_name='Authenticated',
            last_name='Submitter',
            email='submitter@example.com',
        )
        self.client.force_authenticate(user)
        self.client.defaults['REMOTE_ADDR'] = '198.51.100.11'

        for _ in range(10):
            response = self.client.post(self.url, self.make_payload(), format='multipart')
            self.assertEqual(response.status_code, 201)

        response = self.client.post(self.url, self.make_payload(), format='multipart')

        self.assertEqual(response.status_code, 429)
