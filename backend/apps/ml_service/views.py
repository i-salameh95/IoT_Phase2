"""
Views for ML Service API
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from app.models.sensor import SensorReading
from app.services.ml_model_service import ml_model_service
from apps.ml_service.serializers import (
    PredictionRequestSerializer,
    TrainingRequestSerializer,
    ModelComparisonRequestSerializer,
)


@api_view(['POST'])
def predict_health_status(request):
    """
    Predict health status from sensor readings
    
    Request body:
    {
        "readings": [
            {
                "measurement": "heart_rate",
                "device_id": "patient_001_wearable",
                "sensor_id": "hr_001",
                "value": 75.0,
                "tags": {"patient_id": "P001"}
            },
            ...
        ]
    }
    """
    serializer = PredictionRequestSerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            readings_data = data['readings']

            readings = [SensorReading(**reading_data) for reading_data in readings_data]
            prediction = ml_model_service.predict(readings)

            return Response({"status": "success", "prediction": prediction}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def train_model(request):
    """
    Train the ML model with specified algorithm.
    """
    serializer = TrainingRequestSerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            algorithm = data.get('algorithm', 'random_forest')
            test_size = float(data.get('test_size', 0.2))
            force_retrain = bool(data.get('force_retrain', False))

            result = ml_model_service.train(
                algorithm=algorithm,
                force_retrain=force_retrain,
                split=(0.7, max(0.0, 1.0 - (0.7 + test_size)), test_size)
            )
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def compare_models(request):
    """
    Train and compare multiple ML algorithms.
    """
    serializer = ModelComparisonRequestSerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            algorithms = data.get('algorithms')
            test_size = float(data.get('test_size', 0.2))

            result = ml_model_service.compare_models(
                algorithms=algorithms,
                split=(0.7, max(0.0, 1.0 - (0.7 + test_size)), test_size)
            )
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def ml_status(request):
    """
    Minimal status endpoint required by frontend dashboard.
    """
    try:
        if hasattr(ml_model_service, "get_status"):
            return Response(ml_model_service.get_status(), status=status.HTTP_200_OK)

        out = {
            "is_trained": ml_model_service.is_trained() if hasattr(ml_model_service, "is_trained") else False,
            "best_model": getattr(ml_model_service, "best_model_name", None),
            "class_names": ["Normal", "Warning", "Critical"],
        }
        return Response(out, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "is_trained": False,
            "best_model": None,
            "class_names": ["Normal", "Warning", "Critical"],
            "error": str(e)
        }, status=status.HTTP_200_OK)
