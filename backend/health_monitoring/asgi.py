"""
ASGI config for Health Monitoring IoT System
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'health_monitoring.settings')

application = get_asgi_application()
