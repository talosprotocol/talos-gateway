import sys
import os
import time
import uuid

# Add current dir to path to import src
sys.path.append(os.getcwd())

from src.adapters.postgres_store import PostgresAuditStore

def wait_for_db(store, retries=30):
    for _ in range(retries):
        try:
            store._ensure_connection()
            with store._get_cursor() as cur:
                cur.execute("SELECT 1")
            print("Database connected.")
            return
        except Exception as e:
            print(f"Waiting for DB... ({e})")
            time.sleep(2)
    raise ConnectionError("Could not connect to DB")

def test_store():
    print("Initializing Store...")
    store = PostgresAuditStore()
    wait_for_db(store)
    
    # Create mock event
    class MockEvent:
        pass
    
    eid = str(uuid.uuid4())
    ts = int(time.time())
    
    event = MockEvent()
    event.event_id = eid
    event.schema_version = '1'
    event.timestamp = ts
    event.cursor = f"{ts}:{eid}"
    event.event_type = "TEST_EVENT"
    event.outcome = "OK"
    event.session_id = str(uuid.uuid4())
    event.correlation_id = str(uuid.uuid4())
    event.agent_id = "test_agent"
    event.tool = "test_tool"
    event.method = "test_method"
    event.resource = "test_resource"
    event.metadata = {"foo": "bar"}
    event.metrics = {}
    event.hashes = {}
    event.integrity = {}
    event.integrity_hash = "hash_123"
    
    print(f"Appending Event {eid}...")
    store.append(event)
    
    print("Listing Events...")
    page = store.list(limit=10)
    print(f"Got {len(page.events)} events.")
    
    assert len(page.events) > 0
    found = False
    for e in page.events:
        if e.event_id == eid:
            found = True
            print("Found inserted event!")
            break
            
    if not found:
        print("Inserted event not found!")
        sys.exit(1)

    print("Checking Table Existence completely...")
    with store._get_cursor() as cur:
        cur.execute("SELECT to_regclass('public.jobs')")
        if not cur.fetchone()['to_regclass']:
            print("Table 'jobs' missing!")
            sys.exit(1)
        print("Table 'jobs' exists.")
        
        cur.execute("SELECT to_regclass('public.selections')")
        if not cur.fetchone()['to_regclass']:
            print("Table 'selections' missing!")
            sys.exit(1)
        print("Table 'selections' exists.")

    print("SUCCESS: Storage verification passed.")

if __name__ == "__main__":
    test_store()
