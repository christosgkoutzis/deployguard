import os
import time
import json
import boto3
import csv
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

DB_URL = os.getenv("DB_URL", "postgresql://postgres:secretpassword@postgres:5432/postgres")
LOCALSTACK_URL = os.getenv("LOCALSTACK_URL", "http://localstack-service:4566")

engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Greeting(Base):
    __tablename__ = "greetings"
    id = Column(Integer, primary_key=True, index=True)
    greeting = Column(String, index=True)
    status = Column(String)
    created_at = Column(DateTime)

sqs = boto3.client('sqs', endpoint_url=LOCALSTACK_URL, region_name='us-east-1')
s3 = boto3.client('s3', endpoint_url=LOCALSTACK_URL, region_name='us-east-1')

def ensure_aws_resources():
    try:
        s3.create_bucket(Bucket='reports-bucket')
        q = sqs.create_queue(QueueName='report-tasks')
        return q['QueueUrl']
    except Exception as e:
        print(f"WARN: Waiting for LocalStack... {e}")
        return None

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
    print("INFO: CSV Report uploaded to S3 successfully.")

def run_worker():
    print("INFO: Report Worker starting...")
    queue_url = None
    while not queue_url:
        queue_url = ensure_aws_resources()
        time.sleep(5)

    print("INFO: Listening for SQS tasks...")
    while True:
        response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=5)
        messages = response.get('Messages', [])
        
        for msg in messages:
            print("INFO: Received task from SQS.")
            try:
                process_report()
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg['ReceiptHandle'])
                print("INFO: Task completed and deleted from SQS.")
            except Exception as e:
                print(f"ERROR: Failed to process report: {e}")

if __name__ == "__main__":
    run_worker()