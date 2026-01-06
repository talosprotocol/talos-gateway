"""
Talos Gateway - FastAPI Application
Exposes REST API for audit events and integrity verification.
"""

import time
import uuid
import base64
import os
import struct
import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional
import asyncio
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


# Import WS Handler and Manager
from src.handlers import stream
from src.stream.manager import manager as ws_manager

from bootstrap import get_app_container
from talos_sdk.ports.audit_store import IAuditStorePort
from talos_sdk.ports.hash import IHashPort


# Global background tasks reference
background_tasks = set()

class ConnectorError(Exception):
    """Custom exception for connector failures."""

    pass


def derive_cursor(ts: int, eid: str) -> str:
    payload = f"{ts}:{eid}".encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")


# UUIDv7 generator for Python < 3.13 compatibility
def generate_uuid7() -> str:
    """Generate a UUIDv7 (time-ordered) identifier.

    Format: xxxxxxxx-xxxx-7xxx-yxxx-xxxxxxxxxxxx
    - First 48 bits: Unix timestamp in milliseconds
    - Version nibble: 7
    - Variant bits: RFC 4122 (10xx)
    - Remaining: Random
    """
    # Get current time in milliseconds
    ts_ms = int(time.time() * 1000)

    # 48-bit timestamp (6 bytes)
    ts_bytes = struct.pack(">Q", ts_ms)[2:]  # Take last 6 bytes of 8-byte big-endian

    # Random bytes for the rest (10 bytes)
    rand_bytes = os.urandom(10)

    # Build the 16-byte UUID
    uuid_bytes = bytearray(ts_bytes + rand_bytes)

    # Set version to 7 (bits 48-51)
    uuid_bytes[6] = (uuid_bytes[6] & 0x0F) | 0x70

    # Set variant to RFC 4122 (bits 64-65 = 10)
    uuid_bytes[8] = (uuid_bytes[8] & 0x3F) | 0x80

    # Format as UUID string
    hex_str = uuid_bytes.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


app = FastAPI(
    title="Talos Gateway",
    description="API Gateway for Talos Protocol audit events",
    version="0.1.0",
)

# Register WS Router
app.include_router(stream.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuditEventCreate(BaseModel):
    """Request model for creating audit events."""

    event_type: str
    actor: str
    action: str
    resource: Optional[str] = None
    metadata: Optional[dict] = None


class AuditEventResponse(BaseModel):
    """Response model for audit events."""

    event_id: str
    timestamp: float
    event_type: str
    actor: str
    action: str
    resource: Optional[str] = None
    integrity_hash: str


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/gateway/status")
def gateway_status():
    """Gateway status endpoint for integration tests."""

    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "0.1.0",
        "env": os.getenv("TALOS_ENV", "production"),
        "run_id": os.getenv("TALOS_RUN_ID", "default"),
    }


@app.post("/api/events", response_model=AuditEventResponse)
async def create_event(event: AuditEventCreate):
    """Create a new audit event."""
    container = get_app_container()
    audit_store = container.resolve(IAuditStorePort)
    hash_port = container.resolve(IHashPort)

    # Use UUIDv7 for time-ordered, cursor-compatible event IDs
    event_id = generate_uuid7()

    timestamp = int(time.time())

    # Create event object with full schema fields
    event_data = {
        "schema_version": "1",
        "event_id": event_id,
        "timestamp": timestamp,
        "cursor": derive_cursor(timestamp, event_id),
        "event_type": event.event_type,
        "outcome": "OK",
        "session_id": str(uuid.uuid4()),  # Generate a session ID
        "correlation_id": str(uuid.uuid4()),
        "agent_id": event.actor,  # Map actor to agent_id
        "peer_id": "",
        "tool": "talos-gateway",
        "method": event.action,
        "resource": event.resource,
        "metadata": event.metadata or {},
        "metrics": {"latency_ms": 10},
        "hashes": {
            "request_hash": hash_port.canonical_hash({"raw": "mock"}).hex(),
        },
        "integrity": {
            "proof_state": "UNVERIFIED",
            "signature_state": "NOT_PRESENT",
            "anchor_state": "NOT_ENABLED",
            "verifier_version": "3.2",
        },
    }

    # Hash for integrity
    integrity_hash = hash_port.canonical_hash(event_data).hex()

    # Store
    class StoredEvent:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    # Run blocking sync DB call in threadpool
    await run_in_threadpool(audit_store.append, StoredEvent(**event_data, integrity_hash=integrity_hash))

    # Broadcast to WS clients
    # Note: In a real distributed system this would efficiently fan-out via Redis PubSub
    # For now, local memory broadcast
    task = asyncio.create_task(ws_manager.broadcast_event(event_data))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    return AuditEventResponse(
        event_id=event_id,
        timestamp=timestamp,
        event_type=event.event_type,
        actor=event.actor,
        action=event.action,
        resource=event.resource,
        integrity_hash=integrity_hash,
    )


