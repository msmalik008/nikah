from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.cache import cache
import uuid
import logging

logger = logging.getLogger(__name__)


class UserProfile(models.Model):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('N', 'Prefer not to say'),
    ]
    
    EDUCATION_CHOICES = [
        ('HS', 'High School'),
        ('AD', 'Associate Degree'),
        ('BD', "Bachelor's Degree"),
        ('MD', "Master's Degree"),
        ('PHD', 'Doctorate'),
        ('OT', 'Other'),
    ]
    
    PRACTICE_LEVEL_CHOICES = [
        ('B', 'Beginner'),
        ('I', 'Intermediate'),
        ('A', 'Advanced'),
        ('E', 'Expert'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='userprofile')
    age = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, db_index=True)
    bio = models.TextField(max_length=500, blank=True)
    profile_pic = models.ImageField(upload_to='profile_pics/%Y/%m/', null=True, blank=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)
    sect = models.CharField(max_length=100, blank=True, help_text="Religious or philosophical sect")
    education = models.CharField(max_length=10, choices=EDUCATION_CHOICES, blank=True)
    practice_level = models.CharField(max_length=1, choices=PRACTICE_LEVEL_CHOICES, blank=True)
    
    preferences = models.JSONField(default=dict, blank=True)
    
    # Profile visibility and status
    is_visible = models.BooleanField(default=True, db_index=True)
    approved = models.BooleanField(default=False, db_index=True)
    completed = models.BooleanField(default=False, db_index=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_active = models.DateTimeField(default=timezone.now, db_index=True)
    last_profile_update = models.DateTimeField(null=True, blank=True)
    
    # Privacy settings
    show_age = models.BooleanField(default=True)
    show_location = models.BooleanField(default=True)
    show_sect = models.BooleanField(default=True)
    show_education = models.BooleanField(default=True)
    show_practice_level = models.BooleanField(default=True)
    
    # Verification
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    
    # Profile source tracking
    source = models.CharField(
        max_length=50, 
        default='landing_page', 
        choices=[('landing_page', 'Landing Page'), ('direct_signup', 'Direct Signup')]
    )
    
    # Online status
    is_online = models.BooleanField(default=False, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
        indexes = [
            models.Index(fields=['is_visible', 'approved', 'completed']),
            models.Index(fields=['gender', 'age']),
            models.Index(fields=['city', 'country']),
            models.Index(fields=['last_active']),
        ]
    
    def __str__(self):
        return f"{self.user.username}'s Profile"
    
    def save(self, *args, **kwargs):
        # Update last_profile_update when certain fields are modified
        if self.pk:
            try:
                old_instance = UserProfile.objects.only(
                    'bio', 'age', 'gender', 'city', 'country', 'sect', 
                    'education', 'practice_level', 'profile_pic'
                ).get(pk=self.pk)
                
                fields_to_check = ['bio', 'age', 'gender', 'city', 'country', 'sect', 
                                  'education', 'practice_level', 'profile_pic']
                
                for field in fields_to_check:
                    if getattr(old_instance, field) != getattr(self, field):
                        self.last_profile_update = timezone.now()
                        break
            except UserProfile.DoesNotExist:
                pass
        
        # Mark profile as completed if all required fields are filled
        self.completed = self._is_profile_complete()
        
        # Clear cache
        cache_key = f"user_profile_{self.user_id}"
        cache.delete(cache_key)
        
        super().save(*args, **kwargs)
    
    def _is_profile_complete(self):
        """Check if profile is complete"""
        required_fields = [
            ('age', lambda: bool(self.age) and self.age > 0),
            ('gender', lambda: bool(self.gender)),
            ('city', lambda: bool(self.city)),
            ('country', lambda: bool(self.country)),
            ('sect', lambda: bool(self.sect)),
            ('education', lambda: bool(self.education)),
            ('practice_level', lambda: bool(self.practice_level)),
        ]
        
        # All required fields must have values
        if not all(check() for _, check in required_fields):
            return False
        
        # Also require bio and profile pic for full completion
        if not self.bio or len(self.bio.strip()) < 20 or not self.profile_pic:
            return False
        
        return True
    
    @property
    def profile_completion_percentage(self):
        """Calculate profile completion percentage with caching"""
        cache_key = f"profile_completion_{self.user_id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        check_fields = [
            ('age', lambda: bool(self.age) and self.age > 0),
            ('gender', lambda: bool(self.gender)),
            ('bio', lambda: bool(self.bio) and len(self.bio.strip()) > 20),
            ('profile_pic', lambda: bool(self.profile_pic)),
            ('city', lambda: bool(self.city)),
            ('country', lambda: bool(self.country)),
            ('sect', lambda: bool(self.sect)),
            ('education', lambda: bool(self.education)),
            ('practice_level', lambda: bool(self.practice_level)),
        ]
        
        completed = sum(1 for _, check in check_fields if check())
        percentage = int((completed / len(check_fields)) * 100)
        
        # Cache for 5 minutes
        cache.set(cache_key, percentage, 300)
        
        return percentage
    
    def get_profile_completion_percentage(self):
        """Backward compatibility method"""
        return self.profile_completion_percentage
    
    def get_preference(self, key, default=None):
        """Helper method to get preference from JSON field"""
        return self.preferences.get(key, default)
    
    def set_preference(self, key, value):
        """Helper method to set preference in JSON field"""
        if not self.preferences:
            self.preferences = {}
        self.preferences[key] = value
        self.save(update_fields=['preferences'])
    
    def calculate_compatibility(self, other_profile):
        """Calculate compatibility score with another profile"""
        cache_key = f"compatibility_{self.user_id}_{other_profile.user_id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        score = 0
        total_weight = 0
        
        # Get preferences for looking_for
        looking_for = self.get_preference('looking_for', '')
        
        # Check gender preference compatibility (weight: 25%)
        if looking_for and other_profile.gender:
            if looking_for == 'B' or looking_for == other_profile.gender:
                score += 25
            else:
                # If gender preference doesn't match, low compatibility
                result = 20
                cache.set(cache_key, result, 300)  # Cache for 5 minutes
                return result
        total_weight += 25
        
        # Age compatibility (weight: 20%)
        if self.age and other_profile.age:
            age_diff = abs(self.age - other_profile.age)
            if age_diff <= 5:
                score += 20
            elif age_diff <= 10:
                score += 15
            elif age_diff <= 15:
                score += 10
            else:
                score += 5
            total_weight += 20
        
        # Education compatibility (weight: 15%)
        if self.education and other_profile.education:
            if self.education == other_profile.education:
                score += 15
            else:
                # Add partial score based on education level
                education_weights = {'HS': 1, 'AD': 2, 'BD': 3, 'MD': 4, 'PHD': 5, 'OT': 3}
                self_weight = education_weights.get(self.education, 3)
                other_weight = education_weights.get(other_profile.education, 3)
                
                diff = abs(self_weight - other_weight)
                if diff == 0:
                    score += 15
                elif diff == 1:
                    score += 12
                elif diff == 2:
                    score += 8
                else:
                    score += 3
            total_weight += 15
        
        # Practice level compatibility (weight: 15%)
        if self.practice_level and other_profile.practice_level:
            if self.practice_level == other_profile.practice_level:
                score += 15
            else:
                level_values = {'B': 1, 'I': 2, 'A': 3, 'E': 4}
                try:
                    diff = abs(level_values[self.practice_level] - level_values[other_profile.practice_level])
                    if diff <= 1:
                        score += 12
                    elif diff <= 2:
                        score += 8
                    else:
                        score += 3
                except KeyError:
                    score += 5
            total_weight += 15
        
        # Sect compatibility (weight: 15%)
        if self.sect and other_profile.sect:
            if self.sect.lower() == other_profile.sect.lower():
                score += 15
            else:
                # Check if sects are similar
                if self._are_sects_similar(self.sect, other_profile.sect):
                    score += 12
                else:
                    score += 3
            total_weight += 15
        
        # Location compatibility (weight: 10%)
        if self.city and other_profile.city and self.country and other_profile.country:
            if self.city.lower() == other_profile.city.lower() and self.country.lower() == other_profile.country.lower():
                score += 10
            elif self.country.lower() == other_profile.country.lower():
                score += 8
            else:
                score += 3
            total_weight += 10
        
        # Calculate final score
        if total_weight > 0:
            final_score = (score / total_weight) * 100
        else:
            final_score = 0
        
        final_score = round(final_score, 1)
        
        # Cache result
        cache.set(cache_key, final_score, 300)  # 5 minutes
        
        return final_score
    
    def _are_sects_similar(self, sect1, sect2):
        """Check if two sects are similar"""
        similar_sects_map = {
            'sunni': ['sunni', 'hanafi', 'maliki', 'shafi', 'hanbali'],
            'shia': ['shia', 'jafari', 'ismaili', 'zaidi'],
            'sufi': ['sufi', 'naqshbandi', 'qadiri', 'chishti'],
            'christian': ['christian', 'catholic', 'protestant', 'orthodox'],
            'hindu': ['hindu', 'vaishnavism', 'shaivism', 'shaktism', 'smartism'],
            'buddhist': ['buddhist', 'theravada', 'mahayana', 'vajrayana'],
            'jewish': ['jewish', 'orthodox', 'conservative', 'reform'],
        }
        
        sect1_lower = sect1.lower()
        sect2_lower = sect2.lower()
        
        for group, sects in similar_sects_map.items():
            if sect1_lower in sects and sect2_lower in sects:
                return True
        
        return False
    
    def get_public_profile_data(self):
        """Get profile data respecting privacy settings with caching"""
        cache_key = f"public_profile_{self.user_id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        data = {
            'username': self.user.username,
            'bio': self.bio,
            'profile_pic': self.profile_pic.url if self.profile_pic else None,
        }
        
        # Add fields based on privacy settings
        if self.show_age and self.age:
            data['age'] = self.age
        
        if self.show_location:
            if self.city:
                data['city'] = self.city
            if self.country:
                data['country'] = self.country
        
        if self.show_sect and self.sect:
            data['sect'] = self.sect
        
        if self.show_education and self.education:
            data['education'] = self.get_education_display()
        
        if self.show_practice_level and self.practice_level:
            data['practice_level'] = self.get_practice_level_display()
        
        # Cache for 1 hour
        cache.set(cache_key, data, 3600)
        
        return data


