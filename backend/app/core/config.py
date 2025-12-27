"""
Application configuration (Compatibility layer for Django)
Uses Django settings when available, falls back to environment variables
"""
import os


def _get_django_setting(name, default=None):
    """Safely get Django setting, handling cases where Django isn't configured"""
    try:
        from django.conf import settings as django_settings
        # Check if Django is configured
        try:
            # Try to access a known setting to check if Django is configured
            _ = django_settings.SECRET_KEY
            return getattr(django_settings, name, default)
        except Exception:
            # Django not configured yet
            return default
    except ImportError:
        # Django not installed
        return default


class Settings:
    """Settings class that works with both Django and standalone"""

    def __init__(self):
        # Try to get from Django settings first, fallback to environment variables
        self.MONGODB_URL = _get_django_setting('MONGODB_URL') or os.getenv('MONGODB_URL',
                                                                           'mongodb://admin:admin123@localhost:27017/health_data?authSource=admin')
        self.MONGODB_DATABASE = _get_django_setting('MONGODB_DATABASE') or os.getenv('MONGODB_DATABASE', 'health_data')

        # MQTT Configuration
        self.MQTT_ENABLED = (_get_django_setting('MQTT_ENABLED') or os.getenv('MQTT_ENABLED', 'True')) == 'True'
        self.MQTT_BROKER_HOST = _get_django_setting('MQTT_BROKER_HOST') or os.getenv('MQTT_BROKER_HOST', 'mqtt')
        self.MQTT_BROKER_PORT = int(_get_django_setting('MQTT_BROKER_PORT') or os.getenv('MQTT_BROKER_PORT', '1883'))
        self.MQTT_USERNAME = _get_django_setting('MQTT_USERNAME') or os.getenv('MQTT_USERNAME')
        self.MQTT_PASSWORD = _get_django_setting('MQTT_PASSWORD') or os.getenv('MQTT_PASSWORD')
        self.MQTT_TOPIC_RAW = _get_django_setting('MQTT_TOPIC_RAW') or os.getenv('MQTT_TOPIC_RAW', 'iot/health/raw/#')
        self.MQTT_TOPIC_PROCESSED = _get_django_setting('MQTT_TOPIC_PROCESSED') or os.getenv('MQTT_TOPIC_PROCESSED',
                                                                                             'iot/health/processed/#')
        self.MQTT_QOS = int(_get_django_setting('MQTT_QOS') or os.getenv('MQTT_QOS', '1'))
        self.MQTT_CONNECT_RETRIES = int(
            _get_django_setting('MQTT_CONNECT_RETRIES') or os.getenv('MQTT_CONNECT_RETRIES', '20'))
        self.MQTT_CONNECT_DELAY = float(
            _get_django_setting('MQTT_CONNECT_DELAY') or os.getenv('MQTT_CONNECT_DELAY', '1.0'))

        # CORS origins
        cors_origins = _get_django_setting('CORS_ALLOWED_ORIGINS')
        if cors_origins:
            self.CORS_ORIGINS = cors_origins
        else:
            self.CORS_ORIGINS = [
                "http://localhost:3000",
                "http://localhost:8000",
            ]


settings = Settings()