@app.get("/api/events")
def list_events(
    limit: int = 100, 
    cursor: Optional[str] = None, 
    session_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    outcome: Optional[str] = None
):
    """List recent audit events with filters."""
    container = get_app_container()
    audit_store = container.resolve(IAuditStorePort)

    filters = {}
    if session_id: filters["session_id"] = session_id
    if correlation_id: filters["correlation_id"] = correlation_id
    if outcome: filters["outcome"] = outcome

    page = audit_store.list(before=cursor, limit=limit, filters=filters)

    return {
        "items": [
            {
                "schema_version": getattr(e, "schema_version", "1"),
                "event_id": getattr(e, "event_id", ""),
                "timestamp": getattr(e, "timestamp", 0),
                "cursor": getattr(e, "cursor", ""),
                "event_type": getattr(e, "event_type", "ERROR"),
                "outcome": getattr(e, "outcome", "OK"),
                "session_id": getattr(e, "session_id", ""),
                "correlation_id": getattr(e, "correlation_id", ""),
                "agent_id": getattr(e, "agent_id", ""),
                "peer_id": getattr(e, "peer_id", ""),
                "tool": getattr(e, "tool", ""),
                "method": getattr(e, "method", ""),
                "resource": getattr(e, "resource", ""),
                "metadata": getattr(e, "metadata", {}),
                "metrics": getattr(e, "metrics", {}),
                "hashes": getattr(e, "hashes", {}),
                # Integrity object is required by frontend schema
                "integrity": getattr(
                    e,
                    "integrity",
                    {
                        "proof_state": "UNVERIFIED",
                        "signature_state": "NOT_PRESENT",
                        "anchor_state": "NOT_ENABLED",
                        "verifier_version": "3.2",
                    },
                ),
            }
            for e in page.events
        ],
        "next_cursor": page.next_cursor,
        "has_more": len(page.events) >= limit,
    }


@app.get("/api/events/stats")
def get_event_stats(
    from_ts: float = Query(..., alias="from"), 
    to_ts: float = Query(..., alias="to")
):
    """Get audit statistics."""
    container = get_app_container()
    audit_store = container.resolve(IAuditStorePort)
    
    return audit_store.stats(from_ts, to_ts)


# In-memory session store for MVP
sessions = {}


class ChatRequest(BaseModel):
    session_id: str
    model: str
    messages: list[dict]
    capability: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 512
    timeout_ms: int = 60000
    client_request_id: Optional[str] = None


def verify_capability(req: ChatRequest) -> bool:
    """Simulated capability verification."""
    if req.capability:
        if req.capability.startswith("cap_"):
            if "invalid" in req.capability:
                return False
            # Bind to session
            sessions[req.session_id] = {"allowed_tools": ["chat"]}
            return True
        return False

    # Check session
    return req.session_id in sessions and "chat" in sessions[req.session_id].get(
        "allowed_tools", []
    )


def invoke_connector_chat(req: ChatRequest, correlation_id: str) -> dict:
    """Low-level connector invocation."""
    invoke_payload = {
        "method": "tools/call",
        "params": {
            "name": "chat",
            "arguments": {
                "session_id": req.session_id,
                "model": req.model,
                "messages": req.messages,
                "temperature": req.temperature,
                "max_tokens": req.max_tokens,
                "timeout_ms": req.timeout_ms,
            },
        },
        "id": correlation_id,
    }

    res = requests.post(
        "http://localhost:8082/api/mcp/invoke",
        json=invoke_payload,
        timeout=req.timeout_ms / 1000.0 + 5,
    )

    if res.status_code != 200:
        raise ConnectorError(f"Connector returned {res.status_code}")

    return res.json()


