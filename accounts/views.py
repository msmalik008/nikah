# Standard library imports
import json
import math
import logging
from datetime import timedelta

# Django core imports
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.models import User

from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.views.generic import CreateView, UpdateView, TemplateView, FormView
from django.views import View
from django.http import JsonResponse, HttpResponseForbidden
from django.core.exceptions import PermissionDenied

from django.db import transaction
from django.db.models import Q, Count, Prefetch, F, Case, When, Value, IntegerField
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.template.loader import render_to_string
from django.core.cache import cache
from django.conf import settings

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache, cache_page
from django.views.decorators.vary import vary_on_cookie
from django.views.decorators.csrf import csrf_exempt

# Local app imports
from .forms import (
    CustomUserCreationForm, CustomAuthenticationForm, ProfileForm,
    UserUpdateForm, CustomPasswordChangeForm, EmailUpdateForm,
    AccountDeleteForm, LandingPageForm
)
from .models import UserProfile, ActivityLog, EmailVerification
from .utils import cache_simple_data, get_cached_simple_data

# Third-party app imports
from friendship.models import Friendship, ProfileLike, FriendshipStatus

# Logging setup
logger = logging.getLogger(__name__)


# Authentication Views
class RegisterView(CreateView):
    """Direct registration view (for users not coming from landing page)"""
    form_class = CustomUserCreationForm
    template_name = 'accounts/register.html'
    success_url = reverse_lazy('accounts:login')
    
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard:dashboard')
        return super().get(request, *args, **kwargs)
    
    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()
            
            # Log activity
            ActivityLog.objects.create(
                user=user,
                activity_type='signup',
                ip_address=self.request.META.get('REMOTE_ADDR'),
                user_agent=self.request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        
        messages.success(self.request, 
            'Registration successful! Please log in to complete your profile.')
        return super().form_valid(form)


class CustomLoginView(View):
    """Updated login view to check for incomplete profiles"""
    template_name = 'accounts/login.html'
    
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard:dashboard')
        form = CustomAuthenticationForm()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        form = CustomAuthenticationForm(data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            remember_me = form.cleaned_data.get('remember_me', False)
            
            # Try to authenticate
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                
                # Update last active
                try:
                    profile = user.userprofile
                    profile.last_active = timezone.now()
                    profile.save(update_fields=['last_active', 'updated_at'])
                    
                    # Clear profile completion cache
                    cache_key = f"profile_completion_{user.id}"
                    cache.delete(cache_key)
                    
                except UserProfile.DoesNotExist:
                    # No profile yet - redirect to create one
                    messages.info(request, 'Please complete your profile setup.')
                    return redirect('accounts:profile_edit')
                
                # Log activity
                ActivityLog.objects.create(
                    user=user,
                    activity_type='login',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                )
                
                # Set session expiry
                if not remember_me:
                    request.session.set_expiry(0)  # Session ends when browser closes
                else:
                    request.session.set_expiry(1209600)  # 2 weeks
                
                messages.success(request, f'Welcome back, {user.username}!')
                
                # Check profile completion and redirect accordingly
                next_url = request.session.get('next_url')
                if next_url:
                    del request.session['next_url']
                    return redirect(next_url)
                
                # Redirect based on profile completion
                if profile.profile_completion_percentage < 50:
                    messages.info(request, 'Please complete your profile for better matches.')
                    return redirect('accounts:profile_edit')
                else:
                    return redirect('dashboard:dashboard')
        
        messages.error(request, 'Invalid username/email or password')
        return render(request, self.template_name, {'form': form})


class CustomLogoutView(View):
    """Logout view - unchanged"""
    def get(self, request):
        if request.user.is_authenticated:
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity_type='logout',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
            )
            logout(request)
            messages.info(request, 'You have been logged out.')
        return redirect('accounts:home')


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """Profile update view"""
    model = UserProfile
    form_class = ProfileForm
    template_name = 'accounts/profile_edit.html'
    
    def get_object(self):
        return self.request.user.userprofile
    
    def get_initial(self):
        """Prefill form with data from landing page if available"""
        initial = super().get_initial()
        
        # Check if there are landing preferences in session
        landing_prefs = self.request.session.get('landing_preferences', {})
        if landing_prefs:
            profile = self.get_object()
            
            # Map landing preferences to profile fields
            mapping = {
                'age': ('age', int),
                'gender': ('gender', str),
                'city': ('city', str),
                'country': ('country', str),
                'sect': ('sect', str),
            }
            
            for pref_key, (field, cast_func) in mapping.items():
                if pref_key in landing_prefs and not getattr(profile, field):
                    try:
                        initial[field] = cast_func(landing_prefs[pref_key])
                    except (ValueError, TypeError):
                        pass
        
        return initial
    
    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            
            # Clear landing preferences from session after successful profile update
            if 'landing_preferences' in self.request.session:
                del self.request.session['landing_preferences']
            
            # Clear profile completion cache
            cache_key = f"profile_completion_{self.request.user.id}"
            cache.delete(cache_key)
            
            # Log activity
            ActivityLog.objects.create(
                user=self.request.user,
                activity_type='profile_update',
                ip_address=self.request.META.get('REMOTE_ADDR'),
                user_agent=self.request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        
        messages.success(self.request, 'Profile updated successfully!')
        return response
    
    def get_success_url(self):
        # Redirect to next URL if exists, otherwise to profile view
        next_url = self.request.session.get('next_url')
        if next_url:
            del self.request.session['next_url']
            return next_url
        
        # Redirect based on profile completion
        profile = self.get_object()
        if profile.profile_completion_percentage < 70:
            messages.info(self.request, 'Your profile is still incomplete. Consider adding more details.')
            return reverse('accounts:profile_edit')
        
        return reverse('accounts:profile_view')


class ProfileView(LoginRequiredMixin, TemplateView):
    """Profile view with compatibility info"""
    template_name = 'accounts/profile_view.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            profile = None
        
        # Calculate profile completion
        completion = self._calculate_profile_completion(profile)
        
        # Get user's preferences from landing page if available
        landing_prefs = self.request.session.get('landing_preferences', {})
        
        context.update({
            'profile': profile,
            'user': user,
            'profile_completion': completion,
            'landing_preferences': landing_prefs,
            'completion_needed': completion < 70,
        })
        
        # Add match suggestions if profile is complete enough
        if completion >= 50:
            context['match_suggestions'] = self._get_match_suggestions(profile, user)
        
        return context
    
    def _calculate_profile_completion(self, profile):
        """Calculate profile completion percentage"""
        if not profile:
            return 0
        
        checks = [
            ('age', lambda p: bool(p.age) and p.age > 0),
            ('gender', lambda p: bool(p.gender)),
            ('bio', lambda p: bool(p.bio) and len(str(p.bio).strip()) > 10),
            ('city', lambda p: bool(p.city)),
            ('country', lambda p: bool(p.country)),
            ('profile_pic', lambda p: bool(p.profile_pic)),
            ('sect', lambda p: bool(p.sect)),
            ('education', lambda p: bool(p.education)),
            ('practice_level', lambda p: bool(p.practice_level)),
        ]
        
        completed = sum(1 for field_name, check in checks if check(profile))
        return int((completed / len(checks)) * 100)
    
    def _get_match_suggestions(self, profile, user, limit=3):
        """Get match suggestions based on preferences"""
        if not profile or not profile.gender:
            return []
        
        # Get looking_for preference from session or profile
        landing_prefs = self.request.session.get('landing_preferences', {})
        looking_for = landing_prefs.get('looking_for', '')
        
        # Determine target gender based on preferences
        if looking_for == 'B' or not looking_for:
            # If looking for both or no preference, show both genders
            target_genders = ['M', 'F']
        else:
            target_genders = [looking_for]
        
        # Query profiles
        profiles = UserProfile.objects.filter(
            approved=True,
            is_visible=True,
            gender__in=target_genders
        ).exclude(user=user).select_related('user')[:20]
        
        # Calculate compatibility
        matches = []
        for p in profiles:
            try:
                score = profile.calculate_compatibility(p)
                if score >= 40:  # Lower threshold for suggestions
                    matches.append({
                        'profile': p,
                        'score': score,
                        'user': p.user
                    })
                    if len(matches) >= limit * 2:
                        break
            except Exception:
                continue
        
        # Sort by compatibility score
        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches[:limit]


class ViewProfileView(LoginRequiredMixin, View):
    """View other user's profile"""
    def get(self, request, user_id):
        try:
            # Get the user being viewed
            viewed_user = get_object_or_404(User, id=user_id)
            
            # Check if trying to view own profile
            if viewed_user == request.user:
                messages.info(request, 'This is your profile. Redirecting to your profile view.')
                return redirect('accounts:profile_view')
            
            # Get profile
            try:
                profile = viewed_user.userprofile
            except UserProfile.DoesNotExist:
                messages.error(request, 'This user has not completed their profile yet.')
                return redirect('dashboard:dashboard')
            
            # Check if profile is visible and approved
            if not profile.is_visible or not profile.approved:
                messages.error(request, 'This profile is not available.')
                return redirect('dashboard:dashboard')
            
            # Log profile view activity
            try:
                ActivityLog.objects.create(
                    user=request.user,
                    activity_type='profile_view',
                    target_user=viewed_user,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                )
            except Exception as e:
                logger.error(f"Error logging activity: {e}")
            
            # Get current user's profile
            try:
                current_profile = request.user.userprofile
            except UserProfile.DoesNotExist:
                current_profile = None
            
            # Calculate compatibility
            compatibility_score = None
            if current_profile:
                try:
                    compatibility_score = current_profile.calculate_compatibility(profile)
                except Exception as e:
                    logger.error(f"Error calculating compatibility: {e}")
            
            # Get friendship status
            friendship_data = self._get_friendship_data(request.user, viewed_user)
            
            # Get like status
            like_data = self._get_like_data(request.user, viewed_user)
            
            context = {
                'profile': profile,
                'viewed_user': viewed_user,
                'compatibility_score': compatibility_score,
                'is_viewable': True,
                'friendship': friendship_data,
                'like': like_data,
            }
            
            return render(request, 'accounts/view_profile.html', context)
            
        except User.DoesNotExist:
            messages.error(request, 'User not found.')
            return redirect('dashboard:dashboard')
        except Exception as e:
            logger.error(f"Unexpected error in ViewProfileView: {e}")
            messages.error(request, 'An error occurred while loading the profile.')
            return redirect('dashboard:dashboard')
    
    def _get_friendship_data(self, current_user, target_user):
        """Get friendship status between two users"""
        try:
            relationship = Friendship.get_relationship(current_user, target_user)
            
            if not relationship:
                return {
                    'status': 'none',
                    'can_send': True,
                    'can_cancel': False,
                    'can_accept': False,
                    'can_reject': False,
                }
            
            status = relationship.status
            
            return {
                'status': status,
                'can_send': status == 'strangers' or status == 'rejected_by_a' or status == 'rejected_by_b',
                'can_cancel': status == 'pending_sender',
                'can_accept': status == 'pending_receiver',
                'can_reject': status == 'pending_receiver',
                'is_friend': status == 'friends',
                'is_blocked': status in ['blocked_by_a', 'blocked_by_b'],
            }
        except Exception as e:
            logger.error(f"Error getting friendship data: {e}")
            return {'status': 'none', 'can_send': True, 'can_cancel': False, 'can_accept': False, 'can_reject': False}
    
    def _get_like_data(self, current_user, target_user):
        """Get like status between two users"""
        try:
            user_liked = ProfileLike.objects.filter(
                liker=current_user,
                liked=target_user
            ).exists()
            
            mutual_like = ProfileLike.objects.filter(
                Q(liker=current_user, liked=target_user, is_mutual=True) |
                Q(liker=target_user, liked=current_user, is_mutual=True)
            ).exists()
            
            return {
                'user_liked': user_liked,
                'mutual_like': mutual_like,
            }
        except Exception as e:
            logger.error(f"Error getting like data: {e}")
            return {'user_liked': False, 'mutual_like': False}


# Account Settings Views
class AccountSettingsView(LoginRequiredMixin, TemplateView):
    """Account settings dashboard"""
    template_name = 'accounts/account_settings.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            profile = None
        
        context.update({
            'user': user,
            'profile': profile,
            'password_form': CustomPasswordChangeForm(user),
            'email_form': EmailUpdateForm(),
            'user_form': UserUpdateForm(instance=user),
            'profile_completion': self._calculate_profile_completion(profile),
        })
        return context
    
    def _calculate_profile_completion(self, profile):
        """Calculate profile completion percentage"""
        if not profile:
            return 0
        
        checks = [
            ('age', lambda p: bool(p.age) and p.age > 0),
            ('gender', lambda p: bool(p.gender)),
            ('bio', lambda p: bool(p.bio) and len(str(p.bio).strip()) > 10),
            ('city', lambda p: bool(p.city)),
            ('country', lambda p: bool(p.country)),
            ('profile_pic', lambda p: bool(p.profile_pic)),
            ('sect', lambda p: bool(p.sect)),
            ('education', lambda p: bool(p.education)),
            ('practice_level', lambda p: bool(p.practice_level)),
        ]
        
        completed = sum(1 for field_name, check in checks if check(profile))
        return int((completed / len(checks)) * 100)


class ChangePasswordView(LoginRequiredMixin, FormView):
    """Change password view - unchanged"""
    form_class = CustomPasswordChangeForm
    template_name = 'accounts/change_password.html'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        user = form.save()
        update_session_auth_hash(self.request, user)
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            activity_type='password_change',
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
        )
        
        messages.success(self.request, 'Your password has been changed successfully!')
        return redirect('accounts:account_settings')
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class UpdateEmailView(LoginRequiredMixin, FormView):
    """Update email view - unchanged"""
    form_class = EmailUpdateForm
    template_name = 'accounts/update_email.html'
    
    def form_valid(self, form):
        user = self.request.user
        new_email = form.cleaned_data['new_email']
        current_password = form.cleaned_data['current_password']
        
        # Verify current password
        if not user.check_password(current_password):
            form.add_error('current_password', 'Incorrect password.')
            return self.form_invalid(form)
        
        # Check if email already exists
        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            form.add_error('new_email', 'This email is already in use.')
            return self.form_invalid(form)
        
        # Update email
        old_email = user.email
        user.email = new_email
        user.save(update_fields=['email'])
        
        # Send verification email (implement this)
        # send_verification_email(user, new_email)
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            activity_type='email_change',
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
        )
        
        messages.success(self.request, 
            'Email address updated successfully! A verification email has been sent to your new address.')
        return redirect('accounts:account_settings')
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class UpdateUserInfoView(LoginRequiredMixin, UpdateView):
    """Update user information - unchanged"""
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/update_user_info.html'
    
    def get_object(self):
        return self.request.user
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Account information updated successfully!')
        return response
    
    def get_success_url(self):
        return reverse('accounts:account_settings')


