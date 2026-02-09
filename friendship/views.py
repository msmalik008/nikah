from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from .models import Friendship, FriendshipStatus, ProfileLike
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model

User = get_user_model()


@login_required
def send_friend_request(request, user_id):
    """Send a friend request to another user"""
    if request.method == 'POST':
        to_user = get_object_or_404(User, id=user_id)
        
        if to_user == request.user:
            messages.error(request, "You cannot send a friend request to yourself.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'Cannot send request to yourself'
            })
        
        # Get current relationship
        relationship = Friendship.get_relationship(request.user, to_user)
        
        # Check if can send request
        can_send = True
        error_msg = None
        
        if relationship:
            status = relationship.status
            
            if status in [FriendshipStatus.PENDING_SENDER, FriendshipStatus.PENDING_RECEIVER]:
                error_msg = "Friend request already exists."
                can_send = False
            elif status == FriendshipStatus.FRIENDS:
                error_msg = "You are already friends."
                can_send = False
            elif status in [FriendshipStatus.REJECTED_BY_A, FriendshipStatus.REJECTED_BY_B]:
                if status == FriendshipStatus.REJECTED_BY_B and relationship.initiator == to_user:
                    error_msg = "Cannot send request (previously rejected by user)."
                    can_send = False
                elif status == FriendshipStatus.REJECTED_BY_A and relationship.initiator == request.user:
                    error_msg = "You previously rejected this user."
                    can_send = False
        
        if not can_send:
            messages.error(request, error_msg)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': error_msg})
            return redirect('view_profile', user_id=user_id)
        
        # Create friend request
        Friendship.create_or_update(
            user1=request.user,
            user2=to_user,
            new_status=FriendshipStatus.PENDING_SENDER,
            initiator=request.user
        )
        
        messages.success(request, f"Friend request sent to {to_user.username}!")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Friend request sent successfully'})
        
        return redirect('view_profile', user_id=user_id)
    
    return redirect('dashboard')

@login_required
def accept_friend_request(request, user_id):
    """Accept a friend request from specific user"""
    if request.method == 'POST':
        from_user = get_object_or_404(User, id=user_id)
        
        # Check if request exists
        relationship = Friendship.get_relationship(from_user, request.user)
        
        if not relationship or relationship.status != FriendshipStatus.PENDING_RECEIVER:
            messages.error(request, "No pending friend request found.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'No pending request found'
            })
        
        # Update to friends
        Friendship.create_or_update(
            user1=request.user,
            user2=from_user,
            new_status=FriendshipStatus.FRIENDS,
            initiator=request.user
        )
        
        messages.success(request, f"You are now friends with {from_user.username}!")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Friend request accepted'})
    
    return redirect('dashboard', tab='friends')

@login_required
def reject_friend_request(request, user_id):
    """Reject a friend request"""
    if request.method == 'POST':
        from_user = get_object_or_404(User, id=user_id)
        
        # Check if request exists
        relationship = Friendship.get_relationship(from_user, request.user)
        
        if not relationship or relationship.status != FriendshipStatus.PENDING_RECEIVER:
            messages.error(request, "No pending friend request found.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'No pending request found'
            })
        
        # Set as rejected (user B rejects user A)
        Friendship.create_or_update(
            user1=request.user,
            user2=from_user,
            new_status=FriendshipStatus.REJECTED_BY_B,
            initiator=request.user
        )
        
        messages.info(request, "Friend request rejected.")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Friend request rejected'})
    
    return redirect('dashboard', tab='friends')

@login_required
def withdraw_rejection(request, user_id):
    """Withdraw a rejection you made earlier"""
    if request.method == 'POST':
        other_user = get_object_or_404(User, id=user_id)
        
        relationship = Friendship.get_relationship(request.user, other_user)
        
        if not relationship:
            messages.error(request, "No relationship found.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'No relationship found'
            })
        
        # Check if current user is the one who rejected
        if relationship.status == FriendshipStatus.REJECTED_BY_A and relationship.initiator == request.user:
            # Withdraw rejection - go back to strangers
            Friendship.create_or_update(
                user1=request.user,
                user2=other_user,
                new_status=FriendshipStatus.STRANGERS,
                initiator=request.user
            )
            messages.success(request, "Rejection withdrawn.")
        elif relationship.status == FriendshipStatus.REJECTED_BY_B:
            messages.info(request, "You were rejected by this user.")
        else:
            messages.error(request, "No rejection to withdraw.")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Rejection withdrawn'})
    
    return redirect('dashboard', tab='friends')

@login_required
def cancel_friend_request(request, user_id):
    """Cancel a friend request you sent"""
    if request.method == 'POST':
        to_user = get_object_or_404(User, id=user_id)
        
        relationship = Friendship.get_relationship(request.user, to_user)
        
        if not relationship or relationship.status != FriendshipStatus.PENDING_SENDER:
            messages.error(request, "No pending request to cancel.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'No request to cancel'
            })
        
        # Delete the friendship record (go back to strangers)
        u1, u2 = (request.user, to_user) if request.user.id < to_user.id else (to_user, request.user)
        Friendship.objects.filter(user_a=u1, user_b=u2).delete()
        
        messages.info(request, "Friend request cancelled.")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Request cancelled'})
    
    return redirect('dashboard', tab='friends')

