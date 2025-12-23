"""
URLs for ML Service API
"""
from django.urls import path
from apps.ml_service import views

urlpatterns = [
    path('ml/predict', views.predict_health_status, name='predict_health_status'),
    path('ml/train', views.train_model, name='train_model'),
    path('ml/compare', views.compare_models, name='compare_models'),
    path('ml/status', views.model_status, name='model_status'),
]

