from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ProfileLike
from useractivity.models import Activity

@receiver(post_save, sender=ProfileLike)
def create_profile_like_activity(sender, instance, created, **kwargs):
    """Create activity when someone likes a profile"""
    if created:
        Activity.objects.create(
            user=instance.liker,
            activity_type='profile_liked',
            target_user=instance.liked,
            metadata={'like_id': instance.id}
        )