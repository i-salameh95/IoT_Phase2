"""
Health Monitoring Actuator Controller

Applies decisions computed by the simulation engine (ML-first with rule-based
fallback) to the actuators: alert system, emergency call, health report
generator, medication dispenser.
"""
import time
from typing import Dict, List

from app.core.logger import iot_logger
from app.models.actuator import ActuatorState


class HealthActuatorController:
    """Turns patient status decisions into actuator state changes."""

    GLUCOSE_LOW = 70  # mg/dL - hypoglycemia -> dispense glucose
    GLUCOSE_DOSE = 15.0

    def __init__(self):
        # Track actuator states per device (actuator_id -> state)
        self.actuators: Dict[str, str] = {}

    def apply_decision(self, decision: Dict) -> List[ActuatorState]:
        """
        Apply a precomputed decision payload from the simulation engine.

        - critical -> emergency call + alert ON
        - warning  -> alert ON + health report ACTIVE
        - normal   -> clear (OFF) any active actuators for the device
        """
        if not decision:
            return []

        status = str(decision.get("status", "normal")).lower()
        patient_id = decision.get("patient_id", "unknown")
        device_id = decision.get("device_id") or f"patient_{patient_id}"
        timestamp = int(time.time())

        iot_logger.info(
            f"Decision applied: {status}",
            source="controller",
            device_id=device_id,
            metadata={"patient_id": patient_id, "status": status, "cycle": decision.get("cycle")}
        )

        if status == "critical":
            states = self._activate_emergency(device_id, patient_id, timestamp)
        elif status == "warning":
            states = self._activate_warning(device_id, patient_id, timestamp)
        else:
            states = self._deactivate_all(device_id, patient_id, timestamp)

        states += self._apply_medication_rules(decision, device_id, patient_id, timestamp)
        return states

    def _apply_medication_rules(
            self,
            decision: Dict,
            device_id: str,
            patient_id: str,
            timestamp: int
    ) -> List[ActuatorState]:
        """Hypoglycemia -> dispense glucose; stop dispensing once glucose recovers."""
        readings = decision.get("latest_readings") or {}
        glucose = readings.get("glucose_level")
        if glucose is None:
            return []

        if glucose < self.GLUCOSE_LOW:
            states = self._set_state(
                device_id, patient_id, "medication_dispenser", "ON", timestamp,
                value=self.GLUCOSE_DOSE, tags={"medication": "glucose"}
            )
            if states:
                iot_logger.warning(
                    f"Glucose = {glucose} mg/dL -> Medication Dispensed",
                    source="controller",
                    device_id=device_id,
                    metadata={"rule": "hypoglycemia", "action": "medication", "patient_id": patient_id},
                )
            return states

        return self._set_state(device_id, patient_id, "medication_dispenser", "OFF", timestamp)

    def _set_state(
            self,
            device_id: str,
            patient_id: str,
            actuator_type: str,
            state: str,
            timestamp: int,
            value: float = None,
            tags: Dict = None
    ) -> List[ActuatorState]:
        """Set one actuator state; returns a change record only on transitions."""
        actuator_id = f"{device_id}_{actuator_type}"
        if self.actuators.get(actuator_id) == state:
            return []

        self.actuators[actuator_id] = state
        return [ActuatorState(
            actuator_id=actuator_id,
            device_id=device_id,
            actuator_type=actuator_type,
            state=state,
            value=value,
            timestamp=timestamp,
            tags={"patient_id": patient_id, **(tags or {})}
        )]

    def _activate_emergency(self, device_id: str, patient_id: str, timestamp: int) -> List[ActuatorState]:
        """Activate emergency systems (emergency call + alert)."""
        states = []
        states += self._set_state(device_id, patient_id, "emergency_call", "ON", timestamp,
                                  tags={"severity": "critical"})
        states += self._set_state(device_id, patient_id, "alert", "ON", timestamp,
                                  tags={"severity": "critical"})
        return states

    def _activate_warning(self, device_id: str, patient_id: str, timestamp: int) -> List[ActuatorState]:
        """Activate warning systems (alert + health report)."""
        states = []
        states += self._set_state(device_id, patient_id, "alert", "ON", timestamp,
                                  tags={"severity": "warning"})
        states += self._set_state(device_id, patient_id, "health_report", "ACTIVE", timestamp)
        # An emergency call from a previous critical cycle is no longer needed
        if self.actuators.get(f"{device_id}_emergency_call") == "ON":
            states += self._set_state(device_id, patient_id, "emergency_call", "OFF", timestamp)
        return states

    def _deactivate_all(self, device_id: str, patient_id: str, timestamp: int) -> List[ActuatorState]:
        """Patient back to normal: turn off any active actuator for the device."""
        states = []
        for actuator_id, state in list(self.actuators.items()):
            if not actuator_id.startswith(f"{device_id}_") or state == "OFF":
                continue
            actuator_type = actuator_id[len(device_id) + 1:]
            states += self._set_state(device_id, patient_id, actuator_type, "OFF", timestamp)
        if states:
            iot_logger.info(
                f"Status normal -> {len(states)} actuator(s) turned OFF",
                source="controller",
                device_id=device_id,
                metadata={"patient_id": patient_id}
            )
        return states

    def get_actuator_states(self) -> Dict[str, str]:
        """Get current state of all actuators"""
        return self.actuators.copy()

    def reset_states(self):
        """Clear in-memory actuator states."""
        self.actuators = {}


# Global instance
health_actuator_controller = HealthActuatorController()