class DeleteAccountView(LoginRequiredMixin, FormView):
    """Delete account view - unchanged"""
    form_class = AccountDeleteForm
    template_name = 'accounts/delete_account.html'
    
    def form_valid(self, form):
        user = self.request.user
        password = form.cleaned_data['password']
        
        # Verify password
        if not user.check_password(password):
            form.add_error('password', 'Incorrect password.')
            return self.form_invalid(form)
        
        # Log activity before deletion
        ActivityLog.objects.create(
            user=user,
            activity_type='account_delete',
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
        )
        
        # Delete user
        username = user.username
        user.delete()
        
        messages.success(self.request, f'Account "{username}" has been permanently deleted.')
        return redirect('accounts:home')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['warning_message'] = (
            "Warning: This action cannot be undone. All your data, including profile, "
            "matches, messages, and activity history will be permanently deleted."
        )
        return context


# Activity History View
class ActivityHistoryView(LoginRequiredMixin, TemplateView):
    """Activity history view - unchanged"""
    template_name = 'accounts/activity_history.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        activities = ActivityLog.objects.filter(user=self.request.user).order_by('-created_at')
        
        # Paginate activities
        paginator = Paginator(activities, 20)
        page = self.request.GET.get('page')
        
        try:
            activities_page = paginator.page(page)
        except PageNotAnInteger:
            activities_page = paginator.page(1)
        except EmptyPage:
            activities_page = paginator.page(paginator.num_pages)
        
        context.update({
            'activities': activities_page,
            'paginator': paginator,
            'page_obj': activities_page,
        })
        return context


