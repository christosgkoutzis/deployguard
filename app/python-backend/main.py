import os
import time
import requests
import datetime
from fastapi import FastAPI, Request, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from migrate import Greeting
from confluent_kafka import Producer
import json

APP_NAME = os.getenv("APP_NAME", "python-backend")
DB_URL = os.getenv("DB_URL", "postgresql://postgres:secretpassword@postgres:5432/postgres")
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL", "http://external-api-mock-service:80")
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")

kafka_producer = None
def get_producer():
    global kafka_producer
    if not kafka_producer:
        kafka_producer = Producer({'bootstrap.servers': KAFKA_BROKER})
    return kafka_producer

app = FastAPI(title=APP_NAME)
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

@app.get("/db/read")
def read_db():
    try:
        db = SessionLocal()
        latest = db.query(Greeting).order_by(Greeting.id.desc()).first()
        db.close()
        if latest:
            return {
                "greeting": latest.greeting,
                "status": latest.status,
                "created_at": latest.created_at.strftime("%Y-%m-%d %H:%M:%S") if latest.created_at else None
            }
        return {"error": "No greetings yet"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/db/write")
def write_db():
    try:
        db = SessionLocal()
        new_greeting = Greeting(greeting="Awaiting validation from Worker")
        db.add(new_greeting)
        db.commit()
        db.refresh(new_greeting)
        greeting_id = new_greeting.id
        db.close()

        p = get_producer()
        payload = json.dumps({'greeting_id': greeting_id}).encode('utf-8')
        p.produce('pending-greetings', value=payload)
        p.flush()
        
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}