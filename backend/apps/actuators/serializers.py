"""
Serializers for Health Monitoring Actuators
"""
from rest_framework import serializers


class ActuatorStateSerializer(serializers.Serializer):
    """Serializer for actuator state"""
    actuator_id = serializers.CharField()
    device_id = serializers.CharField()
    actuator_type = serializers.CharField()
    state = serializers.CharField()
    value = serializers.FloatField(required=False, allow_null=True)
    timestamp = serializers.IntegerField(required=False, allow_null=True)
    tags = serializers.DictField(required=False, allow_null=True)


class ActuatorStateResponseSerializer(serializers.Serializer):
    """Serializer for actuator state response"""
    time = serializers.CharField()
    actuator_id = serializers.CharField()
    device_id = serializers.CharField()
    actuator_type = serializers.CharField()
    state = serializers.CharField()
    value = serializers.FloatField(required=False, allow_null=True)
