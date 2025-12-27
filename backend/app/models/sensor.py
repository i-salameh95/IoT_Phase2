"""
Sensor data models
"""
from typing import Optional

from pydantic import BaseModel, Field


class SensorReading(BaseModel):
    """Model for ingesting sensor data"""
    measurement: str = Field(..., description="Measurement type (e.g., 'temperature', 'humidity')")
    device_id: str = Field(..., description="Device identifier")
    sensor_id: str = Field(..., description="Sensor identifier")
    value: float = Field(..., description="Sensor reading value")
    timestamp: Optional[int] = Field(None, description="Unix timestamp (optional, defaults to now)")
    tags: Optional[dict] = Field(None, description="Additional tags")


class SensorReadingResponse(BaseModel):
    """Model for sensor data response"""
    time: str
    measurement: str
    device_id: str
    sensor_id: str
    value: float


class HistoricalDataQuery(BaseModel):
    """Model for querying historical data"""
    measurement: str
    device_id: Optional[str] = None
    sensor_id: Optional[str] = None
    start_time: Optional[str] = None  # RFC3339 format--
    stop_time: Optional[str] = None  # RFC3339 format
    limit: int = Field(default=1000, ge=1, le=10000)


class AggregatedDataQuery(BaseModel):
    """Model for querying aggregated data"""
    measurement: str
    device_id: Optional[str] = None
    sensor_id: Optional[str] = None
    window: str = Field(default="1h", description="Time window (e.g., '1h', '5m')")
    aggregate: str = Field(default="mean", description="Aggregation function (mean, max, min, sum)")