class ActivityLog(models.Model):
    ACTIVITY_CHOICES = [
        ('signup', 'User Signup'),
        ('login', 'User Login'),
        ('logout', 'User Logout'),
        ('profile_view', 'Profile View'),
        ('profile_update', 'Profile Updated'),
        ('profile_approved', 'Profile Approved'),
        ('profile_unapproved', 'Profile Unapproved'),
        ('like_sent', 'Like Sent'),
        ('like_received', 'Like Received'),
        ('match', 'New Match'),
        ('message_sent', 'Message Sent'),
        ('friend_request', 'Friend Request'),
        ('friend_added', 'Friend Added'),
        ('password_change', 'Password Changed'),
        ('email_change', 'Email Changed'),
        ('account_delete', 'Account Deleted'),
        ('preferences_saved', 'Preferences Saved'),
        ('landing_page_submit', 'Landing Page Submitted'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activity_logs', db_index=True)
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_CHOICES, db_index=True)
    target_user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='logged_activities_targeting'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    additional_info = models.JSONField(default=dict, blank=True, null=True)  # Allow null
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'
        indexes = [
            models.Index(fields=['user', 'activity_type', 'created_at']),
            models.Index(fields=['activity_type', 'created_at']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.get_activity_type_display()} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"
    
    @classmethod
    def log_activity(cls, user, activity_type, **kwargs):
        """Helper method to log activities"""
        additional_info = kwargs.get('additional_info', {})
        
        # Ensure additional_info is JSON serializable
        if additional_info and not isinstance(additional_info, (dict, list)):
            additional_info = {'text': str(additional_info)}
        
        return cls.objects.create(
            user=user,
            activity_type=activity_type,
            ip_address=kwargs.get('ip_address'),
            user_agent=kwargs.get('user_agent', '')[:500],
            target_user=kwargs.get('target_user'),
            additional_info=additional_info,
        )

class EmailVerification(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    
    class Meta:
        verbose_name = 'Email Verification'
        verbose_name_plural = 'Email Verifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_verified', 'created_at']),
        ]
    
    def is_expired(self):
        """Check if token is expired (24 hours)"""
        return (timezone.now() - self.created_at).total_seconds() >= 86400  # 24 hours in seconds
    
    def verify(self):
        """Mark email as verified"""
        self.is_verified = True
        self.verified_at = timezone.now()
        self.save(update_fields=['is_verified', 'verified_at'])
        
        # Update user profile
        try:
            profile = self.user.userprofile
            profile.email_verified = True
            profile.save(update_fields=['email_verified'])
        except UserProfile.DoesNotExist:
            pass
    
    def __str__(self):
        return f"Email verification for {self.user.email} - {'Verified' if self.is_verified else 'Pending'}"


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    used = models.BooleanField(default=False, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Password Reset Token'
        verbose_name_plural = 'Password Reset Tokens'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['used', 'created_at']),
        ]
    
    def is_expired(self):
        """Check if token is expired (2 hours)"""
        return (timezone.now() - self.created_at).total_seconds() > 7200  # 2 hours in seconds
    
    def mark_used(self):
        """Mark token as used"""
        self.used = True
        self.used_at = timezone.now()
        self.save(update_fields=['used', 'used_at'])
    
    def __str__(self):
        status = "Used" if self.used else "Active"
        expired = " (Expired)" if self.is_expired() and not self.used else ""
        return f"Password reset for {self.user.username} - {status}{expired}"


class LandingPageSubmission(models.Model):
    """Track landing page submissions for analytics"""
    session_key = models.CharField(max_length=100, unique=True, db_index=True)
    preferences = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    converted_to_user = models.BooleanField(default=False, db_index=True)
    converted_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Landing Page Submission'
        verbose_name_plural = 'Landing Page Submissions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['converted_to_user', 'created_at']),
        ]
    
    def __str__(self):
        return f"Submission {self.session_key} - {'Converted' if self.converted_to_user else 'Pending'}"
    
    def mark_converted(self, user):
        """Mark submission as converted to user"""
        self.converted_to_user = True
        self.converted_user = user
        self.converted_at = timezone.now()
        self.save()


