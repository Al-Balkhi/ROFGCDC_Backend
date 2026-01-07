import pytest
from django.core.exceptions import ValidationError
from optimization.validators import validate_damascus_latitude, validate_damascus_longitude


def test_validate_latitude_accepts_within_bounds():
    validate_damascus_latitude(33.5)


def test_validate_latitude_rejects_out_of_bounds():
    with pytest.raises(ValidationError):
        validate_damascus_latitude(34.0)


def test_validate_longitude_accepts_within_bounds():
    validate_damascus_longitude(36.2)


def test_validate_longitude_rejects_out_of_bounds():
    with pytest.raises(ValidationError):
        validate_damascus_longitude(37.0)
