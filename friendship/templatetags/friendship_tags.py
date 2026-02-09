from django import template
from ..models import Friendship, FriendshipStatus

register = template.Library()

@register.simple_tag
def get_relationship(user1, user2):
    """Get relationship between two users"""
    if not user1 or not user2:
        return None
    return Friendship.get_relationship(user1, user2)

@register.filter
def can_send_request(user1, user2):
    """Check if user1 can send friend request to user2"""
    if not user1 or not user2 or user1 == user2:
        return False
    
    relationship = Friendship.get_relationship(user1, user2)
    
    if not relationship:
        return True
    
    status = relationship.status
    
    # Can send request in these cases:
    if status == FriendshipStatus.STRANGERS:
        return True
    elif status in [FriendshipStatus.UNFRIENDED_BY_A, FriendshipStatus.UNFRIENDED_BY_B]:
        return True
    elif status == FriendshipStatus.REJECTED_BY_A and relationship.initiator == user2:
        return True  # User2 rejected user1, user1 can send again
    
    return False

@register.simple_tag
def get_friends_count(user):
    """Get count of friends for a user"""
    if not user:
        return 0
    return len(Friendship.get_friends(user))

@register.simple_tag
def get_pending_requests_count(user):
    """Get count of pending friend requests for a user"""
    if not user:
        return 0
    return Friendship.objects.filter(
        user_b=user,
        status=FriendshipStatus.PENDING_SENDER
    ).count()
