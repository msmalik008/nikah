from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # User online status WebSocket
    re_path(r'ws/accounts/online-status/$', consumers.OnlineStatusConsumer.as_asgi()),
    
    # Real-time profile updates
    re_path(r'ws/accounts/profile-updates/$', consumers.ProfileUpdateConsumer.as_asgi()),
    
    # Activity notifications
    re_path(r'ws/accounts/notifications/$', consumers.ActivityNotificationConsumer.as_asgi()),
]