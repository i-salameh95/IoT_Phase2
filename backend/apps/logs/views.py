"""
Views for System Logs API
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from app.core.logger import iot_logger


@api_view(['GET'])
def get_logs(request):
    """
    Get system logs
    
    Query parameters:
        level: Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        source: Filter by source (sensor, controller, simulation, edge_processor)
        device_id: Filter by device_id
        limit: Maximum number of logs (default: 100)
    """
    try:
        level = request.query_params.get('level')
        source = request.query_params.get('source')
        device_id = request.query_params.get('device_id')
        limit = int(request.query_params.get('limit', 100))

        logs = iot_logger.get_logs(
            level=level,
            source=source,
            device_id=device_id,
            limit=limit
        )

        return Response(logs)
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
