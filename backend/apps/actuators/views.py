"""
Views for Health Monitoring Actuators API
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from app.core.mongodb_client import mongodb_service
from apps.actuators.serializers import ActuatorStateSerializer, ActuatorStateResponseSerializer


@api_view(['GET'])
def get_actuator_states(request):
    """
    Get actuator states (with limit)
    """
    limit = int(request.query_params.get('limit', 100))
    try:
        data = mongodb_service.get_actuator_states(limit=limit)
        serializer = ActuatorStateResponseSerializer(data=data, many=True)
        if serializer.is_valid():
            return Response(serializer.validated_data)
        return Response(data)
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_current_actuator_states(request):
    """
    Get current state of all actuators
    """
    try:
        data = mongodb_service.get_current_actuator_states()
        return Response(data)
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def control_actuator(request):
    """
    Manually control an actuator
    """
    serializer = ActuatorStateSerializer(data=request.data)
    if serializer.is_valid():
        try:
            data = serializer.validated_data
            from app.models.actuator import ActuatorState
            actuator_state = ActuatorState(
                actuator_id=data['actuator_id'],
                device_id=data['device_id'],
                actuator_type=data['actuator_type'],
                state=data['state'],
                value=data.get('value'),
                timestamp=data.get('timestamp'),
                tags=data.get('tags')
            )
            mongodb_service.write_actuator_state(actuator_state)
            return Response({
                "status": "success",
                "message": f"Actuator {data['actuator_id']} set to {data['state']}"
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

