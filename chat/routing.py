from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Private chat WebSocket
    # re_path(r'ws/chat/private/(?P<room_name>\w+)/$', consumers.PrivateChatConsumer.as_asgi()),
    
    # Group chat WebSocket
    # re_path(r'ws/chat/group/(?P<group_id>\w+)/$', consumers.GroupChatConsumer.as_asgi()),
    
    # Chat notifications WebSocket
    # re_path(r'ws/chat/notifications/$', consumers.ChatNotificationConsumer.as_asgi()),

    re_path(r'ws/chat/(?P<conversation_id>[^/]+)/$', consumers.ChatConsumer.as_asgi()),
    re_path(r'ws/chat/notifications/$', consumers.NotificationConsumer.as_asgi()),
]
