from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from .models import Friendship, FriendshipStatus, ProfileLike
from accounts.models import UserProfile
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from django.views.generic import TemplateView, ListView
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q, Exists, OuterRef
from django.db.models.functions import Now
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class FriendsView(LoginRequiredMixin, ListView):
    """
    Display all friends of the logged-in user with their details
    """
    template_name = 'friendship/friends_list.html'
    context_object_name = 'friends'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        user_id = self.kwargs.get('user_id')
        
        # If user_id is provided and different from logged-in user,
        # check if they are friends before showing friends list
        if user_id and int(user_id) != user.id:
            other_user = User.objects.get(id=user_id)
            relationship = Friendship.get_relationship(user, other_user)
            
            # Only show if they are friends
            if relationship and relationship.status == FriendshipStatus.FRIENDS:
                # Get friends of the other user - returns a list, not QuerySet
                friends_list = Friendship.get_friends(other_user)
                self.profile_user = other_user
            else:
                # Not friends, return empty list
                self.profile_user = other_user
                return []
        else:
            # Show logged-in user's friends - returns a list, not QuerySet
            friends_list = Friendship.get_friends(user)
            self.profile_user = user
        
        # At this point, friends_list is a Python list of User objects
        # Extract friend IDs from the list
        friend_ids = [f.id for f in friends_list]
        
        # Get mutual friends count for each friend
        mutual_friends_data = {}
        user_friends_set = set(Friendship.get_friends(user))  # Get current user's friends once
        
        for friend in friends_list:
            friend_friends = set(Friendship.get_friends(friend))
            mutual_count = len(user_friends_set & friend_friends)
            mutual_friends_data[friend.id] = mutual_count
        
        # Get like status
        likes_sent = set(
            ProfileLike.objects.filter(
                liker=user,
                liked_id__in=friend_ids
            ).values_list('liked_id', flat=True)
        )
        
        likes_received = set(
            ProfileLike.objects.filter(
                liked=user,
                liker_id__in=friend_ids
            ).values_list('liker_id', flat=True)
        )
        
        # Get online status (active in last 15 minutes)
        fifteen_minutes_ago = timezone.now() - timedelta(minutes=15)
        online_users = set(
            User.objects.filter(
                id__in=friend_ids,
                userprofile__last_active__gte=fifteen_minutes_ago
            ).values_list('id', flat=True)
        )
        
        # Attach data to user objects
        for friend in friends_list:
            friend.mutual_friends_count = mutual_friends_data.get(friend.id, 0)
            friend.user_liked = friend.id in likes_sent
            friend.user_liked_by = friend.id in likes_received
            friend.is_online = friend.id in online_users
            
            # Get last active time
            if hasattr(friend, 'userprofile'):
                friend.last_active = friend.userprofile.last_active
            
            # Get profile picture
            if hasattr(friend, 'userprofile') and friend.userprofile.profile_pic:
                friend.profile_pic_url = friend.userprofile.profile_pic.url
            else:
                friend.profile_pic_url = None
            
            # Get location
            if hasattr(friend, 'userprofile'):
                friend.city = friend.userprofile.city if friend.userprofile.show_location else None
                friend.country = friend.userprofile.country if friend.userprofile.show_location else None
        
        return friends_list
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Get the friends list ONCE - it's a Python list
        friends_list = self.get_queryset()
        
        # Use len() for Python lists (not .count())
        context['total_friends'] = len(friends_list)
        context['online_friends'] = sum(1 for f in friends_list if getattr(f, 'is_online', False))
        context['profile_user'] = getattr(self, 'profile_user', user)
        
        # Add friend request counts
        from .models import Friendship, FriendshipStatus
        context['pending_requests'] = Friendship.objects.filter(
            user_b=user,
            status=FriendshipStatus.PENDING_SENDER
        ).count()
        
        context['sent_requests'] = Friendship.objects.filter(
            user_a=user,
            status=FriendshipStatus.PENDING_SENDER
        ).count()
        
        return context


