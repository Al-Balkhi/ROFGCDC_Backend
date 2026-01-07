import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.mark.django_db
class TestAccountsIntegration:
    def setup_method(self):
        self.client = APIClient()
        self.password = "password123"
        self.user = User.objects.create_user(
            email="test@example.com",
            password=self.password,
            is_active=True
        )

    def test_full_login_flow(self):
        """
        يختبر هذا التابع:
        1. urls.py (الوصول للروابط)
        2. views.py (LoginView)
        3. serializers.py (LoginSerializer)
        4. authentication.py (Cookie Setting)
        """
        # 1. Login
        url = reverse('auth-login')
        data = {
            "email": self.user.email,
            "password": self.password
        }
        response = self.client.post(url, data)
        
        assert response.status_code == 200
        assert "access" in response.cookies
        assert "refresh" in response.cookies

        # 2. Access Profile (Protected View)
        profile_url = reverse('profile')
        response_profile = self.client.get(profile_url)
        assert response_profile.status_code == 200
        assert response_profile.data['email'] == self.user.email

    def test_logout(self):
        # Login first
        self.client.force_authenticate(user=self.user)
        # Logout
        url = reverse('auth-logout')
        response = self.client.post(url)
        assert response.status_code == 204
        assert response.cookies['access'].value == '' # Cookie cleared