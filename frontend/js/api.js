/**
 * API Client for Health Monitoring System
 */

const API_BASE_URL = 'http://localhost:8000/api/v1';

function normalizeAxiosError(error) {
  if (error?.response?.data?.detail) return new Error(error.response.data.detail);
  if (error?.response?.data?.error) return new Error(error.response.data.error);
  if (error?.response?.data?.message) return new Error(error.response.data.message);
  if (error?.message) return new Error(error.message);
  return new Error('Unknown API error');
}

const api = {
  async runCycle(patientId = null, simulateEmergency = false) {
    try {
      const response = await axios.post(`${API_BASE_URL}/simulation/run-cycle`, {
        patient_id: patientId,
        simulate_emergency: simulateEmergency
      });
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async runSimulation(numCycles = 20, delaySeconds = 2, patientId = null, simulateEmergency = false) {
    try {
      const response = await axios.post(`${API_BASE_URL}/simulation/run`, {
        num_cycles: numCycles,
        delay_seconds: delaySeconds,
        patient_id: patientId,
        simulate_emergency: simulateEmergency
      });
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async stopSimulation() {
    try {
      const response = await axios.post(`${API_BASE_URL}/simulation/stop`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async getActuatorStates() {
    try {
      const response = await axios.get(`${API_BASE_URL}/actuators/states/current`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async getHistoricalData(measurement, deviceId = null, limit = 100, startTime = null, stopTime = null) {
    try {
      const payload = { measurement, device_id: deviceId, limit };
      // Only send time filters if you support them in backend
      if (startTime) payload.start_time = startTime;
      if (stopTime) payload.stop_time = stopTime;

      const response = await axios.post(`${API_BASE_URL}/sensors/query/historical`, payload);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async getMeasurements() {
    try {
      const response = await axios.get(`${API_BASE_URL}/sensors/measurements`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async getDevices() {
    try {
      const response = await axios.get(`${API_BASE_URL}/sensors/devices`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async getLogs(level = null, source = null, limit = 100) {
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (level) params.append('level', level);
      if (source) params.append('source', source);

      const response = await axios.get(`${API_BASE_URL}/logs?${params.toString()}`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async getResponseTimeStats(limit = 100) {
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      const response = await axios.get(`${API_BASE_URL}/analytics/response-times?${params.toString()}`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async getMlStatus() {
    try {
      const response = await axios.get(`${API_BASE_URL}/ml/status`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async trainModel(algorithm = 'random_forest') {
    try {
      const response = await axios.post(`${API_BASE_URL}/ml/train`, { algorithm });
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async compareModels(algorithms = null) {
    try {
      const payload = algorithms ? { algorithms } : {};
      const response = await axios.post(`${API_BASE_URL}/ml/compare`, payload);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  async resetSimulation() {
    try {
      const response = await axios.post(`${API_BASE_URL}/simulation/reset`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  },

  // Optional: if you have analytics summary endpoint
  async getAnalyticsSummary(measurement, deviceId = null) {
    try {
      const params = new URLSearchParams({ measurement });
      if (deviceId) params.append('device_id', deviceId);
      const response = await axios.get(`${API_BASE_URL}/analytics/summary?${params.toString()}`);
      return response.data;
    } catch (error) {
      throw normalizeAxiosError(error);
    }
  }
};
