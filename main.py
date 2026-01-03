"""
Talos Gateway - FastAPI Application
Exposes REST API for audit events and integrity verification.
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import time
import uuid

from bootstrap import get_app_container
from talos_sdk.ports.audit_store import IAuditStorePort
from talos_sdk.ports.hash import IHashPort


app = FastAPI(
    title="Talos Gateway",
    description="API Gateway for Talos Protocol audit events",
    version="0.1.0",
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
    import os

    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "0.1.0",
        "env": os.getenv("TALOS_ENV", "production"),
        "run_id": os.getenv("TALOS_RUN_ID", "default"),
    }


@app.post("/events", response_model=AuditEventResponse)
def create_event(event: AuditEventCreate):
    """Create a new audit event."""
    container = get_app_container()
    audit_store = container.resolve(IAuditStorePort)
    hash_port = container.resolve(IHashPort)

    event_id = str(uuid.uuid4())
    timestamp = time.time()

    # Create event object
    event_data = {
        "event_id": event_id,
        "timestamp": timestamp,
        "event_type": event.event_type,
        "actor": event.actor,
        "action": event.action,
        "resource": event.resource,
        "metadata": event.metadata,
    }

    # Hash for integrity
    integrity_hash = hash_port.canonical_hash(event_data).hex()

    # Store (using a simple object for now)
    class StoredEvent:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    audit_store.append(StoredEvent(**event_data, integrity_hash=integrity_hash))

    return AuditEventResponse(
        event_id=event_id,
        timestamp=timestamp,
        event_type=event.event_type,
        actor=event.actor,
        action=event.action,
        resource=event.resource,
        integrity_hash=integrity_hash,
    )


@app.get("/events")
def list_events(limit: int = 100):
    """List recent audit events."""
    container = get_app_container()
    audit_store = container.resolve(IAuditStorePort)

    page = audit_store.list(limit=limit)

    return {
        "events": [
            {
                "event_id": getattr(e, "event_id", None),
                "timestamp": getattr(e, "timestamp", None),
                "event_type": getattr(e, "event_type", None),
            }
            for e in page.events
        ],
        "count": len(page.events),
    }
