from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')

# Import WebSocket routing from each app
import chat.routing

# Initialize Django ASGI application for HTTP
django_asgi_app = get_asgi_application()

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