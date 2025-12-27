"""
Health Simulation Engine
Orchestrates:
  sensors -> edge processing -> storage -> (optional) ML -> actuators -> logging

"""
from __future__ import annotations

import random
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

from app.core.logger import iot_logger
from app.core.mongodb_client import mongodb_service
from app.core.config import settings
from app.core.mqtt_client import create_mqtt_client, connect_mqtt
from app.models.actuator import ActuatorState
from app.models.sensor import SensorReading
from app.services.edge_processor import edge_processor
from app.services.health_actuator_controller import health_actuator_controller
from app.services.health_sensor_simulator import health_sensor_simulator
from app.services.ml_model_service import ml_model_service

MEASUREMENTS = [
    "heart_rate",
    "blood_pressure_systolic",
    "blood_pressure_diastolic",
    "body_temperature",
    "oxygen_saturation",
    "glucose_level",
    "activity_steps",
]

DEFAULT_EMERGENCY_RATE = 0.15


class HealthSimulationEngine:
    """Main simulation engine for health monitoring system."""

    def __init__(self):
        self.is_running = False
        self.current_cycle = 0
        self.patients = ["P001", "P002"]
        self.mqtt_client = None
        self.mqtt_ready = False
        if settings.MQTT_ENABLED:
            try:
                # Publisher client (no on_message needed)
                self.mqtt_client = create_mqtt_client(client_id="health_monitoring_publisher")
                connect_mqtt(self.mqtt_client)
                self.mqtt_client.loop_start()
                self.mqtt_ready = True
                iot_logger.info("MQTT publisher connected", source="mqtt")
            except Exception as exc:
                self.mqtt_ready = False
                iot_logger.warning(f"MQTT publisher unavailable: {exc}", source="mqtt")

    def run_single_cycle(self, patient_id: Optional[str] = None, simulate_emergency: bool = False,
                         emergency_rate: Optional[float] = None) -> Dict[str, Any]:
        """
        Run one simulation cycle.

        Returns:
            Cycle result payload used by frontend "Latest Cycle Output".
        """
        self.current_cycle += 1
        cycle = self.current_cycle

        patient_ids = self.patients if not patient_id else [patient_id]

        # Normalize emergency probability: when a rate is provided, only a fraction of cycles become emergencies
        if emergency_rate is not None:
            try:
                rate = float(emergency_rate)
            except (TypeError, ValueError):
                rate = DEFAULT_EMERGENCY_RATE
            if rate > 1.0:
                rate = rate / 100.0
            rate = max(0.0, min(rate, 1.0))
            simulate_emergency = bool(simulate_emergency) and (random.random() < rate)
        elif simulate_emergency:
            # If caller asked for emergencies but no rate supplied, use default probability
            simulate_emergency = random.random() < DEFAULT_EMERGENCY_RATE

        # Stage timing (seconds)
        t0 = time.perf_counter()
        stage = {}

        readings_raw: List[SensorReading] = []
        readings_processed: List[SensorReading] = []
        actuator_states: List[ActuatorState] = []

        total_sensor_readings = 0
        total_decisions = 0

        # 1) Sensor generation
        gen_start = time.perf_counter()
        for pid in patient_ids:
            batch = health_sensor_simulator.generate_patient_readings(
                patient_id=pid,
                cycle=cycle,
                simulate_emergency=simulate_emergency
            )
            readings_raw.extend(batch)
            total_sensor_readings += len(batch)
        stage["sensor_generation"] = time.perf_counter() - gen_start

        # 2) Edge processing
        edge_start = time.perf_counter()
        # Ensure tags carry cycle/patient for later ML grouping
        for r in readings_raw:
            r.tags = dict(r.tags or {})
            r.tags.update({"patient_id": r.tags.get("patient_id"), "cycle": cycle, "processed": False})

            # Avoid double-processing the designated sensor-edge readings.
            # If sensor already processed at the sensor tier, accept it as "processed" and only normalize tags.
            if (r.tags or {}).get("processed_by") == "sensor_edge":
                r.tags.update({"processed": True, "processed_by": "sensor_edge"})
                readings_processed.append(r)
                continue

            pr = edge_processor.process_reading(r)
            if pr is not None:
                pr.tags = dict(pr.tags or {})
                pr.tags.update({"patient_id": r.tags.get("patient_id"), "cycle": cycle, "processed": True})
                readings_processed.append(pr)
        stage["edge_processing"] = time.perf_counter() - edge_start

        # 3) Storage (processed readings) - prefer MQTT publish when enabled
        store_start = time.perf_counter()
        for pr in readings_processed:
            published = self._publish_processed_reading(pr)
            if not published:
                mongodb_service.write_sensor_data(
                    measurement=pr.measurement,
                    device_id=pr.device_id,
                    sensor_id=pr.sensor_id,
                    value=pr.value,
                    timestamp=pr.timestamp,
                    tags=pr.tags
                )
        stage["storage"] = time.perf_counter() - store_start

        # Auto-retrain policy: keep ML updated as new cycles accumulate (requirement 1d)
        try:
            retrain_result = ml_model_service.maybe_retrain(current_cycle=cycle)
        except Exception as e:
            retrain_result = {"status": "error", "action": "retrain_failed", "message": str(e)}
        stage["ml_retrain"] = 0.0

        # 4) ML prediction (optional)
        ml_start = time.perf_counter()
        ml_predictions = {}
        try:
            # Small optimization: only predict on patient-level feature vector (one per patient per cycle)
            if ml_model_service.is_trained():
                for pid in patient_ids:
                    pred = ml_model_service.predict_health_status(patient_id=pid)
                    if pred:
                        ml_predictions[pid] = pred
        except Exception as e:
            iot_logger.warning(f"ML prediction failed: {e}", source="simulation")
        stage["ml_prediction"] = time.perf_counter() - ml_start

        # 5) Decisions + actuators
        # Requirement alignment: ML should guide actuation (not only rule-based).
        act_start = time.perf_counter()
        decisions = []
        for pid in patient_ids:
            # Use latest processed readings for that patient
            pid_readings = [r for r in readings_processed if (r.tags or {}).get("patient_id") == pid]

            ml_pred = ml_predictions.get(pid)

            # ML-first control decision (fallback to rules when ML unavailable)
            if ml_pred and ml_pred.get("health_status"):
                status_norm = str(ml_pred.get("health_status", "")).strip().lower()
                status_norm = "critical" if status_norm == "critical" else "warning" if status_norm == "warning" else "normal"

                decision = {
                    "patient_id": pid,
                    "device_id": (pid_readings[0].device_id if pid_readings else f"patient_{pid}"),
                    "status": status_norm,
                    "alerts": [f"ML prediction: {ml_pred.get('health_status')} (conf={ml_pred.get('confidence')})"],
                    "confidence": float(ml_pred.get("confidence", 0.75)),
                    "cycle": self.current_cycle,
                    "timestamp": int(time.time()),
                    "decision_source": "ml",
                    "ml_algorithm": ml_pred.get("algorithm"),
                }
            else:
                decision = self._evaluate_health(pid, pid_readings)
                decision["decision_source"] = "rules"

            decisions.append(decision)
            total_decisions += 1

            # Activate actuators based on the decision
            states = health_actuator_controller.apply_decision(decision)
            actuator_states.extend(states)

            # Persist actuator states
            for st in states:
                mongodb_service.write_actuator_state(st)

        stage["actuator_decision"] = time.perf_counter() - act_start

        # Total
        stage["total"] = time.perf_counter() - t0

        # Persist response times (cycle-level)
        mongodb_service.write_response_times(cycle=cycle, response_times=stage, patient_id=patient_id or "all")

        # Build UI-friendly "readings" payload (raw vs processed)
        # Use a composite key to avoid collisions across patients/devices.
        processed_map = {}
        for pr in readings_processed:
            key = (pr.device_id, pr.sensor_id, pr.measurement)
            processed_map[key] = pr

        readings_payload = []
        for raw in readings_raw:
            key = (raw.device_id, raw.sensor_id, raw.measurement)
            pr = processed_map.get(key)
            readings_payload.append({
                "patient_id": (raw.tags or {}).get("patient_id"),
                "device_id": raw.device_id,
                "sensor_id": raw.sensor_id,
                "measurement": raw.measurement,
                "value": raw.value,
                "processed_value": pr.value if pr else None,
                "outlier": bool((pr.tags or {}).get("outlier")) if pr else False,
                "filtered": bool((pr.tags or {}).get("filtered")) if pr else bool(pr is None),
            })

        emergency_triggered = any(d.get("status") == "critical" for d in decisions)

        result = {
            "status": "success",
            "cycle": cycle,
            "patient_id": patient_id or "all",
            "simulate_emergency": bool(simulate_emergency),
            "emergency_triggered": bool(simulate_emergency) or emergency_triggered,
            "sensor_readings": total_sensor_readings,
            "decisions_made": total_decisions,
            "decisions": decisions,
            "ml_predictions": ml_predictions,
            "ml_retrain": retrain_result,
            "actuators_activated": len([a for a in actuator_states if a.state in ["ON", "ACTIVE"]]),
            "actuator_states": [self._actuator_to_dict(a) for a in actuator_states],
            "response_times": stage,
            "readings": readings_payload,
            "timestamp": time.time(),
        }

        iot_logger.info(
            f"Cycle {cycle} completed: readings={total_sensor_readings} decisions={total_decisions} emergency={simulate_emergency}",
            source="simulation"
        )
        return result

    def run_simulation(self, num_cycles: int = 20, delay_seconds: float = 2.0, patient_id: Optional[str] = None,
                       simulate_emergency: bool = False, emergency_rate: Optional[float] = None) -> Dict[str, Any]:
        """
        Run multiple cycles.

        Returns:
            {status, total_cycles, results, last_cycle_result}
        """
        self.is_running = True
        results: List[Dict[str, Any]] = []
        rate = DEFAULT_EMERGENCY_RATE
        if emergency_rate is not None:
            try:
                rate = float(emergency_rate)
            except (TypeError, ValueError):
                rate = DEFAULT_EMERGENCY_RATE
        if rate > 1.0:
            rate = rate / 100.0
        rate = max(0.0, min(rate, 1.0))

        for _ in range(int(num_cycles)):
            if not self.is_running:
                break
            cycle_emergency = bool(simulate_emergency) and random.random() < rate
            # Pass emergency_rate=1.0 so the per-cycle emergency flag is honored without re-randomizing
            res = self.run_single_cycle(patient_id=patient_id, simulate_emergency=cycle_emergency,
                                        emergency_rate=1.0)
            results.append(res)
            time.sleep(max(0.0, float(delay_seconds)))

        self.is_running = False
        return {
            "status": "success",
            "total_cycles": len(results),
            "results": results,
            "last_cycle_result": results[-1] if results else None,
        }

    def stop_simulation(self) -> Dict[str, Any]:
        self.is_running = False
        return {"status": "success", "message": "Simulation stopped"}

    def reset_run(self) -> Dict[str, Any]:
        """Reset in-memory simulation state."""
        self.is_running = False
        self.current_cycle = 0
        health_actuator_controller.reset_states()
        edge_processor.reset()
        return {"status": "success", "message": "Simulation state reset"}

    def _publish_processed_reading(self, reading: SensorReading) -> bool:
        """
        Publish a processed reading to MQTT; returns True if queued.
        """
        if not self.mqtt_ready or self.mqtt_client is None:
            return False

        try:
            tags = dict(reading.tags or {})
            pid = tags.get("patient_id") or "unknown"
            topic = f"iot/health/processed/{pid}/{reading.device_id}/{reading.measurement}"
            payload = json.dumps({
                "measurement": reading.measurement,
                "device_id": reading.device_id,
                "sensor_id": reading.sensor_id,
                "value": reading.value,
                "timestamp": reading.timestamp,
                "tags": tags,
            })
            # Fire-and-forget; QoS controlled by settings
            self.mqtt_client.publish(topic, payload, qos=getattr(settings, "MQTT_QOS", 1))
            return True
        except Exception as exc:
            iot_logger.warning(f"MQTT publish failed: {exc}", source="mqtt")
            return False

    # ------------------------
    # Rule-based fallback (used when ML is not trained)
    # ------------------------
    def _evaluate_health(self, patient_id: str, readings: List[SensorReading]) -> Dict[str, Any]:
        """
        Rule-based evaluation:
        - Determine overall status and alerts list based on thresholds.
        - Used as a fallback when ML is not trained or prediction is unavailable.
        """
        status = "normal"
        alerts: List[str] = []

        latest: Dict[str, float] = {}
        device_id: Optional[str] = None
        for r in readings:
            latest[r.measurement] = float(r.value)
            if device_id is None and r.device_id:
                device_id = r.device_id

        def raise_status(new_status: str) -> None:
            nonlocal status
            if status == "critical":
                return
            if new_status == "critical":
                status = "critical"
            elif new_status == "warning" and status == "normal":
                status = "warning"

        hr = latest.get("heart_rate")
        if hr is not None:
            if hr < 50 or hr > 150:
                raise_status("critical")
                alerts.append(f"Heart Rate critical: {hr} bpm")
            elif hr < 60 or hr > 120:
                raise_status("warning")
                alerts.append(f"Heart Rate warning: {hr} bpm")

        spo2 = latest.get("oxygen_saturation")
        if spo2 is not None:
            if spo2 < 90:
                raise_status("critical")
                alerts.append(f"SpO2 critical: {spo2}% (hypoxia)")
            elif spo2 < 95:
                raise_status("warning")
                alerts.append(f"SpO2 warning: {spo2}%")

        temp = latest.get("body_temperature")
        if temp is not None:
            if temp < 35.0 or temp > 39.0:
                raise_status("critical")
                alerts.append(f"Temperature critical: {temp}°C")
            elif temp < 36.0 or temp > 38.0:
                raise_status("warning")
                alerts.append(f"Temperature warning: {temp}°C")

        gluc = latest.get("glucose_level")
        if gluc is not None:
            if gluc < 70 or gluc > 200:
                raise_status("critical")
                alerts.append(f"Glucose critical: {gluc} mg/dL")
            elif gluc < 80 or gluc > 140:
                raise_status("warning")
                alerts.append(f"Glucose warning: {gluc} mg/dL")

        sys = latest.get("blood_pressure_systolic")
        dia = latest.get("blood_pressure_diastolic")
        if sys is not None and dia is not None:
            if sys > 180 or dia > 120 or sys < 90 or dia < 60:
                raise_status("critical")
                alerts.append(f"Blood Pressure critical: {sys}/{dia} mmHg")
            elif sys > 140 or dia > 90:
                raise_status("warning")
                alerts.append(f"Blood Pressure warning: {sys}/{dia} mmHg")

        return {
            "patient_id": patient_id,
            "device_id": device_id or f"patient_{patient_id}",
            "status": status,
            "alerts": alerts,
            "confidence": 0.9 if status == "normal" else 0.8 if status == "warning" else 0.85,
            "cycle": self.current_cycle,
            "timestamp": int(time.time()),
        }

    @staticmethod
    def _actuator_to_dict(a: ActuatorState) -> Dict[str, Any]:
        return {
            "actuator_id": a.actuator_id,
            "device_id": a.device_id,
            "actuator_type": a.actuator_type,
            "state": a.state,
            "value": a.value,
            "time": HealthSimulationEngine._datetime_utc_iso(a.timestamp),
        }

    @staticmethod
    def _datetime_utc_iso(ts: int) -> str:
        return datetime.utcfromtimestamp(int(ts)).isoformat() + "Z"


health_simulation_engine = HealthSimulationEngine()
