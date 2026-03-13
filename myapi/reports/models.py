from django.contrib.gis.db import models
from django.conf import settings
from optimization.models import Municipality, Bin, Scenario
from django.db.models.signals import post_delete
from django.dispatch import receiver
import os

class DeviceFingerprint(models.Model):
    device_id = models.CharField(max_length=255, unique=True)
    ip_address = models.GenericIPAddressField()
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_report_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.device_id

class Report(models.Model):
    class IssueType(models.TextChoices):
        CONTAINER_FULL = 'container_full', 'Container Full'
        NO_CONTAINER = 'no_container', 'No Container'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        PROCESSED = 'processed', 'Processed'

    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.CASCADE,
        related_name='citizen_reports'
    )
    location = models.PointField(geography=True)
    
    @property
    def latitude(self):
        return self.location.y if self.location else None

    @property
    def longitude(self):
        return self.location.x if self.location else None

    description = models.TextField(blank=True)
    issue_type = models.CharField(
        max_length=20,
        choices=IssueType.choices,
        default=IssueType.CONTAINER_FULL,
    )
    urgency_score = models.IntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    assigned_scenario = models.ForeignKey(
        Scenario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reports'
    )
    devices = models.ManyToManyField(DeviceFingerprint, related_name='reports')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        # If the report is marked as processed, reset its urgency score to the minimum
        if self.status == self.Status.PROCESSED:
            self.urgency_score = 1
        super().save(*args, **kwargs)
    
    class Meta:
        ordering = ['-urgency_score', '-created_at']

    def __str__(self):
        return f"Report {self.id} - Score: {self.urgency_score}"


class ReportMedia(models.Model):
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name='media'
    )
    device = models.ForeignKey(
        DeviceFingerprint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    image = models.ImageField(upload_to='reports/')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Media for Report {self.report.id}"


class BinRequest(models.Model):
    class RequestType(models.TextChoices):
        NEW_BIN = 'new_bin', 'Create New Bin'
        RESIZE_BIN = 'resize_bin', 'Resize/Change Existing Bin'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    planner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_bin_requests',
        limit_choices_to={'role': 'planner'}
    )
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='handled_bin_requests',
        limit_choices_to={'role': 'admin'}
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name='bin_requests'
    )
    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices
    )
    target_bin = models.ForeignKey(
        Bin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resize_requests'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    note = models.TextField(blank=True, help_text="Planner note or Admin rejection reason")
    
    CAPACITY_CHOICES = [
        (240, '240 L'),
        (660, '660 L'),
        (1100, '1100 L'),
    ]
    requested_capacity = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        help_text="Requested size/capacity",
        choices=CAPACITY_CHOICES
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_request_type_display()} for Report {self.report.id}"


@receiver(post_delete, sender=ReportMedia)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem
    when corresponding `ReportMedia` object is deleted.
    """
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)