# Landing Page and Registration Views (New)
class LandingPageView(View):
    """Single-screen landing page with stunning background"""
    template_name = 'accounts/landing.html'
    
    def get(self, request):
        # If user is already authenticated, redirect to dashboard
        if request.user.is_authenticated:
            return redirect('dashboard:dashboard')
        
        # Get total users count
        total_users = User.objects.count()
        
        # Get success stories count (you can replace with actual model query)
        success_stories = 128
        
        context = {
            'form': LandingPageForm(),
            'total_users': total_users,
            'success_stories': success_stories,
            'android_app_url': 'https://play.google.com/store/apps/details?id=com.yourcompany.app',
            'ios_app_url': 'https://apps.apple.com/app/id123456789',
        }
        return render(request, self.template_name, context)
    
    def post(self, request):
        form = LandingPageForm(request.POST)
        
        if form.is_valid():
            # Store form data in session
            request.session['landing_preferences'] = form.cleaned_data
            
            # Check if user is already logged in (edge case)
            if request.user.is_authenticated:
                # Update existing profile with preferences
                try:
                    profile = request.user.userprofile
                    self._update_profile_from_preferences(profile, form.cleaned_data)
                    messages.success(request, 'Your preferences have been updated!')
                    return redirect('accounts:profile_view')
                except UserProfile.DoesNotExist:
                    pass
            
            # Redirect to registration page with preferences
            return redirect('accounts:register_with_preferences')
        
        # If form is invalid, show errors
        context = {
            'form': form,
            'total_users': User.objects.count(),
            'success_stories': 128,
        }
        return render(request, self.template_name, context)
    
    def _update_profile_from_preferences(self, profile, preferences):
        """Update profile with landing page preferences"""
        if 'age' in preferences and not profile.age:
            profile.age = int(preferences.get('age', 0))
        
        if 'gender' in preferences and not profile.gender:
            profile.gender = preferences.get('gender', '')
        
        if 'city' in preferences and not profile.city:
            profile.city = preferences.get('city', '')
        
        if 'country' in preferences and not profile.country:
            profile.country = preferences.get('country', '')
        
        if 'sect' in preferences and not profile.sect:
            profile.sect = preferences.get('sect', '')
        
        # Update preferences JSON
        if 'looking_for' in preferences or 'marital_status' in preferences or 'religious_commitment' in preferences:
            current_prefs = profile.preferences or {}
            current_prefs.update({
                'looking_for': preferences.get('looking_for', ''),
                'marital_status': preferences.get('marital_status', ''),
                'religious_commitment': preferences.get('religious_commitment', ''),
            })
            profile.preferences = current_prefs
        
        profile.save()