class FriendshipManagementView(LoginRequiredMixin, TemplateView):
    """
    Unified view for managing friendships with tabs:
    - Friends
    - Sent Requests
    - Received Requests
    - Blocked Users
    - Restricted Users
    """
    template_name = 'friendship/friendship_management.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        tab = self.kwargs.get('tab', 'friends')
        
        # Set active tab
        context['active_tab'] = tab
        
        # Common counts for sidebar
        context['total_friends'] = len(Friendship.get_friends(user))
        
        # Pending sent requests (where user is sender)
        context['pending_sent'] = Friendship.objects.filter(
            (Q(user_a=user, status=FriendshipStatus.PENDING_SENDER) |
             Q(user_b=user, status=FriendshipStatus.PENDING_RECEIVER))
        ).count()
        
        # Pending received requests (where user is receiver)
        context['pending_received'] = Friendship.objects.filter(
            (Q(user_a=user, status=FriendshipStatus.PENDING_RECEIVER) |
             Q(user_b=user, status=FriendshipStatus.PENDING_SENDER))
        ).count()
        
        # Get data for current tab
        if tab == 'friends':
            self._get_friends_context(context, user)
        elif tab == 'sent':
            self._get_sent_requests_context(context, user)
        elif tab == 'received':
            self._get_received_requests_context(context, user)
        elif tab == 'blocked':
            self._get_blocked_users_context(context, user)
        elif tab == 'restricted':
            self._get_restricted_users_context(context, user)
        
        return context
    
    def _get_friends_context(self, context, user):
        """Get context for friends tab"""
        friends_list = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends_list]
        
        # Get mutual friends count for each friend
        mutual_friends_data = {}
        user_friends_set = set(Friendship.get_friends(user))
        
        for friend in friends_list:
            friend_friends = set(Friendship.get_friends(friend))
            mutual_count = len(user_friends_set & friend_friends)
            mutual_friends_data[friend.id] = mutual_count
        
        # Get like status
        likes_sent = set(
            ProfileLike.objects.filter(
                liker=user,
                liked_id__in=friend_ids
            ).values_list('liked_id', flat=True)
        )
        
        likes_received = set(
            ProfileLike.objects.filter(
                liked=user,
                liker_id__in=friend_ids
            ).values_list('liker_id', flat=True)
        )
        
        # Get online status (active in last 15 minutes)
        fifteen_minutes_ago = timezone.now() - timedelta(minutes=15)
        online_users = set(
            User.objects.filter(
                id__in=friend_ids,
                userprofile__last_active__gte=fifteen_minutes_ago
            ).values_list('id', flat=True)
        )
        
        # Attach data to user objects
        for friend in friends_list:
            friend.mutual_friends_count = mutual_friends_data.get(friend.id, 0)
            friend.user_liked = friend.id in likes_sent
            friend.user_liked_by = friend.id in likes_received
            friend.is_online = friend.id in online_users
            
            # Get last active time
            if hasattr(friend, 'userprofile'):
                friend.last_active = friend.userprofile.last_active
            
            # Get profile picture
            if hasattr(friend, 'userprofile') and friend.userprofile.profile_pic:
                friend.profile_pic_url = friend.userprofile.profile_pic.url
            else:
                friend.profile_pic_url = None
            
            # Get location
            if hasattr(friend, 'userprofile'):
                friend.city = friend.userprofile.city if friend.userprofile.show_location else None
                friend.country = friend.userprofile.country if friend.userprofile.show_location else None
        
        # Paginate friends list
        page = self.request.GET.get('page', 1)
        paginator = Paginator(friends_list, 20)
        
        try:
            friends_page = paginator.page(page)
        except PageNotAnInteger:
            friends_page = paginator.page(1)
        except EmptyPage:
            friends_page = paginator.page(paginator.num_pages)
        
        context['items'] = friends_page
        context['online_friends'] = sum(1 for f in friends_list if getattr(f, 'is_online', False))
    
    def _get_sent_requests_context(self, context, user):
        """Get context for sent requests tab"""
        sent_requests = Friendship.objects.filter(
            (Q(user_a=user, status=FriendshipStatus.PENDING_SENDER) |
             Q(user_b=user, status=FriendshipStatus.PENDING_RECEIVER))
        ).select_related('user_a', 'user_b').order_by('-created_at')
        
        # Paginate
        page = self.request.GET.get('page', 1)
        paginator = Paginator(sent_requests, 20)
        
        try:
            requests_page = paginator.page(page)
        except PageNotAnInteger:
            requests_page = paginator.page(1)
        except EmptyPage:
            requests_page = paginator.page(paginator.num_pages)
        
        context['items'] = requests_page
        context['total_sent_requests'] = sent_requests.count()
    
    def _get_received_requests_context(self, context, user):
        """Get context for received requests tab"""
        received_requests = Friendship.objects.filter(
            (Q(user_a=user, status=FriendshipStatus.PENDING_RECEIVER) |
             Q(user_b=user, status=FriendshipStatus.PENDING_SENDER))
        ).select_related('user_a', 'user_b').order_by('-created_at')
        
        # Paginate
        page = self.request.GET.get('page', 1)
        paginator = Paginator(received_requests, 20)
        
        try:
            requests_page = paginator.page(page)
        except PageNotAnInteger:
            requests_page = paginator.page(1)
        except EmptyPage:
            requests_page = paginator.page(paginator.num_pages)
        
        context['items'] = requests_page
        context['total_received_requests'] = received_requests.count()
    
    def _get_blocked_users_context(self, context, user):
        """Get context for blocked users tab"""
        # Users blocked by current user
        blocked_by_me = Friendship.objects.filter(
            user_a=user,
            status=FriendshipStatus.BLOCKED_BY_A
        ).select_related('user_b').order_by('-updated_at')
        
        # Users who blocked current user
        blocked_by_others = Friendship.objects.filter(
            user_b=user,
            status=FriendshipStatus.BLOCKED_BY_B
        ).select_related('user_a').order_by('-updated_at')
        
        # Combine and deduplicate
        blocked_users = []
        seen_ids = set()
        
        for fb in blocked_by_me:
            if fb.user_b_id not in seen_ids:
                blocked_users.append({
                    'user': fb.user_b,
                    'blocked_by': 'you',
                    'date': fb.updated_at
                })
                seen_ids.add(fb.user_b_id)
        
        for fb in blocked_by_others:
            if fb.user_a_id not in seen_ids:
                blocked_users.append({
                    'user': fb.user_a,
                    'blocked_by': 'them',
                    'date': fb.updated_at
                })
                seen_ids.add(fb.user_a_id)
        
        # Paginate
        page = self.request.GET.get('page', 1)
        paginator = Paginator(blocked_users, 20)
        
        try:
            blocked_page = paginator.page(page)
        except PageNotAnInteger:
            blocked_page = paginator.page(1)
        except EmptyPage:
            blocked_page = paginator.page(paginator.num_pages)
        
        context['items'] = blocked_page
        context['total_blocked'] = len(blocked_users)
    
    def _get_restricted_users_context(self, context, user):
        """Get context for restricted users tab"""
        # Assuming you have a way to track restricted users
        # This is placeholder - implement based on your actual model
        restricted_users = []  # Replace with actual query
        
        # Paginate
        page = self.request.GET.get('page', 1)
        paginator = Paginator(restricted_users, 20)
        
        try:
            restricted_page = paginator.page(page)
        except PageNotAnInteger:
            restricted_page = paginator.page(1)
        except EmptyPage:
            restricted_page = paginator.page(paginator.num_pages)
        
        context['items'] = restricted_page
        context['total_restricted'] = len(restricted_users)

