from django.utils import timezone
from django.shortcuts import redirect, reverse
from django.utils.deprecation import MiddlewareMixin
from accounts.models import UserProfile


class UpdateLastActiveMiddleware(MiddlewareMixin):
    """
    Updates the last_active timestamp for authenticated users on each request
    """
    
    def process_request(self, request):
        # Update last_active at the beginning of request
        if request.user.is_authenticated:
            try:
                # Update on UserProfile model
                profile = getattr(request.user, 'userprofile', None)
                if profile and hasattr(profile, 'last_active'):
                    profile.last_active = timezone.now()
                    profile.save(update_fields=['last_active', 'updated_at'])
            except Exception as e:
                # Log the error but don't break the request
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to update last_active: {e}")
        
        return None


class ProfileCompletionMiddleware(MiddlewareMixin):
    """
    Redirects users with incomplete profiles to profile completion page
    """
    
    EXEMPT_PATHS = [
        '/admin/',
        '/static/',
        '/media/',
        '/accounts/logout/',
        '/accounts/login/',
        '/accounts/register/',
        '/profile/edit/',
        '/api/',  # Exempt API endpoints
    ]
    
    def process_request(self, request):
        # Always exempt these paths
        if any(request.path.startswith(path) for path in self.EXEMPT_PATHS):
            return None
        
        # Only check authenticated users
        if not request.user.is_authenticated:
            return None
        
        # Check if user has complete profile
        if not self._has_complete_profile(request.user):
            profile_edit_url = reverse('accounts:profile_edit')
            
            # Make sure we're not already going to profile edit
            if request.path != profile_edit_url:
                # Store intended destination for redirect after completion
                request.session['next_url'] = request.get_full_path()
                return redirect(profile_edit_url)
        
        return None
    
    def _has_complete_profile(self, user):
        """Check if user has a complete profile"""
        try:
            profile = user.userprofile
            completion = profile.get_profile_completion_percentage()
            return completion >= 50  # Threshold for basic functionality
        except UserProfile.DoesNotExist:
            return False
    
    def _calculate_profile_completion(self, profile):
        """This method is now in the UserProfile model"""
        return profile.get_profile_completion_percentage()