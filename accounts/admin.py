from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import UserProfile, ActivityLog, EmailVerification, PasswordResetToken, LandingPageSubmission


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile Details'
    fk_name = 'user'
    fieldsets = (
        ('Basic Information', {
            'fields': ('age', 'gender', 'bio', 'profile_pic', 'profile_pic_preview')
        }),
        ('Location', {
            'fields': ('city', 'country')
        }),
        ('Religious Information', {
            'fields': ('sect', 'education', 'practice_level')
        }),
        ('Preferences', {
            'fields': ('preferences',),
            'classes': ('collapse',)
        }),
        ('Status & Privacy', {
            'fields': ('is_visible', 'approved', 'completed', 
                      'show_age', 'show_location', 'show_sect',
                      'show_education', 'show_practice_level')
        }),
        ('Verification', {
            'fields': ('email_verified', 'phone_verified')
        }),
        ('Tracking', {
            'fields': ('source', 'last_active', 'last_profile_update'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('last_active', 'last_profile_update', 'profile_pic_preview')
    
    def profile_pic_preview(self, obj):
        if obj.profile_pic:
            return format_html('<img src="{}" style="max-height: 200px; max-width: 200px;" />', obj.profile_pic.url)
        return "No image"
    profile_pic_preview.short_description = 'Profile Picture Preview'


class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 
                    'is_active', 'date_joined', 'get_profile_status', 'get_completion_status', 'get_admin_actions')
    list_select_related = ('userprofile',)
    list_filter = ('is_staff', 'is_active', 'userprofile__approved', 
                  'userprofile__completed', 'userprofile__source')
    search_fields = ('username', 'email', 'first_name', 'last_name', 
                    'userprofile__city', 'userprofile__country')
    actions = ['approve_profiles', 'disapprove_profiles', 'mark_profiles_complete', 'mark_profiles_incomplete']
    
    def get_profile_status(self, instance):
        try:
            return instance.userprofile.approved
        except UserProfile.DoesNotExist:
            return False
    get_profile_status.short_description = 'Approved'
    get_profile_status.boolean = True
    get_profile_status.admin_order_field = 'userprofile__approved'
    
    def get_completion_status(self, instance):
        try:
            return instance.userprofile.completed
        except UserProfile.DoesNotExist:
            return False
    get_completion_status.short_description = 'Completed'
    get_completion_status.boolean = True
    get_completion_status.admin_order_field = 'userprofile__completed'
    
    def get_admin_actions(self, instance):
        """Render admin action buttons"""
        try:
            profile = instance.userprofile
            view_url = reverse('admin:accounts_userprofile_change', args=[profile.id])
            
            html = f'<a href="{view_url}" class="button" style="padding: 5px 10px; background: #417690; color: white; text-decoration: none; border-radius: 3px;">View</a>'
            if not profile.approved:
                approve_url = reverse('admin:accounts_userprofile_approve', args=[profile.id])
                html += f' <a href="{approve_url}" class="button" style="padding: 5px 10px; background: green; color: white; text-decoration: none; border-radius: 3px; margin-left: 5px;">Approve</a>'
            return format_html(html)
        except UserProfile.DoesNotExist:
            return ""
    get_admin_actions.short_description = 'Actions'
    get_admin_actions.allow_tags = True
    
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        return super().get_inline_instances(request, obj)
    
    def approve_profiles(self, request, queryset):
        """Approve selected user profiles"""
        for user in queryset:
            try:
                profile = user.userprofile
                profile.approved = True
                profile.save()
            except UserProfile.DoesNotExist:
                pass
        self.message_user(request, f"{queryset.count()} profiles approved.")
    approve_profiles.short_description = "Approve selected user profiles"
    
    def disapprove_profiles(self, request, queryset):
        """Disapprove selected user profiles"""
        for user in queryset:
            try:
                profile = user.userprofile
                profile.approved = False
                profile.save()
            except UserProfile.DoesNotExist:
                pass
        self.message_user(request, f"{queryset.count()} profiles disapproved.")
    disapprove_profiles.short_description = "Disapprove selected user profiles"
    
    def mark_profiles_complete(self, request, queryset):
        """Mark selected profiles as complete"""
        for user in queryset:
            try:
                profile = user.userprofile
                profile.completed = True
                profile.save()
            except UserProfile.DoesNotExist:
                pass
        self.message_user(request, f"{queryset.count()} profiles marked as complete.")
    mark_profiles_complete.short_description = "Mark selected profiles as complete"
    
    def mark_profiles_incomplete(self, request, queryset):
        """Mark selected profiles as incomplete"""
        for user in queryset:
            try:
                profile = user.userprofile
                profile.completed = False
                profile.save()
            except UserProfile.DoesNotExist:
                pass
        self.message_user(request, f"{queryset.count()} profiles marked as incomplete.")
    mark_profiles_incomplete.short_description = "Mark selected profiles as incomplete"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'age', 'gender', 'city', 'country', 'sect', 
                    'is_visible', 'approved', 'completed', 'email_verified', 
                    'get_completion_percentage', 'created_at')
    list_filter = ('is_visible', 'approved', 'completed', 'email_verified', 
                  'gender', 'education', 'practice_level', 'source', 'created_at')
    search_fields = ('user__username', 'user__email', 'city', 'country', 'sect', 'bio')
    readonly_fields = ('created_at', 'updated_at', 'last_active', 'last_profile_update', 
                      'get_completion_percentage', 'preferences_display', 
                      'profile_pic_preview')  # ADD THIS
    list_per_page = 50
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'source')
        }),
        ('Basic Information', {
            'fields': ('age', 'gender', 'bio', 'profile_pic', 'profile_pic_preview')
        }),
        ('Location', {
            'fields': ('city', 'country')
        }),
        ('Religious Information', {
            'fields': ('sect', 'education', 'practice_level')
        }),
        ('Preferences', {
            'fields': ('preferences_display',),
            'classes': ('collapse',)
        }),
        ('Status & Settings', {
            'fields': ('is_visible', 'approved', 'completed',
                      'show_age', 'show_location', 'show_sect',
                      'show_education', 'show_practice_level')
        }),
        ('Verification', {
            'fields': ('email_verified', 'phone_verified')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_active', 'last_profile_update'),
            'classes': ('collapse',)
        }),
        ('Completion', {
            'fields': ('get_completion_percentage',),
            'classes': ('collapse',)
        }),
    )
    
    def profile_pic_preview(self, obj):
        if obj.profile_pic:
            return format_html('<img src="{}" style="max-height: 200px; max-width: 200px;" />', obj.profile_pic.url)
        return "No image"
    profile_pic_preview.short_description = 'Profile Picture Preview'
    
    def preferences_display(self, obj):
        if obj.preferences:
            html = '<table style="width: 100%;">'
            for key, value in obj.preferences.items():
                html += f'<tr><td style="padding: 5px; font-weight: bold;">{key}:</td><td style="padding: 5px;">{value}</td></tr>'
            html += '</table>'
            return format_html(html)
        return "No preferences set"
    preferences_display.short_description = 'Preferences'
    
    def get_completion_percentage(self, obj):
        return f"{obj.get_profile_completion_percentage()}%"
    get_completion_percentage.short_description = 'Completion %'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
    
    def approve_profile(self, request, profile_id):
        profile = UserProfile.objects.get(id=profile_id)
        profile.approved = True
        profile.save()
        self.message_user(request, f"Profile for {profile.user.username} has been approved.")
    
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:profile_id>/approve/', self.admin_site.admin_view(self.approve_profile), name='accounts_userprofile_approve'),
        ]
        return custom_urls + urls


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'activity_type', 'target_user_display', 'ip_address', 
                    'created_at', 'additional_info_preview')
    list_filter = ('activity_type', 'created_at')
    search_fields = ('user__username', 'target_user__username', 'ip_address', 
                    'user_agent', 'additional_info')
    readonly_fields = ('created_at', 'additional_info_display')
    list_per_page = 100
    date_hierarchy = 'created_at'
    
    def target_user_display(self, obj):
        if obj.target_user:
            url = reverse('admin:auth_user_change', args=[obj.target_user.id])
            return format_html('<a href="{}">{}</a>', url, obj.target_user.username)
        return "N/A"
    target_user_display.short_description = 'Target User'
    
    def additional_info_preview(self, obj):
        if obj.additional_info and len(obj.additional_info) > 50:
            return f"{obj.additional_info[:50]}..."
        return obj.additional_info or ""
    additional_info_preview.short_description = 'Additional Info'
    
    def additional_info_display(self, obj):
        if obj.additional_info:
            return format_html('<pre style="background-color: #f5f5f5; padding: 10px; border-radius: 5px;">{}</pre>', 
                              obj.additional_info)
        return "No additional info"
    additional_info_display.short_description = 'Additional Info'
    
    def get_queryset(self, request):
        # Only show activities from the last 90 days by default
        ninety_days_ago = timezone.now() - timezone.timedelta(days=90)
        return super().get_queryset(request).filter(
            created_at__gte=ninety_days_ago
        ).select_related('user', 'target_user')


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_verified', 'created_at', 'verified_at', 'is_expired', 'days_since_created')
    list_filter = ('is_verified', 'created_at', 'verified_at')
    search_fields = ('user__username', 'user__email', 'token')
    readonly_fields = ('token', 'created_at', 'verified_at', 'is_expired_display')
    list_per_page = 50
    
    def days_since_created(self, obj):
        return (timezone.now() - obj.created_at).days
    days_since_created.short_description = 'Days Since Created'
    
    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.short_description = 'Is Expired?'
    is_expired_display.boolean = True
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'token_short', 'created_at', 'used', 'used_at', 'is_expired', 'hours_since_created')
    list_filter = ('used', 'created_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('token', 'created_at', 'used_at', 'is_expired_display')
    list_per_page = 50
    
    def token_short(self, obj):
        return str(obj.token)[:8] + "..."
    token_short.short_description = 'Token'
    
    def hours_since_created(self, obj):
        return int((timezone.now() - obj.created_at).seconds / 3600)
    hours_since_created.short_description = 'Hours Since Created'
    
    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.short_description = 'Is Expired?'
    is_expired_display.boolean = True
    
    def get_queryset(self, request):
        # Only show tokens from the last 7 days
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        return super().get_queryset(request).filter(
            created_at__gte=seven_days_ago
        ).select_related('user')


@admin.register(LandingPageSubmission)
class LandingPageSubmissionAdmin(admin.ModelAdmin):
    list_display = ('session_key', 'converted_to_user', 'converted_user', 
                    'created_at', 'converted_at', 'days_to_convert')
    list_filter = ('converted_to_user', 'created_at')
    search_fields = ('session_key', 'converted_user__username', 'converted_user__email')
    readonly_fields = ('session_key', 'preferences_display', 'created_at', 
                      'converted_at', 'converted_user_link')
    list_per_page = 50
    
    def preferences_display(self, obj):
        if obj.preferences:
            html = '<table style="width: 100%;">'
            for key, value in obj.preferences.items():
                html += f'<tr><td style="padding: 5px; font-weight: bold;">{key}:</td><td style="padding: 5px;">{value}</td></tr>'
            html += '</table>'
            return format_html(html)
        return "No preferences"
    preferences_display.short_description = 'Preferences'
    
    def converted_user_link(self, obj):
        if obj.converted_user:
            url = reverse('admin:auth_user_change', args=[obj.converted_user.id])
            return format_html('<a href="{}">{}</a>', url, obj.converted_user.username)
        return "Not converted"
    converted_user_link.short_description = 'Converted User'
    
    def days_to_convert(self, obj):
        if obj.converted_at and obj.converted_to_user:
            return (obj.converted_at - obj.created_at).days
        return None
    days_to_convert.short_description = 'Days to Convert'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('converted_user')


# Unregister the default User admin and register with custom
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)