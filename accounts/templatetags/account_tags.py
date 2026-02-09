from django import template
from django.utils import timezone
from django.contrib.auth.models import User
from accounts.models import UserProfile, ActivityLog
from datetime import timedelta
import json

register = template.Library()


@register.filter
def get_profile_preference(profile, key):
    """Get a specific preference from profile's JSON field"""
    if not profile or not profile.preferences:
        return None
    return profile.preferences.get(key)


@register.filter
def get_user_preferences(user, key):
    """Get preferences from user's profile"""
    try:
        profile = user.userprofile
        return get_profile_preference(profile, key)
    except UserProfile.DoesNotExist:
        return None


@register.filter
def get_preference_display(profile, key):
    """Get display value for preference with human-readable labels"""
    if not profile or not profile.preferences:
        return ""
    
    value = profile.preferences.get(key)
    if not value:
        return ""
    
    # Define display mappings for common preferences
    display_maps = {
        'looking_for': {
            'M': 'Male',
            'F': 'Female',
            'B': 'Both',
            'A': 'Anyone',
        },
        'marital_status': {
            'S': 'Single',
            'D': 'Divorced',
            'W': 'Widowed',
            'N': 'Never Married',
            'SEP': 'Separated',
        },
        'religious_commitment': {
            'V': 'Very Religious',
            'M': 'Moderately Religious',
            'S': 'Somewhat Religious',
            'N': 'Not Religious',
        }
    }
    
    if key in display_maps and value in display_maps[key]:
        return display_maps[key][value]
    
    return value


@register.filter
def profile_completion_percentage(profile):
    """Calculate and return profile completion percentage"""
    if not profile:
        return 0
    return profile.get_profile_completion_percentage()


@register.filter
def profile_completion_class(percentage):
    """Return CSS class based on completion percentage"""
    if percentage >= 90:
        return "success"
    elif percentage >= 70:
        return "info"
    elif percentage >= 50:
        return "warning"
    else:
        return "danger"


@register.filter
def profile_completion_message(percentage):
    """Return motivational message based on completion percentage"""
    if percentage >= 90:
        return "Excellent! Your profile is almost complete!"
    elif percentage >= 70:
        return "Good progress! Add more details for better matches."
    elif percentage >= 50:
        return "Halfway there! Complete your profile for better results."
    else:
        return "Please complete your profile to start matching."


@register.filter
def format_last_active(last_active):
    """Format last active time in a human-readable way"""
    if not last_active:
        return "Never active"
    
    now = timezone.now()
    diff = now - last_active
    
    if diff < timedelta(minutes=1):
        return "Just now"
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < timedelta(days=7):
        days = diff.days
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif diff < timedelta(days=30):
        weeks = int(diff.days / 7)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    else:
        return last_active.strftime("%b %d, %Y")


@register.filter
def can_view_field(profile, field_name):
    """Check if a field should be visible based on privacy settings"""
    if not profile:
        return False
    
    privacy_map = {
        'age': profile.show_age,
        'city': profile.show_location,
        'country': profile.show_location,
        'sect': profile.show_sect,
        'education': profile.show_education,
        'practice_level': profile.show_practice_level,
    }
    
    return privacy_map.get(field_name, True)


@register.filter
def get_public_data(profile, field_name):
    """Get field data only if allowed by privacy settings"""
    if not can_view_field(profile, field_name):
        return "Hidden"
    
    if hasattr(profile, field_name):
        value = getattr(profile, field_name)
        if value:
            return value
    
    return "Not specified"


@register.filter
def get_display_value(profile, field_name):
    """Get display value for choice fields"""
    if not profile or not hasattr(profile, field_name):
        return ""
    
    value = getattr(profile, field_name)
    if not value:
        return ""
    
    # Get display method name
    display_method = f"get_{field_name}_display"
    if hasattr(profile, display_method):
        return getattr(profile, display_method)()
    
    return value


