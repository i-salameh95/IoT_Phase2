"""
Views for Health Monitoring Sensors API
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

# Add parent directory to path to import core modules
from app.core.mongodb_client import mongodb_service
from apps.sensors.serializers import (
    SensorReadingSerializer,
    SensorReadingResponseSerializer,
    HistoricalDataQuerySerializer,
    AggregatedDataQuerySerializer
)


@api_view(['POST'])
def ingest_sensor_data(request):
    """
    Ingest sensor data into MongoDB
    
    In Phase 2: Health monitoring sensor data
    """
    serializer = SensorReadingSerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            mongodb_service.write_sensor_data(
                measurement=data['measurement'],
                device_id=data['device_id'],
                sensor_id=data['sensor_id'],
                value=data['value'],
                timestamp=data.get('timestamp'),
                tags=data.get('tags')
            )
            return Response({
                "status": "success",
                "message": "Sensor data ingested successfully"
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def ingest_sensor_data_batch(request):
    """
    Ingest multiple sensor readings in batch
    """
    serializer = SensorReadingSerializer(data=request.data, many=True)
    if serializer.is_valid():
        try:
            count = 0
            for data in serializer.validated_data:
                mongodb_service.write_sensor_data(
                    measurement=data['measurement'],
                    device_id=data['device_id'],
                    sensor_id=data['sensor_id'],
                    value=data['value'],
                    timestamp=data.get('timestamp'),
                    tags=data.get('tags')
                )
                count += 1
            return Response({
                "status": "success",
                "message": f"{count} sensor readings ingested successfully"
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def get_historical_data(request):
    """
    Retrieve historical sensor data
    """
    serializer = HistoricalDataQuerySerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            results = mongodb_service.query_sensor_data(
                measurement=data['measurement'],
                device_id=data.get('device_id'),
                sensor_id=data.get('sensor_id'),
                start_time=data.get('start_time'),
                stop_time=data.get('stop_time'),
                limit=data.get('limit', 1000)
            )
            response_serializer = SensorReadingResponseSerializer(data=results, many=True)
            if response_serializer.is_valid():
                return Response(response_serializer.validated_data)
            return Response(results)
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def get_aggregated_data(request):
    """
    Retrieve aggregated sensor data (summaries)
    """
    serializer = AggregatedDataQuerySerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            results = mongodb_service.get_aggregated_data(
                measurement=data['measurement'],
                device_id=data.get('device_id'),
                sensor_id=data.get('sensor_id'),
                window=data.get('window', '1h'),
                aggregate=data.get('aggregate', 'mean')
            )
            response_serializer = SensorReadingResponseSerializer(data=results, many=True)
            if response_serializer.is_valid():
                return Response(response_serializer.validated_data)
            return Response(results)
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def get_measurements(request):
    """
    Get list of available measurement types (Health Monitoring Sensors)
    """
    try:
        measurements = mongodb_service.get_distinct_measurements()
        # If no measurements exist, return health monitoring sensor types
        if not measurements:
            return Response([
                "heart_rate",
                "blood_pressure_systolic",
                "blood_pressure_diastolic",
                "body_temperature",
                "oxygen_saturation",
                "glucose_level",
                "activity_steps",
                "ambient_temperature",
                "humidity",
                "light_level",
                "motion_detected",
                "co2_level",
                "sound_level"
            ])
        return Response(measurements)
    except Exception as e:
        # Fallback to health monitoring sensor types on error
        return Response([
            "heart_rate",
            "blood_pressure_systolic",
            "blood_pressure_diastolic",
            "body_temperature",
            "oxygen_saturation",
            "glucose_level",
            "activity_steps",
            "ambient_temperature",
            "humidity",
            "light_level",
            "motion_detected",
            "co2_level",
            "sound_level"
        ])


@api_view(['GET'])
def get_devices(request):
    """
    Get list of available device IDs (Patient devices)
    """
    try:
        devices = mongodb_service.get_distinct_devices()
        return Response(devices)
    except Exception as e:
        return Response([])
