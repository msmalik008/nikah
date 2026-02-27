from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

app_name = 'accounts'

urlpatterns = [
    # Landing Page & Home
    path('', views.LandingPageView.as_view(), name='home'),
    
    # Authentication Flow with Preferences
    path('register-with-preferences/', views.RegisterWithPreferencesView.as_view(), 
         name='register_with_preferences'),
    
    # Traditional Authentication (Direct Access)
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('search/', views.ProfileSearchView.as_view(), name='profile_search'),
    # Profile Management
    path('profile/', views.ProfileView.as_view(), name='profile_view'),
    path('profile/edit/', views.ProfileUpdateView.as_view(), name='profile_edit'),
    path('profile/<int:user_id>/', views.ViewProfileView.as_view(), name='view_profile'),

    path("people/", views.PeopleNearbyPageView.as_view(), name="find_friends"),
    path("people/nearby/", views.PeopleNearbyPageView.as_view(), name="people_nearby"),
    
    # Account Settings & Security
    path('settings/', views.AccountSettingsView.as_view(), name='account_settings'),
    path('settings/password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('settings/email/', views.UpdateEmailView.as_view(), name='update_email'),
    path('settings/info/', views.UpdateUserInfoView.as_view(), name='update_user_info'),
    path('settings/delete/', views.DeleteAccountView.as_view(), name='delete_account'),
    path('settings/activity/', views.ActivityHistoryView.as_view(), name='activity_history'),
    
    # Password Reset (Django Built-in with Custom Templates)
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(
             template_name='accounts/password_reset.html',
             email_template_name='accounts/password_reset_email.html',
             subject_template_name='accounts/password_reset_subject.txt',
             success_url='done/'
         ), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(
             template_name='accounts/password_reset_done.html'
         ), 
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='accounts/password_reset_confirm.html',
             success_url='complete/'
         ), 
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(
             template_name='accounts/password_reset_complete.html'
         ), 
         name='password_reset_complete'),
    
    # Informational Pages
    path('download-app/', views.DownloadAppView.as_view(), name='download_app'),
    path('success-stories/', views.SuccessStoriesView.as_view(), name='success_stories'),
    
    # API Endpoints (AJAX)
    path('api/check-username/', views.check_username_availability, name='check_username'),
    path('api/check-email/', views.check_email_availability, name='check_email'),
    path('api/update-visibility/', views.update_profile_visibility, name='update_visibility'),
]