from django.db.models.signals import post_save
from django.dispatch import receiver
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from accounts.models import Notification

@receiver(post_save, sender=Notification)
def notification_created(sender, instance, created, **kwargs):
    if created:
        channel_layer = get_channel_layer()
        group_name = f"user_{instance.user.id}_notifications"
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "send_notification",
                "message": {
                    "id": instance.id,
                    "title": str(instance.title),
                    "message": str(instance.message),
                    "is_read": instance.is_read,
                    "type": instance.type,
                    "related_id": instance.related_id,
                    "created_at": instance.created_at.isoformat()
                }
            }
        )
