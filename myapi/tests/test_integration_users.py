import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.mark.django_db
class TestUsersIntegration:
    def setup_method(self):
        self.client = APIClient()
        # نحتاج أدمن لأن معظم عمليات المستخدمين تتطلب صلاحية أدمن
        self.admin = User.objects.create_superuser(email="admin@test.com", password="password")
        self.client.force_authenticate(user=self.admin)

    def test_create_user_flow(self):
        url = reverse('user-list') # تأكد من اسم الرابط في urls.py
        data = {
            "email": "newdriver@test.com",
            "username": "driver1",
            "role": "driver"
        }
        response = self.client.post(url, data)
        assert response.status_code == 201
        assert response.data['email'] == "newdriver@test.com"

    def test_list_users(self):
        User.objects.create_user(email="driver_list@test.com", password="pw", role="driver")
        url = reverse('user-list')
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.data['results']) >= 1

    def test_archive_restore_user(self):
        # 1. Create user
        user = User.objects.create_user(email="temp@test.com", password="pw")
        
        # 2. Archive
        url_archive = reverse('user-archive', args=[user.id])
        self.client.patch(url_archive)
        user.refresh_from_db()
        assert user.is_archived is True

        # 3. Restore
        url_restore = reverse('user-restore', args=[user.id])
        self.client.patch(url_restore)
        user.refresh_from_db()
        assert user.is_archived is False