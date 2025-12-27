"""
URLs for Sensors API
"""
from django.urls import path

from apps.sensors import views

urlpatterns = [
    path('sensors/ingest', views.ingest_sensor_data, name='ingest_sensor_data'),
    path('sensors/ingest/batch', views.ingest_sensor_data_batch, name='ingest_sensor_data_batch'),
    path('sensors/query/historical', views.get_historical_data, name='get_historical_data'),
    path('sensors/query/aggregated', views.get_aggregated_data, name='get_aggregated_data'),
    path('sensors/measurements', views.get_measurements, name='get_measurements'),
    path('sensors/devices', views.get_devices, name='get_devices'),
]