class SentRequestsView(LoginRequiredMixin, ListView):
    """
    Display all sent friend requests that are pending (status = PENDING_SENDER)
    """
    template_name = 'friendship/sent_requests.html'
    context_object_name = 'friend_requests'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        
        # Get all pending sent friend requests
        # Assuming Friendship model has fields: user_a (sender), user_b (receiver), status
        return Friendship.objects.filter(
            user_a=user,
            status=FriendshipStatus.PENDING_SENDER
        ).select_related('user_b__userprofile').order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Get total count of pending sent requests (not paginated)
        context['total_sent_requests'] = self.get_queryset().count()
        
        # You might want to add other counts similar to FriendsView
        context['pending_requests'] = Friendship.objects.filter(
            user_b=user,
            status=FriendshipStatus.PENDING_RECEIVER  # Note: PENDING_RECEIVER for incoming requests
        ).count()
        
        context['total_friends'] = len(Friendship.get_friends(user))  # Assuming get_friends returns list
        
        return context


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
            
            # Allow sending if status is STRANGERS
            if status == FriendshipStatus.STRANGERS:
                can_send = True
            elif status in [FriendshipStatus.PENDING_SENDER, FriendshipStatus.PENDING_RECEIVER]:
                error_msg = "Friend request already exists."
                can_send = False
            elif status == FriendshipStatus.FRIENDS:
                error_msg = "You are already friends."
                can_send = False
            elif status == FriendshipStatus.REJECTED_BY_B:
                error_msg = "Cannot send request (previously rejected by user)."
                can_send = False
            elif status == FriendshipStatus.REJECTED_BY_A:
                if relationship.initiator == request.user:
                    error_msg = "You previously rejected this user."
                    can_send = False
                else:
                    # The other user rejected you, you can send again
                    can_send = True
            elif status in [FriendshipStatus.BLOCKED_BY_A, FriendshipStatus.BLOCKED_BY_B]:
                error_msg = "Cannot send request (blocked)."
                can_send = False
            elif status in [FriendshipStatus.UNFRIENDED_BY_A, FriendshipStatus.UNFRIENDED_BY_B]:
                # Can send request again after unfriending
                can_send = True
        
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
            return JsonResponse({
                'success': True, 
                'message': 'Friend request sent successfully',
                'new_status': 'pending_sender'
            })
        
        return redirect('view_profile', user_id=user_id)
    
    return redirect('dashboard')

