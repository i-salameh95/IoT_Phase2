"""
URLs for Simulation API
"""
from django.urls import path
from apps.simulation import views

urlpatterns = [
    path('simulation/run-cycle', views.run_single_cycle, name='run_single_cycle'),
    path('simulation/run', views.run_simulation, name='run_simulation'),
    path('simulation/stop', views.stop_simulation, name='stop_simulation'),
    path('simulation/reset', views.reset_simulation, name='reset_simulation'),
]
