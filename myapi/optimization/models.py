from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.gis.db import models
from django.conf import settings
from .validators import validate_damascus_latitude, validate_damascus_longitude


class Municipality(models.Model):
    name = models.CharField(max_length=255, unique=True)
    hq_location = models.PointField(null=True, blank=True, geography=True)

    planner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_municipalities',
        limit_choices_to={'role': 'planner'}
    )

    @property
    def hq_latitude(self):
        return self.hq_location.y if self.hq_location else None

    @property
    def hq_longitude(self):
        return self.hq_location.x if self.hq_location else None

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_municipalities'
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Landfill(models.Model):
    name = models.CharField(max_length=255)
    location = models.PointField(geography=True)
    
    @property
    def latitude(self):
        return self.location.y if self.location else None

    @property
    def longitude(self):
        return self.location.x if self.location else None

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_landfills'
    )

    # Many-to-Many with Municipality
    municipalities = models.ManyToManyField(
        Municipality,
        related_name='landfills',
        blank=True
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} Landfill"


class Bin(models.Model):
    name = models.CharField(max_length=255)
    location = models.PointField(geography=True)

    @property
    def latitude(self):
        return self.location.y if self.location else None

    @property
    def longitude(self):
        return self.location.x if self.location else None
    CAPACITY_CHOICES = [
        (240, '240 L'),
        (660, '660 L'),
        (1100, '1100 L'),
    ]
    capacity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        choices=CAPACITY_CHOICES
    )
    is_active = models.BooleanField(default=True)

    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.PROTECT,
        related_name='bins'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_bins'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.latitude}, {self.longitude})"


class Vehicle(models.Model):
    name = models.CharField(max_length=255)
    CAPACITY_CHOICES = [
        (5000, '5000 L'),
        (15000, '15000 L'),
    ]
    capacity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        choices=CAPACITY_CHOICES
    )

    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.PROTECT,
        related_name='vehicles'
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_vehicles'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} (Capacity: {self.capacity})"


class Scenario(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'معلقة'
        IN_PROGRESS = 'in_progress', 'قيد الانجاز'
        COMPLETED = 'completed', 'منجزة'

    name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.CASCADE,
        related_name='scenarios'
    )
    start_location = models.PointField(null=True, blank=True, geography=True)

    @property
    def start_latitude(self):
        return self.start_location.y if self.start_location else None

    @property
    def start_longitude(self):
        return self.start_location.x if self.start_location else None
    collection_date = models.DateField()
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name='scenarios'
    )
    end_landfill = models.ForeignKey(
        Landfill,
        on_delete=models.PROTECT,
        related_name='ending_scenarios',
        null=True,
        blank=True,
    )
    bins = models.ManyToManyField(
        Bin,
        related_name='scenarios',
        blank=False
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    generated_from_template = models.ForeignKey(
        'ScenarioTemplate',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='generated_scenarios'
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='scenarios'
    )
    # -------------------

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # FIX: Add index for frequent date filtering
            models.Index(fields=['collection_date']),
        ]

    def __str__(self):
        user_email = self.created_by.email if self.created_by else "Unknown"
        return f"{self.name} (by {user_email})"


class RouteSolution(models.Model):
    scenario = models.ForeignKey(
        Scenario,
        on_delete=models.CASCADE,
        related_name='solutions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    total_distance = models.FloatField(
        validators=[MinValueValidator(0.0)]
    )
    data = models.JSONField()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['scenario', '-created_at']),
        ]

    def __str__(self):
        return f"Solution for {self.scenario.name} - Distance: {self.total_distance:.2f}"


class ScenarioTemplate(models.Model):
    name = models.CharField(max_length=255)
    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.CASCADE,
        related_name='scenario_templates'
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name='scenario_templates'
    )
    end_landfill = models.ForeignKey(
        Landfill,
        on_delete=models.PROTECT,
        related_name='scenario_templates'
    )
    bins = models.ManyToManyField(Bin, related_name='scenario_templates')
    weekdays = models.CharField(
        max_length=20,
        help_text='Comma separated weekdays numbers where Monday=0 and Sunday=6',
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scenario_templates'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
