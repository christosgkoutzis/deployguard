import os
import time
import requests

TARGET_URL = os.getenv("TARGET_URL", "http://ruby-gateway-service:80")

def test_sync_mock():
    """Test 1: Sync Flow & Mocks"""
    matched = False
    for _ in range(15):
        try:
            res = requests.get(f"{TARGET_URL}/", timeout=5)
            if res.status_code == 200 and "Hello from the mocked API!" in res.text:
                matched = True
                break
        except Exception:
            pass
        time.sleep(2)
    assert matched, "Mock greeting was not propagated to the gateway HTML."

def test_event_driven_write_and_read():
    """Test 2: Event-Driven Write (Kafka) & Cached Read (Redis/Postgres)"""
    res = requests.post(f"{TARGET_URL}/write", data={"greeting_text": "Integration Test Greeting"})
    assert res.status_code == 200

    approved = False
    for _ in range(15):
        res = requests.get(f"{TARGET_URL}/read", allow_redirects=False)
        if res.status_code in [301, 302]:
            loc = res.headers.get("Location", "")
            if "Approved" in loc:
                approved = True
                break
        time.sleep(2)
    assert approved, "Eventual consistency failed, status not Approved."

def test_elasticsearch():
    """Test 3: Full-Text Search (Elasticsearch)"""
    time.sleep(2)  # Allow ES to index
    res = requests.get(f"{TARGET_URL}/search?q=Integration", allow_redirects=False)
    if res.status_code in [301, 302]:
        loc = res.headers.get("Location", "")
        assert "ID" in loc, "Elasticsearch failed to return results."

def test_async_export():
    """Test 4: Async Export (RabbitMQ & MinIO S3)"""
    res = requests.post(f"{TARGET_URL}/report/generate")
    assert res.status_code == 200
    
    ready = False
    for _ in range(15):
        res = requests.get(f"{TARGET_URL}/report/download", allow_redirects=False)
        if res.status_code in [301, 302]:
            loc = res.headers.get("Location", "")
            if "reports-bucket" in loc:
                ready = True
                break
        time.sleep(2)
    assert ready, "Report generation to MinIO failed."