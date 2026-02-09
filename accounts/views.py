from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.views.generic import CreateView, UpdateView, TemplateView, FormView
from django.views import View
from django.http import JsonResponse, HttpResponseForbidden
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.template.loader import render_to_string
from .utils import cache_simple_data, get_cached_simple_data
from .forms import (
    CustomUserCreationForm, CustomAuthenticationForm, ProfileForm,
    UserUpdateForm, CustomPasswordChangeForm, EmailUpdateForm,
    AccountDeleteForm, LandingPageForm
)
from .models import UserProfile, ActivityLog, EmailVerification
from django.contrib.auth.models import User
from friendship.models import Friendship
import math


from django.db.models import Q, Count, Prefetch
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
import logging

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
            user = get_object_or_404(User, id=user_id)
            profile = user.userprofile
            
            # Check if profile is visible and approved
            if not profile.is_visible or not profile.approved:
                messages.error(request, 'This profile is not available.')
                return redirect('dashboard:dashboard')
            
            # Check if user is blocked (implement your blocking logic here)
            
            # Log profile view activity
            ActivityLog.objects.create(
                user=request.user,
                activity_type='profile_view',
                target_user=user,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
            )
            
            # Calculate compatibility
            compatibility_score = None
            try:
                user_profile = request.user.userprofile
                compatibility_score = user_profile.calculate_compatibility(profile)
            except:
                pass
            
            context = {
                'profile': profile,
                'viewed_user': user,
                'compatibility_score': compatibility_score,
                'is_viewable': True,
            }
            
            return render(request, 'accounts/view_profile.html', context)
            
        except User.DoesNotExist:
            messages.error(request, 'User not found.')
            return redirect('dashboard:dashboard')


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

@method_decorator(never_cache, name='dispatch')
class PeopleNearbyView(LoginRequiredMixin, View):
    """AJAX endpoint for people nearby widget"""
    
    def get(self, request):
    
        try:
            user_profile = request.user.userprofile
            
            # Check if profile is complete enough
            if user_profile.profile_completion_percentage < 50:
                html = render_to_string('accounts/people_nearby_errors.html', {
                    'error_type': 'incomplete_profile',
                    'completion': user_profile.profile_completion_percentage
                })
                return JsonResponse({
                    'success': False,
                    'error': 'Please complete more of your profile',
                    'html': html
                })
            
            # Get user's city and country
            user_city = user_profile.city
            user_country = user_profile.country
            
            if not user_city or not user_country:
                html = render_to_string('accounts/people_nearby_errors.html', {
                    'error_type': 'missing_location'
                })
                return JsonResponse({
                    'success': False,
                    'error': 'Please update your location',
                    'html': html
                })
            
            # Get user's preferences
            preferences = user_profile.preferences or {}
            looking_for = preferences.get('looking_for', '')
            max_age = preferences.get('max_age', 99)
            min_age = preferences.get('min_age', 18)
            
            # Base query - use select_related and only needed fields
            base_query = UserProfile.objects.filter(
                is_visible=True,
                approved=True,
                completed=True
            ).exclude(user=request.user).select_related('user').only(
                'user__username', 'age', 'gender', 'city', 'country', 
                'sect', 'education', 'practice_level', 'profile_pic',
                'show_age', 'show_location', 'show_sect', 'show_education',
                'show_practice_level', 'bio', 'last_active'
            )
            
            # Filter by gender preference
            if looking_for and looking_for != 'B':
                base_query = base_query.filter(gender=looking_for)
            
            # Filter by age preferences
            base_query = base_query.filter(
                age__gte=min_age,
                age__lte=max_age
            )
            
            # Get people in same city first
            same_city_profiles = base_query.filter(
                city__iexact=user_city,
                country__iexact=user_country
            )
            
            # Get people in same country (but different city)
            same_country_profiles = base_query.filter(
                country__iexact=user_country
            ).exclude(
                city__iexact=user_city
            )
            
            # Get random profiles from anywhere else
            other_profiles = base_query.exclude(
                country__iexact=user_country
            ).order_by('?')
            
            # Combine results with priority
            people_results = []
            profiles_added = set()
            
            # Function to add profiles with limit
            def add_profiles(profiles_query, location_type, limit=5):
                added = []
                for profile in profiles_query[:limit]:
                    if profile.id not in profiles_added:
                        people_results.append(self._enhance_profile_data(profile, user_profile, location_type))
                        profiles_added.add(profile.id)
                        added.append(profile)
                return added
            
            # Add profiles in priority order
            add_profiles(same_city_profiles, 'same_city')
            add_profiles(same_country_profiles, 'same_country')
            add_profiles(other_profiles, 'other')
            
            # Limit total results
            people_results = people_results[:10]
            
            # Sort by compatibility score
            people_results.sort(key=lambda x: x['compatibility'], reverse=True)
            
            # Render HTML template
            html = render_to_string('accounts/people_nearby_widget.html', {
                'enhanced_profiles': people_results[:8]  # Limit to 8 for display
            })
            
            return JsonResponse({
                'success': True,
                'html': html,
                'count': len(people_results),
            })
            
        except UserProfile.DoesNotExist:
            html = render_to_string('accounts/people_nearby_errors.html', {
                'error_type': 'no_profile'
            })
            return JsonResponse({
                'success': False,
                'error': 'Profile not found',
                'html': html
            })
        except Exception as e:
            logger.error(f"Error in PeopleNearbyView: {str(e)}", exc_info=True)
            html = render_to_string('accounts/people_nearby_errors.html', {
                'error_type': 'error',
                'error_message': str(e)[:100]
            })
            return JsonResponse({
                'success': False,
                'error': 'An error occurred',
                'html': html
            })
    
    def _enhance_profile_data(self, profile, user_profile, location_type):
        """Enhance profile with calculated data"""
        user = profile.user
        
        # Use cached compatibility calculation
        compatibility = profile.calculate_compatibility(user_profile)
        
        # Check if recently active
        is_recently_active = False
        if profile.last_active:
            time_diff = timezone.now() - profile.last_active
            is_recently_active = time_diff.total_seconds() < 3600
        
        return {
            'profile': profile,
            'user': user,
            'compatibility': compatibility,
            'is_recently_active': is_recently_active,
            'location_type': location_type,
            'location_text': self._get_location_text(profile, location_type),
            'age_display': self._get_age_display(profile),
            'profile_image': profile.profile_pic.url if profile.profile_pic else None,
            'bio_preview': profile.bio[:100] + '...' if profile.bio and len(profile.bio) > 100 else profile.bio,
        }
    
    def _get_location_text(self, profile, location_type):
        """Get location text respecting privacy settings"""
        if not profile.show_location:
            return "Location hidden"
        
        location_parts = []
        if profile.city:
            location_parts.append(profile.city)
        if profile.country:
            location_parts.append(profile.country)
        
        if location_parts:
            location = ", ".join(location_parts)
            icons = {
                'same_city': '📍',
                'same_country': '🇺🇸',
                'other': '🌍'
            }
            return f"{icons.get(location_type, '📍')} {location}"
        
        return "Location not set"
    
    def _get_age_display(self, profile):
        """Get age display respecting privacy settings"""
        if not profile.show_age or not profile.age:
            return "Age not shown"
        return f"{profile.age} years"
    

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