"""
Edge Processing Service
Implements data filtering, aggregation, and anomaly detection for health sensors.
Acts as the gateway tier between sensors and cloud (Phase 2 Requirement B).

Design note (demo + realism):
- We SHOULD NOT drop clinically-important anomalies (critical/warning readings).
- Instead of filtering outliers by default, we tag them and allow the pipeline to continue.
  This preserves emergency scenarios and allows actuators + ML labels to reflect reality.
"""
import statistics
from collections import deque
from typing import List, Dict, Optional, Tuple

from app.core.logger import iot_logger
from app.models.sensor import SensorReading


class EdgeProcessor:
    """
    Edge processing service for health monitoring sensors.

    Pipeline:
      1) Range validation (hard bounds per measurement)
      2) Noise filtering (moving average)
      3) Outlier detection (IQR) - tag by default, optionally drop
      4) Statistics update (for normal readings, not outliers)
      5) Emit processed SensorReading with traceability tags
    """

    def __init__(self, window_size: int = 5, outlier_mode: str = "tag"):
        """
        Args:
            window_size: Size of moving average window for noise filtering
            outlier_mode: "tag" (default) or "drop"
                - "tag": preserve readings but mark outliers in tags
                - "drop": filter outliers out of the pipeline
        """
        self.window_size = window_size
        self.outlier_mode = outlier_mode
        self.sensor_buffers: Dict[str, deque] = {}
        self.sensor_stats: Dict[str, Dict] = {}

    def process_reading(self, reading: SensorReading) -> Optional[SensorReading]:
        """
        Process a single sensor reading through edge processing pipeline.

        Returns:
            Processed SensorReading, or None if filtered out (range invalid, or outlier_mode="drop").
        """
        sensor_key = f"{reading.device_id}_{reading.sensor_id}"

        # Step 1: Range validation (quick filter)
        if not self._validate_range(reading):
            iot_logger.warning(
                f"Reading out of range: {reading.measurement}={reading.value}",
                source="edge_processor",
                device_id=reading.device_id,
                sensor_id=reading.sensor_id
            )
            return None

        # Step 2: Noise filtering (moving average)
        filtered_value = self._apply_noise_filter(reading, sensor_key)
        if filtered_value is None:
            return None

        # Step 3: Outlier detection (IQR) using historical window (excluding current sample)
        is_outlier, bounds = self._is_outlier(sensor_key, filtered_value)

        if is_outlier and self.outlier_mode == "drop":
            iot_logger.warning(
                f"Outlier dropped: {reading.measurement}={filtered_value}",
                source="edge_processor",
                device_id=reading.device_id,
                sensor_id=reading.sensor_id,
                metadata={"outlier_bounds": bounds}
            )
            return None

        # Step 4: Update statistics (do not contaminate stats with outliers)
        if not is_outlier:
            self._update_statistics(sensor_key, filtered_value)

        # Step 5: Create processed reading with traceability tags
        tags = dict(reading.tags or {})
        tags.update({
            "processed_by": "edge_processor",
            "original_value": reading.value,
            "filtered": reading.value != filtered_value,
            "outlier": bool(is_outlier),
        })
        if bounds:
            tags["outlier_bounds"] = bounds

        processed_reading = SensorReading(
            measurement=reading.measurement,
            device_id=reading.device_id,
            sensor_id=reading.sensor_id,
            value=filtered_value,
            timestamp=reading.timestamp,
            tags=tags
        )
        iot_logger.info(
            f"Edge processed: {reading.measurement}={filtered_value}",
            source="edge_processor",
            device_id=reading.device_id,
            sensor_id=reading.sensor_id,
            metadata={"original_value": reading.value, "outlier": bool(is_outlier)}
        )
        return processed_reading

    def process_batch(self, readings: List[SensorReading]) -> List[SensorReading]:
        """Process a batch of sensor readings."""
        processed: List[SensorReading] = []
        for reading in readings:
            pr = self.process_reading(reading)
            if pr is not None:
                processed.append(pr)
        return processed

    def aggregate_readings(self, readings: List[SensorReading], window_seconds: int = 60) -> List[SensorReading]:
        """
        Aggregate sensor readings over a time window (mean).

        Notes:
        - Aggregation is measurement-aware (no "readings[0].measurement" bug).
        """
        if not readings:
            return []

        grouped: Dict[Tuple[str, int, str], List[float]] = {}
        for reading in readings:
            sensor_key = f"{reading.device_id}_{reading.sensor_id}"
            window_start = (int(reading.timestamp) // window_seconds) * window_seconds
            key = (sensor_key, window_start, reading.measurement)
            grouped.setdefault(key, []).append(reading.value)

        aggregated: List[SensorReading] = []
        for (sensor_key, window_start, measurement), values in grouped.items():
            device_id, sensor_id = sensor_key.rsplit('_', 1)
            avg_value = statistics.mean(values)
            aggregated.append(SensorReading(
                measurement=measurement,
                device_id=device_id,
                sensor_id=sensor_id,
                value=round(avg_value, 2),
                timestamp=window_start,
                tags={
                    "aggregated": True,
                    "window_seconds": window_seconds,
                    "count": len(values),
                    "processed_by": "edge_processor"
                }
            ))
        return aggregated

    def _validate_range(self, reading: SensorReading) -> bool:
        """Validate sensor reading is within expected hard bounds (device plausibility bounds)."""
        ranges = {
            "heart_rate": (40, 200),
            "blood_pressure_systolic": (70, 220),
            "blood_pressure_diastolic": (40, 140),
            "body_temperature": (35.0, 42.0),
            "oxygen_saturation": (70, 100),
            "glucose_level": (40, 400),
            "activity_steps": (0, 50000),
        }
        expected = ranges.get(reading.measurement)
        if not expected:
            return True
        lo, hi = expected
        return lo <= reading.value <= hi

    def _apply_noise_filter(self, reading: SensorReading, sensor_key: str) -> Optional[float]:
        """Apply moving average filter to reduce noise."""
        if sensor_key not in self.sensor_buffers:
            self.sensor_buffers[sensor_key] = deque(maxlen=self.window_size)

        buf = self.sensor_buffers[sensor_key]
        buf.append(reading.value)

        # Not enough for smoothing; keep original value
        if len(buf) < 2:
            return float(reading.value)

        return round(float(statistics.mean(buf)), 2)

    def _is_outlier(self, sensor_key: str, value: float) -> Tuple[bool, Optional[dict]]:
        """
        Detect outliers using IQR (Interquartile Range) method, based on historical values.

        Returns:
            (is_outlier, bounds_dict_or_none)
        """
        # Initialize stats bucket
        if sensor_key not in self.sensor_stats:
            self.sensor_stats[sensor_key] = {"values": deque(maxlen=20), "mean": None, "std": None}

        stats = self.sensor_stats[sensor_key]
        hist = list(stats["values"])  # historical values only (no current appended)

        # Need at least 4 historical values to establish IQR
        if len(hist) < 4:
            return (False, None)

        hist_sorted = sorted(hist)
        n = len(hist_sorted)
        q1 = hist_sorted[n // 4]
        q3 = hist_sorted[(3 * n) // 4]
        iqr = q3 - q1

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        is_outlier = value < lower or value > upper
        return (is_outlier, {"lower": round(float(lower), 2), "upper": round(float(upper), 2)})

    def _update_statistics(self, sensor_key: str, value: float):
        """Update rolling statistics for non-outlier readings."""
        if sensor_key not in self.sensor_stats:
            self.sensor_stats[sensor_key] = {"values": deque(maxlen=20), "mean": None, "std": None}

        stats = self.sensor_stats[sensor_key]
        stats["values"].append(float(value))
        stats["mean"] = float(statistics.mean(stats["values"]))
        stats["std"] = float(statistics.stdev(stats["values"])) if len(stats["values"]) > 1 else 0.0

    def detect_anomaly(self, reading: SensorReading) -> Dict:
        """
        Detect anomalies based on health thresholds (clinical semantics).

        This is separate from statistical outlier detection.
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

        return {"has_anomaly": bool(anomalies), "anomalies": anomalies, "severity": severity}

    def get_statistics(self, sensor_key: str) -> Optional[Dict]:
        """Get statistics for a sensor."""
        return self.sensor_stats.get(sensor_key)

    def reset(self) -> None:
        """Clear in-memory buffers and stats."""
        self.sensor_buffers = {}
        self.sensor_stats = {}


# Global instance
edge_processor = EdgeProcessor()
