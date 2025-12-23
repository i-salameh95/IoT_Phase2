# Health Monitoring IoT System – Phase 2

---

## 1. Executive Summary

- **Scope**: Health Monitoring IoT System with health sensors (heart rate, blood pressure, temperature, SpO2, glucose), health actuators (alert system, medication dispenser, emergency call), ML-based decision making, and edge processing.
- **Features**: Health monitoring simulation cycles, historical queries, actuator monitoring, centralized logging, MongoDB data warehouse, Dockerized deployment, HTML/CSS/JS dashboard, ML service, analytics export.
- **Data Flow**: Health Sensors → Edge Processor (Python) → Django Cloud → ML Model → Controller → Actuators → MongoDB → Dashboard.
- **Why it matters**: Demonstrates IoT principles for healthcare (data acquisition, edge processing, ML-based decision making, actuation, visualization) with production-ready architecture.

---

## 2. Architecture at a Glance

```
Health Sensors (simulated) ─┐
                             │ raw sensor data
                       ┌──────▼──────────────┐
                       │ Edge Processor      │  Edge Processing (Local)
                       │ (Python Service)    │  - Filter noise
                       │                     │  - Detect outliers
                       └──────┬──────────────┘  - Range validation
                              │                  - Anomaly detection
                              │ processed data
                       ┌──────▼─────────────┐
                       │ Django Backend     │  Gateway/Cloud Service
                       │  (Gateway)         │  - ML Model Service
                       │  + ML Model        │  - Actuator Controller
                       │  + Controller      │  - Data Storage
                       └──────┬─────────────┘
                              │
                       ┌──────▼─────────────┐
                       │ MongoDB            │  Data Warehouse
                       │ (Data Warehouse)   │  - sensor_readings
                       │                    │  - actuator_states
                       └──────┬─────────────┘  - response_times
                              │                  - logs
                       ┌──────▼──────┐
                       │ HTML/CSS/JS │
                       │  Dashboard  │
                       └─────────────┘
```

### Architecture Components Explained:

1. **Health Sensors (Simulated)**: Generate health data (heart rate, BP, temperature, etc.)
2. **Edge Processor**: Python service that processes data BEFORE it reaches the gateway:
   - Filters noise (moving average)
   - Detects outliers (IQR method)
   - Validates ranges (medical thresholds)
   - Detects anomalies (bradycardia, hypoxia, etc.)
   - **Why Edge Processing?** Reduces bandwidth, improves reliability, reduces latency
3. **Django Backend (Gateway/Cloud)**: Central processing service:
   - Receives processed sensor data
   - ML Model Service: Predicts health status (Normal/Warning/Critical)
   - Actuator Controller: Makes decisions based on ML predictions or rules
   - Stores data in MongoDB
4. **MongoDB (Data Warehouse)**: Stores all data for analysis:
   - `sensor_readings`: All health sensor data
   - `actuator_states`: Actuator state history
   - `response_times`: Performance metrics
   - `logs`: System event logs
5. **Frontend Dashboard**: Real-time visualization of system state

---

## 3. Technology Stack

| Layer        | Technology                                                    |
| ------------ | -------------------------------------------------------------- |
| Backend      | Python 3.11+/Django 4.2, Django REST Framework                |
| Storage      | MongoDB (primary), UTF-8 CSV fallback (sensor/actuator/logs) |
| Frontend     | HTML5, CSS3, JavaScript (Chart.js, Axios)                    |
| Edge Processing | Python Service (noise filtering, outlier detection, validation) |
| ML/Analytics | scikit-learn, pandas, numpy, xgboost                          |
| Messaging    | MQTT (Mosquitto broker, paho-mqtt client)                     |
| Tooling      | Docker Compose                                                |

---

## 4. Repository Layout

