import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import patch
from accounts.services import OTPServiceError

User = get_user_model()

@pytest.mark.django_db
class TestAccountsAdvanced:
    def setup_method(self):
        self.client = APIClient()
        self.password = "pass12345"
        self.user = User.objects.create_user(email="test@app.com", password=self.password, is_active=True)
        self.admin = User.objects.create_superuser(email="admin@app.com", password=self.password)

    def test_refresh_token_missing_cookie(self):
        """Test refresh endpoint without cookie"""
        url = reverse('auth-refresh')
        response = self.client.post(url)
        assert response.status_code == 401

    def test_refresh_token_invalid(self):
        """Test refresh endpoint with garbage cookie"""
        url = reverse('auth-refresh')
        self.client.cookies['refresh'] = 'invalid_token_string'
        response = self.client.post(url)
        assert response.status_code == 401

    def test_profile_update(self):
        """Test PUT /api/profile/"""
        self.client.force_authenticate(user=self.user)
        url = reverse('profile')
        data = {"username": "updated_name", "phone": "0912345678"}
        response = self.client.put(url, data)
        assert response.status_code == 200
        assert response.data['username'] == "updated_name"

    def test_change_password_success(self):
        """Test change password with valid data"""
        self.client.force_authenticate(user=self.user)
        url = reverse('profile-password')
        data = {
            "old_password": self.password,
            "new_password": "new_pass_123",
            "confirm_new_password": "new_pass_123"
        }
        response = self.client.post(url, data)
        assert response.status_code == 200
        # Verify login with new password
        self.client.logout()
        login_resp = self.client.post(reverse('auth-login'), {"email": self.user.email, "password": "new_pass_123"})
        assert login_resp.status_code == 200

    def test_change_password_mismatch(self):
        """Test change password when new passwords don't match"""
        self.client.force_authenticate(user=self.user)
        url = reverse('profile-password')
        data = {
            "old_password": self.password,
            "new_password": "new_pass_123",
            "confirm_new_password": "mismatch_pass"
        }
        response = self.client.post(url, data)
        assert response.status_code == 400
        assert "confirm_new_password" in response.data

    def test_change_password_wrong_old(self):
        """Test change password with wrong old password"""
        self.client.force_authenticate(user=self.user)
        url = reverse('profile-password')
        data = {
            "old_password": "wrong_password",
            "new_password": "new_pass_123",
            "confirm_new_password": "new_pass_123"
        }
        response = self.client.post(url, data)
        assert response.status_code == 400
        assert "old_password" in response.data

    def test_password_reset_request_invalid_email(self):
        """Test requesting reset for non-existent email"""
        url = reverse('password-reset-request')
        response = self.client.post(url, {"email": "nobody@nowhere.com"})
        # Serializer validation should catch this
        assert response.status_code == 400 

    def test_password_reset_confirm_user_not_found(self):
        """Test confirming reset with email that doesn't exist (edge case)"""
        url = reverse('password-reset-confirm')
        data = {
            "email": "ghost@app.com",
            "otp": "12345",
            "new_password": "StrongPass123!" 
        }
        response = self.client.post(url, data)
        assert response.status_code == 404

    @patch('accounts.services.OTPService.verify')
    def test_password_reset_confirm_otp_error(self, mock_verify):
        """Test confirming reset with bad OTP"""
        mock_verify.side_effect = OTPServiceError("Invalid OTP")
        url = reverse('password-reset-confirm')
        data = {
            "email": self.user.email,
            "otp": "00000",
            "new_password": "StrongPass123!"
        }
        response = self.client.post(url, data)
        assert response.status_code == 400
        assert "Invalid OTP" in str(response.data)

    def test_admin_stats_view(self):
        """Test admin stats calculation"""
        self.client.force_authenticate(user=self.admin)
        url = reverse('admin-stats')
        response = self.client.get(url)
        assert response.status_code == 200
        assert 'users_active' in response.data
        assert 'vehicles_total' in response.data

    def test_activity_log_view(self):
        """Test activity log access"""
        self.client.force_authenticate(user=self.admin)
        url = reverse('activity-log')
        response = self.client.get(url)
        assert response.status_code == 200
        assert isinstance(response.data, list)