@login_required
def accept_friend_request(request, user_id):
    """Accept a friend request from specific user"""
    if request.method == 'POST':
        from_user = get_object_or_404(User, id=user_id)
        
        # Get relationship from the receiver's perspective
        relationship = Friendship.get_relationship(request.user, from_user)
        
        # Also check from sender's perspective as a backup
        sender_relationship = Friendship.get_relationship(from_user, request.user)
        
        # Check if there's a pending request
        has_pending = (
            (relationship and relationship.status == FriendshipStatus.PENDING_RECEIVER) or
            (sender_relationship and sender_relationship.status == FriendshipStatus.PENDING_SENDER)
        )
        
        if not has_pending:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': 'No pending friend request found'
                })
            messages.error(request, "No pending friend request found.")
            return redirect('dashboard')
        
        # Update to friends
        Friendship.create_or_update(
            user1=request.user,
            user2=from_user,
            new_status=FriendshipStatus.FRIENDS,
            initiator=request.user
        )
        
        messages.success(request, f"You are now friends with {from_user.username}!")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True, 
                'message': 'Friend request accepted',
                'new_status': 'friends'
            })
    
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
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': 'No request to cancel'
                })
            return redirect('dashboard', tab='friends')
        
        # Instead of deleting, update to STRANGERS
        Friendship.create_or_update(
            user1=request.user,
            user2=to_user,
            new_status=FriendshipStatus.STRANGERS,
            initiator=request.user
        )
        
        messages.info(request, "Friend request cancelled.")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True, 
                'message': 'Request cancelled',
                'new_status': 'strangers'
            })
    
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

class LikesManagementView(LoginRequiredMixin, TemplateView):
    """Main page for viewing likes with tabs"""
    template_name = 'friendship/likes_management.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Get counts for sidebar badges
        context['mutual_likes_count'] = ProfileLike.objects.filter(
            (Q(liker=user) | Q(liked=user)) & Q(is_mutual=True)
        ).count()
        
        context['sent_likes_count'] = ProfileLike.objects.filter(
            liker=user, is_mutual=False
        ).count()
        
        context['received_likes_count'] = ProfileLike.objects.filter(
            liked=user, is_mutual=False
        ).count()
        
        return context


