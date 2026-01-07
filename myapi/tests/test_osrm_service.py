import pytest
import requests  # <-- تم إضافة هذا السطر الضروري
from unittest import mock
from django.core.exceptions import ValidationError

from optimization.services import OSRMService


class DummyResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            # يفضل استخدام HTTPError لمحاكاة requests بدقة، لكن Exception تفي بالغرض هنا
            raise requests.exceptions.HTTPError("HTTP error") 

    def json(self):
        return self._json


def test_get_distance_matrix_success(monkeypatch):
    # locations: list of (lat, lon)
    locations = [(33.45, 36.2), (33.46, 36.21)]
    fake = {"distances": [[0, 1000], [1000, 0]]}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: DummyResponse(fake))
    matrix = OSRMService.get_distance_matrix(locations)
    assert matrix == [[0, 1000], [1000, 0]]


def test_get_distance_matrix_request_failure(monkeypatch):
    # التصحيح هنا: استخدام دالة ترمي RequestException بدلاً من lambda مع Exception عام
    def mock_raise(*args, **kwargs):
        raise requests.exceptions.RequestException("Connection refused")

    monkeypatch.setattr("requests.get", mock_raise)
    
    with pytest.raises(ValidationError):
        OSRMService.get_distance_matrix([(33.45, 36.2)])


def test_get_distance_matrix_invalid_payload(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: DummyResponse({}))
    with pytest.raises(ValidationError):
        OSRMService.get_distance_matrix([(33.45, 36.2)])