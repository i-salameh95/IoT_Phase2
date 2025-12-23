"""
URLs for Logs API
"""
from django.urls import path
from apps.logs import views

urlpatterns = [
    path('logs', views.get_logs, name='get_logs'),
]

