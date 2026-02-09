import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')

# Import the application from routing
from api.routing import application

# This file should be minimal