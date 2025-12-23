"""
Edge Processing Service
Implements data filtering, aggregation, and anomaly detection for health sensors
Acts as the gateway/edge tier between sensors and cloud (Phase 2 Requirement B)

Key improvements:
- Fixed stats double-counting (values were appended twice)
- Added explicit, structured edge metadata (range/noise/outlier stats and bounds)
- Corrected aggregation logic (measurement was incorrectly assumed constant)
- Safer tags handling when tags is None
- Deterministic and explainable filtering reasons (embedded in tags when kept;
  logged when dropped)
"""
import statistics
from typing import List, Dict, Optional, Tuple
from collections import deque

from app.models.sensor import SensorReading
from app.core.logger import iot_logger


class EdgeProcessor:
    """
    Edge processing service for health monitoring sensors.
    Performs initial filtration/processing before data reaches the gateway/cloud.
    """

    def __init__(self, window_size: int = 5, stats_window: int = 20):
        """
        Initialize edge processor

        Args:
            window_size: Size of moving average window for noise filtering
            stats_window: Size of rolling window used for outlier detection statistics
        """
        self.window_size = window_size
        self.stats_window = stats_window

        # Store recent readings for each sensor (for moving average)
        self.sensor_buffers: Dict[str, deque] = {}

        # Store rolling history for outlier detection (per sensor_key)
        self.sensor_history: Dict[str, deque] = {}

        # Store computed stats (mean/std/etc.) for observability
        self.sensor_stats: Dict[str, Dict] = {}

    def _sensor_key(self, reading: SensorReading) -> str:
        return f"{reading.device_id}_{reading.sensor_id}"

    def process_reading(self, reading: SensorReading) -> Optional[SensorReading]:
        """
        Process a single sensor reading through edge processing pipeline.

        Steps:
        1) Range validation (fast reject)
        2) Noise filtering (moving average)
        3) Outlier detection (IQR) based on rolling history
        4) Update stats and history (only after passing)
        5) Emit processed reading with edge metadata in tags

        Returns:
            Processed SensorReading or None if filtered out
        """
        sensor_key = self._sensor_key(reading)
        tags = (reading.tags or {}).copy()

        # 1) Range validation
        ok_range, range_info = self._validate_range(reading)
        if not ok_range:
            iot_logger.warning(
                f"Edge filter: range_invalid for {reading.measurement} value={reading.value}",
                source="edge_processor",
                device_id=reading.device_id,
                sensor_id=reading.sensor_id,
                metadata={
                    "measurement": reading.measurement,
                    "value": reading.value,
                    "reason": "range_invalid",
                    **range_info,
                },
            )
            return None

        # 2) Noise filtering (moving average)
        filtered_value, noise_info = self._apply_noise_filter(reading, sensor_key)

        # 3) Outlier detection (IQR) using history (do NOT mutate history before decision)
        outlier_ok, outlier_info = self._detect_outlier(sensor_key, filtered_value)
        if not outlier_ok:
            iot_logger.warning(
                f"Edge filter: outlier_detected for {reading.measurement} value={reading.value} filtered={filtered_value}",
                source="edge_processor",
                device_id=reading.device_id,
                sensor_id=reading.sensor_id,
                metadata={
                    "measurement": reading.measurement,
                    "value": reading.value,
                    "filtered_value": filtered_value,
                    "reason": "outlier_detected",
                    **outlier_info,
                },
            )
            return None

        # 4) Update history + stats only after passing filters
        self._update_history(sensor_key, filtered_value)
        self._update_statistics(sensor_key)

        # 5) Create processed reading with explicit metadata for demo/UI traceability
        processed_tags = {
            **tags,
            "processed_by": "edge_processor",
            "edge": {
                "range_validation": range_info,
                "noise_filter": noise_info,
                "outlier_detection": outlier_info,
            },
            "original_value": reading.value,
            "filtered_value": filtered_value,
            "filtered": reading.value != filtered_value,
        }

        return SensorReading(
            measurement=reading.measurement,
            device_id=reading.device_id,
            sensor_id=reading.sensor_id,
            value=filtered_value,
            timestamp=reading.timestamp,
            tags=processed_tags,
        )

    def process_batch(self, readings: List[SensorReading]) -> List[SensorReading]:
        """
        Process a batch of sensor readings.
        Returns only readings that pass edge checks.
        """
        processed: List[SensorReading] = []
        for reading in readings:
            out = self.process_reading(reading)
            if out is not None:
                processed.append(out)
        return processed

    def aggregate_readings(self, readings: List[SensorReading], window_seconds: int = 60) -> List[SensorReading]:
        """
        Aggregate sensor readings over a time window.

        FIXED:
        - measurement was previously assumed constant; now grouped per measurement too.

        Returns:
            Aggregated SensorReadings (mean aggregation)
        """
        if not readings:
            return []

        grouped: Dict[Tuple[str, str, int], List[float]] = {}
        # key = (sensor_key, measurement, window_start)
        for r in readings:
            sensor_key = self._sensor_key(r)
            window_start = (r.timestamp // window_seconds) * window_seconds
            key = (sensor_key, r.measurement, window_start)
            grouped.setdefault(key, []).append(r.value)

        aggregated: List[SensorReading] = []
        for (sensor_key, measurement, window_start), values in grouped.items():
            device_id, sensor_id = sensor_key.rsplit("_", 1)
            avg_value = statistics.mean(values)

            aggregated.append(
                SensorReading(
                    measurement=measurement,
                    device_id=device_id,
                    sensor_id=sensor_id,
                    value=round(avg_value, 2),
                    timestamp=window_start,
                    tags={
                        "processed_by": "edge_processor",
                        "aggregated": True,
                        "window_seconds": window_seconds,
                        "count": len(values),
                        "aggregate": "mean",
                    },
                )
            )

        return aggregated

    # ---------------------------
    # Validation / Filtering
    # ---------------------------

    def _validate_range(self, reading: SensorReading) -> Tuple[bool, Dict]:
        """
        Validate sensor reading is within expected range.
        Returns (ok, info_dict) for UI/logs.
        """
        ranges = {
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

        expected_range = ranges.get(reading.measurement)
        if not expected_range:
            return True, {"enabled": False, "reason": "unknown_measurement"}

        min_val, max_val = expected_range
        ok = min_val <= reading.value <= max_val
        return ok, {
            "enabled": True,
            "min": min_val,
            "max": max_val,
            "ok": ok,
        }

    def _apply_noise_filter(self, reading: SensorReading, sensor_key: str) -> Tuple[float, Dict]:
        """
        Apply moving average filter to reduce noise.
        Always returns a float (never None), to keep pipeline deterministic.

        Returns:
            (filtered_value, info_dict)
        """
        if sensor_key not in self.sensor_buffers:
            self.sensor_buffers[sensor_key] = deque(maxlen=self.window_size)

        buf = self.sensor_buffers[sensor_key]
        buf.append(reading.value)

        if len(buf) < 2:
            # Not enough history; return raw
            return reading.value, {
                "method": "moving_average",
                "window_size": self.window_size,
                "buffer_len": len(buf),
                "applied": False,
                "reason": "insufficient_history",
            }

        filtered = round(statistics.mean(buf), 2)
        return filtered, {
            "method": "moving_average",
            "window_size": self.window_size,
            "buffer_len": len(buf),
            "applied": True,
        }

    def _detect_outlier(self, sensor_key: str, filtered_value: float) -> Tuple[bool, Dict]:
        """
        Detect outliers using IQR method based on rolling history (without mutating history first).

        Returns:
            (ok, info_dict)
        """
        history = self.sensor_history.get(sensor_key)
        if not history:
            return True, {
                "method": "iqr",
                "enabled": True,
                "history_len": 0,
                "ok": True,
                "reason": "insufficient_history",
            }

        values = sorted(list(history))
        if len(values) < 4:
            return True, {
                "method": "iqr",
                "enabled": True,
                "history_len": len(values),
                "ok": True,
                "reason": "insufficient_history",
            }

        q1 = values[len(values) // 4]
        q3 = values[(3 * len(values)) // 4]
        iqr = q3 - q1

        # If iqr == 0, everything is identical; allow through unless wildly different.
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        is_outlier = filtered_value < lower_bound or filtered_value > upper_bound

        return (not is_outlier), {
            "method": "iqr",
            "enabled": True,
            "history_len": len(values),
            "q1": q1,
            "q3": q3,
            "iqr": iqr,
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "ok": (not is_outlier),
        }

    # ---------------------------
    # History + Stats
    # ---------------------------

    def _update_history(self, sensor_key: str, value: float) -> None:
        """Append value into rolling history used for outlier detection."""
        if sensor_key not in self.sensor_history:
            self.sensor_history[sensor_key] = deque(maxlen=self.stats_window)
        self.sensor_history[sensor_key].append(value)

    def _update_statistics(self, sensor_key: str) -> None:
        """Compute mean/std on current rolling history for observability."""
        history = self.sensor_history.get(sensor_key)
        if not history:
            return

        values = list(history)
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0

        self.sensor_stats[sensor_key] = {
            "history_len": len(values),
            "mean": mean,
            "std": std,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }

    # ---------------------------
    # Anomaly detection (rule-based)
    # ---------------------------

    def detect_anomaly(self, reading: SensorReading) -> Dict:
        """
        Detect anomalies based on health thresholds.

        Returns:
            {has_anomaly: bool, anomalies: list[str], severity: normal|warning|critical}
        """
        anomalies = []
        severity = "normal"

        if reading.measurement == "heart_rate":
            if reading.value < 50:
                anomalies.append("bradycardia")
                severity = "critical"
            elif reading.value > 120:
                anomalies.append("tachycardia")
                severity = "warning" if reading.value < 150 else "critical"

        elif reading.measurement == "oxygen_saturation":
            if reading.value < 90:
                anomalies.append("hypoxia")
                severity = "critical"

        elif reading.measurement == "body_temperature":
            if reading.value < 35.0:
                anomalies.append("hypothermia")
                severity = "critical"
            elif reading.value > 38.0:
                anomalies.append("fever")
                severity = "warning" if reading.value < 39.0 else "critical"

        elif reading.measurement == "glucose_level":
            if reading.value < 70:
                anomalies.append("hypoglycemia")
                severity = "critical"
            elif reading.value > 180:
                anomalies.append("hyperglycemia")
                severity = "warning"
        elif reading.measurement == "ambient_temperature":
            if reading.value < 18.0 or reading.value > 27.0:
                anomalies.append("room_temperature_out_of_range")
                severity = "warning"
        elif reading.measurement == "humidity":
            if reading.value < 25 or reading.value > 70:
                anomalies.append("humidity_out_of_range")
                severity = "warning"
        elif reading.measurement == "co2_level":
            if reading.value > 1500:
                anomalies.append("co2_high")
                severity = "warning"
        elif reading.measurement == "sound_level":
            if reading.value > 80:
                anomalies.append("noise_high")
                severity = "warning"

        return {
            "has_anomaly": len(anomalies) > 0,
            "anomalies": anomalies,
            "severity": severity,
        }

    def get_statistics(self, sensor_key: str) -> Optional[Dict]:
        """Get statistics for a sensor."""
        return self.sensor_stats.get(sensor_key)

    def reset(self):
        """Reset in-memory buffers and stats."""
        self.sensor_buffers = {}
        self.sensor_history = {}
        self.sensor_stats = {}


# Global instance
edge_processor = EdgeProcessor()
