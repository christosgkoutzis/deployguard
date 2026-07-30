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
import redis
from elasticsearch import Elasticsearch

APP_NAME = os.getenv("APP_NAME", "python-backend")
DB_URL = os.getenv("DB_URL", "postgresql://postgres:secretpassword@postgres:5432/postgres")
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL", "http://external-api-mock-service:80")
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
REDIS_HOST = os.getenv("REDIS_HOST", "redis-master")
ES_HOST = os.getenv("ES_HOST", "http://elasticsearch:9200")

kafka_producer = None
cache = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)
es = Elasticsearch([ES_HOST])

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
        # 1. Check cache first!
        try:
            cached = cache.get("latest_greeting")
            if cached:
                data = json.loads(cached)
                data["source"] = "Redis Cache"
                return data
        except Exception as e:
            print(f"WARN: Redis Error: {e}")

        # 2. If not in cache, read from DB
        db = SessionLocal()
        latest = db.query(Greeting).order_by(Greeting.id.desc()).first()
        db.close()
        
        if latest:
            response_data = {
                "greeting": latest.greeting,
                "status": latest.status,
                "created_at": latest.created_at.strftime("%Y-%m-%d %H:%M:%S") if latest.created_at else None
            }
            
            # 3. Store the result in Redis for 15 seconds
            try:
                cache.setex("latest_greeting", 15, json.dumps(response_data))
            except Exception:
                pass
                
            response_data["source"] = "PostgreSQL"
            return response_data
            
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

@app.get("/search")
def search(q: str):
    try:
        res = es.search(index="greetings", body={"query": {"match": {"greeting": q}}})
        hits = res['hits']['hits']
        results = [h['_source'] for h in hits]
        return {"results": results}
    except Exception as e:
        return {"error": f"Elasticsearch Error: {str(e)}"}