from django.db.models.signals import post_save, pre_save, pre_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.utils import timezone
from .models import UserProfile, ActivityLog, EmailVerification
import logging

logger = logging.getLogger(__name__)


# Signals
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile and related objects when a new User is created"""
    if created:
        try:
            # Create user profile with default settings
            profile = UserProfile.objects.create(user=instance)
            logger.info(f"Created UserProfile for user: {instance.username}")
            
            # Create email verification token
            EmailVerification.objects.create(user=instance)
            
            # Log signup activity
            ActivityLog.objects.create(
                user=instance,
                activity_type='signup',
                user_agent='',  # Will be updated by view if available
            )
            
        except Exception as e:
            logger.error(f"Error creating UserProfile for {instance.username}: {e}")


@receiver(post_save, sender=User)
def update_user_profile_timestamp(sender, instance, **kwargs):
    """
    Update profile timestamp when user is updated.
    """
    try:
        profile = instance.userprofile
        profile.updated_at = timezone.now()
        profile.save(update_fields=['updated_at'])
    except UserProfile.DoesNotExist:
        # Profile doesn't exist yet, will be created by create_user_profile
        pass


@receiver(pre_save, sender=User)
def log_email_change(sender, instance, **kwargs):
    """
    Log when a user changes their email address.
    """
    if instance.pk:  # Only for existing users
        try:
            old_user = User.objects.get(pk=instance.pk)
            if old_user.email != instance.email:
                # Email is being changed
                ActivityLog.objects.create(
                    user=instance,
                    activity_type='email_change',
                    ip_address=None,
                    user_agent='',
                    additional_info=f"Changed from {old_user.email} to {instance.email}"
                )
                logger.info(f"User {instance.username} changed email from {old_user.email} to {instance.email}")
        except User.DoesNotExist:
            pass


@receiver(pre_save, sender=UserProfile)
def log_profile_changes(sender, instance, **kwargs):
    """
    Log significant profile changes.
    """
    if instance.pk:  # Only for existing profiles
        try:
            old_profile = UserProfile.objects.get(pk=instance.pk)
            
            changes = []
            
            # Check for specific field changes
            if old_profile.age != instance.age:
                changes.append(f"age: {old_profile.age} → {instance.age}")
            
            if old_profile.gender != instance.gender:
                changes.append(f"gender: {old_profile.gender} → {instance.gender}")
            
            if old_profile.city != instance.city:
                changes.append(f"city: {old_profile.city} → {instance.city}")
            
            if old_profile.country != instance.country:
                changes.append(f"country: {old_profile.country} → {instance.country}")
            
            if old_profile.is_visible != instance.is_visible:
                changes.append(f"visibility: {old_profile.is_visible} → {instance.is_visible}")
            
            if old_profile.approved != instance.approved:
                changes.append(f"approved: {old_profile.approved} → {instance.approved}")
            
            if changes:
                ActivityLog.objects.create(
                    user=instance.user,
                    activity_type='profile_update',
                    ip_address=None,
                    user_agent='',
                    additional_info="; ".join(changes)
                )
                logger.info(f"Profile updated for {instance.user.username}: {', '.join(changes)}")
                
        except UserProfile.DoesNotExist:
            pass


@receiver(post_save, sender=UserProfile)
def handle_profile_approval(sender, instance, created, **kwargs):
    """
    Handle actions when a profile is approved or unapproved.
    """
    if not created:  # Only for updates
        try:
            old_profile = UserProfile.objects.get(pk=instance.pk)
            
            if not old_profile.approved and instance.approved:
                # Profile was just approved
                ActivityLog.objects.create(
                    user=instance.user,
                    activity_type='profile_approved',
                    ip_address=None,
                    user_agent='',
                )
                logger.info(f"Profile approved for user: {instance.user.username}")
                
                # Send welcome/approval notification (implement your notification system)
                # send_profile_approved_email(instance.user)
            
            elif old_profile.approved and not instance.approved:
                # Profile was unapproved
                ActivityLog.objects.create(
                    user=instance.user,
                    activity_type='profile_unapproved',
                    ip_address=None,
                    user_agent='',
                )
                logger.info(f"Profile unapproved for user: {instance.user.username}")
                
        except UserProfile.DoesNotExist:
            pass


@receiver(pre_delete, sender=User)
def log_user_deletion(sender, instance, **kwargs):
    """
    Log user deletion before it happens.
    """
    try:
        ActivityLog.objects.create(
            user=instance,
            activity_type='account_delete',
            ip_address=None,
            user_agent='',
            additional_info=f"User {instance.username} deleted"
        )
        logger.info(f"User account deleted: {instance.username}")
    except Exception as e:
        logger.error(f"Error logging user deletion for {instance.username}: {e}")


@receiver(post_save, sender=ActivityLog)
def cleanup_old_activities(sender, instance, created, **kwargs):
    """
    Clean up old activities to prevent database bloat.
    Only keep activities from the last 90 days.
    """
    if created:
        from datetime import timedelta
        cutoff_date = timezone.now() - timedelta(days=90)
        
        # Delete activities older than 90 days
        old_activities = ActivityLog.objects.filter(created_at__lt=cutoff_date)
        count = old_activities.count()
        if count > 0:
            old_activities.delete()
            logger.info(f"Cleaned up {count} old activities")


# Signal to handle user login (cannot be triggered from signals, handled in views)
# @receiver(user_logged_in) - This requires a custom signal or middleware