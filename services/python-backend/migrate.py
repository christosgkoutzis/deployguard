import os
import time
import hvac
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base

print("INFO: Fetching DB_URL securely from Vault for migrations...")
VAULT_URL = os.getenv("VAULT_URL", "http://vault:8200")
TOKEN = os.getenv("VAULT_ROOT_TOKEN")
db_url = os.getenv("DB_URL")

try:
    client = hvac.Client(url=VAULT_URL, token=TOKEN)
    if client.is_authenticated():
        res = client.secrets.kv.v2.read_secret_version(path='deployguard/python-backend')
        db_url = res['data']['data'].get('DB_URL', db_url)
except Exception as e:
    print(f"WARN: Could not fetch from Vault: {e}")

if not db_url:
    raise ValueError("FATAL: DB_URL is missing!")

engine = create_engine(db_url)
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
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS greetings (
                        id SERIAL PRIMARY KEY,
                        greeting VARCHAR,
                        status VARCHAR DEFAULT 'Pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS ix_greetings_id ON greetings (id);
                    CREATE INDEX IF NOT EXISTS ix_greetings_greeting ON greetings (greeting);
                """))
            print("INFO: PostgreSQL stateful migration executed successfully!")
            return
        except Exception as e:
            print(f"WARN: Database not ready yet... ({retries} retries left)")
            retries -= 1
            time.sleep(5)
    print("ERROR: Could not run migrations.")
    exit(1)

if __name__ == "__main__":
    migrate()