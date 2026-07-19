import os
import time
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base

DB_URL = os.getenv("DB_URL", "postgresql://postgres:secretpassword@postgres:5432/postgres")
engine = create_engine(DB_URL)
Base = declarative_base()

class Greeting(Base):
    __tablename__ = "greetings"
    id = Column(Integer, primary_key=True, index=True)
    greeting = Column(String, index=True)
    status = Column(String, default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)

def migrate():
    retries = 15
    while retries > 0:
        try:
            Base.metadata.create_all(bind=engine)
            print("INFO: PostgreSQL schema initialized successfully!")
            return
        except Exception as e:
            print(f"WARN: Database not ready yet... ({retries} retries left) Error: {e}")
            retries -= 1
            time.sleep(5)
    print("ERROR: Could not connect to PostgreSQL to run migrations.")
    exit(1)

if __name__ == "__main__":
    migrate()