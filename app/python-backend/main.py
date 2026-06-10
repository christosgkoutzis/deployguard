import os
import time
import datetime
from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, make_asgi_app

APP_NAME = os.getenv("APP_NAME", "python-backend")

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


app.mount("/metrics", make_asgi_app())
