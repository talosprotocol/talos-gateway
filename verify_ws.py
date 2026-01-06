import asyncio
import json
import time
import uuid
import sys
import websockets
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

URI = "ws://localhost:8093/api/events/stream"

async def test_handshake():
    print(f"Connecting to {URI}...")
    try:
        async with websockets.connect(URI) as ws:
            print("Connected.")
            
            # 1. Negative Test: Send garbage
            # await ws.send("garbage")
            # resp = await ws.recv()
            # print(f"Garbage Resp: {resp}")
            
            # 2. Positive Test: Send Init
            nonce = str(uuid.uuid4())
            from datetime import timezone
            ts = datetime.now(timezone.utc).isoformat() + "Z"
            
            init_msg = {
                "type": "init",
                "version": 1,
                "capability": "talos_read_allow",
                "nonce": nonce,
                "ts": ts
            }
            print(f"Sending Init: {init_msg}")
            await ws.send(json.dumps(init_msg))
            
            resp = await ws.recv()
            print(f"Init Resp: {resp}")
            data = json.loads(resp)
            if data.get("type") != "init_ack":
                print("FAILED: Expected init_ack")
                sys.exit(1)
            
            session_id = data.get("session_id")
            print(f"Session Established: {session_id}")
            
            # 3. Wait for Broadcast (from Main App)
            # To trigger this we need to hit the POST /api/events endpoint
            # We can do that via a separate request
            
            print("Waiting for events (5s)...")
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"Received Event: {msg}")
            except asyncio.TimeoutError:
                print("No events received (Expected if no traffic)")
                
    except Exception as e:
        print(f"WS Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_handshake())
