import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')

# Get the ASGI application
django_asgi_app = get_asgi_application()

# Import the application from routing
from api.routing import application

# This file should be minimal