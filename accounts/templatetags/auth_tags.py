from django import template
from django.contrib.auth.models import User
from accounts.models import UserProfile

register = template.Library()


@register.filter
def is_authenticated_with_profile(user):
    """Check if user is authenticated AND has a profile"""
    return user.is_authenticated and hasattr(user, 'userprofile')


@register.filter
def get_user_profile(user):
    """Safely get user profile"""
    try:
        return user.userprofile
    except UserProfile.DoesNotExist:
        return None


@register.filter
def can_edit_profile(user, profile_user):
    """Check if current user can edit a profile"""
    return user.is_authenticated and (user == profile_user or user.is_staff)


@register.filter
def can_view_profile(current_user, profile_user):
    """Check if current user can view another user's profile"""
    if not current_user.is_authenticated:
        return False
    
    if current_user == profile_user:
        return True
    
    try:
        profile = profile_user.userprofile
        return profile.is_visible and profile.approved
    except UserProfile.DoesNotExist:
        return False


@register.filter
def get_initial_avatar(user, size=40):
    """Generate avatar from initials if no profile picture"""
    if not user:
        return ""
    
    initials = ""
    if user.first_name and user.last_name:
        initials = f"{user.first_name[0]}{user.last_name[0]}"
    else:
        initials = user.username[:2].upper()
    
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#98D8C8']
    color_index = sum(ord(c) for c in user.username) % len(colors)
    
    return f"""
    <div class="avatar-initials" style="
        width: {size}px;
        height: {size}px;
        background-color: {colors[color_index]};
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: bold;
        font-size: {size//2}px;
    ">{initials}</div>
    """


@register.filter
def has_permission(user, permission_codename):
    """Check if user has specific permission"""
    return user.has_perm(permission_codename)


@register.simple_tag(takes_context=True)
def get_current_user_profile(context):
    """Get current user's profile from context"""
    request = context.get('request')
    if request and request.user.is_authenticated:
        try:
            return request.user.userprofile
        except UserProfile.DoesNotExist:
            return None
    return None