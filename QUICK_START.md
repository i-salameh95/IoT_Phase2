# Quick Start Guide

## Running the Project

### Step 1: Start All Services

```bash
# Navigate to project directory
cd /Users/israasalameh/Documents/y3.1\ IOT/Project-P1/IoTSimulator_P1

# Start all services (MongoDB, Django Backend, Frontend)
docker-compose up -d

# Check if all services are running
docker-compose ps
```

### Step 2: Verify Services

- **Frontend Dashboard**: http://localhost
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/api/v1/
- **Django Admin**: http://localhost:8000/admin
- **MQTT Broker**: localhost:1883

### Step 3: Run a Simulation Cycle

```bash
# Run a single simulation cycle
curl -X POST http://localhost:8000/api/v1/simulation/run-cycle \
  -H "Content-Type: application/json" \
  -d '{"patient_id": "P001"}'

# Run multiple cycles (20 cycles with 1 second delay)
curl -X POST http://localhost:8000/api/v1/simulation/run \
  -H "Content-Type: application/json" \
  -d '{"num_cycles": 20, "delay_seconds": 1.0, "patient_id": "P001"}'
```

---

## Connecting MongoDB Compass

### Connection Details

1. **Open MongoDB Compass** on your Mac

2. **Connection String**:
   ```
   mongodb://admin:admin123@localhost:27017/health_data?authSource=admin
   ```

3. **Or use individual fields**:
   - **Host**: `localhost`
   - **Port**: `27017`
   - **Authentication**: `Username/Password`
   - **Username**: `admin`
   - **Password**: `admin123`
   - **Authentication Database**: `admin`
   - **Default Database**: `health_data`

### Collections to View

Once connected, you'll see these collections:

1. **sensor_readings** - All health sensor data
   - Fields: `measurement`, `device_id`, `sensor_id`, `value`, `timestamp`, `tags`

2. **actuator_states** - Actuator state history
   - Fields: `actuator_id`, `device_id`, `actuator_type`, `state`, `value`, `timestamp`

3. **response_times** - Response time metrics (after running cycles)
   - Fields: `cycle`, `timestamp`, `timestamp_dt`, `patient_id`, `sensor_generation`, `edge_processing`, `storage`, `ml_prediction`, `actuator_decision`, `total`

4. **logs** - System logs (if logging to MongoDB)

### Viewing Data in Compass

1. Click on a collection name (e.g., `sensor_readings`)
2. Click "Documents" tab to see all records
3. Use filters to query specific data:
   - `{"measurement": "heart_rate"}` - Filter by measurement type
   - `{"device_id": "patient_001_wearable"}` - Filter by device
   - `{"timestamp": {"$gte": 1703000000}}` - Filter by time range

---

## Testing the System

### 1. Generate Some Data

```bash
# Run 10 simulation cycles
curl -X POST http://localhost:8000/api/v1/simulation/run \
  -H "Content-Type: application/json" \
  -d '{"num_cycles": 10, "delay_seconds": 0.5}'
```

### 2. Check Response Times

```bash
# Get response time statistics
curl http://localhost:8000/api/v1/analytics/response-times?limit=10
```

### 3. Export Data

```bash
# Export heart rate data to Excel
curl "http://localhost:8000/api/v1/analytics/export?measurement=heart_rate&format=xlsx" \
  --output heart_rate.xlsx

# Export to CSV
curl "http://localhost:8000/api/v1/analytics/export?measurement=heart_rate&format=csv" \
  --output heart_rate.csv
```

### 4. View in MongoDB Compass

After running cycles, open MongoDB Compass and:
- Navigate to `health_data` database
- Click on `sensor_readings` collection
- You should see health sensor data
- Click on `response_times` collection to see performance metrics

---

## Troubleshooting

### MongoDB Connection Issues

If Compass can't connect:

1. **Check if MongoDB container is running**:
   ```bash
   docker-compose ps
   ```

2. **Check MongoDB logs**:
   ```bash
   docker-compose logs mongodb
   ```

3. **Verify port 27017 is accessible**:
   ```bash
   # On Mac, check if port is in use
   lsof -i :27017
   ```

### Backend Not Starting

```bash
# Check backend logs
docker-compose logs django_backend

# Restart backend
docker-compose restart django_backend
```

### No Data in MongoDB

1. Make sure you've run simulation cycles
2. Check backend logs for errors
3. Verify MongoDB is accessible from backend container

---

## Useful Commands

```bash
# View all logs
docker-compose logs -f

# Stop all services
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v

# Rebuild containers
docker-compose up -d --build

# Access Django shell
docker-compose exec django_backend python manage.py shell

# Run Django migrations
docker-compose exec django_backend python manage.py migrate


-------

