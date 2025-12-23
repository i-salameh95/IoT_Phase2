"""
URL configuration for Health Monitoring IoT System
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('apps.sensors.urls')),
    path('api/v1/', include('apps.actuators.urls')),
    path('api/v1/', include('apps.simulation.urls')),
    path('api/v1/', include('apps.analytics.urls')),
    path('api/v1/', include('apps.ml_service.urls')),
    path('api/v1/', include('apps.logs.urls')),
]