```text
IoTSimulator_P1/
├── backend/
│   ├── apps/                # Django apps
│   │   ├── sensors/        # Health sensor API
│   │   ├── actuators/       # Health actuator API
│   │   ├── simulation/      # Simulation API
│   │   ├── analytics/       # Analytics (Phase 2)
│   │   └── ml_service/      # ML service (Phase 2)
│   ├── app/                 # Core services (shared)
│   │   ├── core/            # MongoDB, logger, config
│   │   ├── models/          # Data models
│   │   └── services/        # Health monitoring services
│   ├── health_monitoring/   # Django project
│   ├── manage.py            # Django management
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                # HTML/CSS/JS dashboard
├── docker-compose.yml       # All services
├── Project_Phase#1.pdf      # Phase 1 requirements
├── Project-Final.pdf         # Phase 2 requirements
└── README.md                # This document
```

---

## 5. Core Building Blocks

### 5.1 Health Sensor Simulator (`app/services/health_sensor_simulator.py`)
- Generates health sensor readings for patient devices
- **Sensors**: Heart Rate (60-100 bpm), Blood Pressure (120/80 mmHg), Body Temperature (36.1-37.2°C), Oxygen Saturation (95-100%), Glucose Level (70-100 mg/dL), Activity Steps
- **Devices**: `patient_001_wearable`, `patient_001_bedside`, `patient_001_glucose`, etc.
- Supports emergency scenario simulation

### 5.2 Health Simulation Engine (`app/services/health_simulation_engine.py`)
1. Generate health sensor readings for all patient devices
2. Process through Edge Processor (noise filtering, outlier detection, validation)
3. Store processed readings in MongoDB (data warehouse)
4. Invoke ML-based controller to evaluate health status
5. Store actuator responses + logs
6. Track and log response times for all stages
7. Repeat for N cycles with optional delay

### 5.3 Health Actuator Controller (`app/services/health_actuator_controller.py`)
- **ML-Based Decisions**: Uses ML model predictions (Normal/Warning/Critical)
- **Rule-Based Fallback**: Safety rules when ML not available
- **Actuators**:
  - Alert System (ON/OFF) - Health warnings
  - Medication Dispenser (ON/OFF, dosage) - For glucose/medication
  - Emergency Call System (ON/OFF) - Critical situations
  - Health Report Generator (ACTIVE/IDLE) - Daily/weekly reports

### 5.4 Edge Processing (`app/services/edge_processor.py`)
- **Noise Filtering**: Moving average filter to reduce sensor noise
- **Outlier Detection**: IQR-based outlier detection
- **Range Validation**: Validates sensor values against medical thresholds
- **Anomaly Detection**: Detects health anomalies (bradycardia, hypoxia, fever, etc.)

### 5.5 Logging & Storage (`app/core/logger.py`, `app/core/mongodb_client.py`)
- Unified logging API writes to MongoDB when available, otherwise to CSV
- Sensor/actuator data follow the same pattern
- MongoDB indexes for efficient time-range queries

---

## 6. Operating Modes (How to Run)

### Option A – Docker Compose (Full Stack) ⭐ Recommended

```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs (optional)
docker-compose logs -f
```

**Services exposed:**
- Frontend: http://localhost
- Backend/API: http://localhost:8000
- API Docs: http://localhost:8000/api/v1/ (Django REST Framework)
- MongoDB: localhost:27017

**Connecting MongoDB Compass:**
1. Open MongoDB Compass on your Mac
2. Use connection string: `mongodb://admin:admin123@localhost:27017/health_data?authSource=admin`
3. Or use individual fields:
   - Host: `localhost`
   - Port: `27017`
   - Username: `admin`
   - Password: `admin123`
   - Auth Database: `admin`
   - Default Database: `health_data`

**Collections to view:**
- `sensor_readings` - Health sensor data
- `actuator_states` - Actuator state history
- `response_times` - Response time metrics (after running cycles)

### Option B – Local Development

**Backend (Django)**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

**Frontend**
```bash
cd frontend
# Serve with any HTTP server, e.g.:
python3 -m http.server 8001
# Or use nginx/apache
```

