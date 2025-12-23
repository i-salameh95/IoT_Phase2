/**
 * Chart Management for Health Monitoring Dashboard
 */

const RANGE_BANDS = {
    heart_rate: { min: 60, max: 100, unit: 'bpm' },
    blood_pressure_systolic: { min: 90, max: 140, unit: 'mmHg' },
    blood_pressure_diastolic: { min: 60, max: 90, unit: 'mmHg' },
    body_temperature: { min: 36.1, max: 37.2, unit: 'C' },
    oxygen_saturation: { min: 95, max: 100, unit: '%' },
    glucose_level: { min: 70, max: 100, unit: 'mg/dL' },
    activity_steps: { min: 0, max: 20000, unit: 'steps' },
    ambient_temperature: { min: 20, max: 24, unit: 'C' },
    humidity: { min: 30, max: 60, unit: '%' },
    light_level: { min: 100, max: 800, unit: 'lux' },
    motion_detected: { min: 0, max: 1, unit: '' },
    co2_level: { min: 400, max: 1000, unit: 'ppm' },
    sound_level: { min: 30, max: 60, unit: 'dB' }
};

class ChartManager {
    constructor({ canvasId, selectId, defaultSensor }) {
        this.canvasId = canvasId;
        this.selectId = selectId;
        this.currentSensor = defaultSensor;
        this.chart = null;
        this.init();
    }

    init() {
        const select = document.getElementById(this.selectId);
        if (select) {
            select.addEventListener('change', (e) => {
                this.currentSensor = e.target.value;
                this.refresh();
            });
        }

        this.createChart();
        this.refresh();
    }

    createChart() {
        const ctx = document.getElementById(this.canvasId);
        if (!ctx) return;

        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Normal Range Min',
                        data: [],
                        borderColor: 'rgba(31, 111, 120, 0.25)',
                        backgroundColor: 'rgba(31, 111, 120, 0.12)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: '+1'
                    },
                    {
                        label: 'Normal Range Max',
                        data: [],
                        borderColor: 'rgba(31, 111, 120, 0.25)',
                        backgroundColor: 'rgba(31, 111, 120, 0.12)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: false
                    },
                    {
                        label: 'Sensor Reading',
                        data: [],
                        borderColor: 'rgb(31, 111, 120)',
                        backgroundColor: 'rgba(31, 111, 120, 0.1)',
                        tension: 0.35,
                        fill: false,
                        pointRadius: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        title: {
                            display: true,
                            text: 'Value'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Time'
                        }
                    }
                }
            }
        });
    }

    async refresh() {
        if (!this.chart) return;

        try {
            const deviceId = typeof getDeviceIdForMeasurement === 'function'
                ? getDeviceIdForMeasurement(this.currentSensor)
                : null;

            const data = await api.getHistoricalData(this.currentSensor, deviceId, 50);

            if (data && data.length > 0) {
                const labels = data.map(d => {
                    const date = new Date(d.time);
                    return date.toLocaleTimeString();
                });
                const values = data.map(d => d.value);

                const range = RANGE_BANDS[this.currentSensor] || null;
                const minLine = range ? Array(values.length).fill(range.min) : [];
                const maxLine = range ? Array(values.length).fill(range.max) : [];

                this.chart.data.labels = labels;
                this.chart.data.datasets[0].data = minLine;
                this.chart.data.datasets[1].data = maxLine;
                this.chart.data.datasets[2].data = values;
                this.chart.data.datasets[2].label = this.currentSensor.replace(/_/g, ' ').toUpperCase();

                if (range) {
                    this.chart.options.scales.y.title.text = `Value (${range.unit || 'unit'})`;
                } else {
                    this.chart.options.scales.y.title.text = 'Value';
                }

                this.chart.update();
            }
        } catch (error) {
            console.error('Error refreshing chart:', error);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.chartManagers = {
        vitals: new ChartManager({
            canvasId: 'sensor-chart-vitals',
            selectId: 'chart-sensor-vitals',
            defaultSensor: 'heart_rate'
        }),
        env: new ChartManager({
            canvasId: 'sensor-chart-env',
            selectId: 'chart-sensor-env',
            defaultSensor: 'ambient_temperature'
        })
    };
});
