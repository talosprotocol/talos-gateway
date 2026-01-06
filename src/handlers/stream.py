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
