from rest_framework.test import APITestCase, APIClient


'''class UserTestCase(APITestCase):
    def setUp(self):
        self.base_url = '/api/'
        self.client = APIClient()
        self.user_data = {'phone_number': '09337905450',
                          'password': 'te123456',
                          'email': 'test@gmail.com',
                          'first_name': 'test',
                          'last_name': 'test', }

    def test_signup(self):
        response = self.client.post(self.base_url + 'users/signup/', data=self.user_data, format='json')
        print(response.data)
        self.assertTrue(response.status_code // 100 == 2, "Registration failed: " + str(response.status_code))

    def test_login(self):
        self.test_signup()
        user_credentials = {'phone_number': self.user_data['phone_number'], 'password': self.user_data['password']}
        response = self.client.post(self.base_url + 'token/', data=user_credentials, format='json')'''
   #print(response.data)
# accounts/tests.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

User = get_user_model()


class FirstLoginFlowTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpassword123",
            phone_number="09120000000" if hasattr(User, "phone_number") else None,
        )
        self.url = reverse("first-login")

    def test_unauthenticated_request_rejected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_onboarding_status_and_choices(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_first_login"])
        self.assertIn("choices", response.data)
        self.assertTrue(len(response.data["choices"]["heard_about_us"]) > 0)

    def test_successful_first_login_submission_full_data(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "heard_about_us": "telegram",
            "university": "Amirkabir University of Technology",
            "hamkaran_announcement_consent": True,
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_first_login"])

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_first_login)
        self.assertEqual(self.user.heard_about_us, "telegram")
        self.assertEqual(self.user.university, "Amirkabir University of Technology")
        self.assertTrue(self.user.hamkaran_announcement_consent)

    def test_successful_submission_without_optional_university(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "heard_about_us": "hamkaran",
            "hamkaran_announcement_consent": False,
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_first_login)
        self.assertEqual(self.user.heard_about_us, "hamkaran")
        self.assertIsNone(self.user.university)
        self.assertFalse(self.user.hamkaran_announcement_consent)

    def test_missing_mandatory_heard_about_field(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "university": "Sharif University of Technology",
            "hamkaran_announcement_consent": True,
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("heard_about_us", response.data)

    def test_invalid_referral_choice(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "heard_about_us": "invalid_source_channel",
            "hamkaran_announcement_consent": True,
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("heard_about_us", response.data)