class MutualLikesView(LoginRequiredMixin, ListView):
    """Display mutual likes as HTML (for AJAX tabs)"""
    template_name = 'friendship/likes/mutual_likes_list.html'
    context_object_name = 'likes'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        return ProfileLike.get_mutual_matches(user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user'] = self.request.user
        return context


class SentLikesView(LoginRequiredMixin, ListView):
    """Display sent likes as HTML (for AJAX tabs)"""
    template_name = 'friendship/likes/sent_likes_list.html'
    context_object_name = 'likes'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        return ProfileLike.get_likes_given(user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user'] = self.request.user
        return context


class ReceivedLikesView(LoginRequiredMixin, ListView):
    """Display received likes as HTML (for AJAX tabs)"""
    template_name = 'friendship/likes/received_likes_list.html'
    context_object_name = 'likes'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        return ProfileLike.get_likes_received(user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user'] = self.request.user
        return context


class LikeProfileView(LoginRequiredMixin, View):
    """Like a user's profile"""
    
    def post(self, request, user_id):
        logger.info(f"LikeProfileView: user={request.user.id}, target_user={user_id}")
        to_user = get_object_or_404(User, id=user_id)
        
        if request.user == to_user:
            return JsonResponse({'success': False, 'message': 'Cannot like yourself'})
        
        try:
            like, created = ProfileLike.create_like(request.user, to_user)
            
            if like:
                # Get updated counts
                from django.db.models import Q
                mutual_likes_count = ProfileLike.objects.filter(
                    (Q(liker=request.user) | Q(liked=request.user)) & Q(is_mutual=True)
                ).count()
                sent_likes_count = ProfileLike.objects.filter(
                    liker=request.user, is_mutual=False
                ).count()
                received_likes_count = ProfileLike.objects.filter(
                    liked=request.user, is_mutual=False
                ).count()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Liked {to_user.username}!',
                    'is_mutual': like.is_mutual,
                    'like_id': like.id,
                    'counts': {
                        'mutual_likes_count': mutual_likes_count,
                        'sent_likes_count': sent_likes_count,
                        'received_likes_count': received_likes_count,
                    }
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Unable to like user'
                })
        except Exception as e:
            logger.error(f"Error in LikeProfileView: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            })

class UnlikeProfileView(LoginRequiredMixin, View):
    """Remove a like"""
    
    def post(self, request, user_id):
        logger.info(f"UnlikeProfileView: user={request.user.id}, target_user={user_id}")
        to_user = get_object_or_404(User, id=user_id)
        
        if request.user == to_user:
            return JsonResponse({'success': False, 'message': 'Cannot unlike yourself'})
        
        success = ProfileLike.remove_like(request.user, to_user)
        
        if success:
            # Get updated counts
            from django.db.models import Q
            mutual_likes_count = ProfileLike.objects.filter(
                (Q(liker=request.user) | Q(liked=request.user)) & Q(is_mutual=True)
            ).count()
            sent_likes_count = ProfileLike.objects.filter(
                liker=request.user, is_mutual=False
            ).count()
            received_likes_count = ProfileLike.objects.filter(
                liked=request.user, is_mutual=False
            ).count()
            
            return JsonResponse({
                'success': True,
                'message': f'Unliked {to_user.username}',
                'counts': {
                    'mutual_likes_count': mutual_likes_count,
                    'sent_likes_count': sent_likes_count,
                    'received_likes_count': received_likes_count,
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Like not found'
            })


class CheckMutualLikeView(LoginRequiredMixin, View):
    """Check if there's a mutual like between two users"""
    
    def get(self, request, user_id):
        other_user = get_object_or_404(User, id=user_id)
        
        # Check if there's a mutual like
        is_mutual = ProfileLike.objects.filter(
            (Q(liker=request.user, liked=other_user) | 
             Q(liker=other_user, liked=request.user)),
            is_mutual=True
        ).exists()
        
        return JsonResponse({
            'is_mutual': is_mutual
        })