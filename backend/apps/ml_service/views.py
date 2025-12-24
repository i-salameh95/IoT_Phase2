"""
Views for ML Service API
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from app.services.ml_model_service import health_ml_model
from app.models.sensor import SensorReading
from apps.ml_service.serializers import (
    PredictionRequestSerializer, 
    TrainingRequestSerializer,
    ModelComparisonRequestSerializer
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
            
            # Convert to SensorReading objects
            readings = [
                SensorReading(**reading_data)
                for reading_data in readings_data
            ]
            
            # Make prediction
            prediction = health_ml_model.predict(readings)
            
            return Response({
                "status": "success",
                "prediction": prediction
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def train_model(request):
    """
    Train the ML model with specified algorithm
    
    Request body (optional):
    {
        "algorithm": "random_forest",
        "test_size": 0.2,
        "force_retrain": false
    }
    
    Available algorithms:
    - random_forest (default)
    - gradient_boosting
    - ada_boost
    - svm
    - logistic_regression
    - knn
    - naive_bayes
    - decision_tree
    """
    serializer = TrainingRequestSerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            algorithm = data.get('algorithm', 'random_forest')
            test_size = data.get('test_size', 0.2)
            force_retrain = data.get('force_retrain', False)
            
            # Train model
            result = health_ml_model.train(
                algorithm=algorithm,
                force_retrain=force_retrain,
                split=(0.7, max(0.0, 1.0 - (0.7 + test_size)), test_size)
            )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def compare_models(request):
    """
    Train and compare multiple ML algorithms
    
    Request body (optional):
    {
        "algorithms": ["random_forest", "gradient_boosting", "svm"],
        "test_size": 0.2
    }
    
    If algorithms not specified, compares all available algorithms.
    """
    serializer = ModelComparisonRequestSerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            algorithms = data.get('algorithms')
            test_size = data.get('test_size', 0.2)
            
            # Compare models
            result = health_ml_model.compare_models(
                algorithms=algorithms,
                split=(0.7, max(0.0, 1.0 - (0.7 + test_size)), test_size)
            )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def model_status(request):
    """
    Get ML model status
    """
    current_algo = health_ml_model.current_algorithm
    algo_name = health_ml_model.AVAILABLE_ALGORITHMS.get(current_algo, {}).get('name', 'Unknown')
    
    response = {
        "is_trained": health_ml_model.is_trained,
        "model_loaded": health_ml_model.model is not None,
        "current_algorithm": current_algo,
        "current_algorithm_name": algo_name,
        "feature_names": health_ml_model.feature_names,
        "class_names": health_ml_model.class_names,
        "available_algorithms": health_ml_model.get_available_algorithms()
    }
    
    # Add metrics if available
    if current_algo in health_ml_model.model_metrics:
        response["metrics"] = health_ml_model.model_metrics[current_algo]
    
    return Response(response, status=status.HTTP_200_OK)
