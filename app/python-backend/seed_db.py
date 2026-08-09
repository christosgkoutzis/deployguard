import os
import hvac
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from migrate import Greeting

print("INFO: Fetching DB_URL from Vault...")
VAULT_URL = os.getenv("VAULT_URL", "http://vault:8200")
TOKEN = "deployguard-root-token"
db_url = os.getenv("DB_URL")

try:
    client = hvac.Client(url=VAULT_URL, token=TOKEN)
    if client.is_authenticated():
        res = client.secrets.kv.v2.read_secret_version(path='deployguard/python-backend')
        db_url = res['data']['data'].get('DB_URL', db_url)
except Exception as e:
    print(f"WARN: Could not fetch from Vault: {e}")

if not db_url:
    raise ValueError("FATAL: DB_URL not found in ENV or Vault!")

engine = create_engine(db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed():
    db = SessionLocal()
    if db.query(Greeting).count() == 0:
        print("INFO: Database is empty. Seeding initial application data...")
        db.add(Greeting(greeting="Hello from the App DB Seed!", status="Approved"))
        db.add(Greeting(greeting="Waiting for Kafka Worker validation...", status="Pending"))
        db.commit()
        print("INFO: Application database seeded successfully.")
    else:
        print("INFO: Database already contains data. Skipping app seed.")
    db.close()

if __name__ == "__main__":
    seed()