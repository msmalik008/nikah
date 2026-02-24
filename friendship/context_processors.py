from django.db.models import Q
from .models import Friendship, FriendshipStatus, ProfileLike

def friendship_counts(request):
    """Add friendship-related counts to all templates"""
    if not request.user.is_authenticated:
        return {}
    
    user = request.user
    
    # Friendship counts (existing)
    pending_sent = Friendship.objects.filter(
        (Q(user_a=user, status=FriendshipStatus.PENDING_SENDER) |
         Q(user_b=user, status=FriendshipStatus.PENDING_RECEIVER))
    ).count()
    
    pending_received = Friendship.objects.filter(
        (Q(user_a=user, status=FriendshipStatus.PENDING_RECEIVER) |
         Q(user_b=user, status=FriendshipStatus.PENDING_SENDER))
    ).count()
    
    total_friends = len(Friendship.get_friends(user))
    
    # Likes counts (new)
    mutual_likes_count = ProfileLike.objects.filter(
        (Q(liker=user) | Q(liked=user)) & Q(is_mutual=True)
    ).count()
    
    sent_likes_count = ProfileLike.objects.filter(
        liker=user, is_mutual=False
    ).count()
    
    received_likes_count = ProfileLike.objects.filter(
        liked=user, is_mutual=False
    ).count()
    
    return {
        'pending_sent': pending_sent,
        'pending_received': pending_received,
        'total_friends': total_friends,
        'mutual_likes_count': mutual_likes_count,
        'sent_likes_count': sent_likes_count,
        'received_likes_count': received_likes_count,
    }