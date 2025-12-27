"""
URLs for Actuators API
"""
from django.urls import path

from apps.actuators import views

urlpatterns = [
    path('actuators/states', views.get_actuator_states, name='get_actuator_states'),
    path('actuators/states/current', views.get_current_actuator_states, name='get_current_actuator_states'),
    path('actuators/control', views.control_actuator, name='control_actuator'),
]
