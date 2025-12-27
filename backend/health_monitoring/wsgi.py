"""
WSGI config for Health Monitoring IoT System
"""
import atexit
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'health_monitoring.settings')

application = get_wsgi_application()


# Clean up MongoDB connections on shutdown
def cleanup_mongodb():
    try:
        from app.core.mongodb_client import mongodb_service
        mongodb_service.close()
    except Exception:
        pass


atexit.register(cleanup_mongodb)