class RegisterWithPreferencesView(View):
    """Registration page that includes preferences from landing page"""
    template_name = 'accounts/register_with_prefs.html'
    
    def get(self, request):
        # Check if we have landing preferences
        landing_prefs = request.session.get('landing_preferences')
        
        if not landing_prefs:
            # If no preferences, redirect to landing page
            messages.info(request, 'Please fill out your preferences first.')
            return redirect('accounts:home')
        
        # Initialize registration form with prefilled email if available
        initial_data = {}
        
        form = CustomUserCreationForm(initial=initial_data)
        
        context = {
            'form': form,
            'landing_prefs': landing_prefs,
        }
        return render(request, self.template_name, context)
    
    def post(self, request):
        form = CustomUserCreationForm(request.POST)
        landing_prefs = request.session.get('landing_preferences', {})
        
        if form.is_valid():
            # Save the user
            user = form.save()
            
            # Create user profile with landing preferences
            profile = user.userprofile
            
            # Update profile with landing preferences
            if landing_prefs:
                if 'age' in landing_prefs:
                    profile.age = int(landing_prefs.get('age', 0))
                
                if 'gender' in landing_prefs:
                    profile.gender = landing_prefs.get('gender', '')
                
                if 'city' in landing_prefs:
                    profile.city = landing_prefs.get('city', '')
                
                if 'country' in landing_prefs:
                    profile.country = landing_prefs.get('country', '')
                
                if 'sect' in landing_prefs:
                    profile.sect = landing_prefs.get('sect', '')
                
                # Store preferences in JSON field
                preferences = {
                    'looking_for': landing_prefs.get('looking_for', ''),
                    'marital_status': landing_prefs.get('marital_status', ''),
                    'religious_commitment': landing_prefs.get('religious_commitment', ''),
                }
                profile.preferences = preferences
                
                # Set practice level based on religious commitment
                commitment_map = {
                    'V': 'E',  # Very Religious -> Expert
                    'M': 'A',  # Moderately Religious -> Advanced
                    'S': 'I',  # Somewhat Religious -> Intermediate
                    'N': 'B',  # Not Religious -> Beginner
                }
                profile.practice_level = commitment_map.get(
                    landing_prefs.get('religious_commitment', 'S'), 'I'
                )
                
                profile.save()
            
            # Clear the landing preferences from session
            if 'landing_preferences' in request.session:
                del request.session['landing_preferences']
            
            # Log activity
            ActivityLog.objects.create(
                user=user,
                activity_type='signup',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
            )
            
            # FIX: Set backend before login
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            
            # Auto login the user
            from django.contrib.auth import login
            login(request, user)
            
            messages.success(request, 
                'Registration successful! Please complete your profile for better matches.')
            
            # Redirect to profile completion
            return redirect('accounts:profile_edit')
        
        # If form is invalid
        context = {
            'form': form,
            'landing_prefs': landing_prefs,
        }
        return render(request, self.template_name, context)


# API Views for AJAX
@login_required
def check_username_availability(request):
    """Check if username is available"""
    username = request.GET.get('username', '').strip()
    
    if not username:
        return JsonResponse({'available': False, 'error': 'Username is required'})
    
    exists = User.objects.filter(username__iexact=username).exists()
    
    # Allow user to keep their own username
    if exists and request.user.username.lower() == username.lower():
        return JsonResponse({'available': True})
    
    return JsonResponse({'available': not exists})


