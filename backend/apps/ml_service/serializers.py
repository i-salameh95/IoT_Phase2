"""
Serializers for ML Service
"""
from rest_framework import serializers


class SensorReadingInputSerializer(serializers.Serializer):
    """Serializer for sensor reading input"""
    measurement = serializers.CharField()
    device_id = serializers.CharField()
    sensor_id = serializers.CharField()
    value = serializers.FloatField()
    timestamp = serializers.IntegerField(required=False, allow_null=True)
    tags = serializers.DictField(required=False, allow_null=True)


class PredictionRequestSerializer(serializers.Serializer):
    """Serializer for prediction request"""
    readings = SensorReadingInputSerializer(many=True)


class TrainingRequestSerializer(serializers.Serializer):
    """Serializer for training request"""
    algorithm = serializers.CharField(required=False, default='random_forest')
    test_size = serializers.FloatField(required=False, default=0.2, min_value=0.1, max_value=0.5)
    force_retrain = serializers.BooleanField(required=False, default=False)


class ModelComparisonRequestSerializer(serializers.Serializer):
    """Serializer for model comparison request"""
    algorithms = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True
    )
    test_size = serializers.FloatField(required=False, default=0.2, min_value=0.1, max_value=0.5)