### Option C – Development
```bash
cd backend
python manage.py shell
# Or run migrations:
python manage.py migrate
```

---

## 7. API Quick Reference

| Endpoint | Description |
| --- | --- |
| `POST /api/v1/simulation/run-cycle` | Run one health monitoring cycle |
| `POST /api/v1/simulation/run` | Run multiple cycles (with delay) |
| `POST /api/v1/sensors/ingest` | Manually push health sensor readings |
| `POST /api/v1/sensors/ingest/batch` | Batch ingest sensor data |
| `POST /api/v1/sensors/query/historical` | Historical health data (supports measurement/device filters) |
| `POST /api/v1/sensors/query/aggregated` | Windowed aggregations (`mean/max/min/sum`) |
| `GET /api/v1/sensors/measurements` | Available health sensor types |
| `GET /api/v1/sensors/devices` | Available patient device IDs |
| `GET /api/v1/actuators/states` | Full actuator history (chronological) |
| `GET /api/v1/actuators/states/current` | Latest state per actuator |
| `POST /api/v1/actuators/control` | Manually control actuator |
| `POST /api/v1/ml/predict` | Predict health status from sensor readings |
| `POST /api/v1/ml/train` | Train ML model with specified algorithm |
| `POST /api/v1/ml/compare` | Compare multiple ML algorithms and select best |
| `GET /api/v1/ml/status` | Get ML model status and available algorithms |
| `GET /api/v1/analytics/export` | Export sensor data to Excel/CSV |
| `GET /api/v1/analytics/summary` | Get descriptive analytics summary |
| `GET /api/v1/analytics/response-times` | Get response time statistics |

*When running in CSV mode (MongoDB offline), these endpoints read/write CSV files transparently.*

---

## 8. Health Monitoring Sensors

### Sensor Types:
1. **Heart Rate** - 60-100 bpm (normal), 40-200 bpm (full range)
2. **Blood Pressure Systolic** - 90-140 mmHg (normal), 70-220 mmHg (full range)
3. **Blood Pressure Diastolic** - 60-90 mmHg (normal), 40-140 mmHg (full range)
4. **Body Temperature** - 36.1-37.2 C (normal), 35.0-42.0 C (full range)
5. **Oxygen Saturation (SpO2)** - 95-100% (normal), 70-100% (full range)
6. **Glucose Level** - 70-100 mg/dL (normal), 40-400 mg/dL (full range)
7. **Activity Steps** - 0-20000 steps/day
8. **Ambient Temperature** - 20-24 C (normal), 15-35 C (full range)
9. **Humidity** - 30-60% RH (normal), 10-90% RH (full range)
10. **Light Level** - 100-800 lux (normal), 0-2000 lux (full range)
11. **Motion (PIR)** - 0 or 1 (detected)
12. **CO2 Level** - 400-1000 ppm (normal), 350-5000 ppm (full range)
13. **Sound Level** - 30-60 dB (normal), 10-120 dB (full range)

### Patient Devices:
- `patient_001_wearable` - Heart Rate, SpO2, Temperature, Activity
- `patient_001_bedside` - Blood Pressure, Temperature
- `patient_001_glucose` - Glucose Level
- `patient_001_room` - Ambient Temp, Humidity, Light, Motion, CO2, Sound
- `patient_002_wearable`, `patient_002_bedside` - Additional patients
- `patient_002_room` - Room environment sensors

---

## 9. Health Actuators

### Actuator Types:
1. **Alert System** - Health warnings and notifications
2. **Medication Dispenser** - Automatic medication delivery (e.g., glucose for hypoglycemia)
3. **Emergency Call System** - Automatic emergency service calls
4. **Health Report Generator** - Daily/weekly health reports

---

## 10. Edge Processing

### Edge Processor Service (`app/services/edge_processor.py`):
The edge processor performs initial data processing before data reaches the cloud backend:

