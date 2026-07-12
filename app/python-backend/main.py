import os
import time
import requests
import datetime
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

APP_NAME = os.getenv("APP_NAME", "python-backend")
SQL_DB_URL = os.getenv("SQL_DB_URL", "http://sql-database-service:80")
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL", "http://external-api-mock-service:80")

app = FastAPI(title=APP_NAME)

REQUEST_LATENCY = Histogram(
    'python_backend_request_latency_seconds',
    'Time spent processing request',
    ['endpoint']
)
REQUEST_COUNT = Counter(
    'python_backend_requests_total',
    'Total requests received',
    ['endpoint']
)


@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    start_time = time.time()
    endpoint = request.url.path
    response = await call_next(request)
    process_time = time.time() - start_time
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(process_time)
    REQUEST_COUNT.labels(endpoint=endpoint).inc()
    return response


@app.get("/health")
def health_check():
    return {"status": "UP", "timestamp": datetime.datetime.now().isoformat()}


@app.get("/message")
def get_message():
    return {"message": f"Hello from {APP_NAME}!"}

@app.get("/mock-greeting")
def get_mock_greeting():
    try:
        r = requests.get(f"{EXTERNAL_API_URL}/api/greeting", timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e), "source": "Failed to reach External API Mock"}


@app.get("/metrics")
def get_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/db/read")
def read_db():
    try:
        r = requests.get(f"{SQL_DB_URL}/db/greeting", timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

@app.post("/db/write")
def write_db():
    try:
        r = requests.post(f"{SQL_DB_URL}/db/greeting", timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}