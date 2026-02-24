import traceback

from django.db import models, transaction, IntegrityError
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class FriendshipStatus(models.TextChoices):
    STRANGERS = 'strangers', _('Strangers')
    PENDING_SENDER = 'pending_sender', _('Pending (Sender)')
    PENDING_RECEIVER = 'pending_receiver', _('Pending (Receiver)')
    FRIENDS = 'friends', _('Friends')
    REJECTED_BY_B = 'rejected_by_b', _('Rejected by B')
    REJECTED_BY_A = 'rejected_by_a', _('Rejected by A')
    BLOCKED_BY_A = 'blocked_by_a', _('Blocked by A')
    BLOCKED_BY_B = 'blocked_by_b', _('Blocked by B')
    UNFRIENDED_BY_A = 'unfriended_by_a', _('Unfriended by A')
    UNFRIENDED_BY_B = 'unfriended_by_b', _('Unfriended by B')


class Friendship(models.Model):
    """Main relationship model tracking all statuses"""
    user_a = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='friendships_as_a',
        db_index=True
    )
    user_b = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='friendships_as_b',
        db_index=True
    )
    
    # Current relationship status from user_a's perspective
    status = models.CharField(
        max_length=20,
        choices=FriendshipStatus.choices,
        default=FriendshipStatus.STRANGERS,
        db_index=True
    )
    
    # Who initiated the last action
    initiator = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='initiated_actions'
    )
    
    # Store the status before blocking to restore on unblock
    status_before_block = models.CharField(
        max_length=20,
        choices=FriendshipStatus.choices,
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    
    class Meta:
        unique_together = ('user_a', 'user_b')
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user_a', 'user_b']),
            models.Index(fields=['user_a', 'status']),
            models.Index(fields=['user_b', 'status']),
            models.Index(fields=['status', 'updated_at']),
        ]
    
    def __str__(self):
        return f"{self.user_a.username} → {self.user_b.username}: {self.status}"
    
    def clean(self):
        """Ensure user_a.id < user_b.id for consistency"""
        if self.user_a_id and self.user_b_id:
            if self.user_a_id == self.user_b_id:
                raise ValidationError("Cannot create friendship with yourself")
            if self.user_a_id > self.user_b_id:
                # Swap to maintain consistency
                self.user_a, self.user_b = self.user_b, self.user_a
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        
        # Clear friendship caches for both users
        cache_keys = [
            f"friends_{self.user_a_id}",
            f"friends_{self.user_b_id}",
            f"friendship_status_{self.user_a_id}_{self.user_b_id}",
            f"friendship_status_{self.user_b_id}_{self.user_a_id}",
        ]
        cache.delete_many(cache_keys)
    
    @classmethod
    def get_relationship(cls, user1, user2):
        """Get relationship between two users from user1's perspective"""
        if user1.id == user2.id:
            return None
        
        cache_key = f"friendship_status_{user1.id}_{user2.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        # Ensure consistent ordering
        u1, u2 = (user1, user2) if user1.id < user2.id else (user2, user1)
        
        try:
            friendship = cls.objects.select_related('user_a', 'user_b').get(user_a=u1, user_b=u2)
            # Return status from user1's perspective
            if friendship.user_a == user1:
                result = friendship
            else:
                # Need to invert status for perspective
                inverted_friendship = Friendship(
                    user_a=user1,
                    user_b=user2,
                    status=cls.get_inverted_status(friendship.status),
                    initiator=friendship.initiator,
                    created_at=friendship.created_at,
                    updated_at=friendship.updated_at
                )
                result = inverted_friendship
            # Cache for 5 minutes
            cache.set(cache_key, result, 300)
            return result
        except cls.DoesNotExist:
            cache.set(cache_key, None, 300)
            result = None
    
    @classmethod
    def get_inverted_status(cls, status):
        """Get opposite perspective status"""
        inversion_map = {
            FriendshipStatus.PENDING_SENDER: FriendshipStatus.PENDING_RECEIVER,
            FriendshipStatus.PENDING_RECEIVER: FriendshipStatus.PENDING_SENDER,
            FriendshipStatus.REJECTED_BY_A: FriendshipStatus.REJECTED_BY_B,
            FriendshipStatus.REJECTED_BY_B: FriendshipStatus.REJECTED_BY_A,
            FriendshipStatus.BLOCKED_BY_A: FriendshipStatus.BLOCKED_BY_B,
            FriendshipStatus.BLOCKED_BY_B: FriendshipStatus.BLOCKED_BY_A,
            FriendshipStatus.UNFRIENDED_BY_A: FriendshipStatus.UNFRIENDED_BY_B,
            FriendshipStatus.UNFRIENDED_BY_B: FriendshipStatus.UNFRIENDED_BY_A,
        }
        return inversion_map.get(status, status)
    
    @classmethod
    def create_or_update(cls, user1, user2, new_status, initiator):
        """Create or update relationship between two users"""
        if user1.id == user2.id:
            return None
        
        with transaction.atomic():
            # Ensure consistent ordering
            u1, u2 = (user1, user2) if user1.id < user2.id else (user2, user1)
            
            # Determine if we need to invert status
            actual_status = new_status if u1 == user1 else cls.get_inverted_status(new_status)
            
            # If new status is STRANGERS, delete the record instead of keeping it
            if actual_status == FriendshipStatus.STRANGERS:
                deleted_count = cls.objects.filter(user_a=u1, user_b=u2).delete()[0]
                if deleted_count > 0:
                    # Clear cache
                    cache_keys = [
                        f"friends_{user1.id}",
                        f"friends_{user2.id}",
                        f"friendship_status_{user1.id}_{user2.id}",
                        f"friendship_status_{user2.id}_{user1.id}",
                    ]
                    cache.delete_many(cache_keys)
                return None
            
            friendship, created = cls.objects.get_or_create(
                user_a=u1,
                user_b=u2,
                defaults={
                    'status': actual_status,
                    'initiator': initiator,
                    'status_before_block': None
                }
            )
            
            if not created:
                # Store status before block if blocking
                if new_status in [FriendshipStatus.BLOCKED_BY_A, FriendshipStatus.BLOCKED_BY_B]:
                    friendship.status_before_block = friendship.status
                
                friendship.status = actual_status
                friendship.initiator = initiator
                friendship.save()
            
            # Clear cache
            cache_keys = [
                f"friends_{user1.id}",
                f"friends_{user2.id}",
                f"friendship_status_{user1.id}_{user2.id}",
                f"friendship_status_{user2.id}_{user1.id}",
            ]
            cache.delete_many(cache_keys)
            
            return friendship
    
    @classmethod
    def get_friends(cls, user):
        """Get all friends of a user with caching"""
        cache_key = f"friends_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        friendships = cls.objects.filter(
            (Q(user_a=user, status=FriendshipStatus.FRIENDS) |
             Q(user_b=user, status=FriendshipStatus.FRIENDS))
        ).select_related('user_a', 'user_b')
        
        friends = []
        for friendship in friendships:
            if friendship.user_a == user:
                friends.append(friendship.user_b)
            else:
                friends.append(friendship.user_a)
        
        # Cache for 5 minutes
        cache.set(cache_key, friends, 300)
        return friends
    
    @classmethod
    def get_pending_requests_to_user(cls, user):
        """Get pending friend requests sent to user with caching"""
        cache_key = f"pending_requests_to_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        requests = User.objects.filter(
            friendships_as_a__user_b=user,
            friendships_as_a__status=FriendshipStatus.PENDING_SENDER
        ).distinct()
        
        # Cache for 2 minutes
        cache.set(cache_key, requests, 120)
        return requests
    
    @classmethod
    def get_sent_requests_from_user(cls, user):
        """Get pending friend requests sent by user"""
        return User.objects.filter(
            friendships_as_a__user_a=user,
            friendships_as_a__status=FriendshipStatus.PENDING_SENDER
        ).distinct()


