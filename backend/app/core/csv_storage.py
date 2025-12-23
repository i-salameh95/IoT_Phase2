"""
CSV-based fallback storage for Phase 1
Used when MongoDB isn't reachable so the simulator can still operate.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class CSVStorage:
    """Simple CSV storage for sensor readings, actuator states, and logs."""

    SENSOR_HEADERS = [
        "timestamp",
        "measurement",
        "device_id",
        "sensor_id",
        "value",
        "tags",
    ]
    ACTUATOR_HEADERS = [
        "timestamp",
        "actuator_id",
        "device_id",
        "actuator_type",
        "state",
        "value",
        "tags",
    ]
    LOG_HEADERS = [
        "timestamp",
        "level",
        "message",
        "source",
        "device_id",
        "sensor_id",
        "actuator_id",
        "metadata",
    ]

    def __init__(self, base_dir: Optional[Path] = None):
        backend_dir = Path(__file__).resolve().parents[2]
        self.base_dir = base_dir or backend_dir / "storage"
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.sensor_file = self.base_dir / "sensor_readings.csv"
        self.actuator_file = self.base_dir / "actuator_states.csv"
        self.log_file = self.base_dir / "logs.csv"

    def write_sensor_data(
        self,
        measurement: str,
        device_id: str,
        sensor_id: str,
        value: float,
        timestamp: int,
        tags: Optional[dict] = None,
    ):
        row = {
            "timestamp": str(timestamp),
            "measurement": measurement,
            "device_id": device_id,
            "sensor_id": sensor_id,
            "value": f"{value}",
            "tags": json.dumps(tags or {}),
        }
        self._append_row(self.sensor_file, self.SENSOR_HEADERS, row)

    def query_sensor_data(
        self,
        measurement: str,
        device_id: Optional[str] = None,
        sensor_id: Optional[str] = None,
        start_time: Optional[int] = None,
        stop_time: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Dict]:
        rows = self._read_rows(self.sensor_file)
        result = []
        for row in rows:
            if row.get("measurement") != measurement:
                continue
            ts = self._safe_int(row.get("timestamp"))
            if start_time and ts < start_time:
                continue
            if stop_time and ts > stop_time:
                continue
            if device_id and row.get("device_id") != device_id:
                continue
            if sensor_id and row.get("sensor_id") != sensor_id:
                continue
            result.append(
                {
                    "time": datetime.fromtimestamp(ts).isoformat(),
                    "measurement": row.get("measurement"),
                    "device_id": row.get("device_id"),
                    "sensor_id": row.get("sensor_id"),
                    "value": float(row.get("value", 0)),
                }
            )
        return result[-limit:]

    def get_aggregated_data(
        self,
        measurement: str,
        device_id: Optional[str],
        sensor_id: Optional[str],
        window: str,
        aggregate: str,
    ) -> List[Dict]:
        rows = self._read_rows(self.sensor_file)
        window_value = int(window[:-1])
        unit = window[-1]
        bin_seconds = 3600 if unit == "h" else 60 if unit == "m" else 86400
        bin_seconds *= window_value
        now = int(datetime.utcnow().timestamp())
        start_ts = now - bin_seconds

        buckets: Dict[int, List[float]] = {}
        for row in rows:
            if row.get("measurement") != measurement:
                continue
            ts = self._safe_int(row.get("timestamp"))
            if ts < start_ts:
                continue
            if device_id and row.get("device_id") != device_id:
                continue
            if sensor_id and row.get("sensor_id") != sensor_id:
                continue
            bucket = ts - (ts % bin_seconds)
            buckets.setdefault(bucket, []).append(float(row.get("value", 0)))

        agg_results = []
        for bucket_ts in sorted(buckets.keys()):
            values = buckets[bucket_ts]
            if aggregate == "max":
                agg_value = max(values)
            elif aggregate == "min":
                agg_value = min(values)
            elif aggregate == "sum":
                agg_value = sum(values)
            else:
                agg_value = sum(values) / len(values)
            agg_results.append(
                {
                    "time": datetime.fromtimestamp(bucket_ts).isoformat(),
                    "measurement": measurement,
                    "device_id": device_id or "",
                    "sensor_id": sensor_id or "",
                    "value": round(agg_value, 2),
                }
            )
        return agg_results

    def get_distinct_measurements(self) -> List[str]:
        rows = self._read_rows(self.sensor_file)
        return sorted({row.get("measurement") for row in rows if row.get("measurement")})

    def get_distinct_devices(self) -> List[str]:
        rows = self._read_rows(self.sensor_file)
        return sorted({row.get("device_id") for row in rows if row.get("device_id")})

    def write_actuator_state(
        self,
        actuator_id: str,
        device_id: str,
        actuator_type: str,
        state: str,
        value: Optional[float],
        timestamp: int,
        tags: Optional[dict] = None,
    ):
        row = {
            "timestamp": str(timestamp),
            "actuator_id": actuator_id,
            "device_id": device_id,
            "actuator_type": actuator_type,
            "state": state,
            "value": "" if value is None else f"{value}",
            "tags": json.dumps(tags or {}),
        }
        self._append_row(self.actuator_file, self.ACTUATOR_HEADERS, row)

    def get_actuator_states(
        self,
        actuator_id: Optional[str],
        device_id: Optional[str],
        limit: int,
    ) -> List[Dict]:
        rows = self._read_rows(self.actuator_file)
        filtered = []
        for row in rows:
            if actuator_id and row.get("actuator_id") != actuator_id:
                continue
            if device_id and row.get("device_id") != device_id:
                continue
            ts = self._safe_int(row.get("timestamp"))
            filtered.append(
                {
                    "time": datetime.fromtimestamp(ts).isoformat(),
                    "actuator_id": row.get("actuator_id"),
                    "device_id": row.get("device_id"),
                    "actuator_type": row.get("actuator_type"),
                    "state": row.get("state"),
                    "value": self._safe_float(row.get("value")),
                }
            )
        return filtered[-limit:]

    def get_current_actuator_states(self) -> List[Dict]:
        rows = self._read_rows(self.actuator_file)
        latest: Dict[str, Dict] = {}
        for row in rows:
            ts = self._safe_int(row.get("timestamp"))
            actuator_id = row.get("actuator_id")
            existing = latest.get(actuator_id)
            if not existing or ts > existing["timestamp"]:
                latest[actuator_id] = {
                    "timestamp": ts,
                    "actuator_id": actuator_id,
                    "device_id": row.get("device_id"),
                    "actuator_type": row.get("actuator_type"),
                    "state": row.get("state"),
                    "value": self._safe_float(row.get("value")),
                }
        return [
            {
                "actuator_id": data["actuator_id"],
                "device_id": data["device_id"],
                "actuator_type": data["actuator_type"],
                "state": data["state"],
                "value": data["value"],
                "time": datetime.fromtimestamp(data["timestamp"]).isoformat(),
            }
            for data in latest.values()
        ]

    def write_log(self, log_entry: Dict):
        row = {
            "timestamp": str(log_entry["timestamp"]),
            "level": log_entry["level"],
            "message": log_entry["message"],
            "source": log_entry["source"],
            "device_id": log_entry.get("device_id", ""),
            "sensor_id": log_entry.get("sensor_id", ""),
            "actuator_id": log_entry.get("actuator_id", ""),
            "metadata": json.dumps(log_entry.get("metadata") or {}),
        }
        self._append_row(self.log_file, self.LOG_HEADERS, row)

    def get_logs(
        self,
        level: Optional[str],
        source: Optional[str],
        device_id: Optional[str],
        limit: int,
    ) -> List[Dict]:
        rows = self._read_rows(self.log_file)
        filtered = []
        for row in rows:
            if level and row.get("level") != level:
                continue
            if source and row.get("source") != source:
                continue
            if device_id and row.get("device_id") != device_id:
                continue
            ts = self._safe_int(row.get("timestamp"))
            filtered.append(
                {
                    "time": datetime.fromtimestamp(ts).isoformat(),
                    "level": row.get("level"),
                    "message": row.get("message"),
                    "source": row.get("source"),
                    "device_id": row.get("device_id") or None,
                    "sensor_id": row.get("sensor_id") or None,
                    "actuator_id": row.get("actuator_id") or None,
                    "metadata": self._safe_json(row.get("metadata")),
                }
            )
        return filtered[-limit:]

    def _append_row(self, path: Path, headers: List[str], row: Dict):
        file_exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            if not file_exists or path.stat().st_size == 0:
                writer.writeheader()
            writer.writerow({header: row.get(header, "") for header in headers})

    def _read_rows(self, path: Path) -> List[Dict]:
        if not path.exists() or path.stat().st_size == 0:
            return []
        with path.open("r", newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            return list(reader)

    def clear_all(self) -> None:
        """Clear all CSV storage files."""
        for path in [self.sensor_file, self.actuator_file, self.log_file]:
            if path.exists():
                path.write_text("", encoding="utf-8")

    @staticmethod
    def _safe_int(value: Optional[str]) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_float(value: Optional[str]) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_json(value: Optional[str]) -> Optional[dict]:
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
