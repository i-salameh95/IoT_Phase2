"""
Serializers for Health Monitoring Sensors
"""
from rest_framework import serializers


class SensorReadingSerializer(serializers.Serializer):
    """Serializer for ingesting sensor data"""
    measurement = serializers.CharField(help_text="Measurement type (e.g., 'heart_rate', 'blood_pressure')")
    device_id = serializers.CharField(help_text="Device identifier")
    sensor_id = serializers.CharField(help_text="Sensor identifier")
    value = serializers.FloatField(help_text="Sensor reading value")
    timestamp = serializers.IntegerField(required=False, allow_null=True, help_text="Unix timestamp")
    tags = serializers.DictField(required=False, allow_null=True, help_text="Additional tags")


class SensorReadingResponseSerializer(serializers.Serializer):
    """Serializer for sensor data response"""
    time = serializers.CharField()
    measurement = serializers.CharField()
    device_id = serializers.CharField()
    sensor_id = serializers.CharField()
    value = serializers.FloatField()


class HistoricalDataQuerySerializer(serializers.Serializer):
    """Serializer for querying historical data"""
    measurement = serializers.CharField()
    device_id = serializers.CharField(required=False, allow_null=True)
    sensor_id = serializers.CharField(required=False, allow_null=True)
    start_time = serializers.CharField(required=False, allow_null=True, help_text="RFC3339 format")
    stop_time = serializers.CharField(required=False, allow_null=True, help_text="RFC3339 format")
    limit = serializers.IntegerField(default=1000, min_value=1, max_value=10000)


class AggregatedDataQuerySerializer(serializers.Serializer):
    """Serializer for querying aggregated data"""
    measurement = serializers.CharField()
    device_id = serializers.CharField(required=False, allow_null=True)
    sensor_id = serializers.CharField(required=False, allow_null=True)
    window = serializers.CharField(default="1h", help_text="Time window (e.g., '1h', '5m')")
    aggregate = serializers.CharField(default="mean", help_text="Aggregation function (mean, max, min, sum)")
