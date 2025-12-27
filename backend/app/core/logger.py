"""
Centralized logging service with MongoDB or CSV backend
"""
from datetime import datetime
from typing import Optional

from pymongo.errors import PyMongoError

from app.models.log import LogLevel


class IoTLogger:
    """Centralized logger for IoT system"""

    def __init__(self):
        # Lazy import to avoid circular dependency
        from app.core.mongodb_client import mongodb_service
        self.mongodb_service = mongodb_service
        self.use_mongo = mongodb_service.available
        if self.use_mongo:
            self.collection = mongodb_service.db.logs
            self.collection.create_index([("timestamp", -1)])
            self.collection.create_index([("level", 1), ("timestamp", -1)])
            self.collection.create_index([("source", 1), ("timestamp", -1)])
        else:
            self.csv_storage = mongodb_service.csv_storage

    def _switch_to_csv(self) -> None:
        self.use_mongo = False
        self.csv_storage = self.mongodb_service.csv_storage
        self.collection = None

    def _try_reconnect(self) -> bool:
        if not self.mongodb_service.ensure_available():
            return False
        try:
            self.collection = self.mongodb_service.db.logs
            self.collection.create_index([("timestamp", -1)])
            self.collection.create_index([("level", 1), ("timestamp", -1)])
            self.collection.create_index([("source", 1), ("timestamp", -1)])
            self.use_mongo = True
            return True
        except PyMongoError:
            self._switch_to_csv()
            return False

    def log(
            self,
            level: LogLevel,
            message: str,
            source: str,
            device_id: Optional[str] = None,
            sensor_id: Optional[str] = None,
            actuator_id: Optional[str] = None,
            metadata: Optional[dict] = None
    ):
        """
        Log an entry to MongoDB
        
        Args:
            level: Log level
            message: Log message
            source: Source component
            device_id: Device identifier (optional)
            sensor_id: Sensor identifier (optional)
            actuator_id: Actuator identifier (optional)
            metadata: Additional metadata (optional)
        """
        timestamp = int(datetime.utcnow().timestamp())

        log_entry = {
            "level": level.value,
            "message": message,
            "source": source,
            "timestamp": timestamp,
            "created_at": datetime.utcnow()
        }

        if device_id:
            log_entry["device_id"] = device_id
        if sensor_id:
            log_entry["sensor_id"] = sensor_id
        if actuator_id:
            log_entry["actuator_id"] = actuator_id
        if metadata:
            log_entry["metadata"] = metadata

        if self.use_mongo and not self.mongodb_service.available:
            self._switch_to_csv()
        if not self.use_mongo:
            self._try_reconnect()

        if self.use_mongo:
            try:
                self.collection.insert_one(log_entry)
                return
            except PyMongoError:
                self.mongodb_service.available = False
                self._switch_to_csv()

        self.csv_storage.write_log(log_entry)

    def debug(self, message: str, source: str, **kwargs):
        """Log debug message"""
        self.log(LogLevel.DEBUG, message, source, **kwargs)

    def info(self, message: str, source: str, **kwargs):
        """Log info message"""
        self.log(LogLevel.INFO, message, source, **kwargs)

    def warning(self, message: str, source: str, **kwargs):
        """Log warning message"""
        self.log(LogLevel.WARNING, message, source, **kwargs)

    def error(self, message: str, source: str, **kwargs):
        """Log error message"""
        self.log(LogLevel.ERROR, message, source, **kwargs)

    def critical(self, message: str, source: str, **kwargs):
        """Log critical message"""
        self.log(LogLevel.CRITICAL, message, source, **kwargs)

    def get_logs(
            self,
            level: Optional[str] = None,
            source: Optional[str] = None,
            device_id: Optional[str] = None,
            limit: int = 100
    ):
        """
        Retrieve logs from MongoDB
        
        Args:
            level: Filter by log level (optional)
            source: Filter by source (optional)
            device_id: Filter by device_id (optional)
            limit: Maximum number of logs to return
        """
        if not self.use_mongo:
            return self.csv_storage.get_logs(level, source, device_id, limit)

        query = {}

        if level:
            query["level"] = level
        if source:
            query["source"] = source
        if device_id:
            query["device_id"] = device_id

        cursor = self.collection.find(query).sort("timestamp", -1).limit(limit)

        logs = []
        for doc in cursor:
            logs.append({
                "time": datetime.fromtimestamp(doc["timestamp"]).isoformat(),
                "level": doc["level"],
                "message": doc["message"],
                "source": doc["source"],
                "device_id": doc.get("device_id"),
                "sensor_id": doc.get("sensor_id"),
                "actuator_id": doc.get("actuator_id"),
                "metadata": doc.get("metadata")
            })

        return logs


# Global logger instance (lazy initialization to avoid circular import)
_iot_logger_instance = None


def get_logger():
    """Get the global logger instance (lazy initialization)"""
    global _iot_logger_instance
    if _iot_logger_instance is None:
        _iot_logger_instance = IoTLogger()
    return _iot_logger_instance


# For backward compatibility, create instance on first access
class _LazyLogger:
    """Lazy proxy for IoTLogger to avoid circular imports"""

    def __getattr__(self, name):
        return getattr(get_logger(), name)


iot_logger = _LazyLogger()
