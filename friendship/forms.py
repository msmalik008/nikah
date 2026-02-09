from django import forms
from django.contrib.auth.models import User
from .models import Friendship, FriendshipStatus

class FriendshipActionForm(forms.Form):
    """Form for friendship actions (send request, accept, reject, etc.)"""
    user_id = forms.IntegerField(widget=forms.HiddenInput())
    action = forms.CharField(widget=forms.HiddenInput())
    
    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
    
    def clean_user_id(self):
        user_id = self.cleaned_data.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            if user == self.request_user:
                raise forms.ValidationError("You cannot perform this action on yourself.")
            return user
        except User.DoesNotExist:
            raise forms.ValidationError("User does not exist.")
    
    def clean(self):
        cleaned_data = super().clean()
        user = cleaned_data.get('user_id')
        action = cleaned_data.get('action')
        
        if not user or not action:
            return cleaned_data
        
        # Get current relationship status
        relationship = Friendship.get_relationship(self.request_user, user)
        
        # Validate based on action
        if action == 'send_request':
            if relationship:
                status = relationship.status
                if status in [FriendshipStatus.PENDING_SENDER, FriendshipStatus.PENDING_RECEIVER]:
                    raise forms.ValidationError("Friend request already exists.")
                elif status == FriendshipStatus.FRIENDS:
                    raise forms.ValidationError("You are already friends.")
                elif status in [FriendshipStatus.REJECTED_BY_B]:
                    raise forms.ValidationError("Your request was previously rejected.")
                elif status in [FriendshipStatus.BLOCKED_BY_A, FriendshipStatus.BLOCKED_BY_B]:
                    raise forms.ValidationError("Cannot send request (blocked).")
        
        elif action == 'accept_request':
            if not relationship or relationship.status != FriendshipStatus.PENDING_RECEIVER:
                raise forms.ValidationError("No pending friend request to accept.")
        
        elif action == 'reject_request':
            if not relationship or relationship.status != FriendshipStatus.PENDING_RECEIVER:
                raise forms.ValidationError("No pending friend request to reject.")
        
        elif action == 'withdraw_rejection':
            if not relationship or relationship.status != FriendshipStatus.REJECTED_BY_A:
                raise forms.ValidationError("No rejection to withdraw.")
        
        elif action == 'remove_friend':
            if not relationship or relationship.status != FriendshipStatus.FRIENDS:
                raise forms.ValidationError("You are not friends with this user.")
        
        elif action == 'block_user':
            if relationship and relationship.status in [FriendshipStatus.BLOCKED_BY_A, FriendshipStatus.BLOCKED_BY_B]:
                raise forms.ValidationError("User is already blocked.")
        
        elif action == 'unblock_user':
            if not relationship or relationship.status != FriendshipStatus.BLOCKED_BY_A:
                raise forms.ValidationError("User is not blocked by you.")
        
        elif action == 'cancel_request':
            if not relationship or relationship.status != FriendshipStatus.PENDING_SENDER:
                raise forms.ValidationError("No sent request to cancel.")
        
        return cleaned_data


class BlockUserForm(forms.Form):
    """Form specifically for blocking users"""
    user_id = forms.IntegerField(widget=forms.HiddenInput())
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Optional: Reason for blocking...',
            'class': 'form-control'
        }),
        max_length=500
    )
    
    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
    
    def clean_user_id(self):
        user_id = self.cleaned_data.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            if user == self.request_user:
                raise forms.ValidationError("You cannot block yourself.")
            return user
        except User.DoesNotExist:
            raise forms.ValidationError("User does not exist.")


class FriendFilterForm(forms.Form):
    """Form for filtering friends list"""
    SEARCH_BY_CHOICES = [
        ('username', 'Username'),
        ('name', 'Name'),
        ('city', 'City'),
        ('sect', 'Sect'),
    ]
    
    search_by = forms.ChoiceField(
        choices=SEARCH_BY_CHOICES,
        initial='username',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    search_query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search...'
        })
    )
    
    sort_by = forms.ChoiceField(
        choices=[
            ('recent', 'Recently Added'),
            ('name', 'Name A-Z'),
            ('activity', 'Last Activity'),
        ],
        initial='recent',
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class FriendshipSettingsForm(forms.Form):
    """Form for friendship-related settings"""
    auto_accept_requests = forms.BooleanField(
        required=False,
        label='Auto-accept friend requests',
        help_text='Automatically accept all friend requests'
    )
    
    allow_friend_requests_from = forms.ChoiceField(
        choices=[
            ('everyone', 'Everyone'),
            ('friends_of_friends', 'Friends of Friends'),
            ('nobody', 'Nobody'),
        ],
        initial='everyone',
        label='Who can send friend requests',
        widget=forms.RadioSelect
    )
    
    show_online_status = forms.BooleanField(
        required=False,
        initial=True,
        label='Show when I\'m online to friends'
    )
    
    notify_on_request = forms.BooleanField(
        required=False,
        initial=True,
        label='Notify me when I receive a friend request'
    )
    
    notify_on_accept = forms.BooleanField(
        required=False,
        initial=True,
        label='Notify me when someone accepts my request'
    )
