# api/routing.py
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')

# Initialize Django ASGI application FIRST - before any app imports
django_asgi_app = get_asgi_application()

# NOW import WebSocket routing from each app (after Django is initialized)
import chat.routing

# Start with chat routes
websocket_urlpatterns = []
websocket_urlpatterns.extend(chat.routing.websocket_urlpatterns)

# Conditionally add accounts routes if they exist
try:
    import accounts.routing
    if hasattr(accounts.routing, 'websocket_urlpatterns'):
        websocket_urlpatterns.extend(accounts.routing.websocket_urlpatterns)
except ImportError:
    pass

# Conditionally add friendship routes if they exist
try:
    import friendship.routing
    if hasattr(friendship.routing, 'websocket_urlpatterns'):
        websocket_urlpatterns.extend(friendship.routing.websocket_urlpatterns)
except ImportError:
    pass

# Create the ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})