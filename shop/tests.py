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

    def test_each_other_field_is_required(self):
        required_fields = (
            'full_name',
            'biography',
            'phone_number',
            'topic',
            'abstract',
            'slides',
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

    def test_anonymous_throttle_limits_submissions(self):
        self.client.defaults['REMOTE_ADDR'] = '198.51.100.10'

        for _ in range(10):
            response = self.client.post(self.url, self.make_payload(), format='multipart')
            self.assertEqual(response.status_code, 201)

        response = self.client.post(self.url, self.make_payload(), format='multipart')

        self.assertEqual(response.status_code, 429)
