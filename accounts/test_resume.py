from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Resume


class ResumeSubmissionTests(APITestCase):
    url = "/api/resume/upload/"
    valid_pdf = b"%PDF-1.4\nLinuxFest resume\n%%EOF\n"

    def setUp(self):
        cache.clear()
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        storage_settings = override_settings(
            MEDIA_ROOT=self.media_directory.name,
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
                },
            },
        )
        storage_settings.enable()
        self.addCleanup(storage_settings.disable)
        self.user = self.create_user("resume@example.com", "09120000001")

    def create_user(self, email, phone_number, **extra):
        return get_user_model().objects.create_user(
            email=email,
            phone_number=phone_number,
            first_name="Resume",
            last_name="Tester",
            password="test-password-123",
            is_active=True,
            **extra,
        )

    def upload(self, name="resume.pdf", content=None):
        content = self.valid_pdf if content is None else content
        return self.client.post(
            self.url,
            {"file": SimpleUploadedFile(name, content, content_type="application/pdf")},
            format="multipart",
        )

    def test_login_is_required(self):
        response = self.upload()

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Resume.objects.exists())

    def test_authenticated_user_can_upload_and_read_metadata(self):
        self.client.force_authenticate(self.user)

        response = self.upload("my-private-resume.pdf")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["detail"], "Resume uploaded successfully.")
        self.assertNotIn("file", response.data["resume"])
        resume = Resume.objects.get(user=self.user)
        self.assertEqual(resume.original_filename, "my-private-resume.pdf")
        self.assertTrue(resume.file.name.startswith(f"resumes/{self.user.pk}/"))
        self.assertNotIn("my-private-resume", resume.file.name)

        metadata = self.client.get(self.url)
        self.assertEqual(metadata.status_code, 200)
        self.assertEqual(metadata.data["id"], resume.pk)
        self.assertEqual(metadata.data["original_filename"], "my-private-resume.pdf")
        self.assertNotIn("file", metadata.data)

    def test_upload_replaces_previous_resume_and_deletes_old_file(self):
        self.client.force_authenticate(self.user)
        self.upload("first.pdf")
        resume = Resume.objects.get(user=self.user)
        old_name = resume.file.name
        old_path = Path(self.media_directory.name, old_name)
        self.assertTrue(old_path.exists())

        with self.captureOnCommitCallbacks(execute=True):
            response = self.upload("second.pdf", b"%PDF-1.7\nreplacement\n%%EOF\n")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["detail"], "Resume replaced successfully.")
        self.assertEqual(Resume.objects.filter(user=self.user).count(), 1)
        resume.refresh_from_db()
        self.assertEqual(resume.original_filename, "second.pdf")
        self.assertNotEqual(resume.file.name, old_name)
        self.assertFalse(old_path.exists())

    def test_user_can_delete_resume_and_file(self):
        self.client.force_authenticate(self.user)
        self.upload()
        resume = Resume.objects.get(user=self.user)
        path = Path(self.media_directory.name, resume.file.name)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Resume.objects.filter(user=self.user).exists())
        self.assertFalse(path.exists())

    def test_users_cannot_access_each_others_resume(self):
        self.client.force_authenticate(self.user)
        self.upload()
        other = self.create_user("other@example.com", "09120000002")
        self.client.force_authenticate(other)

        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.delete(self.url).status_code, 404)
        self.assertTrue(Resume.objects.filter(user=self.user).exists())

    def test_resume_must_be_a_real_pdf_under_five_mb(self):
        self.client.force_authenticate(self.user)

        wrong_extension = self.upload("resume.txt")
        fake_pdf = self.upload("resume.pdf", b"not a PDF")
        oversized = self.upload("resume.pdf", b"%PDF-" + b"x" * (5 * 1024 * 1024))

        self.assertEqual(wrong_extension.status_code, 400)
        self.assertEqual(fake_pdf.status_code, 400)
        self.assertEqual(oversized.status_code, 400)
        self.assertFalse(Resume.objects.exists())

    def test_resume_upload_is_rate_limited_per_user(self):
        self.client.force_authenticate(self.user)

        for index in range(10):
            response = self.upload(f"resume-{index}.pdf")
            self.assertIn(response.status_code, {200, 201})

        self.assertEqual(self.upload("too-many.pdf").status_code, 429)

    def test_only_permitted_admin_can_download_resume(self):
        self.client.force_authenticate(self.user)
        self.upload("candidate.pdf")
        resume = Resume.objects.get(user=self.user)
        download_url = reverse("admin:accounts_resume_download", args=[resume.pk])

        self.client.force_authenticate(user=None)
        anonymous = self.client.get(download_url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/admin/login/", anonymous["Location"])

        restricted_staff = self.create_user(
            "restricted@example.com",
            "09120000003",
            is_staff=True,
        )
        self.client.force_login(restricted_staff)
        self.assertEqual(self.client.get(download_url).status_code, 403)

        self.client.logout()
        admin = get_user_model().objects.create_superuser(
            email="admin@example.com",
            phone_number="09120000004",
            first_name="Resume",
            last_name="Admin",
            password="test-password-123",
        )
        self.client.force_login(admin)
        response = self.client.get(download_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.valid_pdf)
        self.assertIn('attachment; filename="candidate.pdf"', response["Content-Disposition"])
