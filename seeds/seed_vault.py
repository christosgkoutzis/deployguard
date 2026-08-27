import os
import hvac
import time

VAULT_URL = os.getenv("VAULT_URL", "http://vault:8200")
TOKEN = os.getenv("VAULT_ROOT_TOKEN")

print(f"INFO: Connecting to Vault at {VAULT_URL} for seeding...")

client = hvac.Client(url=VAULT_URL, token=TOKEN)

retries = 10
while retries > 0:
    try:
        if client.is_authenticated():
            print("INFO: Vault authenticated. Proceeding with seed.")
            break
    except Exception:
        pass
    print(f"WARN: Vault not ready... ({retries} retries left)")
    retries -= 1
    time.sleep(3)

if not client.is_authenticated():
    print("ERROR: Failed to authenticate with Vault.")
    exit(1)

services = ["python-backend", "ruby-gateway", "python-worker", "report-worker", "e2e-tests"]

for svc in services:
    secret_data = {
        'AWS_ACCESS_KEY_ID': 'admin',
        'AWS_SECRET_ACCESS_KEY': os.getenv('MINIO_ROOT_PASSWORD', 'minio123'),
        'DB_URL': f"postgresql://postgres:{os.getenv('POSTGRES_PASSWORD', 'postgres')}@postgres:5432/postgres",
        'SEEDED_BY': 'DeployGuard Platform'
    }
    try:
        client.secrets.kv.v2.create_or_update_secret(
            path=f'deployguard/{svc}',
            secret=secret_data
        )
        print(f"INFO: Successfully seeded Vault secrets at 'deployguard/{svc}'.")
    except Exception as e:
        print(f"ERROR: Failed to write secret: {e}")
        exit(1)
