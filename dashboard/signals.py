"""
Django signals for the quizapp
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.cache import cache
from .models import Like


@receiver(post_save, sender=Like)
def like_created(sender, instance, created, **kwargs):
    """
    Handle new likes
    """
    if created:
        # Clear match cache for both users
        cache.delete(f'potential_matches_{instance.liker.profile.uuid}')
        cache.delete(f'potential_matches_{instance.liked.profile.uuid}')