- **Noise Filtering**: Moving average filter to reduce sensor noise
- **Outlier Detection**: IQR-based outlier detection to identify anomalous readings
- **Range Validation**: Validates sensor values against medical thresholds
- **Anomaly Detection**: Detects health anomalies (bradycardia, tachycardia, hypoxia, fever, hypoglycemia, hyperglycemia)

### Processing Flow:
1. Raw sensor readings are generated
2. Edge processor filters and validates data
3. Processed readings are stored in MongoDB
4. ML model and controller use processed data for decisions

---

## 11. Data Outputs & Storage

| Storage | Purpose |
| --- | --- |
| `MongoDB` | Primary data warehouse (sensor_readings, actuator_states, logs) |
| `backend/storage/sensor_readings.csv` | CSV fallback (when MongoDB offline) |
| `backend/storage/actuator_states.csv` | Actuator state history |
| `backend/storage/logs.csv` | System logs |

Delete CSV files to start fresh; the backend will recreate them automatically.

---

## 12. Phase 2 Features (In Progress)

### ✅ Completed:
- Django backend migration
- Health monitoring sensors (7 types)
- Health monitoring actuators (4 types)
- Health simulation engine with response time tracking
- Edge processing service (Python)
- Docker Compose setup
- HTML/CSS/JS frontend dashboard
- **ML service (health status prediction with multi-algorithm comparison)** ✨
- Analytics & data export (Excel/CSV)
- Response time evaluation

### Future Enhancements:
- Real-time model retraining
- Advanced analytics & visualizations
- Cloud deployment
- Real device integration via MQTT (broker + subscriber service available)

---

## 13. Development Notes & Future Work

- **Current**: ML-based and rule-based decision making (ML automatically used when trained)
- **ML Service**: Health status prediction (Normal/Warning/Critical) with multi-algorithm comparison (Random Forest, Gradient Boosting, SVM, Logistic Regression, KNN, Naive Bayes, Decision Tree, AdaBoost)
- **Response Time Evaluation**: Full instrumentation and reporting for all pipeline stages (sensor generation, edge processing, storage, ML prediction, actuator decision)
- **Analytics Export**: Excel/CSV export and descriptive analytics (mean, median, std, percentiles)
- **Edge Processing**: Python-based edge processor with noise filtering, outlier detection, range validation, and anomaly detection
- **Future**: Real device integration, advanced ML models, cloud deployment
- **Performance**: MongoDB indexes optimized for time-range queries

---

## 14. Support / References

- **API Docs**: Django REST Framework browsable API at `/api/v1/` endpoints
- **MongoDB**: localhost:27017 (use MongoDB Compass or any MongoDB client)
- **Django Admin**: http://localhost:8000/admin (admin/admin123)

---

## 15. Example Usage

### Start Simulation:
```bash
curl -X POST http://localhost:8000/api/v1/simulation/run-cycle \
  -H "Content-Type: application/json" \
  -d '{"patient_id": "P001"}'
```

### Get Health Sensor Measurements:
```bash
curl http://localhost:8000/api/v1/sensors/measurements
```

### Get Current Actuator States:
```bash
curl http://localhost:8000/api/v1/actuators/states/current
```

### Query Historical Heart Rate Data:
```bash
curl -X POST http://localhost:8000/api/v1/sensors/query/historical \
  -H "Content-Type: application/json" \
  -d '{
    "measurement": "heart_rate",
    "device_id": "patient_001_wearable",
    "limit": 100
  }'
```

---

## 16. Project Requirements

- **Phase 1**: Smart Home IoT Simulator (completed)
- **Phase 2**: Health Monitoring IoT System with ML (current)
  - Additional sensor types ✅
  - Edge processing (Python service) ✅
  - Data conversion for analytics (Excel/CSV export) ✅
  - ML model for decision making ✅
  - Prescriptive analysis (ML predictions guide actuator decisions) ✅
  - Response time evaluation ✅

---

**Happy monitoring! 🏥💓**
