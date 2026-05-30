import logging
import sys
import os
import time
import datetime
from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, make_asgi_app

APP_NAME = os.getenv("APP_NAME", "telemetry-collector")
ENV = os.getenv("ENV", "local-dev")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TENANT_ID = os.getenv("TENANT_ID", "default-tenant")

# JSON logging structure
logging.basicConfig(
    stream=sys.stdout,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "app":"' + APP_NAME + '", "tenant":"%(message)s"}'
)
logger = logging.getLogger("telemetry-collector")
logger.setLevel(LOG_LEVEL)

app = FastAPI(title=APP_NAME)

REQUEST_LATENCY = Histogram(
    'telemetry_collector_request_latency_seconds', 
    'Time spent processing request', 
    ['tenant_id', 'endpoint']
)

REQUEST_COUNT = Counter(
    'telemetry_collector_requests_total', 
    'Total requests received', 
    ['tenant_id', 'endpoint']
)

# Middleware: Automatically intercepts every request to measure performance
@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    start_time = time.time()
    endpoint = request.url.path
    
    response = await call_next(request)
    
    # Calculate duration and record to Prometheus
    process_time = time.time() - start_time
    REQUEST_LATENCY.labels(tenant_id=TENANT_ID, endpoint=endpoint).observe(process_time)
    REQUEST_COUNT.labels(tenant_id=TENANT_ID, endpoint=endpoint).inc()
    
    return response

# Endpoints: Simulating business logic and health checks
@app.get("/")
def root():
    """Main business logic simulation."""
    logger.info(TENANT_ID)
    return {
        "status": "Active",
        "tenant": TENANT_ID,
        "environment": ENV,
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.get("/health")
def health_check():
    """Liveness/Readiness probe for Kubernetes self-healing."""
    return {"status": "UP", "timestamp": datetime.datetime.now().isoformat()}

# System events: Application lifecycle and resource management.

@app.on_event("startup")
async def startup_event():
    logger.info(f"STARTUP: {APP_NAME} is online in {ENV} mode.")

@app.on_event("shutdown")
def shutdown_event():
    logger.info(f"SHUTDOWN: {APP_NAME} is cleaning up resources.")

# Metrics endpoint for Prometheus to scrape
app.mount("/metrics", make_asgi_app())