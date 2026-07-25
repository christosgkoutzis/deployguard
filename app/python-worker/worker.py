import os
import time
import requests
import json
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from confluent_kafka import Consumer, KafkaException

DB_URL = os.getenv("DB_URL", "postgresql://postgres:secretpassword@postgres:5432/postgres")
VALIDATE_URL = os.getenv("VALIDATE_URL", "http://external-api-mock-service:80/api/validate")
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Greeting(Base):
    __tablename__ = "greetings"
    id = Column(Integer, primary_key=True, index=True)
    greeting = Column(String, index=True)
    status = Column(String)
    created_at = Column(DateTime)

def wait_for_db():
    retries = 15
    while retries > 0:
        try:
            with engine.connect() as conn:
                print("INFO: Connected to database successfully.")
                return
        except Exception as e:
            print(f"WARN: Database not ready... ({retries} retries left)")
            retries -= 1
            time.sleep(5)
    
    print("ERROR: Could not connect to the database. Worker exiting.")
    exit(1)

def run_worker():
    print("INFO: Worker starting...")
    wait_for_db()
    
    conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'validation-group',
        'auto.offset.reset': 'earliest'
    }
    
    print("INFO: Connecting to Kafka...")
    consumer = Consumer(conf)
    
    while True:
        try:
            consumer.subscribe(['pending-greetings'])
            print("INFO: Subscribed to topic.")
            break
        except KafkaException as e:
            print(f"WARN: Topic not ready yet, retrying... {e}")
            time.sleep(5)

    print("INFO: Listening for events...")
    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"WARN: Consumer error: {msg.error()}")
                continue
            
            try:
                data = json.loads(msg.value().decode('utf-8'))
                greeting_id = data.get('greeting_id')
                
                if greeting_id:
                    print(f"INFO: Processing greeting ID: {greeting_id}")
                    db = SessionLocal()
                    pending = db.query(Greeting).filter(Greeting.id == greeting_id).first()
                    
                    if pending and pending.status == "Pending":
                        r = requests.post(VALIDATE_URL, timeout=5)
                        result = r.json().get("result", "Approved") if r.status_code == 200 else "Error"
                        
                        pending.status = result
                        db.commit()
                        print(f"INFO: Greeting {greeting_id} set to {result}.")
                    db.close()
            except Exception as e:
                print(f"ERROR: Processing failed: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()

if __name__ == "__main__":
    run_worker()