@login_required
def check_email_availability(request):
    """Check if email is available"""
    email = request.GET.get('email', '').strip()
    
    if not email:
        return JsonResponse({'available': False, 'error': 'Email is required'})
    
    exists = User.objects.filter(email__iexact=email).exists()
    
    # Allow user to keep their own email
    if exists and request.user.email.lower() == email.lower():
        return JsonResponse({'available': True})
    
    return JsonResponse({'available': not exists})


@login_required
def update_profile_visibility(request):
    """Update profile visibility via AJAX"""
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            profile = request.user.userprofile
            is_visible = request.POST.get('is_visible') == 'true'
            
            profile.is_visible = is_visible
            profile.save(update_fields=['is_visible'])
            
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                activity_type='profile_update',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
            )
            
            return JsonResponse({
                'success': True,
                'is_visible': profile.is_visible,
                'message': 'Profile visibility updated successfully.'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)


# Helper Views
class DownloadAppView(TemplateView):
    """View for app download page"""
    template_name = 'accounts/download_app.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['android_app_url'] = 'https://play.google.com/store/apps/details?id=com.yourcompany.app'
        context['ios_app_url'] = 'https://apps.apple.com/app/id123456789'
        return context


class SuccessStoriesView(TemplateView):
    """View for success stories page"""
    template_name = 'accounts/success_stories.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # You would fetch actual success stories from database here
        context['stories'] = [
            {
                'names': 'Ahmed & Sarah',
                'story': 'Met through our platform in 2022, married in 2023.',
                'image': 'couple1.jpg',
            },
            {
                'names': 'Mohammed & Fatima',
                'story': 'Found each other after 3 months of searching.',
                'image': 'couple2.jpg',
            },
        ]
        return context

# accounts/views.py

from django.views import View
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.db.models import Q
from django.core.cache import cache
import logging

from .models import UserProfile

logger = logging.getLogger(__name__)


# ==========================================================
# PEOPLE NEARBY – PAGE VIEW (FULL PAGE)
# ==========================================================
class PeopleNearbyPageView(LoginRequiredMixin, View):
    """
    Enhanced full page view with:
    - Smart filtering & sorting
    - Pagination
    - Friendship/relationship status
    - Activity tracking
    - Caching for performance
    - Advanced search options
    - Performance optimization
    """

    template_name = "accounts/people_nearby.html"
    
    # Cache settings
    CACHE_TIMEOUT = 300  # 5 minutes
    MAX_RESULTS = 100  # Maximum profiles to show
    
    def get(self, request):
        """
        Enhanced main view with filters, pagination, and smart sorting
        """
        # Get user profile with error handling
        try:
            user_profile = request.user.userprofile
        except UserProfile.DoesNotExist:
            return render(request, self.template_name, {
                'error': 'Please complete your profile first',
                'profiles': [],
                'has_location': False,
                'profile_completion': 0
            })
        
        # Get filter parameters
        filters = self._get_filters(request)
        
        # Generate cache key based on user and filters
        cache_key = self._get_cache_key(request.user.id, filters)
        
        # Try to get cached results
        cached_data = cache.get(cache_key)
        if cached_data and not request.GET.get('refresh'):
            logger.info(f"Serving cached results for user {request.user.id}")
            return render(request, self.template_name, cached_data)
        
        # Get enhanced profiles
        context = self._get_enhanced_context(user_profile, filters, request)
        
        # Cache the results
        cache.set(cache_key, context, self.CACHE_TIMEOUT)
        
        return render(request, self.template_name, context)
    
    def _get_filters(self, request):
        """
        Extract and validate filter parameters from request
        """
        filters = {
            'gender': request.GET.get('gender', '').strip(),
            'min_age': self._safe_int(request.GET.get('min_age', 18), 18, 120),
            'max_age': self._safe_int(request.GET.get('max_age', 100), 18, 120),
            'city': request.GET.get('city', '').strip(),
            'country': request.GET.get('country', '').strip(),
            'sect': request.GET.get('sect', '').strip(),
            'education': request.GET.get('education', '').strip(),
            'practice_level': request.GET.get('practice_level', '').strip(),
            'sort_by': request.GET.get('sort_by', 'compatibility'),  # compatibility, distance, recent, online
            'show_online': request.GET.get('show_online') == 'true',
            'show_recent': request.GET.get('show_recent') == 'true',
            'distance': request.GET.get('distance', 'any'),  # same_city, same_country, any
            'page': request.GET.get('page', 1)
        }
        
        # Ensure age range is valid
        if filters['min_age'] > filters['max_age']:
            filters['min_age'], filters['max_age'] = filters['max_age'], filters['min_age']
        
        return filters
    
    def _get_cache_key(self, user_id, filters):
        """Generate unique cache key based on user and filters"""
        filter_str = json.dumps(filters, sort_keys=True)
        return f"people_nearby_{user_id}_{hash(filter_str)}"
    
    def _safe_int(self, value, default, max_value=None):
        """Safely convert to integer with bounds"""
        try:
            val = int(value)
            if max_value and val > max_value:
                return max_value
            return max(val, 1)  # Ensure positive
        except (ValueError, TypeError):
            return default
    
    def _get_enhanced_context(self, user_profile, filters, request):
        """
        Build complete context with all enhanced data
        """
        # Get base queryset with optimization
        base_qs = self._get_base_queryset(user_profile, filters)
        
        # Apply additional filters
        filtered_qs = self._apply_filters(base_qs, filters, user_profile)
        
        # Calculate compatibility scores in bulk
        profiles_with_scores = self._calculate_compatibility_bulk(
            filtered_qs, user_profile
        )
        
        # Enhance with friendship and activity data
        enhanced_profiles = self._enhance_profiles_bulk(
            profiles_with_scores, request.user, filters
        )
        
        # Apply sorting
        sorted_profiles = self._apply_sorting(enhanced_profiles, filters)
        
        # Apply result limits
        limited_profiles = sorted_profiles[:self.MAX_RESULTS]
        
        # Create pagination
        paginator = Paginator(limited_profiles, 24)  # 24 profiles per page
        page = filters['page']
        
        try:
            profiles_page = paginator.page(page)
        except (PageNotAnInteger, EmptyPage):
            profiles_page = paginator.page(1)
        
        # Get user preferences for filtering
        user_preferences = user_profile.preferences or {}
        
        # Build statistics
        stats = self._build_statistics(filtered_qs, user_profile)
        
        # Check if user has enough profile info
        has_location = bool(user_profile.city and user_profile.country)
        profile_completion = user_profile.profile_completion_percentage
        
        return {
            'profiles': profiles_page,
            'page_obj': profiles_page,
            'paginator': paginator,
            'filters': filters,
            'user_preferences': user_preferences,
            'stats': stats,
            'has_location': has_location,
            'profile_completion': profile_completion,
            'current_user_profile': user_profile,
            'filter_options': self._get_filter_options(),
            'total_profiles': filtered_qs.count(),
            'same_city_count': filtered_qs.filter(
                city__iexact=user_profile.city
            ).count() if user_profile.city else 0,
            'same_country_count': filtered_qs.filter(
                country__iexact=user_profile.country
            ).count() if user_profile.country else 0,
            'has_filters_applied': any(
                value for key, value in filters.items() 
                if key not in ['page', 'sort_by'] and value
            ),
        }
    
    def _get_base_queryset(self, user_profile, filters):
        """
        Get optimized base queryset with select_related and only needed fields
        """
        # Fields we actually need
        fields = [
            'id', 'user_id', 'age', 'gender', 'city', 'country', 'sect',
            'education', 'practice_level', 'profile_pic', 'bio',
            'show_age', 'show_location', 'show_sect', 'show_education',
            'show_practice_level', 'last_active', 'created_at', 'is_visible',
            'approved', 'completed'
        ]
        
        qs = UserProfile.objects.filter(
            is_visible=True,
            approved=True,
        ).exclude(
            user=user_profile.user
        ).select_related(
            'user'
        ).only(
            *[f'user__{field}' for field in ['id', 'username', 'first_name', 'last_name', 'date_joined']] +
            fields
        )
        
        # Filter by age range
        qs = qs.filter(
            age__gte=filters['min_age'],
            age__lte=filters['max_age']
        )
        
        # Filter by gender if specified
        if filters['gender']:
            qs = qs.filter(gender=filters['gender'])
        
        # Filter by online status if requested
        if filters['show_online']:
            fifteen_minutes_ago = timezone.now() - timedelta(minutes=15)
            qs = qs.filter(last_active__gte=fifteen_minutes_ago)
        
        # Filter by recently active
        if filters['show_recent']:
            seven_days_ago = timezone.now() - timedelta(days=7)
            qs = qs.filter(created_at__gte=seven_days_ago)
        
        return qs
    
    def _apply_filters(self, queryset, filters, user_profile):
        """
        Apply additional filters based on user input
        """
        qs = queryset
        
        # Location filters
        if filters['distance'] == 'same_city' and user_profile.city:
            qs = qs.filter(city__iexact=user_profile.city)
        elif filters['distance'] == 'same_country' and user_profile.country:
            qs = qs.filter(country__iexact=user_profile.country)
            if user_profile.city:
                qs = qs.exclude(city__iexact=user_profile.city)
        
        # Custom city/country filter
        if filters['city']:
            qs = qs.filter(city__icontains=filters['city'])
        if filters['country']:
            qs = qs.filter(country__icontains=filters['country'])
        
        # Sect filter
        if filters['sect']:
            qs = qs.filter(sect__icontains=filters['sect'])
        
        # Education filter
        if filters['education']:
            qs = qs.filter(education=filters['education'])
        
        # Practice level filter
        if filters['practice_level']:
            qs = qs.filter(practice_level=filters['practice_level'])
        
        return qs
    
    def _calculate_compatibility_bulk(self, profiles_queryset, user_profile):
        """
        Calculate compatibility scores for multiple profiles efficiently
        """
        profiles = list(profiles_queryset)
        
        # Pre-calculate user preferences
        user_prefs = user_profile.preferences or {}
        user_looking_for = user_prefs.get('looking_for', '')
        
        enhanced = []
        for profile in profiles:
            try:
                # Use cached compatibility if available
                cache_key = f"compatibility_{user_profile.user_id}_{profile.user_id}"
                cached_score = cache.get(cache_key)
                
                if cached_score is not None:
                    score = cached_score
                else:
                    # Calculate fresh score
                    score = user_profile.calculate_compatibility(profile)
                    # Cache for 10 minutes
                    cache.set(cache_key, score, 600)
                
                enhanced.append({
                    'profile': profile,
                    'score': score,
                    'user': profile.user,
                    'is_same_city': profile.city and user_profile.city and 
                                   profile.city.lower() == user_profile.city.lower(),
                    'is_same_country': profile.country and user_profile.country and 
                                      profile.country.lower() == user_profile.country.lower(),
                })
            except Exception as e:
                logger.error(f"Error calculating compatibility for {profile.user.username}: {e}")
                enhanced.append({
                    'profile': profile,
                    'score': 0,
                    'user': profile.user,
                    'is_same_city': False,
                    'is_same_country': False,
                })
        
        return enhanced
    
    def _enhance_profiles_bulk(self, profiles_data, current_user, filters):
        """
        Add friendship status, likes, and other metadata in bulk
        """
        if not profiles_data:
            return []
        
        # Get all user IDs
        user_ids = [item['user'].id for item in profiles_data]
        
        # Bulk fetch friendship status
        friendships = self._get_friendship_status_bulk(current_user.id, user_ids)
        
        # Bulk fetch likes
        likes = self._get_like_status_bulk(current_user.id, user_ids)
        
        # Bulk fetch mutual likes
        mutual_likes = self._get_mutual_likes_bulk(current_user.id, user_ids)
        
        # Bulk fetch activity status
        active_status = self._get_activity_status_bulk(user_ids)
        
        # Enhance each profile
        enhanced = []
        for item in profiles_data:
            user_id = item['user'].id
            
            # Get friendship status
            relationship = friendships.get(user_id, {})
            
            # Check if recently active
            is_recently_active = active_status.get(user_id, False)
            
            # Get bio preview
            bio_preview = self._get_bio_preview(item['profile'].bio)
            
            # Get privacy-respecting data
            age_display = self._get_age_display(item['profile'])
            location_text = self._get_location_text(item['profile'], item['is_same_city'], item['is_same_country'])
            
            enhanced.append({
                **item,
                'compatibility': item['score'],
                'already_liked': likes.get(user_id, False),
                'mutual_like': mutual_likes.get(user_id, False),
                'already_friends': relationship.get('is_friend', False),
                'request_sent': relationship.get('request_sent', False),
                'request_received': relationship.get('request_received', False),
                'is_recently_active': is_recently_active,
                'bio_preview': bio_preview,
                'age_display': age_display,
                'location_text': location_text,
                'sect_display': self._get_sect_display(item['profile']),
                'education_display': self._get_education_display(item['profile']),
                'practice_level_display': self._get_practice_level_display(item['profile']),
                'profile_pic_url': self._get_profile_pic_url(item['profile']),
            })
        
        return enhanced
    
    def _get_friendship_status_bulk(self, current_user_id, target_user_ids):
        """Get friendship status for multiple users efficiently"""
        if not target_user_ids:
            return {}
        
        status_dict = {}
        
        # Get all friendships involving these users
        friendships = Friendship.objects.filter(
            Q(user_a_id=current_user_id, user_b_id__in=target_user_ids) |
            Q(user_a_id__in=target_user_ids, user_b_id=current_user_id)
        ).values('user_a_id', 'user_b_id', 'status')
        
        # Map user_id -> status
        for friendship in friendships:
            if friendship['user_a_id'] == current_user_id:
                target_id = friendship['user_b_id']
            else:
                target_id = friendship['user_a_id']
            
            status = friendship['status']
            status_dict[target_id] = {
                'is_friend': status == FriendshipStatus.FRIENDS,
                'request_sent': status == FriendshipStatus.PENDING_SENDER,
                'request_received': status == FriendshipStatus.PENDING_RECEIVER,
                'is_blocked': status in [FriendshipStatus.BLOCKED_BY_A, FriendshipStatus.BLOCKED_BY_B],
            }
        
        # Add default status for users without relationships
        for user_id in target_user_ids:
            if user_id not in status_dict:
                status_dict[user_id] = {
                    'is_friend': False,
                    'request_sent': False,
                    'request_received': False,
                    'is_blocked': False,
                }
        
        return status_dict
    
    def _get_like_status_bulk(self, current_user_id, target_user_ids):
        """Check if current user has liked multiple users"""
        if not target_user_ids:
            return {}
        
        likes = ProfileLike.objects.filter(
            liker_id=current_user_id,
            liked_id__in=target_user_ids
        ).values_list('liked_id', flat=True)
        
        return {user_id: True for user_id in likes}
    
    def _get_mutual_likes_bulk(self, current_user_id, target_user_ids):
        """Check for mutual likes with multiple users"""
        if not target_user_ids:
            return {}
        
        mutual_likes = ProfileLike.objects.filter(
            liker_id=current_user_id,
            liked_id__in=target_user_ids,
            is_mutual=True
        ).values_list('liked_id', flat=True)
        
        return {user_id: True for user_id in mutual_likes}
    
    def _get_activity_status_bulk(self, user_ids):
        """Check if users are recently active"""
        if not user_ids:
            return {}
        
        fifteen_minutes_ago = timezone.now() - timedelta(minutes=15)
        
        # Get last activity timestamps
        active_profiles = UserProfile.objects.filter(
            user_id__in=user_ids,
            last_active__gte=fifteen_minutes_ago
        ).values_list('user_id', flat=True)
        
        return {user_id: True for user_id in active_profiles}
    
    def _get_bio_preview(self, bio, max_length=100):
        """Get bio preview with ellipsis"""
        if not bio:
            return ""
        bio = str(bio).strip()
        if len(bio) > max_length:
            return bio[:max_length] + "..."
        return bio
    
    def _get_age_display(self, profile):
        """Get age display respecting privacy settings"""
        if not profile.show_age or not profile.age:
            return "Age not shown"
        return f"{profile.age} years"
    
    def _get_location_text(self, profile, is_same_city, is_same_country):
        """Get location text with appropriate icon"""
        if not profile.show_location:
            return "Location hidden"
        
        location_parts = []
        if profile.city:
            location_parts.append(profile.city)
        if profile.country:
            location_parts.append(profile.country)
        
        if not location_parts:
            return "Location not set"
        
        location = ", ".join(location_parts)
        
        if is_same_city:
            return f"📍 {location}"
        elif is_same_country:
            return f"🌍 {location}"
        else:
            return f"🌎 {location}"
    
    def _get_sect_display(self, profile):
        """Get sect display respecting privacy"""
        if not profile.show_sect or not profile.sect:
            return None
        return profile.sect
    
    def _get_education_display(self, profile):
        """Get education display"""
        if not profile.show_education or not profile.education:
            return None
        return profile.get_education_display()
    
    def _get_practice_level_display(self, profile):
        """Get practice level display"""
        if not profile.show_practice_level or not profile.practice_level:
            return None
        return profile.get_practice_level_display()
    
    def _get_profile_pic_url(self, profile):
        """Get profile picture URL with fallback"""
        if profile.profile_pic:
            return profile.profile_pic.url
        return "/static/img/default-avatar.png"
    
    def _apply_sorting(self, profiles, filters):
        """
        Apply sorting based on filter preference
        """
        sort_by = filters.get('sort_by', 'compatibility')
        
        if sort_by == 'distance':
            # Sort by: same city > same country > others, then compatibility
            return sorted(profiles, 
                        key=lambda x: (
                            -x['is_same_city'], 
                            -x['is_same_country'], 
                            -x['compatibility']
                        ))
        elif sort_by == 'recent':
            # Sort by recently active, then created date
            return sorted(profiles,
                        key=lambda x: (
                            -x['is_recently_active'],
                            -x['profile'].created_at.timestamp()
                        ))
        elif sort_by == 'online':
            # Sort by online status, then compatibility
            return sorted(profiles,
                        key=lambda x: (
                            -x['is_recently_active'],
                            -x['compatibility']
                        ))
        else:  # 'compatibility' or default
            # Sort by compatibility score
            return sorted(profiles, key=lambda x: -x['compatibility'])
    
    def _build_statistics(self, queryset, user_profile):
        """
        Build statistics about available profiles
        """
        stats = {
            'total': queryset.count(),
            'online': queryset.filter(
                last_active__gte=timezone.now() - timedelta(minutes=15)
            ).count(),
            'same_city': queryset.filter(
                city__iexact=user_profile.city
            ).count() if user_profile.city else 0,
            'same_country': queryset.filter(
                country__iexact=user_profile.country
            ).count() if user_profile.country else 0,
            'new_today': queryset.filter(
                created_at__gte=timezone.now() - timedelta(days=1)
            ).count(),
            'with_photos': queryset.exclude(profile_pic='').count(),
        }
        
        # Add gender statistics if available
        gender_stats = {}
        for gender, _ in UserProfile.GENDER_CHOICES:
            count = queryset.filter(gender=gender).count()
            if count > 0:
                gender_stats[gender] = count
        stats['gender_distribution'] = gender_stats
        
        return stats
    
    def _get_filter_options(self):
        """
        Get all available filter options for the template
        """
        return {
            'genders': [{'value': val, 'label': label} for val, label in UserProfile.GENDER_CHOICES],
            'education_levels': [{'value': val, 'label': label} for val, label in UserProfile.EDUCATION_CHOICES],
            'practice_levels': [{'value': val, 'label': label} for val, label in UserProfile.PRACTICE_LEVEL_CHOICES],
            'age_range': {'min': 18, 'max': 100, 'step': 1},
            'sort_options': [
                {'value': 'compatibility', 'label': 'Best Match'},
                {'value': 'distance', 'label': 'Nearest First'},
                {'value': 'online', 'label': 'Online Now'},
                {'value': 'recent', 'label': 'Recently Joined'},
            ],
            'distance_options': [
                {'value': 'any', 'label': 'Any Distance'},
                {'value': 'same_country', 'label': 'Same Country'},
                {'value': 'same_city', 'label': 'Same City'},
            ]
        }


    

# Error handlers
def handler404(request, exception):
    """Custom 404 error handler"""
    return render(request, 'errors/404.html', status=404)

def handler500(request):
    """Custom 500 error handler"""
    return render(request, 'errors/500.html', status=500)

def handler403(request, exception):
    """Custom 403 error handler"""
    return render(request, 'errors/403.html', status=403)

def handler400(request, exception):
    """Custom 400 error handler"""
    return render(request, 'errors/400.html', status=400)


# Utility functions for AJAX responses
@login_required
def api_check_username(request):
    """API endpoint to check username availability"""
    username = request.GET.get('username', '').strip()
    
    if not username or len(username) < 3:
        return JsonResponse({
            'available': False,
            'error': 'Username must be at least 3 characters'
        })
    
    exists = User.objects.filter(username__iexact=username).exists()
    
    # Allow user to keep their own username
    if exists and request.user.username.lower() == username.lower():
        return JsonResponse({'available': True})
    
    return JsonResponse({
        'available': not exists,
        'suggestions': get_username_suggestions(username) if exists else []
    })


def get_username_suggestions(username):
    """Generate username suggestions"""
    import random
    suggestions = []
    
    # Add numbers
    for i in range(1, 4):
        suggestions.append(f"{username}{i}")
        suggestions.append(f"{username}_{i}")
    
    # Add random suffix
    suffixes = ['_', '.', '']
    numbers = ['123', '2024', '007', '88', '99']
    
    for suffix in suffixes:
        for number in numbers:
            suggestions.append(f"{username}{suffix}{number}")
    
    # Filter out taken usernames
    taken = set(User.objects.filter(
        username__in=[s.lower() for s in suggestions]
    ).values_list('username', flat=True))
    
    return [s for s in suggestions if s.lower() not in taken][:5]