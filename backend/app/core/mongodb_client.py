"""
MongoDB client configuration and CSV fallback utilities for sensor data storage.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.core.config import settings
from app.core.csv_storage import CSVStorage
from app.core.logger import iot_logger


class MongoDBService:
    """
    Service for interacting with MongoDB (with CSV fallback).

    Key behaviors:
    - If MongoDB is unavailable, fall back to CSV storage for basic demo continuity.
    - Store tags both as a subdocument (tags) AND as flattened fields (tag_<k>) so legacy queries remain simple.
    - Provide response-time analytics persistence for the dashboard.
    """

    def __init__(self):
        self.csv_storage = CSVStorage()
        self.available = False
        self.client: Optional[MongoClient] = None
        self.db = None
        self.collection = None
        self.actuator_collection = None
        self.response_times_collection = None

        self._connect()

    def _connect(self) -> None:
        try:
            self.client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=2000)
            self.client.admin.command("ping")
            self.db = self.client[settings.MONGODB_DATABASE]

            # Sensor readings
            self.collection = self.db.sensor_readings
            self.collection.create_index([("measurement", 1), ("timestamp", -1)])
            self.collection.create_index([("device_id", 1), ("timestamp", -1)])
            self.collection.create_index([("sensor_id", 1), ("timestamp", -1)])
            self.collection.create_index("timestamp")
            self.collection.create_index([("tags.patient_id", 1), ("timestamp", -1)])
            self.collection.create_index([("tags.cycle", 1), ("timestamp", -1)])

            # Actuator states
            self.actuator_collection = self.db.actuator_states
            self.actuator_collection.create_index([("actuator_id", 1), ("timestamp", -1)])
            self.actuator_collection.create_index([("device_id", 1), ("timestamp", -1)])
            self.actuator_collection.create_index("timestamp")

            # Response times
            self.response_times_collection = self.db.response_times
            self.response_times_collection.create_index([("timestamp", -1)])
            self.response_times_collection.create_index([("timestamp_dt", -1)])
            self.response_times_collection.create_index([("cycle", -1)])
            self.response_times_collection.create_index([("patient_id", 1), ("timestamp", -1)])

            self.available = True

        except PyMongoError:
            self.available = False
            self.client = None
            self.db = None
            self.collection = None
            self.actuator_collection = None
            self.response_times_collection = None

    def ensure_available(self) -> bool:
        """
        Ensure MongoDB is connected. If not, attempt to reconnect.

        Returns:
            True if MongoDB is available, False otherwise.
        """
        if self.available and self.client is not None:
            return True

        self._connect()
        if not self.available:
            iot_logger.warning("MongoDB unavailable - using CSV fallback", source="mongodb_client")
        return self.available

    # ----------------------------
    # Sensor data
    # ----------------------------
    def write_sensor_data(
            self,
            measurement: str,
            device_id: str,
            sensor_id: str,
            value: float,
            timestamp: Optional[int] = None,
            tags: Optional[dict] = None
    ) -> None:
        if timestamp is None:
            timestamp = int(datetime.utcnow().timestamp())

        if not self.ensure_available() or self.collection is None:
            self.csv_storage.write_sensor_data(
                measurement=measurement,
                device_id=device_id,
                sensor_id=sensor_id,
                value=value,
                timestamp=timestamp,
                tags=tags,
            )
            return

        document: Dict[str, Any] = {
            "measurement": measurement,
            "device_id": device_id,
            "sensor_id": sensor_id,
            "value": float(value),
            "timestamp": int(timestamp),
            "created_at": datetime.utcnow(),
            "tags": tags or {},
        }

        # Flatten tags (legacy compatibility)
        if tags:
            for k, v in tags.items():
                document[f"tag_{k}"] = v

        self.collection.insert_one(document)

    def query_sensor_data(
            self,
            measurement: str,
            device_id: str = None,
            sensor_id: str = None,
            start_time: str = None,
            stop_time: str = None,
            limit: int = 1000,
            default_time_window: bool = True
    ) -> List[Dict]:
        """
        Query sensor data.

        Returns list items:
            {time, measurement, device_id, sensor_id, value, tags}
        """
        if start_time:
            start_dt = self._parse_datetime(start_time)
            start_ts = int(start_dt.timestamp())
        elif default_time_window:
            start_ts = int((datetime.utcnow() - timedelta(hours=1)).timestamp())
        else:
            start_ts = None

        stop_ts = int(self._parse_datetime(stop_time).timestamp()) if stop_time else None

        if not self.ensure_available() or self.collection is None:
            # CSV fallback does not support tags; still returns consistent shape
            rows = self.csv_storage.query_sensor_data(
                measurement=measurement,
                device_id=device_id,
                sensor_id=sensor_id,
                start_time=start_ts,
                stop_time=stop_ts,
                limit=limit,
            )
            for r in rows:
                r["tags"] = {}
            return rows

        query: Dict[str, Any] = {"measurement": measurement}

        if start_ts is not None or stop_ts is not None:
            query["timestamp"] = {}
            if start_ts is not None:
                query["timestamp"]["$gte"] = start_ts
            if stop_ts is not None:
                query["timestamp"]["$lte"] = stop_ts

        if device_id:
            query["device_id"] = device_id
        if sensor_id:
            query["sensor_id"] = sensor_id

        cursor = self.collection.find(query).sort("timestamp", -1).limit(int(limit))

        data: List[Dict] = []
        for doc in cursor:
            tags = doc.get("tags") or {}
            # Backward compat: rebuild tags from flattened fields if tags missing
            if not tags:
                tags = {k.replace("tag_", ""): v for k, v in doc.items() if isinstance(k, str) and k.startswith("tag_")}
            data.append({
                "time": datetime.utcfromtimestamp(doc["timestamp"]).isoformat() + "Z",
                "measurement": doc.get("measurement"),
                "device_id": doc.get("device_id"),
                "sensor_id": doc.get("sensor_id"),
                "value": doc.get("value"),
                "tags": tags,
            })

        return list(reversed(data))

    def get_latest_sensor_data(self, measurement: str, device_id: str = None, sensor_id: str = None) -> Optional[Dict]:
        """Get latest single reading for a measurement (Mongo only; CSV fallback returns best-effort)."""
        rows = self.query_sensor_data(measurement=measurement, device_id=device_id, sensor_id=sensor_id, limit=1,
                                      default_time_window=False)
        return rows[-1] if rows else None

    def get_aggregated_data(
            self,
            measurement: str,
            device_id: str = None,
            sensor_id: str = None,
            window: str = "1h",
            aggregate: str = "mean"
    ) -> List[Dict]:
        if not self.ensure_available() or self.collection is None:
            return self.csv_storage.get_aggregated_data(measurement, device_id, sensor_id, window, aggregate)

        window_value = int(window[:-1])
        unit = window[-1]

        if unit == "h":
            delta = timedelta(hours=window_value)
            bin_seconds = window_value * 3600
        elif unit == "m":
            delta = timedelta(minutes=window_value)
            bin_seconds = window_value * 60
        elif unit == "d":
            delta = timedelta(days=window_value)
            bin_seconds = window_value * 86400
        else:
            delta = timedelta(hours=1)
            bin_seconds = 3600

        start_ts = int((datetime.utcnow() - delta).timestamp())

        query: Dict[str, Any] = {"measurement": measurement, "timestamp": {"$gte": start_ts}}
        if device_id:
            query["device_id"] = device_id
        if sensor_id:
            query["sensor_id"] = sensor_id

        agg_operator = "$avg" if aggregate == "mean" else "$max" if aggregate == "max" else "$min" if aggregate == "min" else "$sum"

        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": {"$subtract": ["$timestamp", {"$mod": ["$timestamp", bin_seconds]}]},
                "value": {agg_operator: "$value"},
                "measurement": {"$first": "$measurement"},
                "device_id": {"$first": "$device_id"},
                "sensor_id": {"$first": "$sensor_id"},
            }},
            {"$sort": {"_id": 1}},
        ]

        results = list(self.collection.aggregate(pipeline))
        out: List[Dict] = []
        for r in results:
            ts = datetime.utcfromtimestamp(r["_id"]).isoformat() + "Z"
            out.append({
                "time": ts,
                "measurement": r.get("measurement"),
                "device_id": r.get("device_id"),
                "sensor_id": r.get("sensor_id"),
                "value": round(float(r.get("value", 0)), 2),
            })
        return out

    def get_distinct_measurements(self) -> List[str]:
        if not self.ensure_available() or self.collection is None:
            return self.csv_storage.get_distinct_measurements()
        return self.collection.distinct("measurement")

    def get_distinct_devices(self) -> List[str]:
        if not self.ensure_available() or self.collection is None:
            return self.csv_storage.get_distinct_devices()
        return self.collection.distinct("device_id")

    def clear_all_data(self, include_logs: bool = False, include_csv_fallback: bool = True) -> bool:
        """Clear all stored data (MongoDB + optional CSV fallback)."""
        mongo_cleared = False
        if self.ensure_available():
            try:
                if self.collection is not None:
                    self.collection.delete_many({})
                if self.actuator_collection is not None:
                    self.actuator_collection.delete_many({})
                if self.response_times_collection is not None:
                    self.response_times_collection.delete_many({})
                if include_logs and self.db is not None:
                    self.db.logs.delete_many({})
                mongo_cleared = True
            except Exception as e:
                iot_logger.warning(f"Failed to clear MongoDB data: {e}", source="mongodb_client")

        csv_cleared = False
        if include_csv_fallback:
            try:
                self.csv_storage.clear_sensor_data()
                self.csv_storage.clear_actuator_states()
                if include_logs:
                    self.csv_storage.clear_logs()
                csv_cleared = True
            except Exception as e:
                iot_logger.warning(f"Failed to clear CSV data: {e}", source="mongodb_client")

        return mongo_cleared or csv_cleared

    # ----------------------------
    # Actuator states
    # ----------------------------
    def write_actuator_state(self, actuator_state) -> None:
        timestamp = actuator_state.timestamp or int(datetime.utcnow().timestamp())

        if not self.ensure_available() or self.actuator_collection is None:
            self.csv_storage.write_actuator_state(
                actuator_id=actuator_state.actuator_id,
                device_id=actuator_state.device_id,
                actuator_type=actuator_state.actuator_type,
                state=actuator_state.state,
                value=actuator_state.value,
                timestamp=timestamp,
                tags=actuator_state.tags,
            )
            return

        doc: Dict[str, Any] = {
            "actuator_id": actuator_state.actuator_id,
            "device_id": actuator_state.device_id,
            "actuator_type": actuator_state.actuator_type,
            "state": actuator_state.state,
            "value": actuator_state.value,
            "timestamp": int(timestamp),
            "created_at": datetime.utcnow(),
            "tags": actuator_state.tags or {},
        }
        if actuator_state.tags:
            for k, v in actuator_state.tags.items():
                doc[f"tag_{k}"] = v

        self.actuator_collection.insert_one(doc)

    def get_actuator_states(self, actuator_id: str = None, device_id: str = None, limit: int = 100) -> List[Dict]:
        if not self.ensure_available() or self.actuator_collection is None:
            return self.csv_storage.get_actuator_states(actuator_id=actuator_id, device_id=device_id, limit=limit)

        query: Dict[str, Any] = {}
        if actuator_id:
            query["actuator_id"] = actuator_id
        if device_id:
            query["device_id"] = device_id

        cursor = self.actuator_collection.find(query).sort("timestamp", -1).limit(int(limit))
        data: List[Dict] = []
        for doc in cursor:
            data.append({
                "time": datetime.utcfromtimestamp(doc["timestamp"]).isoformat() + "Z",
                "actuator_id": doc.get("actuator_id"),
                "device_id": doc.get("device_id"),
                "actuator_type": doc.get("actuator_type"),
                "state": doc.get("state"),
                "value": doc.get("value"),
            })
        return list(reversed(data))

    def get_current_actuator_states(self) -> List[Dict]:
        """Get most recent state per actuator, but avoid showing very old states from prior runs."""
        if not self.ensure_available() or self.actuator_collection is None:
            return self.csv_storage.get_current_actuator_states()

        five_minutes_ago = int((datetime.utcnow() - timedelta(minutes=5)).timestamp())
        pipeline = [
            {"$match": {"$or": [{"timestamp": {"$gte": five_minutes_ago}}, {"state": {"$in": ["ON", "ACTIVE"]}}]}},
            {"$sort": {"timestamp": -1}},
            {"$group": {"_id": "$actuator_id", "doc": {"$first": "$$ROOT"}}},
        ]

        out: List[Dict] = []
        for r in self.actuator_collection.aggregate(pipeline):
            doc = r["doc"]
            ts = int(doc.get("timestamp", 0))
            state = doc.get("state")
            if state in ["ON", "ACTIVE"] or ts >= five_minutes_ago:
                out.append({
                    "actuator_id": doc.get("actuator_id"),
                    "device_id": doc.get("device_id"),
                    "actuator_type": doc.get("actuator_type"),
                    "state": state,
                    "value": doc.get("value"),
                    "time": datetime.utcfromtimestamp(ts).isoformat() + "Z",
                })
        return out

    # ----------------------------
    # Response times (analytics)
    # ----------------------------
    def write_response_times(self, cycle: int, response_times: dict, patient_id: str = None) -> bool:
        if not self.ensure_available() or self.response_times_collection is None:
            # best-effort; no CSV persistence for response times
            if not hasattr(self, "_rt_warned"):
                iot_logger.warning("Response times collection unavailable - metrics will not be stored",
                                   source="mongodb_client")
                self._rt_warned = True
            return False

        try:
            now = datetime.utcnow()
            doc = {
                "cycle": int(cycle),
                "timestamp_dt": now,
                "timestamp": int(now.timestamp()),
                "patient_id": patient_id or "all",
                "sensor_generation": float(response_times.get("sensor_generation", 0)),
                "edge_processing": float(response_times.get("edge_processing", 0)),
                "storage": float(response_times.get("storage", 0)),
                "ml_prediction": float(response_times.get("ml_prediction", 0)),
                "actuator_decision": float(response_times.get("actuator_decision", 0)),
                "total": float(response_times.get("total", 0)),
            }
            self.response_times_collection.insert_one(doc)
            return True
        except Exception as e:
            iot_logger.warning(f"Failed to store response times: {e}", source="mongodb_client")
            return False

    def query_response_times(self, limit: int = 100, start_time: datetime = None, end_time: datetime = None) -> List[
        Dict]:
        if not self.ensure_available() or self.response_times_collection is None:
            if not hasattr(self, "_rt_query_warned"):
                iot_logger.warning("Response times collection unavailable - cannot query statistics",
                                   source="mongodb_client")
                self._rt_query_warned = True
            return []

        try:
            query: Dict[str, Any] = {}
            if start_time or end_time:
                query["timestamp_dt"] = {}
                if start_time:
                    query["timestamp_dt"]["$gte"] = start_time
                if end_time:
                    query["timestamp_dt"]["$lte"] = end_time

            cursor = self.response_times_collection.find(query).sort("timestamp", -1).limit(int(limit))
            out: List[Dict] = []
            for doc in cursor:
                out.append({
                    "sensor_generation": doc.get("sensor_generation", 0),
                    "edge_processing": doc.get("edge_processing", 0),
                    "storage": doc.get("storage", 0),
                    "ml_prediction": doc.get("ml_prediction", 0),
                    "actuator_decision": doc.get("actuator_decision", 0),
                    "total": doc.get("total", 0),
                    "cycle": doc.get("cycle", 0),
                    "timestamp": doc.get("timestamp"),
                    "patient_id": doc.get("patient_id", "all"),
                })
            return out
        except Exception as e:
            iot_logger.warning(f"Failed to query response times: {e}", source="mongodb_client")
            return []

    # ----------------------------
    def close(self) -> None:
        if self.client:
            self.client.close()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        if not value:
            return datetime.utcnow()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return datetime.utcfromtimestamp(int(value))


# Global instance
mongodb_service = MongoDBService()
