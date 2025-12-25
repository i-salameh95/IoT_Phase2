"""
Shared sensor configuration for ranges and defaults.
"""

SENSOR_VALID_RANGES = {
    "heart_rate": (40, 200),
    "blood_pressure_systolic": (70, 220),
    "blood_pressure_diastolic": (40, 140),
    "body_temperature": (35.0, 42.0),
    "oxygen_saturation": (70, 100),
    "glucose_level": (40, 400),
    "activity_steps": (0, 50000),
    "ambient_temperature": (15.0, 35.0),
    "humidity": (10, 90),
    "light_level": (0, 2000),
    "motion_detected": (0, 1),
    "co2_level": (350, 5000),
    "sound_level": (10, 120),
}

SENSOR_NORMAL_RANGES = {
    "heart_rate": (60, 100),
    "blood_pressure_systolic": (90, 140),
    "blood_pressure_diastolic": (60, 90),
    "body_temperature": (36.1, 37.2),
    "oxygen_saturation": (95, 100),
    "glucose_level": (70, 100),
    "activity_steps": (0, 20000),
    "ambient_temperature": (20.0, 24.0),
    "humidity": (30, 60),
    "light_level": (100, 800),
    "motion_detected": (0, 1),
    "co2_level": (400, 1000),
    "sound_level": (30, 60),
}
