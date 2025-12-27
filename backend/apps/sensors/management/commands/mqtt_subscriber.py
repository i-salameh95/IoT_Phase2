"""
MQTT subscriber for ingesting sensor data into MongoDB/CSV storage.
"""
import json
import time
from typing import Dict, Tuple, Optional

from django.core.management.base import BaseCommand

from app.core.config import settings
from app.core.logger import iot_logger
from app.core.mongodb_client import mongodb_service
from app.core.mqtt_client import create_mqtt_client, connect_mqtt
from app.models.sensor import SensorReading
from app.services.edge_processor import edge_processor


def _parse_topic(topic: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Expected topic patterns:
      iot/health/raw/{patient_id}/{device_id}/{measurement}
      iot/health/processed/{patient_id}/{device_id}/{measurement}
    """
    parts = topic.split("/")
    if len(parts) < 6:
        return None, None, None, None
    _, _, tier, patient_id, device_id, measurement = parts[:6]
    return tier, patient_id, device_id, measurement


def _build_reading(
        payload: Dict,
        patient_id: Optional[str],
        device_id: Optional[str],
        measurement: Optional[str]
) -> SensorReading:
    """
    Build SensorReading from payload and topic metadata.
    """
    value = payload.get("value")
    timestamp = payload.get("timestamp") or int(time.time())
    sensor_id = payload.get("sensor_id") or f"{device_id}_{measurement}"
    tags = payload.get("tags") or {}

    if patient_id:
        tags.setdefault("patient_id", patient_id)
    tags.setdefault("ingest_source", "mqtt")

    return SensorReading(
        measurement=payload.get("measurement") or measurement or "unknown",
        device_id=payload.get("device_id") or device_id or "unknown",
        sensor_id=sensor_id,
        value=float(value),
        timestamp=int(timestamp),
        tags=tags
    )


class Command(BaseCommand):
    help = "Subscribe to MQTT topics and ingest sensor data."

    def handle(self, *args, **options):
        if not settings.MQTT_ENABLED:
            self.stderr.write("MQTT is disabled. Set MQTT_ENABLED=True to run subscriber.")
            return

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                iot_logger.info("MQTT connected", source="mqtt")
                client.subscribe(settings.MQTT_TOPIC_RAW, qos=settings.MQTT_QOS)
                client.subscribe(settings.MQTT_TOPIC_PROCESSED, qos=settings.MQTT_QOS)
                iot_logger.info(
                    f"Subscribed to {settings.MQTT_TOPIC_RAW} and {settings.MQTT_TOPIC_PROCESSED}",
                    source="mqtt"
                )
            else:
                iot_logger.warning(f"MQTT connection failed: rc={rc}", source="mqtt")

        def on_disconnect(client, userdata, rc):
            iot_logger.warning(f"MQTT disconnected: rc={rc}", source="mqtt")

        def on_message(client, userdata, msg):
            try:
                tier, patient_id, device_id, measurement = _parse_topic(msg.topic)
                payload_raw = msg.payload.decode("utf-8", errors="ignore").strip()

                if not payload_raw:
                    return

                # Parse JSON or float payload
                if payload_raw.startswith("{"):
                    payload = json.loads(payload_raw)
                else:
                    payload = {"value": float(payload_raw)}

                reading = _build_reading(payload, patient_id, device_id, measurement)

                # Process based on tier
                if tier == "raw":
                    processed = edge_processor.process_reading(reading)
                    if processed is None:
                        return
                    processed.tags = processed.tags or {}
                    processed.tags["ingest_path"] = "mqtt_raw_processed"
                    mongodb_service.write_sensor_data(
                        measurement=processed.measurement,
                        device_id=processed.device_id,
                        sensor_id=processed.sensor_id,
                        value=processed.value,
                        timestamp=processed.timestamp,
                        tags=processed.tags
                    )
                else:
                    reading.tags = reading.tags or {}
                    reading.tags["ingest_path"] = "mqtt_processed"
                    mongodb_service.write_sensor_data(
                        measurement=reading.measurement,
                        device_id=reading.device_id,
                        sensor_id=reading.sensor_id,
                        value=reading.value,
                        timestamp=reading.timestamp,
                        tags=reading.tags
                    )

            except Exception as exc:
                iot_logger.warning(f"MQTT message error: {exc}", source="mqtt")

        client = create_mqtt_client(
            client_id="health_monitoring_subscriber",
            on_message=on_message,
            on_connect=on_connect,
            on_disconnect=on_disconnect
        )
        connect_mqtt(client)
        client.loop_forever()
