"""
URLs for Analytics API
"""
from django.urls import path
from apps.analytics import views

urlpatterns = [
    path('analytics/export', views.export_data, name='export_data'),
    path('analytics/summary', views.analytics_summary, name='analytics_summary'),
    path('analytics/response-times', views.response_time_report, name='response_time_report'),
]
