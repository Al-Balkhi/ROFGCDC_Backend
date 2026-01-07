import pytest
from rest_framework.test import APIRequestFactory
from rest_framework.request import Request  # <-- 1. يجب استيراد هذا
from django.contrib.auth import get_user_model

from users.views import UserViewSet

User = get_user_model()


@pytest.mark.django_db
def test_get_queryset_search_and_archived():
    factory = APIRequestFactory()
    # Create several users
    u1 = User.objects.create_user(email="u1@example.com", password="pw", username="alice", is_active=True)
    u2 = User.objects.create_user(email="u2@example.com", password="pw", username="al", is_active=True)
    u3 = User.objects.create_user(email="u3@example.com", password="pw", username="bob", is_active=True, is_archived=True)

    view = UserViewSet()
    req = factory.get('/users', {'search': 'a'})
    req.user = u1
    
    # 2. التعديل هنا: تغليف الطلب ليتعرف عليه الـ View
    view.request = Request(req)
    view.format_kwarg = None 

    view.action = 'list'
    qs = view.get_queryset()
    
    # search string of length 1 should not filter; default exclude archived
    assert u1 in qs
    assert u3 not in qs

    # restore action should include archived
    req2 = factory.get('/users', {})
    req2.user = u1
    
    # 3. نفس الشيء هنا للطلب الثاني
    view.request = Request(req2)
    view.format_kwarg = None
    
    view.action = 'restore'
    qs2 = view.get_queryset()
    assert u3 in qs2