"""
Health Monitoring Sensor Simulator
Generates virtual health sensor data for patient monitoring
"""
import random
import time
from typing import List, Optional

from app.models.sensor import SensorReading


class HealthSensorSimulator:
    """Simulates health monitoring IoT sensor data"""
    
    def __init__(self):
        # Patient monitoring devices
        self.devices = [
            {"device_id": "patient_001_wearable", "location": "wrist", "patient_id": "P001"},
            {"device_id": "patient_001_bedside", "location": "bedside", "patient_id": "P001"},
            {"device_id": "patient_001_glucose", "location": "portable", "patient_id": "P001"},
            {"device_id": "patient_001_room", "location": "room", "patient_id": "P001"},
            {"device_id": "patient_002_wearable", "location": "wrist", "patient_id": "P002"},
            {"device_id": "patient_002_bedside", "location": "bedside", "patient_id": "P002"},
            {"device_id": "patient_002_room", "location": "room", "patient_id": "P002"},
        ]
        
        # Health monitoring sensor types
        self.sensor_types = [
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
        ]
        
        # Device-sensor mapping
        self.device_sensors = {
            "patient_001_wearable": ["heart_rate", "oxygen_saturation", "body_temperature", "activity_steps"],
            "patient_001_bedside": ["blood_pressure_systolic", "blood_pressure_diastolic", "body_temperature"],
            "patient_001_glucose": ["glucose_level"],
            "patient_001_room": ["ambient_temperature", "humidity", "light_level", "motion_detected", "co2_level", "sound_level"],
            "patient_002_wearable": ["heart_rate", "oxygen_saturation", "body_temperature", "activity_steps"],
            "patient_002_bedside": ["blood_pressure_systolic", "blood_pressure_diastolic", "body_temperature"],
            "patient_002_room": ["ambient_temperature", "humidity", "light_level", "motion_detected", "co2_level", "sound_level"],
        }
        self.edge_sensor_types = {"oxygen_saturation"}
        self.edge_max_attempts = 3
    
    def generate_reading(
        self,
        device_id: Optional[str] = None,
        sensor_type: Optional[str] = None,
        simulate_emergency: bool = False
    ) -> SensorReading:
        """
        Generate a simulated health sensor reading
        
        Args:
            device_id: Specific device (random if not provided)
            sensor_type: Specific sensor type (random if not provided)
            simulate_emergency: If True, may generate critical values
        
        Returns:
            SensorReading with health data
        """
        # Select random device if not specified
        if not device_id:
            device = random.choice(self.devices)
            device_id = device["device_id"]
        else:
            device = next((d for d in self.devices if d["device_id"] == device_id), self.devices[0])
        
        # Get available sensors for this device
        available_sensors = self.device_sensors.get(device_id, self.sensor_types)
        
        # Select random sensor type if not specified
        if not sensor_type:
            sensor_type = random.choice(available_sensors)
        elif sensor_type not in available_sensors:
            sensor_type = available_sensors[0] if available_sensors else self.sensor_types[0]
        
        # Generate value based on sensor type
        value = self._generate_sensor_value(sensor_type, simulate_emergency)
        
        reading = SensorReading(
            measurement=sensor_type,
            device_id=device_id,
            sensor_id=f"{device_id}_{sensor_type}",
            value=value,
            timestamp=int(time.time()),
            tags={
                "location": device.get("location", "unknown"),
                "patient_id": device.get("patient_id", "unknown"),
                "device_type": device_id.split("_")[-1]  # wearable, bedside, glucose
            }
        )

        if sensor_type in self.edge_sensor_types:
            from app.services.edge_processor import edge_processor

            processed = None
            attempt = 0
            while attempt < self.edge_max_attempts and processed is None:
                attempt += 1
                processed = edge_processor.process_reading(reading)
                if processed is None:
                    reading.value = self._generate_sensor_value(sensor_type, simulate_emergency)

            if processed is not None:
                processed.tags = (processed.tags or {})
                processed.tags["processed_by"] = "sensor_edge"
                processed.tags["sensor_edge_type"] = sensor_type
                processed.tags["sensor_edge_attempts"] = attempt
                return processed

            reading.tags["processed_by"] = "sensor_edge_failed"
            reading.tags["sensor_edge_attempts"] = attempt

        return reading
    
    def _generate_sensor_value(self, sensor_type: str, simulate_emergency: bool = False) -> float:
        """Generate sensor value based on type"""
        
        if simulate_emergency:
            # Generate critical values for emergency simulation
            emergency_values = {
                "heart_rate": random.choice([random.uniform(40, 50), random.uniform(150, 200)]),  # Bradycardia or Tachycardia
                "blood_pressure_systolic": random.choice([random.uniform(70, 90), random.uniform(180, 220)]),  # Low or High
                "blood_pressure_diastolic": random.choice([random.uniform(40, 60), random.uniform(110, 140)]),
                "body_temperature": random.choice([random.uniform(35.0, 35.5), random.uniform(38.5, 42.0)]),  # Hypothermia or Fever
                "oxygen_saturation": random.uniform(70, 90),  # Hypoxia
                "glucose_level": random.choice([random.uniform(40, 70), random.uniform(200, 400)]),  # Hypo or Hyperglycemia
                "activity_steps": random.uniform(0, 100),  # Low activity
                "ambient_temperature": random.choice([random.uniform(16.0, 18.0), random.uniform(28.0, 32.0)]),
                "humidity": random.choice([random.uniform(15, 25), random.uniform(75, 90)]),
                "light_level": random.choice([random.uniform(0, 30), random.uniform(1200, 1600)]),
                "motion_detected": 1.0,
                "co2_level": random.uniform(2000, 3000),
                "sound_level": random.uniform(85, 110),
            }
            return round(emergency_values.get(sensor_type, 0.0), 1)
        
        # Normal ranges
        normal_ranges = {
            "heart_rate": (60, 100),  # bpm - normal resting heart rate
            "blood_pressure_systolic": (90, 140),  # mmHg - normal systolic
            "blood_pressure_diastolic": (60, 90),  # mmHg - normal diastolic
            "body_temperature": (36.1, 37.2),  # C - normal body temperature
            "oxygen_saturation": (95, 100),  # % - normal SpO2
            "glucose_level": (70, 100),  # mg/dL - normal fasting glucose
            "activity_steps": (0, 20000),  # steps per day
            "ambient_temperature": (20.0, 24.0),  # room temperature (C)
            "humidity": (30, 60),  # % RH
            "light_level": (100, 800),  # lux
            "motion_detected": (0, 1),  # boolean
            "co2_level": (400, 1000),  # ppm
            "sound_level": (30, 60),  # dB
        }
        
        min_val, max_val = normal_ranges.get(sensor_type, (0, 100))
        if sensor_type == "motion_detected":
            value = float(random.choice([0, 1]))
        else:
            value = round(random.uniform(min_val, max_val), 1)
        
        # Add some realistic variation (occasional slight deviations)
        if random.random() < 0.1:  # 10% chance of slight deviation
            if sensor_type == "heart_rate":
                value = round(random.uniform(50, 110), 1)  # Slightly outside normal
            elif sensor_type == "body_temperature":
                value = round(random.uniform(35.5, 37.5), 1)  # Slight variation
        
        return value
    
    def generate_all_sensor_readings(self, device_id: Optional[str] = None) -> List[SensorReading]:
        """
        Generate readings for all sensor types for a device
        
        Args:
            device_id: Device ID (random if not provided)
        
        Returns:
            List of SensorReading for all sensor types
        """
        if not device_id:
            device = random.choice(self.devices)
            device_id = device["device_id"]
        
        readings = []
        available_sensors = self.device_sensors.get(device_id, self.sensor_types)
        
        for sensor_type in available_sensors:
            readings.append(self.generate_reading(device_id=device_id, sensor_type=sensor_type))
        
        return readings
    
    def generate_batch(self, count: int = 10, simulate_emergency: bool = False) -> List[SensorReading]:
        """Generate a batch of sensor readings"""
        return [self.generate_reading(simulate_emergency=simulate_emergency) for _ in range(count)]
    
    def generate_patient_readings(self, patient_id: str) -> List[SensorReading]:
        """Generate all sensor readings for a specific patient"""
        patient_devices = [d for d in self.devices if d.get("patient_id") == patient_id]
        all_readings = []
        
        for device in patient_devices:
            device_readings = self.generate_all_sensor_readings(device_id=device["device_id"])
            all_readings.extend(device_readings)
        
        return all_readings


# Global instance
health_sensor_simulator = HealthSensorSimulator()
