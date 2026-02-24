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
    
    SECT_CHOICES = [
        ('sunni_barelvi', 'Sunni / Barelvi'),
        ('deobandi', 'Deobandi'),
        ('ehl_e_hadith', 'Ehl-e-Hadith / Wahabi'),
        ('shia', 'Shia'),
        ('other', 'Other'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='userprofile')
    age = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, db_index=True)
    bio = models.TextField(max_length=500, blank=True)
    profile_pic = models.ImageField(upload_to='profile_pics/%Y/%m/', null=True, blank=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)
    sect = models.CharField(max_length=50, choices=SECT_CHOICES, blank=True, help_text="Islamic sect")
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
        """
        Calculate compatibility score with another profile
        Updated for Muslim-focused app in Pakistan
        """
        cache_key = f"compatibility_{self.user_id}_{other_profile.user_id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        score = 0
        total_weight = 0
        
        # ==========================================
        # 1. GENDER (Always opposite) - 0 points but required
        # ==========================================
        # Always show opposite gender
        if self.gender == other_profile.gender:
            # Same gender - not a match at all
            result = 0
            cache.set(cache_key, result, 300)
            return result
        
        # No points for gender, just a requirement
        
        # ==========================================
        # 2. SECT COMPATIBILITY (30% weight) - Most important
        # ==========================================
        if self.sect and other_profile.sect:
            sect_score = self._are_sects_similar(self.sect, other_profile.sect)
            score += sect_score * 30  # 30% weight
            total_weight += 30
        
        # ==========================================
        # 3. LOCATION COMPATIBILITY (25% weight)
        # ==========================================
        if self.city and other_profile.city and self.country and other_profile.country:
            location_score = self._calculate_location_compatibility(other_profile)
            score += location_score * 25  # 25% weight
            total_weight += 25
        
        # ==========================================
        # 4. AGE COMPATIBILITY (20% weight)
        # ==========================================
        if self.age and other_profile.age:
            age_score = self._calculate_age_compatibility(other_profile.age)
            score += age_score * 20  # 20% weight
            total_weight += 20
        
        # ==========================================
        # 5. PRACTICE LEVEL (15% weight)
        # ==========================================
        if self.practice_level and other_profile.practice_level:
            practice_score = self._calculate_practice_compatibility(other_profile.practice_level)
            score += practice_score * 15  # 15% weight
            total_weight += 15
        
        # ==========================================
        # 6. EDUCATION (10% weight)
        # ==========================================
        if self.education and other_profile.education:
            education_score = self._calculate_education_compatibility(other_profile.education)
            score += education_score * 10  # 10% weight
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
        """
        Calculate compatibility between Islamic sects
        Returns score between 0 and 1
        """
        sect1_lower = sect1.lower().strip()
        sect2_lower = sect2.lower().strip()
        
        # Define sect groups with similarity levels
        SECT_GROUPS = {
            'sunni': {
                'keywords': ['sunni', 'ahle sunnat', 'barelvi', 'hanafi'],
                'compatible': ['deobandi'],  # Sunni groups are compatible
                'incompatible': ['shia', 'ehl-e-hadith', 'wahabi']
            },
            'barelvi': {
                'keywords': ['barelvi', 'ahle sunnat', 'sunni'],
                'compatible': ['deobandi', 'sunni'],
                'incompatible': ['shia', 'ehl-e-hadith', 'wahabi']
            },
            'deobandi': {
                'keywords': ['deobandi', 'hanafi'],
                'compatible': ['barelvi', 'sunni'],
                'incompatible': ['shia', 'ehl-e-hadith', 'wahabi']
            },
            'ehl-e-hadith': {
                'keywords': ['ehl-e-hadith', 'ahl e hadith', 'wahabi', 'salafi'],
                'compatible': [],  # Usually only compatible with themselves
                'incompatible': ['shia', 'barelvi', 'deobandi']
            },
            'shia': {
                'keywords': ['shia', 'ithna ashari', 'jafari'],
                'compatible': [],  # Usually only compatible with themselves
                'incompatible': ['sunni', 'barelvi', 'deobandi', 'ehl-e-hadith', 'wahabi']
            }
        }
        
        # Check if exact match
        if sect1_lower == sect2_lower:
            return 1.0
        
        # Check if in same group
        for group, data in SECT_GROUPS.items():
            sect1_in_group = any(keyword in sect1_lower for keyword in data['keywords'])
            sect2_in_group = any(keyword in sect2_lower for keyword in data['keywords'])
            
            if sect1_in_group and sect2_in_group:
                # Both in same group - good compatibility
                return 0.9
            
            # Check compatibility between groups
            if sect1_in_group:
                for compatible in data['compatible']:
                    if compatible in sect2_lower:
                        return 0.8
                
                for incompatible in data['incompatible']:
                    if incompatible in sect2_lower:
                        return 0.2
        
        # Different sects with no special relationship
        return 0.3
    
    def _calculate_location_compatibility(self, other_profile):
        """
        Calculate location compatibility - city focused, country less important
        Returns score between 0 and 1
        """
        # If location is hidden, give neutral score
        if not self.show_location or not other_profile.show_location:
            return 0.5
        
        # Same city - highest score
        if (self.city and other_profile.city and 
            self.city.lower() == other_profile.city.lower()):
            return 1.0
        
        # Different city but same province (if you have province field)
        # For now, check if cities are in same region
        if (self.city and other_profile.city):
            # You could add a list of major cities in same province
            # For example, Karachi and Hyderabad are both in Sindh
            SINDH_CITIES = ['karachi', 'hyderabad', 'sukkur', 'larkana', 'nawabshah']
            PUNJAB_CITIES = ['lahore', 'faisalabad', 'rawalpindi', 'multan', 'gujranwala']
            KPK_CITIES = ['peshawar', 'mardan', 'abbottabad', 'swat']
            BALOCHISTAN_CITIES = ['quetta', 'gwadar', 'turbat']
            
            city_lower = self.city.lower()
            other_city_lower = other_profile.city.lower()
            
            # Check if in same province
            if (city_lower in SINDH_CITIES and other_city_lower in SINDH_CITIES) or \
            (city_lower in PUNJAB_CITIES and other_city_lower in PUNJAB_CITIES) or \
            (city_lower in KPK_CITIES and other_city_lower in KPK_CITIES) or \
            (city_lower in BALOCHISTAN_CITIES and other_city_lower in BALOCHISTAN_CITIES):
                return 0.8
        
        # Same country (Pakistan) - lower score since most users are from Pakistan
        if (self.country and other_profile.country and 
            self.country.lower() == other_profile.country.lower()):
            if self.country.lower() == 'pakistan':
                return 0.6  # Lower score for same country within Pakistan
            return 0.7  # Slightly higher for other countries
        
        # Different countries
        return 0.3
    

    def _calculate_age_compatibility(self, other_age):
        """
        Calculate age compatibility
        Returns score between 0 and 1
        """
        age_diff = abs(self.age - other_age)
        
        if age_diff <= 3:
            return 1.0      # Perfect match
        elif age_diff <= 5:
            return 0.9      # Excellent
        elif age_diff <= 7:
            return 0.8      # Very good
        elif age_diff <= 10:
            return 0.7      # Good
        elif age_diff <= 12:
            return 0.6      # Okay
        elif age_diff <= 15:
            return 0.5      # Acceptable
        else:
            return 0.3      # Large age gap

    def _calculate_practice_compatibility(self, other_practice_level):
        """
        Calculate practice level compatibility
        Returns score between 0 and 1
        """
        level_values = {
            'B': 1,  # Beginner
            'I': 2,  # Intermediate
            'A': 3,  # Advanced
            'E': 4   # Expert
        }
        
        self_val = level_values.get(self.practice_level, 2)
        other_val = level_values.get(other_practice_level, 2)
        
        diff = abs(self_val - other_val)
        
        if diff == 0:
            return 1.0      # Same level
        elif diff == 1:
            return 0.8      # Close levels
        elif diff == 2:
            return 0.5      # Moderately different
        else:
            return 0.3      # Very different

    def _calculate_education_compatibility(self, other_education):
        """
        Calculate education compatibility
        Returns score between 0 and 1
        """
        education_weights = {
            'HS': 1,   # High School
            'AD': 2,   # Associate Degree
            'BD': 3,   # Bachelor's
            'MD': 4,   # Master's
            'PHD': 5,  # Doctorate
            'OT': 2    # Other
        }
        
        self_weight = education_weights.get(self.education, 2)
        other_weight = education_weights.get(other_education, 2)
        
        diff = abs(self_weight - other_weight)
        
        if diff == 0:
            return 1.0      # Same level
        elif diff == 1:
            return 0.8      # Close levels
        elif diff == 2:
            return 0.6      # Moderate difference
        else:
            return 0.4      # Big difference
    
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
    
    @classmethod
    def new_matches_today(cls):
        """
        Class method to get profiles created today
        """
        today = timezone.now().date()
        return cls.objects.filter(created_at__date=today)

    def get_matches_count(self, threshold=50):
        """
        Count profiles with compatibility above threshold
        """
        cache_key = f"matches_count_{self.user_id}_{threshold}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        # Get all visible, approved, completed profiles
        profiles = UserProfile.objects.filter(
            is_visible=True,
            approved=True,
            #completed=True
        ).exclude(user=self.user).select_related('user')[:100]  # Limit for performance
        
        count = 0
        for profile in profiles:
            try:
                score = self.calculate_compatibility(profile)
                if score > threshold:
                    count += 1
            except Exception:
                continue
        
        # Cache for 30 minutes (since matches don't change often)
        cache.set(cache_key, count, 1800)
        
        return count
    
    @classmethod
    def get_total_matches_count(cls, user, threshold=50):
        """
        Class method to get total matches count for a user
        """
        try:
            profile = user.userprofile
            return profile.get_matches_count(threshold)
        except UserProfile.DoesNotExist:
            return 0


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