class ProfileLike(models.Model):
    """
    Profile likes for matching system.
    When two users like each other, it becomes a mutual match.
    """
    liker = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='sent_profile_likes',
        db_index=True
    )
    liked = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='received_profile_likes',
        db_index=True
    )
    is_mutual = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['liker', 'liked']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['liker', 'created_at']),
            models.Index(fields=['liked', 'created_at']),
            models.Index(fields=['is_mutual']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.liker.username} likes {self.liked.username}"
    
    @classmethod
    def create_like(cls, liker, liked_user):
        """
        Create a profile like and check for mutual match
        Simplified version without recursion issues
        """
        try:
            logger.info(f"Creating like from user {liker.id} to user {liked_user.id}")
            
            # Basic validation
            if not liker or not liked_user:
                logger.error("Invalid users provided")
                return None, False
            
            if liker == liked_user:
                logger.error("User cannot like themselves")
                return None, False
            
            # Check if like already exists
            existing_like = cls.objects.filter(
                liker=liker,
                liked=liked_user
            ).first()
            
            if existing_like:
                logger.info(f"Like already exists: {existing_like.id}")
                return existing_like, False
            
            # Create the like
            try:
                with transaction.atomic():
                    like = cls.objects.create(
                        liker=liker,
                        liked=liked_user,
                        is_mutual=False
                    )
                    logger.info(f"Like created with ID: {like.id}")
                    
                    # Check for mutual like
                    reverse_like = cls.objects.filter(
                        liker=liked_user,
                        liked=liker
                    ).first()
                    
                    if reverse_like:
                        logger.info("Mutual like detected!")
                        # Update both likes to mutual
                        like.is_mutual = True
                        like.save(update_fields=['is_mutual', 'updated_at'])
                        
                        reverse_like.is_mutual = True
                        reverse_like.save(update_fields=['is_mutual', 'updated_at'])
                        
                        # Clear caches
                        cache.delete_many([
                            f"mutual_matches_{liker.id}",
                            f"mutual_matches_{liked_user.id}",
                            f"likes_received_{liker.id}",
                            f"likes_received_{liked_user.id}",
                            f"likes_sent_{liker.id}",
                            f"likes_sent_{liked_user.id}",
                        ])
                    
                    return like, True
                    
            except IntegrityError as e:
                logger.error(f"Integrity error creating like: {e}")
                # Try to get the existing like (race condition)
                like = cls.objects.get(liker=liker, liked=liked_user)
                return like, False
                
        except Exception as e:
            logger.error(f"Unexpected error in create_like: {e}", exc_info=True)
            raise
    
    @classmethod
    def remove_like(cls, liker, liked_user):
        """Remove a like and update mutual status"""
        try:
            like = cls.objects.get(liker=liker, liked=liked_user)
            
            with transaction.atomic():
                # Check if there's a reverse like
                reverse_like = cls.objects.filter(
                    liker=liked_user,
                    liked=liker
                ).first()
                
                # If reverse like exists, remove its mutual status
                if reverse_like and reverse_like.is_mutual:
                    reverse_like.is_mutual = False
                    reverse_like.save(update_fields=['is_mutual', 'updated_at'])
                
                # Delete the like
                like.delete()
                
                # Clear caches
                cache.delete_many([
                    f"mutual_matches_{liker.id}",
                    f"mutual_matches_{liked_user.id}",
                    f"likes_received_{liker.id}",
                    f"likes_received_{liked_user.id}",
                    f"likes_sent_{liker.id}",
                    f"likes_sent_{liked_user.id}",
                ])
                
                return True
                
        except cls.DoesNotExist:
            logger.warning(f"Like not found: {liker.id} -> {liked_user.id}")
            return False
        except Exception as e:
            logger.error(f"Error removing like: {e}", exc_info=True)
            return False

    @classmethod
    def get_mutual_matches(cls, user):
        """Get all mutual matches for a user with caching"""
        cache_key = f"mutual_matches_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        matches = cls.objects.filter(
            (Q(liker=user) | Q(liked=user)) &
            Q(is_mutual=True)
        ).select_related('liker__userprofile', 'liked__userprofile')
        
        cache.set(cache_key, matches, 300)
        return matches  # Return QuerySet, not list

    @classmethod
    def get_likes_received(cls, user):
        """Get all likes received by user (not mutual) with caching"""
        cache_key = f"likes_received_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        likes = cls.objects.filter(
            liked=user,
            is_mutual=False
        ).select_related('liker__userprofile')
        
        cache.set(cache_key, likes, 120)
        return likes  # Return QuerySet, not list

    @classmethod
    def get_likes_given(cls, user):
        """Get all likes given by user (not mutual)"""
        cache_key = f"likes_sent_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        likes = cls.objects.filter(
            liker=user,
            is_mutual=False
        ).select_related('liked__userprofile')
        
        cache.set(cache_key, likes, 120)
        return likes  # Return QuerySet, not list