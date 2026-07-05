import os
import datetime
from fastapi import FastAPI, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = "/data/sqlite.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Greeting(Base):
    __tablename__ = "greetings"
    id = Column(Integer, primary_key=True, index=True)
    greeting = Column(String, index=True)

# Δημιουργία πινάκων αν δεν υπάρχουν
if os.path.exists("/data"):
    Base.metadata.create_all(bind=engine)

app = FastAPI(title="sql-database")

@app.get("/health")
def health_check():
    return {"status": "UP", "timestamp": datetime.datetime.now().isoformat()}

@app.get("/metrics")
def get_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/db/greeting")
def read_greeting():
    db = SessionLocal()
    latest = db.query(Greeting).order_by(Greeting.id.desc()).first()
    db.close()
    return {"greeting": latest.greeting if latest else None}

@app.post("/db/greeting")
def write_greeting():
    db = SessionLocal()
    new_greeting = Greeting(greeting="Hello from SQL database")
    db.add(new_greeting)
    db.commit()
    db.close()
    return {"status": "success"}
