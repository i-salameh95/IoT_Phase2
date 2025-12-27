"""
Logging models
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LogLevel(str, Enum):
    """Log levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogEntry(BaseModel):
    """Model for log entry"""
    level: LogLevel = Field(..., description="Log level")
    message: str = Field(..., description="Log message")
    source: str = Field(..., description="Source component (e.g., 'sensor', 'actuator', 'api')")
    device_id: Optional[str] = Field(None, description="Device identifier (if applicable)")
    sensor_id: Optional[str] = Field(None, description="Sensor identifier (if applicable)")
    actuator_id: Optional[str] = Field(None, description="Actuator identifier (if applicable)")
    timestamp: Optional[int] = Field(None, description="Unix timestamp (optional, defaults to now)")
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class LogEntryResponse(BaseModel):
    """Model for log entry response"""
    time: str
    level: str
    message: str
    source: str
    device_id: Optional[str] = None
    sensor_id: Optional[str] = None
    actuator_id: Optional[str] = None
    metadata: Optional[dict] = None
