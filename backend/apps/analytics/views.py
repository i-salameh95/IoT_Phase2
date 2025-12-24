"""
Views for Analytics API
Provides descriptive and prescriptive analytics with data export
"""
import json
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import HttpResponse, JsonResponse
from datetime import datetime, timedelta
from io import BytesIO

from app.core.mongodb_client import mongodb_service
from app.core.logger import iot_logger

try:
    import pandas as pd
    import openpyxl
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


@api_view(['GET'])
def export_data(request):
    """
    Export sensor data to Excel or CSV format
    
    Query parameters:
    - measurement: Sensor measurement type (optional)
    - device_id: Device ID (optional)
    - start_time: Start time (ISO format, optional)
    - end_time: End time (ISO format, optional)
    - format: Export format ('xlsx' or 'csv', default: 'xlsx')
    - limit: Maximum number of records (default: 10000)
    """
    if not PANDAS_AVAILABLE:
        return Response({
            "status": "error",
            "message": "Pandas and openpyxl required for data export"
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    
    try:
        measurement = request.query_params.get('measurement')
        device_id = request.query_params.get('device_id')
        format_type = request.query_params.get('format', 'xlsx').lower()
        limit = int(request.query_params.get('limit', 10000))
        
        # Parse time range
        start_time = request.query_params.get('start_time')
        end_time = request.query_params.get('end_time')
        
        # Convert ISO strings to datetime if provided
        start_dt = None
        end_dt = None
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except:
                pass
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            except:
                pass
        
        # Fetch data from MongoDB
        # Prepare time filter strings
        start_time_str = start_dt.isoformat() if start_dt else None
        end_time_str = end_dt.isoformat() if end_dt else None
        
        if measurement:
            # Single measurement query
            data = mongodb_service.query_sensor_data(
                measurement=measurement,
                device_id=device_id,
                limit=limit,
                start_time=start_time_str,
                stop_time=end_time_str,
                default_time_window=False  # Allow querying all data if no time filter
            )
        else:
            # Multiple measurements - get all available
            measurements = mongodb_service.get_distinct_measurements()
            if not measurements:
                measurements = [
                    "heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic",
                    "body_temperature", "oxygen_saturation", "glucose_level", "activity_steps",
                    "ambient_temperature", "humidity", "light_level", "motion_detected",
                    "co2_level", "sound_level"
                ]
            measurements = sorted(set(measurements))
            per_measurement_limit = max(1, limit // len(measurements))

            all_data = []
            for meas in measurements:
                meas_data = mongodb_service.query_sensor_data(
                    measurement=meas,
                    device_id=device_id,
                    limit=per_measurement_limit,
                    start_time=start_time_str,
                    stop_time=end_time_str,
                    default_time_window=False  # Allow querying all data if no time filter
                )
                all_data.extend(meas_data)
            data = all_data
        
        if not data:
            return Response({
                "status": "error",
                "message": "No data found for export"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Convert to DataFrame
        df = pd.DataFrame(data)

        # Rename columns for clarity
        if 'time' in df.columns:
            df = df.rename(columns={'time': 'timestamp'})
        if 'timestamp' in df.columns:
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
            except Exception:
                pass

        # Flatten tags into dedicated columns for spreadsheet-friendly exports.
        tag_keys = [
            "patient_id",
            "location",
            "device_type",
            "processed_by",
            "sensor_edge_type",
            "sensor_edge_attempts",
        ]
        if 'tags' in df.columns:
            def _tag_value(tags, key):
                if isinstance(tags, str):
                    try:
                        tags = json.loads(tags)
                    except Exception:
                        tags = {}
                if isinstance(tags, dict):
                    return tags.get(key)
                return None

            for key in tag_keys:
                df[f"tag_{key}"] = df['tags'].apply(lambda t, k=key: _tag_value(t, k))
            df = df.drop(columns=['tags'])

        preferred_cols = ["measurement", "timestamp", "device_id", "sensor_id", "value"]
        tag_cols = [f"tag_{k}" for k in tag_keys if f"tag_{k}" in df.columns]
        ordered_cols = [col for col in preferred_cols if col in df.columns] + tag_cols
        remaining_cols = [col for col in df.columns if col not in ordered_cols]
        if ordered_cols:
            df = df[ordered_cols + remaining_cols]
        
        # Export based on format
        if format_type == 'xlsx':
            # Create Excel file
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Sensor Data', index=False)
                
                # Get workbook and worksheet for formatting
                workbook = writer.book
                worksheet = writer.sheets['Sensor Data']
                
                # Format header row
                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF")
                
                for cell in worksheet[1]:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center")
                
                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            output.seek(0)
            
            # Create HTTP response
            response = HttpResponse(
                output.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            filename = f"health_monitoring_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response
            
        elif format_type == 'csv':
            if 'timestamp' in df.columns and pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                df = df.copy()
                df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')

            # Create CSV file
            output = BytesIO()
            df.to_csv(output, index=False)
            output.seek(0)
            
            response = HttpResponse(output.read(), content_type='text/csv')
            filename = f"health_monitoring_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response
        
        else:
            return Response({
                "status": "error",
                "message": f"Unsupported format: {format_type}. Use 'xlsx' or 'csv'"
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        iot_logger.error(f"Export error: {str(e)}", source="analytics")
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def analytics_summary(request):
    """
    Get descriptive analytics summary for sensor data
    
    Query parameters:
    - measurement: Sensor measurement type (required)
    - device_id: Device ID (optional)
    - window: Time window ('1h', '24h', '7d', '30d', default: '24h')
    """
    try:
        measurement = request.query_params.get('measurement')
        if not measurement:
            return Response({
                "status": "error",
                "message": "measurement parameter is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        device_id = request.query_params.get('device_id')
        window = request.query_params.get('window', '24h')
        
        # Get aggregated data
        aggregated = mongodb_service.get_aggregated_data(
            measurement=measurement,
            device_id=device_id,
            window=window,
            aggregate='mean'
        )
        
        # Get historical data for statistics
        historical = mongodb_service.query_sensor_data(
            measurement=measurement,
            device_id=device_id,
            limit=1000
        )
        
        if not historical:
            return Response({
                "status": "error",
                "message": "No data found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Calculate statistics
        values = [item.get('value', 0) for item in historical if 'value' in item]
        
        if not values:
            return Response({
                "status": "error",
                "message": "No valid values found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        import statistics
        
        summary = {
            "measurement": measurement,
            "device_id": device_id or "all",
            "window": window,
            "statistics": {
                "count": len(values),
                "mean": float(statistics.mean(values)),
                "median": float(statistics.median(values)),
                "std_dev": float(statistics.stdev(values)) if len(values) > 1 else 0.0,
                "min": float(min(values)),
                "max": float(max(values)),
                "range": float(max(values) - min(values))
            },
            "aggregated_data": aggregated[:10] if aggregated else [],
            "timestamp": datetime.now().isoformat()
        }
        
        # Add percentiles if we have enough data
        if len(values) >= 10:
            sorted_values = sorted(values)
            summary["statistics"]["p25"] = float(sorted_values[int(len(sorted_values) * 0.25)])
            summary["statistics"]["p75"] = float(sorted_values[int(len(sorted_values) * 0.75)])
            summary["statistics"]["p95"] = float(sorted_values[int(len(sorted_values) * 0.95)])
        
        return Response({
            "status": "success",
            "summary": summary
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        iot_logger.error(f"Analytics summary error: {str(e)}", source="analytics")
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def response_time_report(request):
    """
    Get response time statistics from simulation cycles

    Query parameters:
    - limit: Number of recent cycles to analyze (default: 100)
    - start_time: Start time (ISO format, optional)
    - end_time: End time (ISO format, optional)
    """
    try:
        limit = int(request.query_params.get('limit', 100))

        start_time = None
        end_time = None
        if request.query_params.get('start_time'):
            start_time = datetime.fromisoformat(request.query_params.get('start_time').replace('Z', '+00:00'))
        if request.query_params.get('end_time'):
            end_time = datetime.fromisoformat(request.query_params.get('end_time').replace('Z', '+00:00'))

        response_times_data = mongodb_service.query_response_times(
            limit=limit,
            start_time=start_time,
            end_time=end_time
        )

        if not response_times_data:
            return Response({
                "status": "info",
                "message": "No response time data found. Run simulation cycles to generate data.",
                "cycles_analyzed": 0,
                "statistics": {}
            }, status=status.HTTP_200_OK)

        stages = ['sensor_generation', 'edge_processing', 'storage', 'ml_prediction', 'actuator_decision', 'total']
        stage_data = {stage: [] for stage in stages}

        for record in response_times_data:
            for stage in stages:
                if stage in record and record[stage] is not None:
                    stage_data[stage].append(float(record[stage]))

        import statistics

        def percentile(sorted_vals, p: float):
            if not sorted_vals:
                return 0.0
            n = len(sorted_vals)
            idx = int(n * p)
            if idx >= n:
                idx = n - 1
            return float(sorted_vals[idx])

        def compute_stats(values):
            if not values:
                return None
            sorted_vals = sorted(values)
            return {
                "count": len(values),
                "avg": round(float(statistics.mean(values)), 4),
                "min": round(float(min(values)), 4),
                "max": round(float(max(values)), 4),
                "p95": round(percentile(sorted_vals, 0.95), 4),
                "median": round(float(statistics.median(values)), 4),
            }

        statistics_result = {}
        for stage in stages:
            stats_obj = compute_stats(stage_data[stage])
            if stats_obj:
                statistics_result[stage] = stats_obj

        return Response({
            "status": "success",
            "cycles_analyzed": len(response_times_data),
            "time_range": {
                "start": start_time.isoformat() if start_time else None,
                "end": end_time.isoformat() if end_time else None
            },
            "statistics": statistics_result,
            "timestamp": datetime.now().isoformat()
        }, status=status.HTTP_200_OK)

    except Exception as e:
        iot_logger.error(f"Response time report error: {str(e)}", source="analytics")
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
