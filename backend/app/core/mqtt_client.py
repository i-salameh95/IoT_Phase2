"""
MQTT client helpers for ingesting IoT sensor data.
"""
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from app.core.config import settings
from app.core.logger import iot_logger


def create_mqtt_client(
    client_id: str,
    on_message: Callable,
    on_connect: Optional[Callable] = None,
    on_disconnect: Optional[Callable] = None
) -> mqtt.Client:
    """
    Create and configure a paho MQTT client.

    Args:
        client_id: MQTT client id
        on_message: callback for incoming messages
        on_connect: optional connect callback
        on_disconnect: optional disconnect callback
    """
    client = mqtt.Client(client_id=client_id, clean_session=True)

    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

    client.on_message = on_message

    if on_connect:
        client.on_connect = on_connect
    if on_disconnect:
        client.on_disconnect = on_disconnect

    return client


def connect_mqtt(client: mqtt.Client) -> None:
    """
    Connect to MQTT broker with basic logging and retries.
    """
    host = settings.MQTT_BROKER_HOST
    port = settings.MQTT_BROKER_PORT
    retries = max(1, int(settings.MQTT_CONNECT_RETRIES))
    delay = max(0.2, float(settings.MQTT_CONNECT_DELAY))

    for attempt in range(1, retries + 1):
        try:
            iot_logger.info(
                f"Connecting to MQTT broker at {host}:{port} (attempt {attempt}/{retries})",
                source="mqtt"
            )
            client.connect(host, port, keepalive=60)
            return
        except Exception as exc:
            iot_logger.warning(
                f"MQTT connect failed: {exc}",
                source="mqtt"
            )
            if attempt < retries:
                import time
                time.sleep(delay)
            else:
                raise
