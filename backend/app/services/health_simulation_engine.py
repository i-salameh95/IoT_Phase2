"""
Health Monitoring Simulation Engine
Runs simulation cycles for health monitoring IoT system
"""
import random
import time
from typing import List, Optional, Dict, Any

from app.services.health_sensor_simulator import health_sensor_simulator
from app.services.health_actuator_controller import health_actuator_controller
from app.services.edge_processor import edge_processor
from app.core.mongodb_client import mongodb_service
from app.core.logger import iot_logger

# Import ML service (optional, will use rule-based if not available)
try:
    from app.services.ml_model_service import health_ml_model
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    health_ml_model = None


class HealthSimulationEngine:
    """Runs health monitoring simulation cycles"""

    def __init__(self):
        self.sensor_simulator = health_sensor_simulator
        self.actuator_controller = health_actuator_controller
        self.edge_processor = edge_processor
        self.current_cycle = 0
        self.is_running = False

    def _reading_key(self, r) -> str:
        # Stable join key for raw vs processed mapping
        return f"{getattr(r, 'device_id', '')}|{getattr(r, 'sensor_id', '')}|{getattr(r, 'measurement', '')}"

    def run_cycle(
        self,
        cycle_number: Optional[int] = None,
        patient_id: Optional[str] = None,
        simulate_emergency: bool = False,
        simulate_warning: bool = False,
        ml_prediction: Optional[dict] = None
    ) -> dict:
        """
        Run a single health monitoring simulation cycle

        Cycle flow:
        1. Health sensors send data
        2. Edge processing (noise filtering, outlier detection, range validation)
        3. Central computer (Django) analyzes with ML
        4. Health actuators respond
        """
        if cycle_number is None:
            self.current_cycle += 1
            cycle_number = self.current_cycle
        else:
            self.current_cycle = cycle_number

        iot_logger.info(
            f"=== Health Monitoring Cycle {cycle_number} Started ===",
            source="simulation"
        )

        # Step 1: Health sensors send data
        if patient_id:
            all_readings = self.sensor_simulator.generate_patient_readings(patient_id)
        else:
            all_readings = []
            for device in self.sensor_simulator.devices:
                device_readings = self.sensor_simulator.generate_all_sensor_readings(
                    device_id=device["device_id"]
                )
                all_readings.extend(device_readings)

        emergency_triggered = False
        warning_triggered = False
        if simulate_emergency and len(all_readings) > 0:
            # Replace multiple readings to ensure visible critical events
            emergency_triggered = True
            for idx, reading in enumerate(list(all_readings)):
                if reading.measurement in {
                    "heart_rate",
                    "blood_pressure_systolic",
                    "blood_pressure_diastolic",
                    "body_temperature",
                    "oxygen_saturation",
                    "glucose_level",
                    "ambient_temperature",
                    "humidity",
                    "co2_level",
                    "sound_level"
                }:
                    emergency_reading = self.sensor_simulator.generate_reading(
                        device_id=reading.device_id,
                        sensor_type=reading.measurement,
                        simulate_emergency=True
                    )
                    all_readings[idx] = emergency_reading
        elif simulate_warning and len(all_readings) > 0:
            warning_triggered = True
            for idx, reading in enumerate(list(all_readings)):
                if reading.measurement in {
                    "heart_rate",
                    "blood_pressure_systolic",
                    "blood_pressure_diastolic",
                    "body_temperature",
                    "oxygen_saturation",
                    "glucose_level",
                    "ambient_temperature",
                    "humidity",
                    "co2_level",
                    "sound_level"
                }:
                    warning_reading = self.sensor_simulator.generate_reading(
                        device_id=reading.device_id,
                        sensor_type=reading.measurement,
                        simulate_warning=True
                    )
                    all_readings[idx] = warning_reading

        # Track response times
        response_times = {
            'sensor_generation': 0.0,
            'edge_processing': 0.0,
            'storage': 0.0,
            'ml_prediction': 0.0,
            'actuator_decision': 0.0,
            'total': 0.0
        }
        cycle_start_time = time.time()

        # Log sensor readings (raw)
        for reading in all_readings:
            unit = self._get_unit(reading.measurement)
            log_msg = f"{reading.measurement.replace('_', ' ').title()} = {reading.value}{unit}"

            iot_logger.info(
                log_msg,
                source="sensor",
                device_id=reading.device_id,
                sensor_id=reading.sensor_id,
                metadata={"patient_id": (reading.tags or {}).get("patient_id", "unknown")}
            )

        sensor_gen_time = time.time()
        response_times['sensor_generation'] = sensor_gen_time - cycle_start_time

        # Step 2: Edge Processing
        edge_start = time.time()
        already_processed = []
        raw_readings = []
        for reading in all_readings:
            tags = (reading.tags or {})
            if tags.get("processed_by") == "sensor_edge":
                already_processed.append(reading)
            else:
                raw_readings.append(reading)

        processed_readings = self.edge_processor.process_batch(raw_readings)
        if already_processed:
            processed_readings = already_processed + processed_readings

        # Build raw->processed mapping for UI traceability
        raw_map = {self._reading_key(r): r for r in all_readings}
        processed_map = {self._reading_key(r): r for r in processed_readings}

        readings_payload = []
        all_keys = set(raw_map.keys()) | set(processed_map.keys())

        for key in sorted(all_keys):
            raw_r = raw_map.get(key)
            proc_r = processed_map.get(key)

            tags = (proc_r.tags if proc_r else (raw_r.tags if raw_r else {})) or {}
            pid = tags.get("patient_id", patient_id or "unknown")

            readings_payload.append({
                "measurement": (proc_r.measurement if proc_r else raw_r.measurement),
                "device_id": (proc_r.device_id if proc_r else raw_r.device_id),
                "sensor_id": (proc_r.sensor_id if proc_r else raw_r.sensor_id),
                "timestamp": (proc_r.timestamp if proc_r else raw_r.timestamp),
                "patient_id": pid,
                "value": (raw_r.value if raw_r else None),
                "processed_value": (proc_r.value if proc_r else None),
                "filtered_out": proc_r is None,
                "critical_value": bool(tags.get("critical_value")),
                "edge": tags.get("edge"),
            })

        edge_time = time.time()
        response_times['edge_processing'] = edge_time - edge_start

        iot_logger.info(
            f"Edge processing: {len(all_readings)} readings -> {len(processed_readings)} processed",
            source="edge_processor",
            metadata={"filtered": len(all_readings) - len(processed_readings)}
        )

        # Step 3: Store processed sensor readings in MongoDB
        storage_start = time.time()
        for reading in processed_readings:
            mongodb_service.write_sensor_data(
                measurement=reading.measurement,
                device_id=reading.device_id,
                sensor_id=reading.sensor_id,
                value=reading.value,
                timestamp=reading.timestamp,
                tags=reading.tags
            )
        storage_time = time.time()
        response_times['storage'] = storage_time - storage_start

        # Step 4: ML prediction (optional)
        ml_start = time.time()
        if ml_prediction is None and ML_AVAILABLE and getattr(health_ml_model, "is_trained", False):
            try:
                ml_prediction = health_ml_model.predict(processed_readings)
                iot_logger.info(
                    f"ML Prediction: {ml_prediction.get('health_status')} "
                    f"(confidence: {ml_prediction.get('confidence', 0):.2f})",
                    source="ml_service"
                )
            except Exception as e:
                iot_logger.warning(
                    f"ML prediction failed, using rule-based: {str(e)}",
                    source="ml_service"
                )
                ml_prediction = None
        ml_time = time.time()
        response_times['ml_prediction'] = ml_time - ml_start

        # Step 5: Actuator decisions
        actuator_start = time.time()
        actuator_states = self.actuator_controller.process_sensor_readings(
            processed_readings,
            ml_prediction=ml_prediction
        )

        actuator_decisions_payload = []
        try:
            for a in actuator_states or []:
                actuator_decisions_payload.append({
                    "actuator_id": getattr(a, "actuator_id", None),
                    "actuator_type": getattr(a, "actuator_type", None),
                    "device_id": getattr(a, "device_id", None),
                    "state": getattr(a, "state", None),
                    "value": getattr(a, "value", None),
                    "timestamp": getattr(a, "timestamp", None),
                    "tags": getattr(a, "tags", None),
                })
        except Exception:
            actuator_decisions_payload = []

        actuator_time = time.time()
        response_times['actuator_decision'] = actuator_time - actuator_start

        # Store actuator states
        for actuator_state in actuator_states or []:
            mongodb_service.write_actuator_state(actuator_state)

        # Current actuator states from controller (in-memory)
        current_states = self.actuator_controller.get_actuator_states()

        # Log actuator states
        for actuator_id, state in (current_states or {}).items():
            iot_logger.info(
                f"Actuator {actuator_id}: {state}",
                source="actuator",
                actuator_id=actuator_id
            )

        cycle_end_time = time.time()
        response_times['total'] = cycle_end_time - cycle_start_time

        # Log response times
        iot_logger.info(
            f"Response Times - Total: {response_times['total']:.3f}s | "
            f"Sensor: {response_times['sensor_generation']:.3f}s | "
            f"Edge: {response_times['edge_processing']:.3f}s | "
            f"Storage: {response_times['storage']:.3f}s | "
            f"ML: {response_times['ml_prediction']:.3f}s | "
            f"Actuator: {response_times['actuator_decision']:.3f}s",
            source="simulation",
            metadata={"response_times": response_times}
        )

        iot_logger.info(
            f"=== Health Monitoring Cycle {cycle_number} Completed ===",
            source="simulation"
        )

        # Store response times for analytics
        mongodb_service.write_response_times(
            cycle=cycle_number,
            response_times=response_times,
            patient_id=patient_id
        )

        return {
            "cycle": cycle_number,
            "patient_id": patient_id or "all",
            "simulate_emergency": bool(simulate_emergency),
            "emergency_triggered": bool(emergency_triggered),
            "warning_triggered": bool(warning_triggered),

            "sensor_readings": len(all_readings),
            "processed_readings": len(processed_readings),
            "filtered_readings": len(all_readings) - len(processed_readings),

            "readings": readings_payload,
            "ml_prediction": ml_prediction,
            "actuator_decisions": actuator_decisions_payload,

            "actuator_states": current_states,
            "decisions_made": len(actuator_states or []),
            "response_times": response_times
        }

    def run_simulation(
        self,
        num_cycles: int = 20,
        delay_seconds: float = 1.0,
        patient_id: Optional[str] = None,
        simulate_emergency: bool = False
    ) -> List[dict]:
        """Run health monitoring simulation for a fixed number of cycles"""
        self.is_running = True
        iot_logger.info(
            f"Starting health monitoring simulation with {num_cycles} cycles",
            source="simulation"
        )

        results = []
        last_cycle_result = None

        emergency_cycles = set()
        warning_cycles = set()
        if simulate_emergency and num_cycles > 0:
            emergency_count = max(1, round(num_cycles * 0.33))
            warning_count = max(1, round(num_cycles * 0.33))

            if emergency_count + warning_count > num_cycles:
                warning_count = max(0, num_cycles - emergency_count)

            cycle_pool = list(range(1, num_cycles + 1))
            emergency_cycles = set(random.sample(cycle_pool, k=emergency_count))
            remaining = [c for c in cycle_pool if c not in emergency_cycles]
            if warning_count:
                warning_cycles = set(random.sample(remaining, k=warning_count))

        for i in range(1, num_cycles + 1):
            if not self.is_running:
                break

            # Simulate randomized emergency + warning cycles (if enabled)
            emergency = bool(simulate_emergency and i in emergency_cycles)
            warning = bool(simulate_emergency and i in warning_cycles)

            last_cycle_result = self.run_cycle(
                i,
                patient_id=patient_id,
                simulate_emergency=emergency,
                simulate_warning=warning
            )
            results.append(last_cycle_result)

            if i < num_cycles:
                time.sleep(delay_seconds)

        self.is_running = False
        iot_logger.info(
            f"Health monitoring simulation completed. Total cycles: {len(results)}",
            source="simulation"
        )

        return results

    def stop_simulation(self):
        """Stop running simulation"""
        self.is_running = False

    def reset(self):
        """Reset simulation state, buffers, and actuator cache."""
        self.stop_simulation()
        self.current_cycle = 0
        try:
            self.edge_processor.reset()
        except Exception:
            pass
        try:
            self.actuator_controller.reset_states()
        except Exception:
            pass

    def _get_unit(self, measurement: str) -> str:
        units = {
            "heart_rate": " bpm",
            "blood_pressure_systolic": " mmHg",
            "blood_pressure_diastolic": " mmHg",
            "body_temperature": " C",
            "oxygen_saturation": "%",
            "glucose_level": " mg/dL",
            "activity_steps": " steps",
            "ambient_temperature": " C",
            "humidity": " %",
            "light_level": " lux",
            "motion_detected": "",
            "co2_level": " ppm",
            "sound_level": " dB"
        }
        return units.get(measurement, "")


# Global instance
health_simulation_engine = HealthSimulationEngine()
