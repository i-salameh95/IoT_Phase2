"""
MongoDB client configuration and CSV fallback utilities for sensor data storage
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.core.config import settings
from app.core.csv_storage import CSVStorage
from app.core.logger import iot_logger


class MongoDBService:
    """Service for interacting with MongoDB (with CSV fallback)."""
    
    def __init__(self):
        self.csv_storage = CSVStorage()
        self.available = False
        try:
            self.client = MongoClient(
                settings.MONGODB_URL,
                serverSelectionTimeoutMS=2000
            )
            # Trigger connection
            self.client.admin.command("ping")
            self.db = self.client[settings.MONGODB_DATABASE]
            self.collection = self.db.sensor_readings
            self.collection.create_index([("measurement", 1), ("timestamp", -1)])
            self.collection.create_index([("device_id", 1), ("timestamp", -1)])
            self.collection.create_index([("sensor_id", 1), ("timestamp", -1)])
            self.collection.create_index("timestamp")
            self.available = True
        except PyMongoError:
            self.client = None
            self.db = None
            self.collection = None
        
        # Actuator states collection
        if self.available:
            try:
                self.actuator_collection = self.db.actuator_states
                self.actuator_collection.create_index([("actuator_id", 1), ("timestamp", -1)])
                self.actuator_collection.create_index("timestamp")
            except Exception:
                self.actuator_collection = None
        else:
            self.actuator_collection = None
        
        # Response times collection
        if self.available:
            try:
                self.response_times_collection = self.db.response_times
                self.response_times_collection.create_index([("timestamp", -1)])
                self.response_times_collection.create_index([("timestamp_dt", -1)])  # For datetime queries
                self.response_times_collection.create_index([("cycle", -1)])
            except Exception:
                self.response_times_collection = None
        else:
            self.response_times_collection = None
    
    def write_sensor_data(
        self,
        measurement: str,
        device_id: str,
        sensor_id: str,
        value: float,
        timestamp: int = None,
        tags: dict = None
    ):
        if timestamp is None:
            timestamp = int(datetime.utcnow().timestamp())

        if not self.available:
            self.csv_storage.write_sensor_data(
                measurement=measurement,
                device_id=device_id,
                sensor_id=sensor_id,
                value=value,
                timestamp=timestamp,
                tags=tags
            )
            return

        document = {
            "measurement": measurement,
            "device_id": device_id,
            "sensor_id": sensor_id,
            "value": value,
            "timestamp": timestamp,
            "created_at": datetime.utcnow(),
            # IMPORTANT: keep tags object for ML + UI
            "tags": tags or {}
        }

        # Keep backward-compatible flattened fields too (optional but OK)
        if tags:
            document.update({f"tag_{k}": v for k, v in tags.items()})

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
        Query sensor data from MongoDB
        
        Args:
            measurement: Measurement name
            device_id: Filter by device_id (optional)
            sensor_id: Filter by sensor_id (optional)
            start_time: Start time (ISO format or Unix timestamp, optional)
            stop_time: Stop time (ISO format or Unix timestamp, optional)
            limit: Maximum number of records to return
            default_time_window: If True and no start_time provided, default to last 1 hour (default: True)
        """
        if start_time:
            start_dt = self._parse_datetime(start_time)
            start_ts = int(start_dt.timestamp())
        elif default_time_window:
            # Default to last 1 hour for backward compatibility
            start_ts = int((datetime.utcnow() - timedelta(hours=1)).timestamp())
        else:
            # No time filter - query all data
            start_ts = None
        stop_ts = int(self._parse_datetime(stop_time).timestamp()) if stop_time else None
        
        if not self.available:
            return self.csv_storage.query_sensor_data(
                measurement=measurement,
                device_id=device_id,
                sensor_id=sensor_id,
                start_time=start_ts,
                stop_time=stop_ts,
                limit=limit
            )
        
        query = {"measurement": measurement}
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

        cursor = self.collection.find(query).sort("timestamp", -1).limit(limit)

        data = []
        for doc in cursor:
            data.append({
                "time": datetime.utcfromtimestamp(doc["timestamp"]).isoformat() + "Z",
                "measurement": doc["measurement"],
                "device_id": doc["device_id"],
                "sensor_id": doc["sensor_id"],
                "value": doc["value"],
                # IMPORTANT: provide tags for ML service if needed
                "tags": doc.get("tags", {})
            })

        return list(reversed(data))


    def get_aggregated_data(
            self,
            measurement: str,
            device_id: str = None,
            sensor_id: str = None,
            window: str = "1h",
            aggregate: str = "mean"
        ) -> List[Dict]:
            """
            Get aggregated sensor data

            Args:
                measurement: Measurement name
                device_id: Filter by device_id (optional)
                sensor_id: Filter by sensor_id (optional)
                window: Time window (e.g., "1h", "5m")
                aggregate: Aggregation function (mean, max, min, sum)
            """
            if not self.available:
                return self.csv_storage.get_aggregated_data(
                    measurement=measurement,
                    device_id=device_id,
                    sensor_id=sensor_id,
                    window=window,
                    aggregate=aggregate
                )

            # Parse window (e.g., "1h" -> 1 hour, "5m" -> 5 minutes)
            window_value = int(window[:-1])
            window_unit = window[-1]

            if window_unit == 'h':
                delta = timedelta(hours=window_value)
                bin_size_seconds = window_value * 3600
            elif window_unit == 'm':
                delta = timedelta(minutes=window_value)
                bin_size_seconds = window_value * 60
            elif window_unit == 'd':
                delta = timedelta(days=window_value)
                bin_size_seconds = window_value * 86400
            else:
                delta = timedelta(hours=1)  # default
                bin_size_seconds = 3600

            start_time = int((datetime.utcnow() - delta).timestamp())

            query = {
                "measurement": measurement,
                "timestamp": {"$gte": start_time}
            }

            if device_id:
                query["device_id"] = device_id

            if sensor_id:
                query["sensor_id"] = sensor_id

            # Determine aggregation operator
            agg_operator = "$avg" if aggregate == "mean" else \
                          "$max" if aggregate == "max" else \
                          "$min" if aggregate == "min" else \
                          "$sum"

            # Use MongoDB aggregation pipeline with simpler grouping
            pipeline = [
                {"$match": query},
                {
                    "$group": {
                        "_id": {
                            "$subtract": [
                                "$timestamp",
                                {"$mod": ["$timestamp", bin_size_seconds]}
                            ]
                        },
                        "value": {agg_operator: "$value"},
                        "measurement": {"$first": "$measurement"},
                        "device_id": {"$first": "$device_id"},
                        "sensor_id": {"$first": "$sensor_id"}
                    }
                },
                {"$sort": {"_id": 1}}
            ]

            results = list(self.collection.aggregate(pipeline))

            data = []
            for result in results:
                timestamp_dt = datetime.utcfromtimestamp(result["_id"])
                data.append({
                    "time": timestamp_dt.isoformat() + "Z",
                    "measurement": result["measurement"],
                    "device_id": result["device_id"],
                    "sensor_id": result["sensor_id"],
                    "value": round(result["value"], 2)
                })

            return data

    def get_distinct_measurements(self) -> List[str]:
        """Get list of distinct measurement types"""
        if not self.available:
            return self.csv_storage.get_distinct_measurements()
        return self.collection.distinct("measurement")
    
    def get_distinct_devices(self) -> List[str]:
        """Get list of distinct device IDs"""
        if not self.available:
            return self.csv_storage.get_distinct_devices()
        return self.collection.distinct("device_id")
    
    def write_actuator_state(self, actuator_state):
        """
        Write actuator state to MongoDB
        
        Args:
            actuator_state: ActuatorState object
        """
        timestamp = actuator_state.timestamp or int(datetime.utcnow().timestamp())
        if not self.available:
            self.csv_storage.write_actuator_state(
                actuator_id=actuator_state.actuator_id,
                device_id=actuator_state.device_id,
                actuator_type=actuator_state.actuator_type,
                state=actuator_state.state,
                value=actuator_state.value,
                timestamp=timestamp,
                tags=actuator_state.tags
            )
            return
        
        if self.actuator_collection is None:
            return
        
        document = {
            "actuator_id": actuator_state.actuator_id,
            "device_id": actuator_state.device_id,
            "actuator_type": actuator_state.actuator_type,
            "state": actuator_state.state,
            "value": actuator_state.value,
            "timestamp": timestamp,
            "created_at": datetime.utcnow()
        }
        
        if actuator_state.tags:
            document.update({f"tag_{k}": v for k, v in actuator_state.tags.items()})
        
        self.actuator_collection.insert_one(document)
    
    def get_actuator_states(
        self,
        actuator_id: str = None,
        device_id: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get actuator states from MongoDB
        
        Args:
            actuator_id: Filter by actuator_id (optional)
            device_id: Filter by device_id (optional)
            limit: Maximum number of records to return
        """
        if not self.available:
            return self.csv_storage.get_actuator_states(
                actuator_id=actuator_id,
                device_id=device_id,
                limit=limit
            )
        
        if self.actuator_collection is None:
            return []
        
        collection = self.actuator_collection
        
        query = {}
        if actuator_id:
            query["actuator_id"] = actuator_id
        if device_id:
            query["device_id"] = device_id
        
        cursor = collection.find(query).sort("timestamp", -1).limit(limit)
        
        data = []
        for doc in cursor:
            data.append({
                "time": datetime.utcfromtimestamp(doc["timestamp"]).isoformat() + "Z",
                "actuator_id": doc["actuator_id"],
                "device_id": doc["device_id"],
                "actuator_type": doc["actuator_type"],
                "state": doc["state"],
                "value": doc.get("value")
            })
        
        return list(reversed(data))
    
    def get_current_actuator_states(self) -> List[Dict]:
        """Get the most recent state of each actuator (only active ones from recent cycles)"""
        if not self.available:
            return self.csv_storage.get_current_actuator_states()
        
        if self.actuator_collection is None:
            return []
        
        # Only show actuators that were active in the last 5 minutes
        # This prevents showing old "ON" states from previous runs
        five_minutes_ago = int((datetime.utcnow() - timedelta(minutes=5)).timestamp())
        
        # Use aggregation pipeline to get latest state per actuator_id
        # Filter to only include recent activations or currently active states
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"timestamp": {"$gte": five_minutes_ago}},  # Recent (last 5 min)
                        {"state": {"$in": ["ON", "ACTIVE"]}}  # Or currently active
                    ]
                }
            },
            {"$sort": {"timestamp": -1}},
            {
                "$group": {
                    "_id": "$actuator_id",
                    "doc": {"$first": "$$ROOT"}
                }
            }
        ]
        
        current_states = []
        for result in self.actuator_collection.aggregate(pipeline):
            doc = result["doc"]
            # Only include if state is ON/ACTIVE or very recent (within 5 min)
            state = doc["state"]
            timestamp = doc["timestamp"]
            is_recent = timestamp >= five_minutes_ago
            
            if state in ["ON", "ACTIVE"] or is_recent:
                current_states.append({
                    "actuator_id": doc["actuator_id"],
                    "device_id": doc["device_id"],
                    "actuator_type": doc["actuator_type"],
                    "state": state,
                    "value": doc.get("value"),
                    "time": datetime.utcfromtimestamp(timestamp).isoformat() + "Z"
                })
        
        return current_states
    
    def write_response_times(self, cycle: int, response_times: dict, patient_id: str = None):
        """
        Store response time metrics for a simulation cycle
        
        Args:
            cycle: Cycle number
            response_times: Dictionary with stage timings (sensor_generation, edge_processing, storage, ml_prediction, actuator_decision, total)
            patient_id: Patient ID (optional)
        
        Returns:
            bool: True if stored successfully, False otherwise
        """
        if not self.available or self.response_times_collection is None:
            # Log warning once to help debugging
            if not hasattr(self, '_response_times_warning_logged'):
                iot_logger.warning(
                    "Response times collection unavailable - response time metrics will not be stored",
                    source="mongodb_client"
                )
                self._response_times_warning_logged = True
            return False
        
        try:
            now = datetime.utcnow()
            doc = {
                "cycle": cycle,
                "timestamp_dt": now,  # datetime for queries
                "timestamp": int(now.timestamp()),  # Unix timestamp for consistency with sensor_readings
                "patient_id": patient_id or "all",
                "sensor_generation": response_times.get("sensor_generation", 0),
                "edge_processing": response_times.get("edge_processing", 0),
                "storage": response_times.get("storage", 0),
                "ml_prediction": response_times.get("ml_prediction", 0),
                "actuator_decision": response_times.get("actuator_decision", 0),
                "total": response_times.get("total", 0)
            }
            self.response_times_collection.insert_one(doc)
            return True
        except Exception as e:
            iot_logger.warning(
                f"Failed to store response times: {str(e)}",
                source="mongodb_client"
            )
            return False
    
    def query_response_times(self, limit: int = 100, start_time: datetime = None, end_time: datetime = None):
        """
        Query response time data for statistics computation
        
        Args:
            limit: Maximum number of records to return
            start_time: Start time filter (optional)
            end_time: End time filter (optional)
        
        Returns:
            List of dictionaries with response time data
        """
        if not self.available or self.response_times_collection is None:
            # Log warning once to help debugging
            if not hasattr(self, '_response_times_query_warning_logged'):
                iot_logger.warning(
                    "Response times collection unavailable - cannot query response time statistics",
                    source="mongodb_client"
                )
                self._response_times_query_warning_logged = True
            return []
        
        try:
            query = {}
            if start_time or end_time:
                # Use timestamp_dt for datetime queries, or timestamp for int queries
                query["timestamp_dt"] = {}
                if start_time:
                    query["timestamp_dt"]["$gte"] = start_time
                if end_time:
                    query["timestamp_dt"]["$lte"] = end_time
            
            cursor = self.response_times_collection.find(query).sort("timestamp", -1).limit(limit)
            
            # Convert to list and ensure all expected keys are present
            results = []
            for doc in cursor:
                result = {
                    "sensor_generation": doc.get("sensor_generation", 0),
                    "edge_processing": doc.get("edge_processing", 0),
                    "storage": doc.get("storage", 0),
                    "ml_prediction": doc.get("ml_prediction", 0),
                    "actuator_decision": doc.get("actuator_decision", 0),
                    "total": doc.get("total", 0),
                    "cycle": doc.get("cycle", 0),
                    "timestamp": doc.get("timestamp"),
                    "patient_id": doc.get("patient_id", "all")
                }
                results.append(result)
            
            return results
        except Exception as e:
            # Log warning to help debugging
            if not hasattr(self, '_response_times_query_exception_logged'):
                iot_logger.warning(
                    f"Failed to query response times: {str(e)}",
                    source="mongodb_client"
                )
                self._response_times_query_exception_logged = True
            return []
    
    def close(self):
        """Close MongoDB client connections"""
        if self.client:
            self.client.close()

    def clear_all_data(self):
        """Clear sensor, actuator, response time, and logs data."""
        if not self.available:
            self.csv_storage.clear_all()
            return True

        try:
            if self.collection is not None:
                self.collection.delete_many({})
            if self.actuator_collection is not None:
                self.actuator_collection.delete_many({})
            if self.response_times_collection is not None:
                self.response_times_collection.delete_many({})
            try:
                self.db.logs.delete_many({})
            except Exception:
                pass
            return True
        except Exception:
            return False

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        if not value:
            return datetime.utcnow()
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            return datetime.utcfromtimestamp(int(value))


# Global instance
mongodb_service = MongoDBService()
