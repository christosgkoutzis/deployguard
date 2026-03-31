# Slim python image for smaller footprint
FROM python:3.9-slim

# Set workspace inside the container
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy our application code
COPY main.py .

# Create a data directory for persistent storage
RUN mkdir /data && chmod 777 /data

# Default settings
ENV APP_NAME="omg-telemetry-collector"
ENV LOG_LEVEL="INFO"

# Listen on port 8000
EXPOSE 8000

# Start the web server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]