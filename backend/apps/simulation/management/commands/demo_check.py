"""
Run a minimal logical system check without manual UI steps.
"""
from django.core.management.base import BaseCommand

from app.services.health_simulation_engine import health_simulation_engine
from app.services.edge_processor import edge_processor
from app.models.sensor import SensorReading


class Command(BaseCommand):
    help = "Run one normal cycle, one emergency cycle, and an edge filter check."

    def handle(self, *args, **options):
        self.stdout.write("Running normal cycle...")
        normal = health_simulation_engine.run_cycle(patient_id="P001", simulate_emergency=False)

        self.stdout.write("Running emergency cycle...")
        emergency = health_simulation_engine.run_cycle(patient_id="P001", simulate_emergency=True)

        self.stdout.write("Edge filter check (out-of-range)...")
        bad = SensorReading(
            measurement="body_temperature",
            device_id="patient_001_wearable",
            sensor_id="patient_001_wearable_body_temperature",
            value=80.0,
            timestamp=0,
            tags={"patient_id": "P001"},
        )
        filtered = edge_processor.process_reading(bad)

        def summarize(result, label):
            return {
                "label": label,
                "readings": result.get("sensor_readings"),
                "processed": result.get("processed_readings"),
                "filtered": result.get("filtered_readings"),
                "emergency": result.get("emergency_triggered"),
                "decisions": result.get("decisions_made"),
                "health_status": (result.get("ml_prediction") or {}).get("health_status"),
            }

        normal_sum = summarize(normal, "normal")
        emergency_sum = summarize(emergency, "emergency")

        self.stdout.write("")
        self.stdout.write("Summary:")
        self.stdout.write(str(normal_sum))
        self.stdout.write(str(emergency_sum))
        self.stdout.write(f"Edge filtered out-of-range: {'YES' if filtered is None else 'NO'}")

        # Basic assertions (non-fatal, just report)
        issues = []
        if normal_sum["readings"] == 0:
            issues.append("normal cycle produced 0 readings")
        if not emergency_sum["emergency"]:
            issues.append("emergency flag did not trigger")
        if emergency_sum["decisions"] == 0:
            issues.append("emergency cycle made 0 actuator decisions")
        if filtered is not None:
            issues.append("edge did not filter out-of-range reading")

        if issues:
            self.stdout.write("")
            self.stdout.write("Issues detected:")
            for issue in issues:
                self.stdout.write(f"- {issue}")
        else:
            self.stdout.write("")
            self.stdout.write("All checks passed.")
