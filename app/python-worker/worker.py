import os
import time
import requests
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError

DB_URL = os.getenv("DB_URL", "postgresql://postgres:secretpassword@postgres:5432/postgres")
VALIDATE_URL = os.getenv("VALIDATE_URL", "http://external-api-mock-service:80/api/validate")

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
    print("INFO: Validation Worker starting...")
    
    # Wait for PostgreSQL to be ready before starting the work loop
    wait_for_db()
    
    print("INFO: Worker is now polling for pending greetings.")
    while True:
        try:
            db = SessionLocal()
            # This will naturally fail if the python-backend init-job hasn't created the table yet.
            # It is caught silently below, and the worker will retry on the next tick.
            pending = db.query(Greeting).filter(Greeting.status == "Pending").first()
            
            if pending:
                print(f"INFO: Validating greeting ID: {pending.id}...")
                r = requests.post(VALIDATE_URL, timeout=5)
                
                if r.status_code == 200:
                    result = r.json().get("result", "Approved")
                    pending.status = result
                    db.commit()
                    print(f"INFO: Greeting ID {pending.id} updated to {result}.")
                else:
                    print(f"WARN: Mock Validation API returned status {r.status_code}.")
            db.close()
        except Exception:
            # Silently handle database unavailability during schema migrations
            pass
            
        # Polling interval to prevent CPU exhaustion
        time.sleep(5)

if __name__ == "__main__":
    run_worker()