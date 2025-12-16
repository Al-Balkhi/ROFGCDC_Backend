from django.core.exceptions import ValidationError


# Damascus bounds
DAMASCUS_LAT_MIN = 33.40
DAMASCUS_LAT_MAX = 33.60
DAMASCUS_LON_MIN = 36.10
DAMASCUS_LON_MAX = 36.40


def validate_damascus_latitude(value):
    """Validate that latitude is within Damascus bounds."""
    if value is not None:
        if value < DAMASCUS_LAT_MIN or value > DAMASCUS_LAT_MAX:
            raise ValidationError(
                f'الإحداثيات خارج حدود مدينة دمشق. خط العرض يجب أن يكون بين {DAMASCUS_LAT_MIN} و {DAMASCUS_LAT_MAX}'
            )


def validate_damascus_longitude(value):
    """Validate that longitude is within Damascus bounds."""
    if value is not None:
        if value < DAMASCUS_LON_MIN or value > DAMASCUS_LON_MAX:
            raise ValidationError(
                f'الإحداثيات خارج حدود مدينة دمشق. خط الطول يجب أن يكون بين {DAMASCUS_LON_MIN} و {DAMASCUS_LON_MAX}'
            )

