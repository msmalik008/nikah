from django.db import models, transaction
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
                friendship.status = cls.get_inverted_status(friendship.status)
                result = friendship
        except cls.DoesNotExist:
            result = None
        
        # Cache for 5 minutes
        cache.set(cache_key, result, 300)
        return result
    
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
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        
        with transaction.atomic():
            super().save(*args, **kwargs)
            
            # Check for mutual like
            if is_new:
                self.check_mutual_like()
                
                # Clear like caches
                cache_keys = [
                    f"likes_received_{self.liked_id}",
                    f"likes_sent_{self.liker_id}",
                    f"mutual_likes_{self.liker_id}",
                    f"mutual_likes_{self.liked_id}",
                ]
                cache.delete_many(cache_keys)
    
    def check_mutual_like(self):
        """Check and update mutual like status"""
        mutual = ProfileLike.objects.filter(
            liker=self.liked,
            liked=self.liker
        ).exists()
        
        if mutual and not self.is_mutual:
            self.is_mutual = True
            self.save(update_fields=['is_mutual', 'updated_at'])
            
            # Update the reverse like
            ProfileLike.objects.filter(
                liker=self.liked,
                liked=self.liker
            ).update(is_mutual=True, updated_at=timezone.now())
        
        return mutual
    
    @classmethod
    def create_like(cls, liker, liked_user):
        """Create a profile like and check for mutual match"""
        with transaction.atomic():
            like, created = cls.objects.get_or_create(
                liker=liker,
                liked=liked_user
            )
            
            if created:
                # Check for mutual like
                like.check_mutual()
                
                # Log activity
                from useractivity.models import Activity
                Activity.create_activity(
                    user=liker,
                    activity_type='profile_liked',
                    target_user=liked_user,
                    metadata={'like_id': like.id}
                )
            
            return like, created
    
    @classmethod
    def get_mutual_matches(cls, user):
        """Get all mutual matches for a user with caching"""
        cache_key = f"mutual_matches_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        matches = cls.objects.filter(
            (models.Q(liker=user) | models.Q(liked=user)) &
            models.Q(is_mutual=True)
        ).select_related('liker__userprofile', 'liked__userprofile')
        
        # Cache for 5 minutes
        cache.set(cache_key, matches, 300)
        return matches
    
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
        
        # Cache for 2 minutes
        cache.set(cache_key, likes, 120)
        return likes
    
    @classmethod
    def get_likes_given(cls, user):
        """Get all likes given by user (not mutual)"""
        return cls.objects.filter(
            liker=user,
            is_mutual=False
        ).select_related('liked__userprofile')