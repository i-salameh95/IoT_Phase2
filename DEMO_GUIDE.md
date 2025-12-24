# Health Monitoring IoT System - Demo Guide

## 🎯 Quick Demo Flow

### Step 1: Start the System
```bash
docker-compose up -d
```

Wait for all services to start (check with `docker-compose ps`).

### Step 2: Access the Dashboard
Open http://localhost in your browser.

---

## 📊 Demo Scenarios

### Scenario A: Normal Operation (Recommended for First Demo)

**What to do:**
1. Select a patient (e.g., "Patient P001")
2. Click **"Run Single Cycle"** (without emergency flag)
3. Observe:
   - Vital signs appear in normal ranges
   - Environment sensors (ambient temp, humidity, CO2) show normal ranges
   - Health status shows "NORMAL" (green)
   - No critical alerts
   - Actuators remain inactive (normal state)

**What this demonstrates:**
- Normal health monitoring
- Sensor data generation
- Additional environmental sensors visible in the UI
- Edge processing (filtering, validation)
- ML prediction (if model is trained)
- Data storage in MongoDB

**When to use:** Start with this to show normal operation.

---

### Scenario B: Emergency Simulation

**What to do:**
1. Check the **"Simulate Emergency"** checkbox
2. Select a patient
3. Click **"Run Single Cycle"**
4. Observe:
   - Vital signs show critical values (red indicators)
   - Health status changes to "CRITICAL" or "WARNING"
   - Alerts appear in the alerts panel
   - Actuators activate (Alert System, Emergency Call, etc.)
   - Logs show emergency events

**What this demonstrates:**
- Emergency detection
- ML-based critical status prediction
- Actuator response to emergencies
- Alert system activation
- Emergency call system

**When to use:** After showing normal operation, demonstrate emergency handling.

---

### Scenario C: Continuous Monitoring

**What to do:**
1. Set cycles: **20**
2. Set delay: **2 seconds**
3. (Optional) Check "Simulate Emergency" for mixed scenarios
4. Click **"Start Monitoring"**
5. Observe:
   - Dashboard updates every 2 seconds
   - Charts populate with historical data
   - Logs accumulate
   - Actuators respond to changing conditions

**What this demonstrates:**
- Continuous monitoring
- Real-time data updates
- Historical data visualization
- System responsiveness

**When to use:** To show continuous operation and data accumulation.

---

## 🏗️ Architecture Explanation

### System Flow (Step by Step)

```
1. Health Sensors (Simulated)
   ↓
   Generate health data (heart rate, BP, temperature, etc.)
   
2. Edge Processor (Python Service)
   ↓
   - Filters noise (moving average)
   - Detects outliers (IQR method)
   - Validates ranges (medical thresholds)
   - Detects anomalies (bradycardia, hypoxia, etc.)
   - SpO2 can be filtered at the sensor layer before gateway
   
3. Django Backend (Cloud/Gateway)
   ↓
   - Receives processed sensor data
   - Stores in MongoDB (data warehouse)
   - Invokes ML model for health status prediction
   - Controller makes actuator decisions
   
4. ML Model Service
   ↓
   - Predicts: Normal / Warning / Critical
   - Uses trained model (Random Forest, etc.)
   - Provides confidence scores
   
5. Actuator Controller
   ↓
   - ML-based decisions (if model trained)
   - Rule-based fallback (safety rules)
   - Triggers actuators:
     * Alert System (warnings)
     * Medication Dispenser (glucose, etc.)
     * Emergency Call System (critical)
   
6. MongoDB (Data Warehouse)
   ↓
   Stores:
   - sensor_readings (all health data)
   - actuator_states (actuator history)
   - response_times (performance metrics)
   - logs (system events)
   
7. Frontend Dashboard
   ↓
   - Displays real-time vital signs
   - Shows health status
   - Visualizes historical data
   - Displays actuator states
   - Shows system logs
```

---

## 🔍 Where is the Gateway?

**Answer:** The Django Backend **IS** the gateway/cloud service.

In this architecture:
- **Edge Processor** = Local processing (on device or edge device)
- **Django Backend** = Cloud/Gateway (central processing)
- **MongoDB** = Data warehouse (cloud storage)

### Why this design?

1. **Edge Processing** happens BEFORE data reaches the gateway:
   - Reduces bandwidth (only valid data sent)
   - Reduces latency (local filtering)
   - Improves reliability (validates before transmission)

2. **Gateway (Django)** receives processed data:
   - Performs ML analysis
   - Makes actuator decisions
   - Stores in data warehouse
   - Serves dashboard

3. **Data Warehouse (MongoDB)** stores everything:
   - Historical sensor data
   - Actuator state history
   - Performance metrics
   - System logs

