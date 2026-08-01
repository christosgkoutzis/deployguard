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
import hvac
import boto3

# Vault Graceful Fallback Helper
def get_secret(path, key, default_env_val):
    try:
        client = hvac.Client(url=os.getenv("VAULT_URL", "http://vault-service:8200"), token="deployguard-root-token")
        if client.is_authenticated():
            res = client.secrets.kv.v2.read_secret_version(path=path)
            return res['data']['data'].get(key, default_env_val)
    except Exception:
        pass # TODO: seed the vault, fallbacks to env for now
    return default_env_val
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

LOCALSTACK_URL = os.getenv("LOCALSTACK_URL", "http://localstack-service:4566")
sqs = boto3.client('sqs', endpoint_url=LOCALSTACK_URL, region_name='us-east-1')
s3 = boto3.client('s3', endpoint_url=LOCALSTACK_URL, region_name='us-east-1')

@app.post("/db/write")
async def write_db(request: Request):
    try:
        data = await request.json()
        custom_greeting = data.get("greeting", "Default Greeting")
        
        db = SessionLocal()
        new_greeting = Greeting(greeting=custom_greeting)
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

@app.post("/report/generate")
def generate_report():
    try:
        q = sqs.create_queue(QueueName='report-tasks')
        sqs.send_message(QueueUrl=q['QueueUrl'], MessageBody=json.dumps({"task": "export_csv"}))
        return {"status": "Task sent to SQS"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/report/download")
def download_report():
    try:
        url = s3.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': 'reports-bucket', 'Key': 'greetings_report.csv'},
            ExpiresIn=3600
        )
        return {"download_url": url}
    except Exception as e:
        return {"error": str(e)}