@app.post("/mcp/tools/chat")
def chat_tool(req: ChatRequest):
    """Secure, audited chat tool endpoint."""
    container = get_app_container()
    audit_store = container.resolve(IAuditStorePort)
    hash_port = container.resolve(IHashPort)

    correlation_id = req.client_request_id or str(uuid.uuid4())

    # 1. CHAT_REQUEST_RECEIVED
    emit_audit_event(
        audit_store,
        hash_port,
        event_type="CHAT_REQUEST_RECEIVED",
        correlation_id=correlation_id,
        session_id=req.session_id,
        agent_id="user",
        method="chat",
        resource=TOOL_CHAT,
        metadata={"model": req.model, "msg_count": len(req.messages)},
    )

    # 2. CAPABILITY VERIFICATION
    if not verify_capability(req):
        emit_audit_event(
            audit_store,
            hash_port,
            event_type="CHAT_RESPONSE_SENT",
            correlation_id=correlation_id,
            session_id=req.session_id,
            agent_id="gateway",
            method="chat",
            resource=TOOL_CHAT,
            outcome="DENY",
            metadata={"error": "Capability verification failed"},
        )
        return JSONResponse(status_code=403, content={"error": "Capability verification failed"})

    # 3. CHAT_TOOL_CALL (Gateway -> Connector)
    emit_audit_event(
        audit_store,
        hash_port,
        event_type="CHAT_TOOL_CALL",
        correlation_id=correlation_id,
        session_id=req.session_id,
        agent_id="gateway",
        method="invoke",
        resource="mcp-connector",
        metadata={"tool": "chat"},
    )

    try:
        mcp_res = invoke_connector_chat(req, correlation_id)
        outcome = "ERROR" if mcp_res.get("error") else "OK"

        emit_audit_event(
            audit_store,
            hash_port,
            event_type="CHAT_TOOL_RESULT",
            correlation_id=correlation_id,
            session_id=req.session_id,
            agent_id="mcp-connector",
            method="return",
            resource=TOOL_CHAT,
            outcome=outcome,
            metadata={"has_error": bool(mcp_res.get("error"))},
        )

        emit_audit_event(
            audit_store,
            hash_port,
            event_type="CHAT_RESPONSE_SENT",
            correlation_id=correlation_id,
            session_id=req.session_id,
            agent_id="gateway",
            method="chat",
            resource=TOOL_CHAT,
            outcome=outcome,
            metadata={},
        )

        if mcp_res.get("error"):
            return JSONResponse(status_code=500, content=mcp_res["error"])
        return mcp_res["result"]

    except Exception as e:
        emit_audit_event(
            audit_store,
            hash_port,
            event_type="CHAT_TOOL_RESULT",
            correlation_id=correlation_id,
            session_id=req.session_id,
            agent_id="mcp-connector",
            method="return",
            resource=TOOL_CHAT,
            outcome="ERROR",
            metadata={"error": str(e)},
        )
        return JSONResponse(status_code=500, content={"code": "GATEWAY_ERROR", "message": str(e)})


def emit_audit_event(
    store,
    hash_port,
    event_type,
    correlation_id,
    session_id,
    agent_id,
    method,
    resource,
    outcome="OK",
    metadata=None,
):
    # Re-use logic from create_event but internalized

    ts = int(time.time())
    eid = generate_uuid7()  # UUIDv7 for cursor compatibility

    event_data = {
        "schema_version": "1",
        "event_id": eid,
        "timestamp": ts,
        "cursor": derive_cursor(ts, eid),
        "event_type": event_type,
        "outcome": outcome,
        "session_id": session_id,
        "correlation_id": correlation_id,
        "agent_id": agent_id,
        "peer_id": "",
        "tool": "talos-gateway",
        "method": method,
        "resource": resource,
        "metadata": metadata or {},
        "hashes": {"request_hash": hash_port.canonical_hash(metadata or {}).hex()},
        "integrity": {
            "proof_state": "UNVERIFIED",
            "signature_state": "NOT_PRESENT",
            "anchor_state": "NOT_ENABLED",
            "verifier_version": "3.2",
        },
    }

    integrity_hash = hash_port.canonical_hash(event_data).hex()

    class StoredEvent:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    store.append(StoredEvent(**event_data, integrity_hash=integrity_hash))
