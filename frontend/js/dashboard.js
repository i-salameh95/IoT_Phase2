/**
 * Main Dashboard Logic (Improved Demo-Ready Version)
 */

// Global state
let isSimulationRunning = false;
let updateInterval = null;
let uiInterval = null;

let currentPatientId = 'P001';
let lastReadings = {};
let lastCycleResult = null;

// Logs incremental state
let lastLogTimestamp = null;
let seenLogIds = new Set(); // if logs have ids; otherwise we dedupe by time+msg
const appStartTime = new Date();
let showPreviousActuators = false;
let mlCompareChart = null;
let lastMqttSeenAt = null;
let cycleHistory = [];
let uiMode = 'idle';
let lastCycleAt = null;

// Update cadence
const IDLE_REFRESH_MS = 5000;
const RUNNING_REFRESH_MS = 1500;

// Vital signs / measurements
const VITAL_MEASUREMENTS = [
  'heart_rate',
  'blood_pressure_systolic',
  'blood_pressure_diastolic',
  'body_temperature',
  'oxygen_saturation',
  'glucose_level',
  'activity_steps'
];

const ENV_MEASUREMENTS = [
  'ambient_temperature',
  'humidity',
  'light_level',
  'motion_detected',
  'co2_level',
  'sound_level'
];

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
  initializeDashboard();
  setupEventListeners();
  updateCurrentTime();
  setInterval(updateCurrentTime, 1000);

  // Initial load
  updateDashboard({ force: true });

  // Start in idle mode refresh
  setRefreshMode('idle');
});

function initializeDashboard() {
  console.log('Initializing Health Monitoring Dashboard...');
  updateSystemStatus('online');
  updateMqttStatus(false);
  updateSessionSummary();
}

function setupEventListeners() {
  // Simulation controls
  document.getElementById('btn-start-cycle')?.addEventListener('click', handleRunCycle);
  document.getElementById('btn-start-demo')?.addEventListener('click', handleStartDemo);
  document.getElementById('btn-start-simulation')?.addEventListener('click', handleStartSimulation);
  document.getElementById('btn-stop-simulation')?.addEventListener('click', handleStopSimulation);
  document.getElementById('btn-ml-train')?.addEventListener('click', handleTrainModel);
  document.getElementById('btn-ml-compare')?.addEventListener('click', handleCompareModels);
  document.getElementById('btn-reset-run')?.addEventListener('click', handleResetRun);

  // Patient selection
  document.getElementById('patient-select')?.addEventListener('change', (e) => {
    currentPatientId = e.target.value;
    // Changing patient should immediately refresh UI
    updateSessionSummary();
    updateDashboard({ force: true });
  });

  // Chart refresh (manual override)
  document.getElementById('btn-refresh-chart-vitals')?.addEventListener('click', () => refreshChart('vitals'));
  document.getElementById('btn-refresh-chart-env')?.addEventListener('click', () => refreshChart('env'));

  // Logs
  document.getElementById('btn-clear-logs')?.addEventListener('click', () => {
    clearLogs();
    lastLogTimestamp = null;
    seenLogIds.clear();
  });
  document.getElementById('log-filter')?.addEventListener('change', () => {
    clearLogs();
    lastLogTimestamp = null;
    seenLogIds.clear();
    updateLogs({ force: true });
  });

  document.getElementById('toggle-previous-actuators')?.addEventListener('change', (e) => {
    showPreviousActuators = Boolean(e.target.checked);
    updateActuators();
  });
}

function setRefreshMode(mode) {
  if (uiInterval) clearInterval(uiInterval);

  const interval = mode === 'running' ? RUNNING_REFRESH_MS : IDLE_REFRESH_MS;
  uiInterval = setInterval(() => updateDashboard(), interval);
  updateSessionSummary();
}

function setUiMode(mode) {
  uiMode = mode;
  updateSessionSummary();
}

function patientIdToDevicePrefix(patientId) {
  if (!patientId) return null;
  const match = String(patientId).match(/^P(\d+)/i);
  if (match) {
    const digits = match[1].padStart(3, '0');
    return `patient_${digits}`;
  }
  return `patient_${patientId}`;
}

function getSelectedDeviceId() {
  if (currentPatientId === 'all') return null;
  const prefix = patientIdToDevicePrefix(currentPatientId);
  return `${prefix}_wearable`;
}

function getDeviceIdForMeasurement(measurement) {
  if (currentPatientId === 'all') return null;
  const prefix = patientIdToDevicePrefix(currentPatientId);
  if (ENV_MEASUREMENTS.includes(measurement)) return `${prefix}_room`;
  if (measurement === 'glucose_level') return `${prefix}_glucose`;
  if (measurement === 'blood_pressure_systolic' || measurement === 'blood_pressure_diastolic' || measurement === 'body_temperature') {
    return `${prefix}_bedside`;
  }
  return `${prefix}_wearable`;
}