@register.filter
def format_activity_type(activity_type):
    """Format activity type for display"""
    type_map = {
        'signup': 'Signed up',
        'login': 'Logged in',
        'logout': 'Logged out',
        'profile_view': 'Viewed profile',
        'profile_update': 'Updated profile',
        'profile_approved': 'Profile approved',
        'profile_unapproved': 'Profile unapproved',
        'preferences_saved': 'Saved preferences',
        'landing_page_submit': 'Submitted landing page form',
    }
    return type_map.get(activity_type, activity_type.replace('_', ' ').title())


@register.filter
def get_recent_activity(user, count=5):
    """Get recent activities for a user"""
    try:
        return ActivityLog.objects.filter(user=user).order_by('-created_at')[:count]
    except:
        return []


@register.filter
def get_age_range(preferences):
    """Extract age range from preferences"""
    if not preferences or 'age_range' not in preferences:
        return "Not specified"
    
    age_range = preferences.get('age_range', {})
    min_age = age_range.get('min', '')
    max_age = age_range.get('max', '')
    
    if min_age and max_age:
        return f"{min_age} - {max_age}"
    elif min_age:
        return f"From {min_age}"
    elif max_age:
        return f"Up to {max_age}"
    
    return "Not specified"


@register.filter
def json_pretty(data):
    """Format JSON data for display"""
    if isinstance(data, dict):
        return json.dumps(data, indent=2)
    return data


@register.filter
def has_complete_profile(user):
    """Check if user has a complete profile"""
    try:
        profile = user.userprofile
        return profile.completed
    except UserProfile.DoesNotExist:
        return False


@register.filter
def is_profile_visible(user):
    """Check if user's profile is visible"""
    try:
        profile = user.userprofile
        return profile.is_visible and profile.approved
    except UserProfile.DoesNotExist:
        return False


@register.filter
def get_match_compatibility(profile1, profile2):
    """Calculate compatibility between two profiles"""
    if not profile1 or not profile2:
        return 0
    try:
        return profile1.calculate_compatibility(profile2)
    except:
        return 0


@register.filter
def compatibility_color(score):
    """Return color class based on compatibility score"""
    if score >= 80:
        return "text-success"
    elif score >= 60:
        return "text-info"
    elif score >= 40:
        return "text-warning"
    else:
        return "text-danger"


@register.filter
def compatibility_message(score):
    """Return message based on compatibility score"""
    if score >= 80:
        return "Excellent Match!"
    elif score >= 60:
        return "Good Match"
    elif score >= 40:
        return "Moderate Match"
    else:
        return "Low Match"


@register.simple_tag
def get_profile_stats(user):
    """Get profile statistics for dashboard"""
    try:
        profile = user.userprofile
        stats = {
            'completion_percentage': profile.get_profile_completion_percentage(),
            'days_since_join': (timezone.now() - user.date_joined).days,
            'last_active': format_last_active(profile.last_active),
            'match_count': 0,  # You'll need to implement match counting
            'views_count': ActivityLog.objects.filter(
                target_user=user, 
                activity_type='profile_view'
            ).count(),
        }
        return stats
    except UserProfile.DoesNotExist:
        return {}


@register.inclusion_tag('accounts/tags/profile_completion_progress.html')
def profile_completion_progress(profile):
    """Render profile completion progress bar"""
    percentage = profile.get_profile_completion_percentage() if profile else 0
    return {
        'percentage': percentage,
        'class': profile_completion_class(percentage),
        'message': profile_completion_message(percentage),
    }


@register.inclusion_tag('accounts/tags/profile_field_display.html')
def profile_field_display(profile, field_name, label=None):
    """Display a profile field with privacy consideration"""
    if not label:
        label = field_name.replace('_', ' ').title()
    
    is_visible = can_view_field(profile, field_name)
    value = get_public_data(profile, field_name) if is_visible else "Hidden"
    display_value = get_display_value(profile, field_name) if is_visible else "Hidden"
    
    return {
        'label': label,
        'field_name': field_name,
        'is_visible': is_visible,
        'value': value,
        'display_value': display_value,
        'has_display_method': display_value != value,
    }


@register.inclusion_tag('accounts/tags/activity_feed.html')
def activity_feed(user, limit=10):
    """Render activity feed for a user"""
    activities = ActivityLog.objects.filter(user=user).order_by('-created_at')[:limit]
    return {
        'activities': activities,
        'user': user,
    }