---

## 🎛️ Understanding the Controls

### "Run Single Cycle"
- Runs **one** complete monitoring cycle
- Good for: Testing, single demonstrations
- Shows: One snapshot of the system

### "Start Monitoring"
- Runs **multiple** cycles continuously
- Good for: Showing continuous operation
- Shows: Data accumulation, trends, actuator responses over time

### "Simulate Emergency" Checkbox

**When to check it:**
- ✅ To demonstrate emergency handling
- ✅ To show actuator responses
- ✅ To test alert system
- ✅ To see critical health status

**When NOT to check it:**
- ❌ To show normal operation
- ❌ To demonstrate baseline monitoring
- ❌ First demo (start with normal)

**What happens when checked:**
- Sensors generate critical values:
  - Heart rate: 40-50 or 150-200 bpm (bradycardia/tachycardia)
  - Blood pressure: Very low or very high
  - Temperature: Hypothermia (35°C) or Fever (38.5-42°C)
  - SpO2: Hypoxia (70-90%)
  - Glucose: Hypoglycemia (40-70) or Hyperglycemia (200-400)

**Where to see effects:**
1. **Vital Signs Cards**: Turn red with ⚠ indicators
2. **Health Status Panel**: Changes to "CRITICAL" or "WARNING"
3. **Alerts Panel**: Shows critical alerts
4. **Actuator Status**: Actuators activate (Alert System ON, Emergency Call ON)
5. **System Logs**: Shows emergency events

---

## 📈 What to Show in Demo

### 1. Normal Operation (2 minutes)
- Run single cycle (no emergency)
- Show normal vital signs
- Show environment sensors panel (ambient temp, humidity, CO2)
- Explain normal ranges
- Show data in MongoDB Compass

### 2. Emergency Detection (2 minutes)
- Check "Simulate Emergency"
- Run single cycle
- Show critical indicators
- Explain actuator responses
- Show alerts

### 3. Continuous Monitoring (1 minute)
- Start monitoring (10 cycles, 2 sec delay)
- Show dashboard updating
- Show charts populating
- Show logs accumulating

### 4. Architecture Overview (2 minutes)
- Explain edge processing
- Explain gateway (Django)
- Explain data warehouse (MongoDB)
- Show data flow diagram

### 5. ML & Analytics (1 minute)
- Show ML training (if time)
- Show analytics export
- Show response time metrics
- Optional: export CSV and point out tag_* columns (patient_id, location, processed_by)

**Total: ~8 minutes**

---

## 🔧 Troubleshooting Demo

### No data showing?
- Run at least one cycle first
- Check MongoDB is running: `docker-compose ps mongodb`
- Check backend logs: `docker-compose logs django_backend`

### Actuators not activating?
- Run a cycle with "Simulate Emergency" checked
- Check actuator states endpoint: `curl http://localhost:8000/api/v1/actuators/states/current`

### Logs not showing?
- Logs populate after running cycles
- Check logs endpoint: `curl http://localhost:8000/api/v1/logs`

### Charts empty?
- Run multiple cycles first
- Click "Refresh Chart"
- Select different sensor from dropdown

---

## 💡 Key Points to Emphasize

1. **Edge Processing**: Happens BEFORE gateway, reduces bandwidth, improves reliability
2. **Designated Sensor Edge**: SpO2 can be processed at the sensor tier before gateway
3. **ML-Based Decisions**: Uses trained models for health status prediction
4. **Actuator Response**: Automatic response to health conditions
5. **Data Warehouse**: All data stored in MongoDB for analysis
6. **Real-Time Dashboard**: Live updates of vital signs and system status
7. **Emergency Handling**: Automatic detection and response to critical conditions

---

## 📝 Demo Script (Example)

"Today I'll demonstrate a Health Monitoring IoT System. This system monitors patients' vital signs and automatically responds to health emergencies.

First, let me show normal operation. I'll run a single monitoring cycle for Patient P001. As you can see, all vital signs are in normal ranges - heart rate 72 bpm, blood pressure 120/80, temperature 36.5°C. The health status is NORMAL.

Now, let me simulate an emergency. I'll check the 'Simulate Emergency' flag and run another cycle. Notice how the vital signs change - heart rate drops to 45 bpm (bradycardia), SpO2 drops to 85% (hypoxia). The system detects this as CRITICAL and automatically activates the Alert System and Emergency Call System.

The system uses edge processing to filter and validate data before it reaches the cloud gateway. The Django backend performs ML-based analysis and makes actuator decisions. All data is stored in MongoDB for historical analysis.

Let me start continuous monitoring to show how the system operates over time..."

---

Good luck with your demo! 🚀
