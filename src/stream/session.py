import logging
import time
from typing import Optional
from fastapi import WebSocket
from src.stream.types import InitMessage, ErrorMessage, ErrorCode, CloseCode, WSMsgType, InitAckMessage
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Simple Nonce Cache to prevent replay (Memory only for now, Redis for Prod)
_nonce_cache = set()

def validate_nonce(nonce: str, ts_str: str) -> bool:
    """
    Validates:
    1. Nonce usage (replay)
    2. Timestamp skew (< 5 minutes)
    """
    # 1. Check Replay
    if nonce in _nonce_cache:
        logger.warning(f"Nonce replay detected: {nonce}")
        return False
        
    # 2. Check Timestamp Skew
    try:
        # Expected format: ISO 8601 "2026-06-01T12:00:00Z"
        # Removing Z for naive parsing if needed, but robust way is:
        client_ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        server_ts = datetime.now(client_ts.tzinfo)
        
        diff = abs((server_ts - client_ts).total_seconds())
        if diff > 300: # 5 minutes
            logger.warning(f"Timestamp skew too large: {diff}s")
            return False
            
    except ValueError:
        logger.warning(f"Invalid timestamp format: {ts_str}")
        return False

    # Validation Passed
    _nonce_cache.add(nonce)
    
    # Prune old nonces if cache grows too large
    if len(_nonce_cache) > 10000:
        _nonce_cache.clear() # Simple clearing strategy for MVP
        
    return True

async def handle_handshake(websocket: WebSocket) -> tuple[Optional[str], Optional[dict]]:
    """
    Performs the strict Init handshake.
    Returns (session_id, filters) if successful, (None, None) if failed.
    """
    try:
        await websocket.accept()
        
        # Wait for first message
        raw = await websocket.receive_json()
        
        # Parse against Schema
        try:
            init = InitMessage(**raw)
        except Exception as e:
            # Schema Violation
            err = ErrorMessage(
                code=ErrorCode.INVALID_MESSAGE,
                message="First message must be valid 'init'",
                details={"error": str(e)}
            )
            await websocket.send_json(err.model_dump())
            await websocket.close(code=CloseCode.INVALID_FORMAT)
            return None, None

        # Validate Security
        if not validate_nonce(init.nonce, init.ts):
             err = ErrorMessage(code=ErrorCode.AUTH_FAILED, message="Invalid nonce or timestamp skew")
             await websocket.send_json(err.model_dump())
             await websocket.close(code=CloseCode.AUTH_FAILED)
             return None, None

        # Validate Capability (Simplified for Gateway-001)
        # Real impl would verify signature/scope
        if "talos_read" not in init.capability and "allow" not in init.capability:
             err = ErrorMessage(code=ErrorCode.AUTH_FAILED, message="Missing required capability scope")
             await websocket.send_json(err.model_dump())
             await websocket.close(code=CloseCode.AUTH_FAILED)
             return None, None

        # Success - Generate Session ID
        session_id = f"ws-{int(time.time())}-{init.nonce[:6]}"
        
        ack = InitAckMessage(
            session_id=session_id,
            heartbeat_interval_ms=30000
        )
        await websocket.send_json(ack.model_dump())
        
        return session_id, init.filters

    except Exception as e:
        logger.error(f"Handshake error: {e}")
        try:
            await websocket.close(code=CloseCode.INTERNAL_ERROR)
        except Exception:
            pass
        return None, None
