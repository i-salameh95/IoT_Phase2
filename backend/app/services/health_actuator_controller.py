"""
Health Monitoring Actuator Controller
Implements ML-based and rule-based decision making for health monitoring
"""
import time
from typing import Dict, List, Optional

from app.models.actuator import ActuatorState
from app.models.sensor import SensorReading
from app.core.logger import iot_logger


class HealthActuatorController:
    """Health monitoring controller that makes decisions based on health sensor data"""
    
    # Health thresholds
    HEART_RATE_LOW = 50  # bpm - bradycardia
    HEART_RATE_HIGH = 120  # bpm - tachycardia
    BP_SYSTOLIC_LOW = 90  # mmHg - hypotension
    BP_SYSTOLIC_HIGH = 180  # mmHg - hypertension
    BP_DIASTOLIC_LOW = 60  # mmHg
    BP_DIASTOLIC_HIGH = 120  # mmHg
    TEMP_LOW = 35.0  # C - hypothermia
    TEMP_HIGH = 38.0  # C - fever
    SPO2_LOW = 90  # % - hypoxia
    GLUCOSE_LOW = 70  # mg/dL - hypoglycemia
    GLUCOSE_HIGH = 180  # mg/dL - hyperglycemia
    ROOM_TEMP_LOW = 18.0  # C - room temperature low
    ROOM_TEMP_HIGH = 27.0  # C - room temperature high
    HUMIDITY_LOW = 25  # % RH
    HUMIDITY_HIGH = 70  # % RH
    CO2_HIGH = 1500  # ppm
    SOUND_HIGH = 80  # dB
    
    def __init__(self):
        # Track actuator states per device (actuator_id -> state)
        self.actuators: Dict[str, str] = {}
        # ML model will be integrated later
        self.ml_model = None
    
    def process_sensor_readings(
        self, 
        readings: List[SensorReading],
        ml_prediction: Optional[Dict] = None
    ) -> List[ActuatorState]:
        """
        Process health sensor readings and make decisions
        
        Args:
            readings: List of health sensor readings
            ml_prediction: Optional ML model prediction (health_status, confidence)
        
        Returns:
            List of ActuatorState changes
        """
        # Group readings by measurement type
        sensor_data: Dict[str, List[SensorReading]] = {}
        for reading in readings:
            sensor_data.setdefault(reading.measurement, []).append(reading)
        
        actuator_states: List[ActuatorState] = []
        
        # Get patient_id from first reading (all readings should be from same patient)
        patient_id = readings[0].tags.get("patient_id", "unknown") if readings else "unknown"
        
        # Use ML prediction if available, otherwise use rule-based
        if ml_prediction and ml_prediction.get("health_status"):
            health_status = ml_prediction["health_status"]
            confidence = ml_prediction.get("confidence", 0.0)
            
            # ML-based decision making
            actuator_states.extend(
                self._ml_based_decisions(health_status, confidence, patient_id, sensor_data)
            )
        else:
            # Rule-based decision making (fallback)
            actuator_states.extend(self._rule_based_decisions(sensor_data, patient_id))
        
        return actuator_states
    
    def _ml_based_decisions(
        self,
        health_status: str,
        confidence: float,
        patient_id: str,
        sensor_data: Dict[str, List[SensorReading]]
    ) -> List[ActuatorState]:
        """Make decisions based on ML model prediction"""
        actuator_states = []
        timestamp = int(time.time())
        
        # Extract device_id (assuming all readings from same patient)
        device_id = sensor_data.get("heart_rate", [{}])[0].device_id if sensor_data.get("heart_rate") else f"patient_{patient_id}"
        
        if health_status == "Critical":
            # Critical: Activate all emergency systems
            actuator_states.extend(self._activate_emergency(device_id, patient_id, timestamp))
        
        elif health_status == "Warning":
            # Warning: Activate alerts, generate health report
            actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
        
        elif health_status == "Normal":
            # Normal: Routine monitoring, no action needed
            # But check for any critical individual readings (safety rules)
            actuator_states.extend(self._check_safety_rules(sensor_data, device_id, patient_id, timestamp))
        
        return actuator_states
    
    def _rule_based_decisions(
        self,
        sensor_data: Dict[str, List[SensorReading]],
        patient_id: str
    ) -> List[ActuatorState]:
        """Rule-based decision making (fallback when ML not available)"""
        actuator_states = []
        timestamp = int(time.time())
        
        # Get device_id
        device_id = sensor_data.get("heart_rate", [{}])[0].device_id if sensor_data.get("heart_rate") else f"patient_{patient_id}"
        
        # Rule 1: Heart Rate monitoring
        if "heart_rate" in sensor_data:
            for hr_reading in sensor_data["heart_rate"]:
                hr_value = hr_reading.value
                actuator_id = f"{device_id}_alert"
                
                if hr_value < self.HEART_RATE_LOW or hr_value > self.HEART_RATE_HIGH:
                    # Critical heart rate
                    actuator_states.extend(self._activate_emergency(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"Heart Rate = {hr_value} bpm -> Emergency Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=hr_reading.sensor_id,
                        metadata={"rule": "heart_rate_critical", "action": "emergency"},
                    )
        
        # Rule 2: Blood Pressure monitoring
        if "blood_pressure_systolic" in sensor_data and "blood_pressure_diastolic" in sensor_data:
            for bp_sys in sensor_data["blood_pressure_systolic"]:
                for bp_dia in sensor_data["blood_pressure_diastolic"]:
                    if bp_sys.device_id == bp_dia.device_id:
                        sys_value = bp_sys.value
                        dia_value = bp_dia.value
                        
                        if (sys_value < self.BP_SYSTOLIC_LOW or sys_value > self.BP_SYSTOLIC_HIGH or
                            dia_value < self.BP_DIASTOLIC_LOW or dia_value > self.BP_DIASTOLIC_HIGH):
                            actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
                            iot_logger.warning(
                                f"Blood Pressure = {sys_value}/{dia_value} mmHg -> Alert",
                                source="controller",
                                device_id=device_id,
                                sensor_id=bp_sys.sensor_id,
                                metadata={"rule": "blood_pressure_abnormal", "action": "alert"},
                            )
        
        # Rule 3: Temperature monitoring
        if "body_temperature" in sensor_data:
            for temp_reading in sensor_data["body_temperature"]:
                temp_value = temp_reading.value
                
                if temp_value < self.TEMP_LOW or temp_value > self.TEMP_HIGH:
                    if temp_value > 38.5:  # High fever
                        actuator_states.extend(self._activate_emergency(device_id, patient_id, timestamp))
                    else:
                        actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"Temperature = {temp_value} C -> Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=temp_reading.sensor_id,
                        metadata={"rule": "temperature_abnormal", "action": "alert"},
                    )
        
        # Rule 4: Oxygen Saturation monitoring
        if "oxygen_saturation" in sensor_data:
            for spo2_reading in sensor_data["oxygen_saturation"]:
                spo2_value = spo2_reading.value
                
                if spo2_value < self.SPO2_LOW:
                    actuator_states.extend(self._activate_emergency(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"SpO2 = {spo2_value}% -> Emergency Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=spo2_reading.sensor_id,
                        metadata={"rule": "spo2_critical", "action": "emergency"},
                    )

        # Rule 4b: Room environment monitoring (hospital/ward)
        if "ambient_temperature" in sensor_data:
            for temp_reading in sensor_data["ambient_temperature"]:
                if temp_reading.value < self.ROOM_TEMP_LOW or temp_reading.value > self.ROOM_TEMP_HIGH:
                    actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"Room Temp = {temp_reading.value} C -> Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=temp_reading.sensor_id,
                        metadata={"rule": "room_temp_out_of_range", "action": "alert"},
                    )

        if "humidity" in sensor_data:
            for hum_reading in sensor_data["humidity"]:
                if hum_reading.value < self.HUMIDITY_LOW or hum_reading.value > self.HUMIDITY_HIGH:
                    actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"Humidity = {hum_reading.value}% -> Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=hum_reading.sensor_id,
                        metadata={"rule": "humidity_out_of_range", "action": "alert"},
                    )

        if "co2_level" in sensor_data:
            for co2_reading in sensor_data["co2_level"]:
                if co2_reading.value > self.CO2_HIGH:
                    actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"CO2 = {co2_reading.value} ppm -> Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=co2_reading.sensor_id,
                        metadata={"rule": "co2_high", "action": "alert"},
                    )

        if "sound_level" in sensor_data:
            for sound_reading in sensor_data["sound_level"]:
                if sound_reading.value > self.SOUND_HIGH:
                    actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"Noise = {sound_reading.value} dB -> Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=sound_reading.sensor_id,
                        metadata={"rule": "noise_high", "action": "alert"},
                    )

        # Rule 5: Glucose monitoring (for diabetic patients)
        if "glucose_level" in sensor_data:
            for glucose_reading in sensor_data["glucose_level"]:
                glucose_value = glucose_reading.value
                
                if glucose_value < self.GLUCOSE_LOW:
                    # Hypoglycemia - activate medication dispenser
                    actuator_states.append(ActuatorState(
                        actuator_id=f"{device_id}_medication_dispenser",
                        device_id=device_id,
                        actuator_type="medication_dispenser",
                        state="ON",
                        value=15.0,  # Glucose dose
                        timestamp=timestamp,
                        tags={"patient_id": patient_id, "medication": "glucose"}
                    ))
                    iot_logger.warning(
                        f"Glucose = {glucose_value} mg/dL -> Medication Dispensed",
                        source="controller",
                        device_id=device_id,
                        sensor_id=glucose_reading.sensor_id,
                        metadata={"rule": "hypoglycemia", "action": "medication"},
                    )
                elif glucose_value > self.GLUCOSE_HIGH:
                    actuator_states.extend(self._activate_warning(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"Glucose = {glucose_value} mg/dL -> Alert",
                        source="controller",
                        device_id=device_id,
                        sensor_id=glucose_reading.sensor_id,
                        metadata={"rule": "hyperglycemia", "action": "alert"},
                    )
        
        return actuator_states
    
    def _activate_emergency(self, device_id: str, patient_id: str, timestamp: int) -> List[ActuatorState]:
        """Activate emergency systems"""
        states = []
        
        # Emergency Call
        actuator_id = f"{device_id}_emergency_call"
        if self.actuators.get(actuator_id) != "ON":
            self.actuators[actuator_id] = "ON"
            states.append(ActuatorState(
                actuator_id=actuator_id,
                device_id=device_id,
                actuator_type="emergency_call",
                state="ON",
                timestamp=timestamp,
                tags={"patient_id": patient_id, "severity": "critical"}
            ))
        
        # Alert System
        actuator_id = f"{device_id}_alert"
        if self.actuators.get(actuator_id) != "ON":
            self.actuators[actuator_id] = "ON"
            states.append(ActuatorState(
                actuator_id=actuator_id,
                device_id=device_id,
                actuator_type="alert",
                state="ON",
                timestamp=timestamp,
                tags={"patient_id": patient_id, "severity": "critical"}
            ))
        
        return states
    
    def _activate_warning(self, device_id: str, patient_id: str, timestamp: int) -> List[ActuatorState]:
        """Activate warning systems"""
        states = []
        
        # Alert System (warning level)
        actuator_id = f"{device_id}_alert"
        if self.actuators.get(actuator_id) != "ON":
            self.actuators[actuator_id] = "ON"
            states.append(ActuatorState(
                actuator_id=actuator_id,
                device_id=device_id,
                actuator_type="alert",
                state="ON",
                timestamp=timestamp,
                tags={"patient_id": patient_id, "severity": "warning"}
            ))
        
        # Health Report Generator
        actuator_id = f"{device_id}_health_report"
        if self.actuators.get(actuator_id) != "ACTIVE":
            self.actuators[actuator_id] = "ACTIVE"
            states.append(ActuatorState(
                actuator_id=actuator_id,
                device_id=device_id,
                actuator_type="health_report",
                state="ACTIVE",
                timestamp=timestamp,
                tags={"patient_id": patient_id}
            ))
        
        return states
    
    def _check_safety_rules(
        self,
        sensor_data: Dict[str, List[SensorReading]],
        device_id: str,
        patient_id: str,
        timestamp: int
    ) -> List[ActuatorState]:
        """Check safety rules even when ML says Normal (safety override)"""
        states = []
        
        # Safety rule: SpO2 < 85% always triggers emergency
        if "oxygen_saturation" in sensor_data:
            for spo2_reading in sensor_data["oxygen_saturation"]:
                if spo2_reading.value < 85:
                    states.extend(self._activate_emergency(device_id, patient_id, timestamp))
                    iot_logger.warning(
                        f"Safety Rule: SpO2 = {spo2_reading.value}% < 85% -> Emergency Override",
                        source="controller",
                        device_id=device_id,
                        sensor_id=spo2_reading.sensor_id,
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