@login_required
def remove_friend(request, user_id):
    """Unfriend a user"""
    if request.method == 'POST':
        friend = get_object_or_404(User, id=user_id)
        
        relationship = Friendship.get_relationship(request.user, friend)
        
        if not relationship or relationship.status != FriendshipStatus.FRIENDS:
            messages.error(request, "You are not friends with this user.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'Not friends'
            })
        
        # Unfriend (from request.user's perspective)
        Friendship.create_or_update(
            user1=request.user,
            user2=friend,
            new_status=FriendshipStatus.UNFRIENDED_BY_A,
            initiator=request.user
        )
        
        messages.info(request, f"{friend.username} has been removed from friends.")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Friend removed'})
    
    return redirect('dashboard', tab='friends')

@login_required
def block_user(request, user_id):
    """Block a user"""
    if request.method == 'POST':
        user_to_block = get_object_or_404(User, id=user_id)
        
        if user_to_block == request.user:
            messages.error(request, "You cannot block yourself.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'Cannot block yourself'
            })
        
        # Block from request.user's perspective
        Friendship.create_or_update(
            user1=request.user,
            user2=user_to_block,
            new_status=FriendshipStatus.BLOCKED_BY_A,
            initiator=request.user
        )
        
        messages.warning(request, f"{user_to_block.username} has been blocked.")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'User blocked'})
    
    return redirect('dashboard', tab='friends')

@login_required
def unblock_user(request, user_id):
    """Unblock a user"""
    if request.method == 'POST':
        user_to_unblock = get_object_or_404(User, id=user_id)
        
        relationship = Friendship.get_relationship(request.user, user_to_unblock)
        
        if not relationship or relationship.status != FriendshipStatus.BLOCKED_BY_A:
            messages.error(request, "User is not blocked by you.")
            return redirect('dashboard') if not request.headers.get('X-Requested-With') == 'XMLHttpRequest' else JsonResponse({
                'success': False,
                'message': 'User not blocked'
            })
        
        # Restore to status before block, or strangers if none
        new_status = relationship.status_before_block or FriendshipStatus.STRANGERS
        
        Friendship.create_or_update(
            user1=request.user,
            user2=user_to_unblock,
            new_status=new_status,
            initiator=request.user
        )
        
        messages.success(request, f"{user_to_unblock.username} has been unblocked.")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'User unblocked'})
    
    return redirect('dashboard', tab='friends')

class LikeProfileView(LoginRequiredMixin, View):
    """Like or unlike a user profile"""
    def post(self, request, user_id):
        liked_user = get_object_or_404(User, id=user_id)
        
        # Check if trying to like self
        if liked_user == request.user:
            return JsonResponse({
                'success': False,
                'error': 'You cannot like your own profile'
            })
        
        # Check if already liked
        existing_like = ProfileLike.objects.filter(
            liker=request.user,
            liked=liked_user
        ).first()
        
        if existing_like:
            # Unlike
            existing_like.delete()
            
            # Remove mutual status from other like if exists
            other_like = ProfileLike.objects.filter(
                liker=liked_user,
                liked=request.user
            ).first()
            if other_like:
                other_like.is_mutual = False
                other_like.save(update_fields=['is_mutual', 'updated_at'])
            
            return JsonResponse({
                'success': True,
                'action': 'unliked',
                'is_mutual': False
            })
        
        # Create new like
        like, created = ProfileLike.create_like(request.user, liked_user)
        
        return JsonResponse({
            'success': True,
            'action': 'liked',
            'is_mutual': like.is_mutual,
            'like_id': like.id
        })


class CheckMutualLikeView(LoginRequiredMixin, View):
    """Check if there's a mutual like between users"""
    def get(self, request, user_id):
        other_user = get_object_or_404(User, id=user_id)
        
        mutual = ProfileLike.objects.filter(
            liker=request.user,
            liked=other_user,
            is_mutual=True
        ).exists() or ProfileLike.objects.filter(
            liker=other_user,
            liked=request.user,
            is_mutual=True
        ).exists()
        
        return JsonResponse({
            'success': True,
            'is_mutual': mutual
        })


class GetLikesView(LoginRequiredMixin, View):
    """Get likes received and given"""
    def get(self, request):
        likes_received = ProfileLike.get_likes_received(request.user)
        likes_given = ProfileLike.get_likes_given(request.user)
        mutual_matches = ProfileLike.get_mutual_matches(request.user)
        
        # Format response
        data = {
            'received': [
                {
                    'id': like.id,
                    'user_id': like.liker.id,
                    'username': like.liker.username,
                    'created_at': like.created_at.isoformat(),
                    'profile_pic': like.liker.userprofile.profile_pic.url if hasattr(like.liker, 'userprofile') and like.liker.userprofile.profile_pic else None
                }
                for like in likes_received
            ],
            'given': [
                {
                    'id': like.id,
                    'user_id': like.liked.id,
                    'username': like.liked.username,
                    'created_at': like.created_at.isoformat(),
                    'is_mutual': like.is_mutual,
                    'profile_pic': like.liked.userprofile.profile_pic.url if hasattr(like.liked, 'userprofile') and like.liked.userprofile.profile_pic else None
                }
                for like in likes_given
            ],
            'mutual_matches': [
                {
                    'id': match.id,
                    'other_user': match.liked.id if match.liker == request.user else match.liker.id,
                    'username': match.liked.username if match.liker == request.user else match.liker.username,
                    'created_at': match.created_at.isoformat(),
                    'profile_pic': (match.liked.userprofile.profile_pic.url if match.liker == request.user and hasattr(match.liked, 'userprofile') and match.liked.userprofile.profile_pic 
                                  else match.liker.userprofile.profile_pic.url if hasattr(match.liker, 'userprofile') and match.liker.userprofile.profile_pic else None)
                }
                for match in mutual_matches
            ]
        }
        
        return JsonResponse({
            'success': True,
            'data': data
        })