async function handleRunCycle() {
  const btn = document.getElementById('btn-start-cycle');
  if (btn) btn.disabled = true;

  const simulateEmergency = document.getElementById('simulate-emergency')?.checked || false;
  const statusDiv = document.getElementById('simulation-status');

  try {
    setStatus(statusDiv, 'Running cycle...', 'info');
    setUiMode('manual');

    const result = await api.runCycle(currentPatientId === 'all' ? null : currentPatientId, simulateEmergency);
    lastCycleResult = result;

    setStatus(
      statusDiv,
      `Cycle ${result.cycle} completed. ${result.sensor_readings} readings, ${result.decisions_made} decisions.`,
      'success'
    );

    // Immediately reflect the cycle output in UI (no need to wait for polling)
    renderLatestCycle(result);
    await updateDashboard({ force: true });

  } catch (error) {
    setStatus(statusDiv, `Error: ${error.message || 'Failed to run cycle'}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleStartDemo() {
  if (isSimulationRunning) return;

  const startBtn = document.getElementById('btn-start-simulation');
  const stopBtn = document.getElementById('btn-stop-simulation');
  const demoBtn = document.getElementById('btn-start-demo');
  const statusDiv = document.getElementById('simulation-status');

  if (startBtn) startBtn.disabled = true;
  if (demoBtn) demoBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = false;
  isSimulationRunning = true;
  setUiMode('demo');

  setStatus(statusDiv, 'Starting demo: normal -> emergency -> normal', 'info');
  setRefreshMode('running');

  try {
    const patientId = currentPatientId === 'all' ? null : currentPatientId;

    const normal = await api.runCycle(patientId, false);
    lastCycleResult = normal;
    renderLatestCycle(normal);
    await updateDashboard({ force: true });

    await new Promise((r) => setTimeout(r, 800));

    const emergency = await api.runCycle(patientId, true);
    lastCycleResult = emergency;
    renderLatestCycle(emergency);
    await updateDashboard({ force: true });

    await new Promise((r) => setTimeout(r, 800));

    const normal2 = await api.runCycle(patientId, false);
    lastCycleResult = normal2;
    renderLatestCycle(normal2);
    await updateDashboard({ force: true });

    setStatus(statusDiv, 'Demo completed. You can start monitoring next.', 'success');
  } catch (error) {
    setStatus(statusDiv, `Error: ${error.message || 'Demo failed'}`, 'error');
  } finally {
    isSimulationRunning = false;
    setUiMode('manual');
    if (startBtn) startBtn.disabled = false;
    if (demoBtn) demoBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    setRefreshMode('idle');
  }
}

async function handleTrainModel() {
  const statusEl = document.getElementById('ml-status-message');
  setStatus(statusEl, 'Training model (default)...', 'info');
  try {
    await api.trainModel('random_forest');
    setStatus(statusEl, 'Model trained successfully.', 'success');
    await updateMlStatus();
  } catch (error) {
    setStatus(statusEl, `Error: ${error.message || 'Training failed'}`, 'error');
  }
}

async function handleCompareModels() {
  const statusEl = document.getElementById('ml-status-message');
  setStatus(statusEl, 'Comparing models (this may take a minute)...', 'info');
  try {
    const result = await api.compareModels();
    setStatus(statusEl, 'Model comparison complete.', 'success');
    renderModelComparison(result);
  } catch (error) {
    setStatus(statusEl, `Error: ${error.message || 'Comparison failed'}`, 'error');
  }
}

async function handleResetRun() {
  const statusDiv = document.getElementById('simulation-status');
  setStatus(statusDiv, 'Resetting run data...', 'info');
  try {
    await api.resetSimulation();
    lastReadings = {};
    lastCycleResult = null;
    cycleHistory = [];
    lastCycleAt = null;
    clearLogs();
    if (window.chartManagers) {
      if (window.chartManagers.vitals) window.chartManagers.vitals.refresh();
      if (window.chartManagers.env) window.chartManagers.env.refresh();
    }
    const timeline = document.getElementById('cycle-timeline');
    if (timeline) timeline.innerHTML = '';
    renderLatestCycle({ readings: [] });
    updateFlowMap(null);
    setStatus(statusDiv, 'Run data cleared. Start a cycle to generate new data.', 'success');
  } catch (error) {
    setStatus(statusDiv, `Error: ${error.message || 'Reset failed'}`, 'error');
  }
}

async function handleStartSimulation() {
  if (isSimulationRunning) return;

  const numCycles = parseInt(document.getElementById('num-cycles')?.value, 10) || 20;
  const delaySeconds = parseFloat(document.getElementById('delay-seconds')?.value) || 2;
  const simulateEmergency = document.getElementById('simulate-emergency')?.checked || false;

  const startBtn = document.getElementById('btn-start-simulation');
  const stopBtn = document.getElementById('btn-stop-simulation');
  const statusDiv = document.getElementById('simulation-status');

  if (startBtn) startBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = false;
  isSimulationRunning = true;
  setUiMode('monitoring');

  setStatus(statusDiv, `Starting simulation: ${numCycles} cycles...`, 'info');

  // Switch to high-frequency refresh while running
  setRefreshMode('running');

  // Fire and forget
  api.runSimulation(numCycles, delaySeconds, currentPatientId === 'all' ? null : currentPatientId, simulateEmergency)
    .then(result => {
      lastCycleResult = result?.last_cycle_result || lastCycleResult;

      setStatus(statusDiv, `Simulation completed. ${result.total_cycles} cycles.`, 'success');
      isSimulationRunning = false;
      setUiMode('manual');
      if (startBtn) startBtn.disabled = false;
      if (stopBtn) stopBtn.disabled = true;

      // Back to idle refresh
      setRefreshMode('idle');
      updateDashboard({ force: true });
    })
    .catch(error => {
      setStatus(statusDiv, `Error: ${error.message || 'Simulation failed'}`, 'error');
      isSimulationRunning = false;
      setUiMode('manual');
      if (startBtn) startBtn.disabled = false;
      if (stopBtn) stopBtn.disabled = true;

      setRefreshMode('idle');
    });
}

async function handleStopSimulation() {
  const startBtn = document.getElementById('btn-start-simulation');
  const stopBtn = document.getElementById('btn-stop-simulation');
  const statusDiv = document.getElementById('simulation-status');

  try {
    await api.stopSimulation();
    isSimulationRunning = false;
    setUiMode('manual');

    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;

    setStatus(statusDiv, 'Simulation stopped', 'info');

    // Back to idle refresh
    setRefreshMode('idle');
  } catch (error) {
    console.error('Error stopping simulation:', error);
    setStatus(statusDiv, `Error stopping simulation: ${error.message}`, 'error');
  }
}

function setStatus(el, message, type) {
  if (!el) return;
  el.textContent = message;
  el.className = `status-message ${type === 'success' ? 'success' : type === 'error' ? 'error' : ''}`.trim();
}

async function updateDashboard({ force = false } = {}) {
  try {
    await updateVitalSigns();
    await updateHealthStatus();
    await updateActuators();
    await updateLogs({ force });
    await updateMlStatus();
    updateSessionSummary();

    // Auto-refresh chart periodically (but not every tick)
    if (window.chartManagers && (force || shouldRefreshChart())) {
      if (window.chartManagers.vitals) window.chartManagers.vitals.refresh();
      if (window.chartManagers.env) window.chartManagers.env.refresh();
    }

    // Response time stats panel (optional)
    await updateResponseTimesPanel();

  } catch (error) {
    console.error('Error updating dashboard:', error);
  }
}

let lastChartRefreshAt = 0;
function shouldRefreshChart() {
  const now = Date.now();
  if (now - lastChartRefreshAt > 5000) {
    lastChartRefreshAt = now;
    return true;
  }
  return false;
}

async function updateVitalSigns() {
  const allMeasurements = [...VITAL_MEASUREMENTS, ...ENV_MEASUREMENTS];
  const requests = allMeasurements.map((m) => {
    const deviceId = getDeviceIdForMeasurement(m);
    return api.getHistoricalData(m, deviceId, 1).then((d) => ({ m, d })).catch(() => ({ m, d: [] }));
  });

  const results = await Promise.all(requests);

  results.forEach(({ m, d }) => {
    if (d && d.length > 0) {
      const reading = d[d.length - 1];
      lastReadings[m] = reading.value;
      updateVitalSignCard(m, reading.value);
    }
  });

  const sys = lastReadings['blood_pressure_systolic'];
  const dia = lastReadings['blood_pressure_diastolic'];
  if (sys != null && dia != null) {
    updateVitalSignCard('blood_pressure', sys, dia);
  }
}

function updateVitalSignCard(measurement, value, value2 = null) {
  const cardMap = {
    'heart_rate': { valueId: 'value-hr', statusId: 'status-hr', cardId: 'card-heart-rate' },
    'blood_pressure': { valueId: 'value-bp', statusId: 'status-bp', cardId: 'card-blood-pressure' },
    'body_temperature': { valueId: 'value-temp', statusId: 'status-temp', cardId: 'card-temperature' },
    'oxygen_saturation': { valueId: 'value-spo2', statusId: 'status-spo2', cardId: 'card-spo2' },
    'glucose_level': { valueId: 'value-glucose', statusId: 'status-glucose', cardId: 'card-glucose' },
    'activity_steps': { valueId: 'value-activity', statusId: 'status-activity', cardId: 'card-activity' },
    'ambient_temperature': { valueId: 'value-room-temp', statusId: 'status-room-temp', cardId: 'card-ambient-temperature' },
    'humidity': { valueId: 'value-humidity', statusId: 'status-humidity', cardId: 'card-humidity' },
    'light_level': { valueId: 'value-light', statusId: 'status-light', cardId: 'card-light' },
    'motion_detected': { valueId: 'value-motion', statusId: 'status-motion', cardId: 'card-motion' },
    'co2_level': { valueId: 'value-co2', statusId: 'status-co2', cardId: 'card-co2' },
    'sound_level': { valueId: 'value-sound', statusId: 'status-sound', cardId: 'card-sound' }
  };

  const card = cardMap[measurement];
  if (!card) return;

  const valueEl = document.getElementById(card.valueId);
  if (valueEl) {
    if (value2 !== null) valueEl.textContent = `${Math.round(value)}/${Math.round(value2)}`;
    else if (measurement === 'motion_detected') valueEl.textContent = value > 0 ? '1' : '0';
    else valueEl.textContent = Math.round(value * 10) / 10;
  }

  const status = getHealthStatus(measurement, value, value2);
  const statusEl = document.getElementById(card.statusId);
  if (statusEl) {
    statusEl.textContent = status.label;
    statusEl.className = `card-status ${status.class}`;
  }

  const cardEl = document.getElementById(card.cardId);
  if (cardEl) {
    if (status.class === 'critical') {
      cardEl.style.background = 'linear-gradient(135deg, rgba(196, 69, 54, 0.18) 0%, rgba(196, 69, 54, 0.08) 100%)';
      cardEl.style.color = '#112125';
    } else {
      cardEl.style.background = 'linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(233, 239, 236, 0.9) 100%)';
      cardEl.style.color = '#112125';
    }
  }
}

function getHealthStatus(measurement, value, value2 = null) {
  if (measurement === 'heart_rate') {
    if (value < 50 || value > 150) return { label: 'CRIT', class: 'critical' };
    if (value < 60 || value > 120) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'blood_pressure_systolic') {
    if (value < 90 || value > 180) return { label: 'CRIT', class: 'critical' };
    if (value > 140) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'blood_pressure_diastolic') {
    if (value < 60 || value > 120) return { label: 'CRIT', class: 'critical' };
    if (value > 90) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'blood_pressure') {
    if (value < 90 || value > 180 || value2 < 60 || value2 > 120) return { label: 'CRIT', class: 'critical' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'body_temperature') {
    if (value < 35.0 || value > 39.0) return { label: 'CRIT', class: 'critical' };
    if (value < 36.0 || value > 38.0) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'oxygen_saturation') {
    if (value < 90) return { label: 'CRIT', class: 'critical' };
    if (value < 95) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'glucose_level') {
    if (value < 70 || value > 200) return { label: 'CRIT', class: 'critical' };
    if (value < 80 || value > 140) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'ambient_temperature') {
    if (value < 18.0 || value > 27.0) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'humidity') {
    if (value < 25 || value > 70) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'light_level') {
    if (value < 50 || value > 1200) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'motion_detected') {
    return { label: value > 0 ? 'ON' : 'OFF', class: value > 0 ? 'warning' : 'normal' };
  }
  if (measurement === 'co2_level') {
    if (value > 1500) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  if (measurement === 'sound_level') {
    if (value > 80) return { label: 'WARN', class: 'warning' };
    return { label: 'OK', class: 'normal' };
  }
  return { label: 'OK', class: 'normal' };
}

async function updateActuators() {
  try {
    const actuators = await api.getActuatorStates();
    const grid = document.getElementById('actuators-grid');
    if (!grid) return;

    grid.innerHTML = '';

    if (!actuators || actuators.length === 0) {
      grid.innerHTML = '<p>No actuators active</p>';
      return;
    }

    const actuatorIcons = {
      'alert': 'ALERT',
      'medication_dispenser': 'MED',
      'emergency_call': 'CALL',
      'health_report': 'REPORT',
      'alert_system': 'ALERT',
      'medication': 'MED',
      'emergency': 'CALL',
      'report': 'REPORT'
    };

    actuators.forEach(actuator => {
      const item = document.createElement('div');
      item.className = 'actuator-item';

      const icon = actuatorIcons[(actuator.actuator_type || '').toLowerCase()] || 'ACT';
      const typeName = (actuator.actuator_type || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

      const state = (actuator.state || '').toUpperCase();
      const isActive = state === 'ON' || state === 'ACTIVE';

      const logTime = new Date(actuator.time);
      const now = new Date();
      const minutesAgo = (now - logTime) / (1000 * 60);
      const isRecent = minutesAgo < 5;
      const isFromThisSession = logTime >= appStartTime;

      if (!showPreviousActuators && !isFromThisSession) {
        return;
      }

      item.innerHTML = `
        <div class="actuator-icon">${icon}</div>
        <h4>${typeName}</h4>
        <div class="actuator-state ${isActive ? 'on' : 'off'}">${state || 'UNKNOWN'}</div>
        ${!isFromThisSession ? '<div style="font-size: 0.75em; color: #999; margin-top: 3px;">(Previous run)</div>' : ''}
        <div style="font-size: 0.85em; color: #666; margin-top: 5px;">${actuator.device_id || ''}</div>
      `;
      grid.appendChild(item);
    });
  } catch (error) {
    console.error('Error updating actuators:', error);
  }
}

async function updateHealthStatus() {
  const statusEl = document.getElementById('health-status-indicator');
  const textEl = document.getElementById('health-status-text');

  let overallStatus = 'normal';
  let alerts = [];

  if (lastReadings.heart_rate != null) {
    if (lastReadings.heart_rate < 50 || lastReadings.heart_rate > 150) {
      overallStatus = 'critical';
      alerts.push({ type: 'critical', message: `Heart Rate: ${lastReadings.heart_rate} bpm (Critical)` });
    } else if (lastReadings.heart_rate < 60 || lastReadings.heart_rate > 120) {
      if (overallStatus !== 'critical') overallStatus = 'warning';
      alerts.push({ type: 'warning', message: `Heart Rate: ${lastReadings.heart_rate} bpm (Warning)` });
    }
  }

  if (lastReadings.oxygen_saturation != null && lastReadings.oxygen_saturation < 90) {
    overallStatus = 'critical';
    alerts.push({ type: 'critical', message: `SpO2: ${lastReadings.oxygen_saturation}% (Critical - Hypoxia)` });
  }

  if (lastReadings.body_temperature != null) {
    if (lastReadings.body_temperature < 35.0 || lastReadings.body_temperature > 39.0) {
      overallStatus = 'critical';
      alerts.push({ type: 'critical', message: `Temperature: ${lastReadings.body_temperature} C (Critical)` });
    }
  }

  if (lastReadings.co2_level != null && lastReadings.co2_level > 1500) {
    if (overallStatus !== 'critical') overallStatus = 'warning';
    alerts.push({ type: 'warning', message: `CO2: ${lastReadings.co2_level} ppm (High)` });
  }

  if (lastReadings.humidity != null && (lastReadings.humidity < 25 || lastReadings.humidity > 70)) {
    if (overallStatus !== 'critical') overallStatus = 'warning';
    alerts.push({ type: 'warning', message: `Humidity: ${lastReadings.humidity}% (Out of range)` });
  }

  if (statusEl && textEl) {
    const icon = document.getElementById('health-status-icon');
    if (icon) icon.textContent = overallStatus === 'critical' ? 'CRIT' : overallStatus === 'warning' ? 'WARN' : 'OK';
    textEl.textContent = overallStatus.toUpperCase();
    statusEl.className = `status-indicator-large ${overallStatus}`;
  }

  updateAlerts(alerts);
}

function updateAlerts(alerts) {
  const alertsList = document.getElementById('alerts-list');
  if (!alertsList) return;

  alertsList.innerHTML = '';

  if (!alerts || alerts.length === 0) {
    alertsList.innerHTML = '<p style="color: #666;">No alerts</p>';
    return;
  }

  alerts.forEach(alert => {
    const item = document.createElement('div');
    item.className = `alert-item ${alert.type}`;
    item.textContent = alert.message;
    alertsList.appendChild(item);
  });
}

function updateCurrentTime() {
  const timeEl = document.getElementById('current-time');
  if (timeEl) timeEl.textContent = new Date().toLocaleString();
}

function updateSystemStatus(status) {
  const pill = document.getElementById('system-status-pill');
  if (!pill) return;
  const upper = (status || 'offline').toUpperCase();
  pill.textContent = `SYSTEM: ${upper}`;
  pill.className = `status-pill${status === 'online' ? '' : ' muted'}`;
}

function updateSessionSummary() {
  const patientEl = document.getElementById('overview-patient');
  const modeEl = document.getElementById('overview-mode');
  const cycleEl = document.getElementById('overview-cycle');
  const emergencyEl = document.getElementById('overview-emergency');
  const sourceEl = document.getElementById('overview-source');
  const refreshEl = document.getElementById('overview-refresh');

  if (patientEl) patientEl.textContent = currentPatientId.toUpperCase();
  if (modeEl) {
    const label = uiMode === 'monitoring' ? 'MONITORING' : uiMode === 'demo' ? 'DEMO' : uiMode === 'manual' ? 'MANUAL' : 'IDLE';
    modeEl.textContent = label;
  }
  if (cycleEl) {
    const cycleText = lastCycleAt ? `${lastCycleAt.toLocaleTimeString()}` : '-';
    cycleEl.textContent = cycleText;
  }
  if (emergencyEl) {
    emergencyEl.textContent = lastCycleResult?.emergency_triggered ? 'YES' : 'NO';
  }
  if (sourceEl) {
    const mqttFresh = lastMqttSeenAt && (Date.now() - lastMqttSeenAt) < 120000;
    sourceEl.textContent = mqttFresh ? 'MQTT' : 'SIMULATOR';
  }
  if (refreshEl) {
    const interval = isSimulationRunning ? RUNNING_REFRESH_MS : IDLE_REFRESH_MS;
    refreshEl.textContent = `${Math.round(interval / 1000)}s`;
  }
}

function updateMqttStatus(isOn) {
  const pill = document.getElementById('mqtt-status-pill');
  if (!pill) return;
  pill.textContent = `MQTT: ${isOn ? 'ON' : 'OFF'}`;
  pill.className = `status-pill${isOn ? '' : ' muted'}`;
}

async function updateLogs({ force = false } = {}) {
  const container = document.getElementById('logs-container');
  if (!container) return;

  try {
    const filter = document.getElementById('log-filter')?.value || 'all';
    const source = filter === 'all' ? null : filter;

    // Keep it simple: fetch latest 50 each time, but append only new ones
    const logs = await api.getLogs(null, source, 50);

    if (!logs || logs.length === 0) {
      if (container.childElementCount === 0) {
        container.innerHTML = '<div class="log-entry info"><span class="log-message">No logs available</span></div>';
      }
      return;
    }

    // Clear "No logs" placeholder on first real data
    if (container.childElementCount === 1 && container.textContent.includes('No logs available')) {
      container.innerHTML = '';
    }

    const hasMqtt = logs.some((log) => String(log.source || '').toLowerCase() === 'mqtt');
    if (hasMqtt) {
      lastMqttSeenAt = Date.now();
    }
    const mqttFresh = lastMqttSeenAt && (Date.now() - lastMqttSeenAt) < 120000;
    updateMqttStatus(Boolean(mqttFresh));
    updateSessionSummary();

    // Append only new logs (best-effort dedupe)
    const toAppend = [];
    logs.forEach(log => {
      const key = `${log.time || ''}|${log.level || ''}|${log.source || ''}|${log.message || ''}`;
      if (!seenLogIds.has(key)) {
        seenLogIds.add(key);
        toAppend.push(log);
      }
    });

    // If force (filter change), rebuild list
    if (force) {
      container.innerHTML = '';
      seenLogIds.clear();
      logs.forEach(log => {
        const key = `${log.time || ''}|${log.level || ''}|${log.source || ''}|${log.message || ''}`;
        seenLogIds.add(key);
        renderLogEntry(container, log);
      });
      container.scrollTop = container.scrollHeight;
      return;
    }

    // Append in chronological order
    toAppend.reverse().forEach(log => renderLogEntry(container, log));

    container.scrollTop = container.scrollHeight;
  } catch (error) {
    console.error('Error updating logs:', error);
    container.innerHTML = '<div class="log-entry error"><span class="log-message">Error loading logs</span></div>';
  }
}

function renderLogEntry(container, log) {
  const entry = document.createElement('div');
  entry.className = `log-entry ${(log.level || 'info').toLowerCase()}`;

  const time = log.time ? new Date(log.time).toLocaleTimeString() : '';
  const sourceText = log.source || 'unknown';
  const message = log.message || '';

  entry.innerHTML = `
    <span class="log-time">[${time}]</span>
    <span class="log-source">[${sourceText}]</span>
    <span class="log-message">${escapeHtml(message)}</span>
  `;
  container.appendChild(entry);
}

function escapeHtml(str) {
  return String(str)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function clearLogs() {
  const container = document.getElementById('logs-container');
  if (container) container.innerHTML = '';
}

function refreshChart(target = 'all') {
  if (!window.chartManagers) return;
  if (target === 'vitals' && window.chartManagers.vitals) window.chartManagers.vitals.refresh();
  if (target === 'env' && window.chartManagers.env) window.chartManagers.env.refresh();
  if (target === 'all') {
    if (window.chartManagers.vitals) window.chartManagers.vitals.refresh();
    if (window.chartManagers.env) window.chartManagers.env.refresh();
  }
}

async function updateResponseTimesPanel() {
  const el = document.getElementById('response-times-panel');
  if (!el) return;

  try {
    const stats = await api.getResponseTimeStats(100);
    // Expected: { statistics: { total: { avg, p95, ... }, sensor_generation: {...}, ... } }
    if (!stats || !stats.statistics || !stats.statistics.total) return;

    const total = stats.statistics.total;
    el.innerHTML = `
      <div><strong>Response Time (Total)</strong></div>
      <div>avg: ${formatMs(total.avg)} | p95: ${formatMs(total.p95)} | max: ${formatMs(total.max)}</div>
    `;
  } catch (e) {
    // non-critical
  }
}

async function updateMlStatus() {
  const statusEl = document.getElementById('ml-status');
  const algoEl = document.getElementById('ml-algorithm');
  const classesEl = document.getElementById('ml-classes');
  if (!statusEl || !algoEl || !classesEl) return;

  try {
    const status = await api.getMlStatus();
    statusEl.textContent = status.is_trained ? 'TRAINED' : 'UNTRAINED';
    algoEl.textContent = status.current_algorithm_name || status.current_algorithm || '-';
    classesEl.textContent = Array.isArray(status.class_names) ? status.class_names.join(', ') : '-';
  } catch (e) {
    statusEl.textContent = 'UNKNOWN';
    algoEl.textContent = '-';
    classesEl.textContent = '-';
  }
}

function formatMs(seconds) {
  if (seconds == null) return '-';
  return `${Math.round(seconds * 1000)} ms`;
}

function renderLatestCycle(result) {
  // Optional UI elements - only update if present
  const meta = document.getElementById('latest-cycle-meta');
  if (meta) {
    const mlText = result.ml_prediction && result.ml_prediction.health_status
      ? `${result.ml_prediction.health_status} (${Math.round((result.ml_prediction.confidence || 0) * 100)}%)`
      : 'N/A';
    const cycleLabel = result.cycle != null ? result.cycle : '-';
    meta.innerHTML = `
      <div><strong>Last Cycle:</strong> ${cycleLabel}</div>
      <div><strong>Readings:</strong> ${result.sensor_readings ?? '-'} | <strong>Decisions:</strong> ${result.decisions_made ?? '-'}</div>
      <div><strong>Emergency:</strong> ${result.emergency_triggered ? 'YES' : 'NO'} | <strong>ML:</strong> ${mlText}</div>
    `;
  }

  updatePipeline(result);
  updateFlowMap(result);

  if (result.cycle != null) {
    lastCycleAt = new Date();
  }
  updateSessionSummary();

  const emergencyBanner = document.getElementById('emergency-banner');
  if (emergencyBanner) {
    emergencyBanner.style.display = result.emergency_triggered ? 'block' : 'none';
  }
  const page = document.querySelector('.page');
  if (page) {
    page.classList.toggle('critical-mode', Boolean(result.emergency_triggered));
  }

  const decisionsEl = document.getElementById('actuator-decisions');
  if (decisionsEl) {
    const decisions = result.actuator_decisions || [];
    if (!decisions.length) {
      decisionsEl.textContent = 'No actuator decisions yet.';
    } else {
      decisionsEl.innerHTML = decisions.map((d) => {
        const type = (d.actuator_type || '').replace(/_/g, ' ');
        const state = d.state || 'UNKNOWN';
        const device = d.device_id || '';
        return `<div><strong>${type}</strong>: ${state} ${device ? `(${device})` : ''}</div>`;
      }).join('');
    }
  }

  const confidenceEl = document.getElementById('health-confidence');
  if (confidenceEl) {
    if (result.ml_prediction && result.ml_prediction.health_status) {
      const conf = Math.round((result.ml_prediction.confidence || 0) * 100);
      confidenceEl.textContent = `Confidence: ${conf}% (${result.ml_prediction.algorithm || 'model'})`;
    } else {
      confidenceEl.textContent = 'Confidence: -';
    }
  }

  // If backend returns readings list, show table
  // Expect something like result.readings = [{measurement, value, ...}, ...]
  const tbody = document.getElementById('latest-cycle-table');
  if (!tbody) return;

  tbody.innerHTML = '';
  const readings = result.readings || result.latest_readings || [];
  if (!Array.isArray(readings) || readings.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4">No cycle readings payload returned. (Consider adding it to run-cycle response)</td></tr>';
    return;
  }

  readings.forEach(r => {
    const value = r.processed_value != null ? r.processed_value : r.value;
    const status = r.filtered_out ? { label: 'FILTERED', class: 'filtered' } : getHealthStatus(r.measurement, value);
    const rowClass = status.class === 'critical' ? 'row-critical' : status.class === 'warning' ? 'row-warning' : '';
    const tr = document.createElement('tr');
    if (rowClass) tr.className = rowClass;
    tr.innerHTML = `
      <td>${r.measurement || ''}</td>
      <td>${r.value != null ? r.value : ''}</td>
      <td>${r.processed_value != null ? r.processed_value : ''}</td>
      <td><span class="flag-badge ${status.class}">${status.label}</span></td>
    `;
    tbody.appendChild(tr);
  });

  updateCycleTimeline(result);
}

function updateFlowMap(result) {
  const sensorsEl = document.getElementById('flow-sensors');
  const edgeEl = document.getElementById('flow-edge');
  const gatewayEl = document.getElementById('flow-gateway');
  const storageEl = document.getElementById('flow-storage');
  const mlEl = document.getElementById('flow-ml');
  const actuatorsEl = document.getElementById('flow-actuators');

  if (!sensorsEl || !edgeEl || !gatewayEl || !storageEl || !mlEl || !actuatorsEl) return;

  const setState = (el, state) => {
    if (!el) return;
    el.parentElement.classList.remove('active', 'warning', 'critical');
    if (state) el.parentElement.classList.add(state);
  };

  if (!result) {
    sensorsEl.textContent = 'Waiting for data';
    edgeEl.textContent = 'Idle';
    gatewayEl.textContent = 'Idle';
    storageEl.textContent = 'MongoDB/CSV';
    mlEl.textContent = 'Not trained';
    actuatorsEl.textContent = 'No actions';
    setState(sensorsEl, null);
    setState(edgeEl, null);
    setState(gatewayEl, null);
    setState(storageEl, null);
    setState(mlEl, null);
    setState(actuatorsEl, null);
    return;
  }

  const rawCount = result.sensor_readings ?? '-';
  const processedCount = result.processed_readings ?? '-';

  sensorsEl.textContent = `Generated ${rawCount} readings`;
  edgeEl.textContent = `Processed ${processedCount}`;
  gatewayEl.textContent = `Django stored ${processedCount}`;
  storageEl.textContent = 'MongoDB/CSV updated';
  mlEl.textContent = result.ml_prediction && result.ml_prediction.health_status
    ? `${result.ml_prediction.health_status} (${Math.round((result.ml_prediction.confidence || 0) * 100)}%)`
    : 'No prediction';
  actuatorsEl.textContent = `${result.decisions_made || 0} actions`;

  setState(sensorsEl, 'active');
  setState(edgeEl, 'active');
  setState(gatewayEl, 'active');
  setState(storageEl, 'active');
  setState(mlEl, result.ml_prediction && result.ml_prediction.health_status === 'Critical' ? 'critical' : result.ml_prediction && result.ml_prediction.health_status === 'Warning' ? 'warning' : 'active');
  setState(actuatorsEl, result.decisions_made > 0 ? 'critical' : 'active');
}

function updatePipeline(result) {
  if (!result || !result.response_times) return;
  const rt = result.response_times;

  const sensorEl = document.getElementById('pipe-sensor');
  const edgeEl = document.getElementById('pipe-edge');
  const storageEl = document.getElementById('pipe-storage');
  const mlEl = document.getElementById('pipe-ml');
  const actuatorEl = document.getElementById('pipe-actuator');
  const totalEl = document.getElementById('pipe-total');

  if (sensorEl) sensorEl.textContent = formatMs(rt.sensor_generation);
  if (edgeEl) edgeEl.textContent = formatMs(rt.edge_processing);
  if (storageEl) storageEl.textContent = formatMs(rt.storage);
  if (mlEl) mlEl.textContent = formatMs(rt.ml_prediction);
  if (actuatorEl) actuatorEl.textContent = formatMs(rt.actuator_decision);
  if (totalEl) totalEl.textContent = formatMs(rt.total);
}

function updateCycleTimeline(result) {
  const timelineEl = document.getElementById('cycle-timeline');
  if (!timelineEl || !result || result.cycle == null) return;

  const status = getCycleSeverity(result);
  cycleHistory.push({ cycle: result.cycle, status });
  if (cycleHistory.length > 10) {
    cycleHistory = cycleHistory.slice(cycleHistory.length - 10);
  }

  timelineEl.innerHTML = '';
  cycleHistory.forEach((entry) => {
    const div = document.createElement('div');
    div.className = `timeline-item ${entry.status}`;
    div.textContent = entry.cycle;
    timelineEl.appendChild(div);
  });
}

function getCycleSeverity(result) {
  const mlStatus = (result.ml_prediction || {}).health_status;
  if (mlStatus === 'Critical' || result.emergency_triggered) return 'critical';
  if (mlStatus === 'Warning') return 'warning';
  if (result.decisions_made > 0) return 'warning';
  return 'normal';
}

function renderModelComparison(result) {
  const tbody = document.getElementById('ml-compare-table');
  if (!tbody) return;

  const rows = result?.comparison || [];
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5">No comparison results</td></tr>';
    return;
  }

  tbody.innerHTML = '';

  const labels = [];
  const accuracies = [];
  const precisions = [];
  const recalls = [];
  const f1s = [];

  rows.forEach((row) => {
    if (row.status !== 'success') return;
    const metrics = row.metrics || {};
    labels.push(row.algorithm_name || row.algorithm || 'model');
    accuracies.push(metrics.accuracy || 0);
    precisions.push(metrics.precision || 0);
    recalls.push(metrics.recall || 0);
    f1s.push(metrics.f1_score || 0);

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.algorithm_name || row.algorithm}</td>
      <td>${(metrics.accuracy || 0).toFixed(3)}</td>
      <td>${(metrics.precision || 0).toFixed(3)}</td>
      <td>${(metrics.recall || 0).toFixed(3)}</td>
      <td>${(metrics.f1_score || 0).toFixed(3)}</td>
    `;
    tbody.appendChild(tr);
  });

  renderMlChart(labels, accuracies, precisions, recalls, f1s);
}

function renderMlChart(labels, accuracies, precisions, recalls, f1s) {
  const canvas = document.getElementById('ml-compare-chart');
  if (!canvas) return;

  if (mlCompareChart) {
    mlCompareChart.destroy();
  }

  mlCompareChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Accuracy', data: accuracies, backgroundColor: 'rgba(31, 111, 120, 0.75)' },
        { label: 'Precision', data: precisions, backgroundColor: 'rgba(242, 177, 56, 0.75)' },
        { label: 'Recall', data: recalls, backgroundColor: 'rgba(44, 156, 106, 0.75)' },
        { label: 'F1', data: f1s, backgroundColor: 'rgba(196, 69, 54, 0.75)' }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: true,
          max: 1,
          title: {
            display: true,
            text: 'Score'
          }
        }
      }
    }
  });
}
