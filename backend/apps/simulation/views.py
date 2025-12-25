"""
Views for Health Monitoring Simulation API
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from app.services.health_simulation_engine import health_simulation_engine
from app.core.logger import iot_logger
from app.core.mongodb_client import mongodb_service


@api_view(['POST'])
def run_single_cycle(request):
    """
    Run a single health monitoring simulation cycle
    Sensors send data -> Edge processes -> Cloud analyzes -> Actuators respond
    """
    try:
        patient_id = request.data.get('patient_id')
        simulate_emergency = request.data.get('simulate_emergency', False)

        result = health_simulation_engine.run_cycle(
            patient_id=patient_id,
            simulate_emergency=bool(simulate_emergency)
        )

        # IMPORTANT: Return the full engine payload (UI relies on readings/response_times)
        return Response({
            "status": "success",
            **result
        }, status=status.HTTP_200_OK)

    except Exception as e:
        iot_logger.error(
            f"Error running simulation cycle: {str(e)}",
            source="simulation"
        )
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def run_simulation(request):
    """
    Run health monitoring simulation for a fixed number of cycles
    """
    try:
        num_cycles = int(request.data.get('num_cycles', 20))
        delay_seconds = float(request.data.get('delay_seconds', 1.0))
        patient_id = request.data.get('patient_id')
        simulate_emergency = request.data.get('simulate_emergency', False)

        if num_cycles < 1 or num_cycles > 10000:
            return Response({
                "status": "error",
                "message": "num_cycles must be between 1 and 10000"
            }, status=status.HTTP_400_BAD_REQUEST)

        if delay_seconds < 0.1 or delay_seconds > 10.0:
            return Response({
                "status": "error",
                "message": "delay_seconds must be between 0.1 and 10.0"
            }, status=status.HTTP_400_BAD_REQUEST)

        results = health_simulation_engine.run_simulation(
            num_cycles=num_cycles,
            delay_seconds=delay_seconds,
            patient_id=patient_id,
            simulate_emergency=bool(simulate_emergency)
        )

        last_cycle_result = results[-1] if results else None

        return Response({
            "status": "success",
            "total_cycles": len(results),
            "results": results,
            # Frontend currently reads result?.last_cycle_result optionally
            "last_cycle_result": last_cycle_result
        }, status=status.HTTP_200_OK)

    except Exception as e:
        iot_logger.error(
            f"Error running simulation: {str(e)}",
            source="simulation"
        )
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def stop_simulation(request):
    """Stop running simulation"""
    try:
        health_simulation_engine.stop_simulation()
        return Response({
            "status": "success",
            "message": "Simulation stopped"
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def reset_simulation(request):
    """Clear stored data and reset in-memory simulation state."""
    try:
        health_simulation_engine.reset()
        ok = mongodb_service.clear_all_data()
        return Response({
            "status": "success",
            "cleared": bool(ok)
        }, status=status.HTTP_200_OK)
    except Exception as e:
        iot_logger.error(
            f"Error resetting simulation: {str(e)}",
            source="simulation"
        )
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
