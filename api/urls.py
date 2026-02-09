"""api URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
"""api URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # API endpoints
    path('api/auth/', include('accounts.urls', namespace='accounts')),
    path('api/friends/', include('friendship.urls', namespace='friendship')),
    path('api/chat/', include('chat.urls', namespace='chat')),
    path('api/activity/', include('useractivity.urls', namespace='useractivity')),
    
    # Dashboard
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
    
    # Redirect root to appropriate page
    path('', RedirectView.as_view(pattern_name='accounts:home', permanent=False)),
]

# Development static/media files
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # Debug toolbar
    try:
        import debug_toolbar
        urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    except ImportError:
        pass

# Custom error handlers
handler404 = 'accounts.views.handler404'
handler500 = 'accounts.views.handler500'
handler403 = 'accounts.views.handler403'
handler400 = 'accounts.views.handler400'