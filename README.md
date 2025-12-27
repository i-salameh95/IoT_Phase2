# Health Monitoring IoT System (Phase 2)

End-to-end health IoT stack with simulated sensors (vitals + environment), edge processing, ML-guided actuation, MQTT ingestion, and a web dashboard. Designed to demonstrate a realistic device → edge → broker → cloud → analytics/control pipeline with CSV fallback when the database is offline.

---

## Quick Start (Docker Compose)

```bash
docker compose up -d          # start backend, frontend, MongoDB, Mosquitto, MQTT subscriber
docker compose ps             # verify all services are Up
```

Services: frontend (http://localhost), backend/API (http://localhost:8000), MongoDB (27017), Mosquitto (1883), MQTT subscriber (ingest), ML/analytics inside backend.  
Mongo Compass URI: `mongodb://admin:admin123@localhost:27017/health_data?authSource=admin`

Sanity checks:
- Recent sensor rows: `docker compose exec mongodb mongosh health_data --eval 'db.sensor_readings.find().sort({timestamp:-1}).limit(3).pretty()'`
- ML dataset report: `docker compose exec django_backend sh -c "PYTHONPATH=/app python3 tools/ml_report.py --per_measurement_limit 5000 --train"`

---

## Architecture & Services

**Device / Simulator** (`backend/app/services/health_sensor_simulator.py`): generates readings per device/patient; SpO2 is pre-filtered at the sensor tier.  
**Edge Processor (Gateway)** (`backend/app/services/edge_processor.py`): range validation, moving-average smoothing, IQR outlier tagging (or drop), anomaly tags.  
**Messaging**: Mosquitto broker; publisher uses MQTT when `MQTT_ENABLED=True`; subscriber ingests raw/processed topics.  
**Ingestion / API** (Django backend): persists to MongoDB (or CSV fallback), exposes REST, ML, analytics, and actuator control.  
**Storage**: MongoDB primary; CSV fallback in `backend/storage` for sensors, actuators, logs when DB unavailable.  
**ML/Analytics**: scikit-learn models, training/comparison endpoints, descriptive stats, export to CSV/XLSX, response-time metrics.  
**Actuators**: alert, medication dispenser, emergency call, health report generator.  
**Dashboard** (frontend): charts, controls, ML status, response-time view, MQTT indicator (based on recent `source="mqtt"` logs).

Docker Compose layers:
- `django_backend`: REST/ML/analytics/ingest fallback.
- `frontend`: static dashboard.
- `mongodb`: data warehouse.
- `mqtt` (Mosquitto): broker.
- `mqtt_subscriber`: consumes MQTT topics, writes to storage.

---

## Sensors, Actuators, and Devices

Sensors (13): heart_rate, blood_pressure_systolic, blood_pressure_diastolic, body_temperature, oxygen_saturation (sensor-edge), glucose_level, activity_steps, ambient_temperature, humidity, light_level, motion_detected, co2_level, sound_level.  
Devices: `patient_001_*` (wearable, bedside, glucose, room) and `patient_002_*` (wearable, bedside, room).  
Actuators: alert system, medication dispenser, emergency call system, health report generator.

---

## Data Flow (two ingestion modes)

1) **Simulation/REST path** (default demo):  
   Simulator → sensor-edge (SpO2) → gateway edge processor → Django API → MongoDB → dashboard/analytics/ML.

2) **MQTT path** (IoT-style):  
   Simulator publishes processed readings to `iot/health/processed/{patient}/{device}/{measurement}` → Mosquitto → `mqtt_subscriber` → MongoDB → dashboard/analytics/ML. Raw devices can publish to `iot/health/raw/...`; subscriber will edge-process before storage.

CSV fallback: if Mongo is down, sensor/actuator/log writes go to `backend/storage/*.csv`; endpoints read/write transparently. Response-time metrics are Mongo-only.

Emergency simulation: toggle in UI or send `simulate_emergency` with optional `emergency_rate` (0–1 or percent). Default ~15% when enabled. Emergency values push vitals into critical ranges to exercise edge + ML + actuators.

---

## Edge Processing (gateway)

- Range validation (plausibility bounds per measurement).  
- Noise filtering: moving-average smoothing with rolling buffers.  
- Outlier detection: IQR-based; default mode tags outliers instead of dropping to preserve emergencies (configurable to drop).  
- Anomaly tags: hypoxia, tachycardia, fever, hypoglycemia, etc.  
- Traceability: tags include `processed_by`, `original_value`, `filtered`, `outlier`, optional bounds. SpO2 processed at sensor tier is tagged `processed_by=sensor_edge`.

---

## Simulation & Data Generation

- Per-cycle tagging: every reading carries `patient_id` and `cycle` to support per-cycle feature building.  
- Devices emit their mapped measurements each cycle; timestamps are epoch seconds.  
- Emergency and warning scenarios adjust generator ranges to hit clinical thresholds.  
- MQTT publish happens after edge processing when enabled; otherwise writes directly to Mongo/CSV.

---

## ML Service and Labeling

Features used for prediction (`app/services/ml_model_service.py`):  
`heart_rate, blood_pressure_systolic, blood_pressure_diastolic, body_temperature, oxygen_saturation, glucose_level, activity_steps`

Labeling (weak supervision): derived from clinical thresholds per feature (normal/warning/critical). Grouped per patient + cycle to form one sample with 7 features.  
Algorithms: RandomForest, GradientBoosting, LogisticRegression, SVM, KNN, NaiveBayes, DecisionTree, AdaBoost.  
Training: `/api/v1/ml/train` fits a chosen model; `/api/v1/ml/compare` runs CV/holdout, selects best, and fits it for immediate use.  
Retrain policy: auto-trains when enough samples exist; periodic retrain after N cycles/new samples.  
Prediction: `/api/v1/ml/predict` (ad-hoc readings) or automatic per cycle; actuator controller uses ML-first decisions with safety-rule fallback.

---

## Analytics & Exports

- Descriptive stats: `/api/v1/analytics/summary` (mean/median/std/p25/p75/p95).  
- Response times: `/api/v1/analytics/response-times` (sensor_gen, edge_processing, storage, ml_prediction, actuator_decision, total).  
- Export: `/api/v1/analytics/export` → CSV/XLSX; flattens tags to `tag_*` columns for analysis readiness.

---

## Running Without Docker (development)

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Frontend (static)
cd ../frontend
python3 -m http.server 8001
```

Set env vars for Mongo/MQTT if not using Docker (see `backend/app/core/config.py`).

---

## API Highlights

- Simulation: `POST /api/v1/simulation/run-cycle`, `POST /api/v1/simulation/run`  
- Sensors: `POST /api/v1/sensors/ingest`, `/ingest/batch`, `/query/historical`, `/query/aggregated`, `GET /measurements`, `GET /devices`  
- Actuators: `GET /actuators/states`, `GET /actuators/states/current`, `POST /actuators/control`  
- ML: `POST /ml/predict`, `POST /ml/train`, `POST /ml/compare`, `GET /ml/status`  
- Analytics: `GET /analytics/export`, `GET /analytics/summary`, `GET /analytics/response-times`

---

## Notes on MQTT Indicator

The dashboard MQTT badge is driven by recent `source="mqtt"` logs (expires after ~2 minutes). It may show OFF even while Mosquitto and the subscriber are running; rely on `docker compose ps` or Mongo inserts for truth.
