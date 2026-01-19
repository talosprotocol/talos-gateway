from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.stream.session import handle_handshake
from src.stream.manager import manager
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/api/events/stream")
async def websocket_endpoint(websocket: WebSocket):
    session_id, filters = await handle_handshake(websocket)
    
    if not session_id:
        # Handshake failed, socket is already closed by handler
        return

    # Handshake Success - Register
    manager.connect(websocket, session_id, filters)
    
    try:
        while True:
            # We mostly just listen for close frames or Heartbeats from client (if we want bi-di heartbeats)
            # For now, server pushes, client listens.
            # We must await receive to keep connection open and detect disconnects
            _ = await websocket.receive_text()
            # Optionally handle client-side heartbeats or commands here
            
    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WS error {session_id}: {e}")
        manager.disconnect(session_id)


from fastapi.responses import StreamingResponse
from fastapi import Request
import json
import uuid
import asyncio

@router.get("/events")
async def sse_audit_stream(request: Request):
    """
    Server-Sent Events endpoint for dashboard audit stream.
    Compatible with Talos Audit Service protocol.
    """
    session_id = str(uuid.uuid4())
    queue = manager.connect_sse(session_id)
    
    async def event_generator():
        try:
            # Send initial connection metadata
            yield f"event: meta\ndata: {json.dumps({'status':'connected', 'session_id': session_id})}\n\n"
            
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    # Wait for message with timeout to allow heartbeat
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    
                    # Convert internal message format to SSE
                    # msg is { type: "event", event: {...}, ... }
                    if msg.get("type") == "event":
                        yield f"event: audit_event\ndata: {json.dumps(msg['event'])}\n\n"
                        
                except asyncio.TimeoutError:
                    # Send Heartbeat
                    yield ": heartbeat\n\n"
                    
        finally:
            manager.disconnect(session_id)

    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream"
    )
