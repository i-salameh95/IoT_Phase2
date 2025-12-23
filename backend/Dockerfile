FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for static files, media, and ML models
RUN mkdir -p /app/staticfiles /app/media /app/models

# Expose port
EXPOSE 8000

# Run Django migrations and start server
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn health_monitoring.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
