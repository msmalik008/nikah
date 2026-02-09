from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Friend request notifications
    re_path(r'ws/friends/requests/$', consumers.FriendRequestConsumer.as_asgi()),
    
    # Friend online status
    re_path(r'ws/friends/status/$', consumers.FriendStatusConsumer.as_asgi()),
]