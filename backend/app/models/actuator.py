"""
Actuator data models
"""
from typing import Optional

from pydantic import BaseModel, Field


class ActuatorState(BaseModel):
    """Model for actuator state"""
    actuator_id: str = Field(..., description="Actuator identifier")
    device_id: str = Field(..., description="Device identifier")
    actuator_type: str = Field(..., description="Actuator type (e.g., 'LED', 'relay', 'motor')")
    state: str = Field(..., description="Actuator state (e.g., 'ON', 'OFF', '50%')")
    value: Optional[float] = Field(None, description="Actuator value (if applicable)")
    timestamp: Optional[int] = Field(None, description="Unix timestamp (optional, defaults to now)")
    tags: Optional[dict] = Field(None, description="Additional tags")


class ActuatorStateResponse(BaseModel):
    """Model for actuator state response"""
    time: str
    actuator_id: str
    device_id: str
    actuator_type: str
    state: str
    value: Optional[float] = None
