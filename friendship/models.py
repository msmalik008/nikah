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

    # =====================================================
    # CACHE UTILITIES
    # =====================================================

    @staticmethod
    def clear_like_caches(user1, user2):
        """Clear all like-related caches for both users."""
        for user in [user1, user2]:
            cache.delete(f"mutual_matches_{user.id}")
            cache.delete(f"likes_received_{user.id}")
            cache.delete(f"likes_sent_{user.id}")

    # =====================================================
    # COUNT HELPER
    # =====================================================

    @classmethod
    def get_counts(cls, user):
        return {
            'mutual_likes_count': cls.objects.filter(
                Q(liker=user) | Q(liked=user),
                is_mutual=True
            ).count(),
            'sent_likes_count': cls.objects.filter(
                liker=user,
                is_mutual=False
            ).count(),
            'received_likes_count': cls.objects.filter(
                liked=user,
                is_mutual=False
            ).count()
        }

    # =====================================================
    # CREATE LIKE
    # =====================================================

    @classmethod
    def create_like(cls, liker, liked_user):
        """
        Create like and safely handle mutual match.
        Returns (like_instance, created_boolean)
        """

        if liker == liked_user:
            return None, False

        with transaction.atomic():

            # Lock reverse like if exists
            reverse_like = cls.objects.select_for_update().filter(
                liker=liked_user,
                liked=liker
            ).first()

            # Prevent duplicate like
            existing_like = cls.objects.filter(
                liker=liker,
                liked=liked_user
            ).first()

            if existing_like:
                return existing_like, False

            # Create new like
            new_like = cls.objects.create(
                liker=liker,
                liked=liked_user,
                is_mutual=False
            )

            # If reverse like exists → make mutual
            if reverse_like:
                new_like.is_mutual = True
                reverse_like.is_mutual = True

                new_like.save(update_fields=['is_mutual'])
                reverse_like.save(update_fields=['is_mutual'])

            # Clear caches AFTER successful DB operations
            cls.clear_like_caches(liker, liked_user)

            return new_like, True

    # =====================================================
    # REMOVE LIKE
    # =====================================================

    @classmethod
    def remove_like(cls, liker, liked_user):
        """
        Remove like and safely break mutual if needed.
        Returns True if deleted, False otherwise.
        """

        with transaction.atomic():

            like = cls.objects.filter(
                liker=liker,
                liked=liked_user
            ).first()

            if not like:
                return False

            reverse_like = cls.objects.select_for_update().filter(
                liker=liked_user,
                liked=liker
            ).first()

            # Break mutual if needed
            if reverse_like and reverse_like.is_mutual:
                reverse_like.is_mutual = False
                reverse_like.save(update_fields=['is_mutual'])

            like.delete()

            # Clear caches AFTER deletion
            cls.clear_like_caches(liker, liked_user)

            return True

    # =====================================================
    # QUERY METHODS (SAFE CACHING)
    # =====================================================

    @classmethod
    def get_mutual_matches(cls, user):
        """
        Return all users that have mutual likes with the current user.
        Caches list of user IDs (NOT QuerySet).
        """
        cache_key = f"mutual_matches_{user.id}"
        cached_ids = cache.get(cache_key)

        if cached_ids is None:
            mutual_ids = list(
                cls.objects.filter(
                    liker=user,
                    is_mutual=True
                ).values_list('liked_id', flat=True)
            )
            cache.set(cache_key, mutual_ids, 300)
        else:
            mutual_ids = cached_ids

        return User.objects.filter(
            id__in=mutual_ids
        ).select_related('userprofile')

    @classmethod
    def get_likes_received(cls, user):
        """
        Get all likes received by user (not mutual).
        Caches list of like IDs.
        """
        cache_key = f"likes_received_{user.id}"
        cached_ids = cache.get(cache_key)

        if cached_ids is None:
            like_ids = list(
                cls.objects.filter(
                    liked=user,
                    is_mutual=False
                ).values_list('id', flat=True)
            )
            cache.set(cache_key, like_ids, 120)
        else:
            like_ids = cached_ids

        return cls.objects.filter(
            id__in=like_ids
        ).select_related('liker__userprofile')

    @classmethod
    def get_likes_given(cls, user):
        """
        Get all likes given by user (not mutual).
        Caches list of like IDs.
        """
        cache_key = f"likes_sent_{user.id}"
        cached_ids = cache.get(cache_key)

        if cached_ids is None:
            like_ids = list(
                cls.objects.filter(
                    liker=user,
                    is_mutual=False
                ).values_list('id', flat=True)
            )
            cache.set(cache_key, like_ids, 120)
        else:
            like_ids = cached_ids

        return cls.objects.filter(
            id__in=like_ids
        ).select_related('liked__userprofile')