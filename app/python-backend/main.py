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
import pika
from botocore.config import Config

# Vault Graceful Fallback Helper
def get_secret(path, key, default_env_val=None):
    try:
        client = hvac.Client(url=os.getenv("VAULT_URL", "http://vault:8200"), token="deployguard-root-token")
        if client.is_authenticated():
            res = client.secrets.kv.v2.read_secret_version(path=path)
            return res['data']['data'].get(key, default_env_val)
    except Exception as e:
        print(f"WARN: Vault fetch failed: {e}")
    return default_env_val

APP_NAME = os.getenv("APP_NAME", "python-backend")
DB_URL = get_secret('deployguard/python-backend', 'DB_URL', os.getenv("DB_URL"))
if not DB_URL:
    raise ValueError("FATAL: DB_URL not found in ENV or Vault!")

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

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
# Strict config to prevent virtual-hosted K8s DNS failures with MinIO
s3_config = Config(s3={'addressing_style': 'path'})
s3 = boto3.client('s3', endpoint_url=S3_ENDPOINT, region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'), config=s3_config)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("AWS_ACCESS_KEY_ID", "admin")
RABBITMQ_PASS = os.getenv("AWS_SECRET_ACCESS_KEY", "adminpassword")

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
        # Ephemeral connection to avoid thread-pool safety issues in FastAPI
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials))
        channel = connection.channel()
        channel.queue_declare(queue='report-tasks', durable=True)
        channel.basic_publish(
            exchange='',
            routing_key='report-tasks',
            body=json.dumps({"task": "export_csv"}),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        return {"status": "Task sent to RabbitMQ"}
    except Exception as e:
        return {"error": f"RabbitMQ Error: {str(e)}"}

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