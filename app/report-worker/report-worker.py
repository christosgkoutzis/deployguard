import os
import time
import json
import boto3
import csv
import pika
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from botocore.config import Config
import hvac

VAULT_URL = os.getenv("VAULT_URL", "http://vault:8200")
DB_URL = os.getenv("DB_URL")
try:
    client = hvac.Client(url=VAULT_URL, token="deployguard-root-token")
    if client.is_authenticated():
        res = client.secrets.kv.v2.read_secret_version(path='deployguard/python-backend')
        DB_URL = res['data']['data'].get('DB_URL', DB_URL)
except Exception:
    pass

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("AWS_ACCESS_KEY_ID", "admin")
RABBITMQ_PASS = os.getenv("AWS_SECRET_ACCESS_KEY", "adminpassword")

engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Greeting(Base):
    __tablename__ = "greetings"
    id = Column(Integer, primary_key=True, index=True)
    greeting = Column(String, index=True)
    status = Column(String)
    created_at = Column(DateTime)

# MinIO client with strict PATH-STYLE addressing to avoid K8s DNS failures
s3_config = Config(s3={'addressing_style': 'path'})
s3 = boto3.client('s3', endpoint_url=S3_ENDPOINT, region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'), config=s3_config)

def ensure_s3_bucket():
    try:
        s3.create_bucket(Bucket='reports-bucket')
    except Exception as e:
        print(f"WARN: Bucket might already exist or MinIO not ready: {e}")

def process_report():
    db = SessionLocal()
    greetings = db.query(Greeting).all()
    db.close()

    filepath = "/tmp/greetings_report.csv"
    with open(filepath, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['ID', 'Greeting', 'Status', 'CreatedAt'])
        for g in greetings:
            writer.writerow([g.id, g.greeting, g.status, g.created_at])
    
    s3.upload_file(filepath, 'reports-bucket', 'greetings_report.csv')
    print("INFO: CSV Report uploaded to MinIO successfully.")

def run_worker():
    print("INFO: Report Worker starting...")
    time.sleep(15) # Give MinIO time to initialize
    ensure_s3_bucket()

    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    
    connection = None
    while not connection:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials))
        except Exception as e:
            print(f"WARN: Waiting for RabbitMQ... {e}")
            time.sleep(5)

    channel = connection.channel()
    channel.queue_declare(queue='report-tasks', durable=True)

    def callback(ch, method, properties, body):
        print("INFO: Received task from RabbitMQ.")
        try:
            process_report()
            ch.basic_ack(delivery_tag=method.delivery_tag)
            print("INFO: Task completed and ACK sent.")
        except Exception as e:
            print(f"ERROR: Failed to process report: {e}")
            # Requeue on failure
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue='report-tasks', on_message_callback=callback)

    print("INFO: Listening for RabbitMQ tasks...")
    channel.start_consuming()

if __name__ == "__main__":
    run_worker()