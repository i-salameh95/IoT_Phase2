"""
Views for Health Monitoring Simulation API
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from app.core.logger import iot_logger
from app.core.mongodb_client import mongodb_service
from app.services.health_simulation_engine import health_simulation_engine


def _parse_bool(value, default: bool = False) -> bool:
    """
    Robust bool parsing for DRF inputs (handles True/False, "true"/"false", 1/0, etc.)
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return True
        if v in {"false", "0", "no", "n", "off", ""}:
            return False
    return default


def _pick_ml_prediction(result: dict, patient_id: str | None):
    preds = result.get("ml_predictions") or result.get("ml_predictions")  # keep defensive
    if not isinstance(preds, dict) or not preds:
        return None


def _adapt_cycle_payload_for_ui(result: dict, patient_id: str | None) -> dict:
    out = dict(result)
    out["ml_prediction"] = _pick_ml_prediction(result, patient_id)
    if "actuator_decisions" not in out:
        out["actuator_decisions"] = out.get("actuator_states") or []
    return out


@api_view(['POST'])
def run_single_cycle(request):
    """
    Run a single health monitoring simulation cycle
    """
    try:
        patient_id = request.data.get('patient_id')
        simulate_emergency = _parse_bool(request.data.get('simulate_emergency', False), default=False)
        emergency_rate = request.data.get('emergency_rate', None)
        if emergency_rate is not None:
            try:
                emergency_rate = float(emergency_rate)
            except (TypeError, ValueError):
                return Response({"status": "error", "message": "emergency_rate must be a number"},
                                status=status.HTTP_400_BAD_REQUEST)
            if emergency_rate < 0:
                return Response({"status": "error", "message": "emergency_rate must be >= 0"},
                                status=status.HTTP_400_BAD_REQUEST)

        result = health_simulation_engine.run_single_cycle(
            patient_id=patient_id,
            simulate_emergency=simulate_emergency,
            emergency_rate=emergency_rate
        )

        result = _adapt_cycle_payload_for_ui(result, patient_id)
        result["status"] = "success"
        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        iot_logger.error(f"Error running simulation cycle: {str(e)}", source="simulation")
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def run_simulation(request):
    """
    Run health monitoring simulation for a fixed number of cycles
    """
    try:
        num_cycles = int(request.data.get('num_cycles', 20))
        delay_seconds = float(request.data.get('delay_seconds', 1.0))
        patient_id = request.data.get('patient_id')
        simulate_emergency = _parse_bool(request.data.get('simulate_emergency', False), default=False)
        emergency_rate = request.data.get('emergency_rate', None)
        if emergency_rate is not None:
            try:
                emergency_rate = float(emergency_rate)
            except (TypeError, ValueError):
                return Response({"status": "error", "message": "emergency_rate must be a number"},
                                status=status.HTTP_400_BAD_REQUEST)
            if emergency_rate < 0:
                return Response({"status": "error", "message": "emergency_rate must be >= 0"},
                                status=status.HTTP_400_BAD_REQUEST)

        if num_cycles < 1 or num_cycles > 10000:
            return Response({"status": "error", "message": "num_cycles must be between 1 and 10000"},
                            status=status.HTTP_400_BAD_REQUEST)

        if delay_seconds < 0.1 or delay_seconds > 10.0:
            return Response({"status": "error", "message": "delay_seconds must be between 0.1 and 10.0"},
                            status=status.HTTP_400_BAD_REQUEST)

        engine_out = health_simulation_engine.run_simulation(
            num_cycles=num_cycles,
            delay_seconds=delay_seconds,
            patient_id=patient_id,
            simulate_emergency=simulate_emergency,
            emergency_rate=emergency_rate
        )

        results_list = engine_out.get("results") or []
        last_cycle_result = engine_out.get("last_cycle_result")
        if isinstance(last_cycle_result, dict):
            last_cycle_result = _adapt_cycle_payload_for_ui(last_cycle_result, patient_id)

        return Response({
            "status": "success",
            "total_cycles": int(engine_out.get("total_cycles") or len(results_list)),
            "last_cycle_result": last_cycle_result,
            "results": results_list,
        }, status=status.HTTP_200_OK)

    except Exception as e:
        iot_logger.error(f"Error running simulation: {str(e)}", source="simulation")
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def stop_simulation(request):
    """Stop running simulation"""
    try:
        health_simulation_engine.stop_simulation()
        return Response({"status": "success", "message": "Simulation stopped"}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def reset_simulation(request):
    """Clear stored data and reset in-memory simulation state."""
    try:
        # FIX: engine method name
        health_simulation_engine.reset_run()
        ok = mongodb_service.clear_all_data()
        return Response({"status": "success", "cleared": bool(ok)}, status=status.HTTP_200_OK)
    except Exception as e:
        iot_logger.error(f"Error resetting simulation: {str(e)}", source="simulation")
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
