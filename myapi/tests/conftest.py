import pytest
from django.conf import settings


@pytest.fixture(autouse=True)
def disable_email_sending(monkeypatch):
    """Prevent real emails during tests by monkeypatching send_mail."""
    def _noop(*args, **kwargs):
        return 1

    monkeypatch.setattr("django.core.mail.send_mail", _noop)


@pytest.fixture
def sample_coords():
    # Some valid Damascus-coordinates within validators bounds
    return (33.45, 36.2)


def pytest_configure():
    # Minimal sanity: ensure settings module loaded
    assert settings is not None
