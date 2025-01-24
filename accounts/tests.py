from rest_framework.test import APITestCase, APIClient


class UserTestCase(APITestCase):
    """Create a user and test API"""

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
        print(response)
        self.assertTrue(response.status_code // 100 == 2, "Registration failed: " + str(response.status_code))

    def test_login(self):
        self.test_signup()
        user_credentials = {'phone_number': self.user_data['phone_number'], 'password': self.user_data['password']}
        response = self.client.post(self.base_url + 'token/', data=user_credentials, format='json')
        print(response.data)
        self.assertTrue(response.status_code // 100 == 2, "login failed: " + str(response.status_code))
