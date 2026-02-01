"""
Talos Gateway - FastAPI Application
Exposes REST API for audit events and integrity verification.
"""

import asyncio
import hashlib
import json
import logging
import os
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Union, cast

import requests
from bootstrap import get_app_container
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from src.config import settings
from src.handlers import stream
from src.routers import admin, mcp
from src.routers.mcp import MCP_REGISTRY
from src.stream.manager import manager as ws_manager
from talos_sdk.ports.audit_store import IAuditStorePort
from talos_sdk.ports.hash import IHashPort

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("talos-gateway")
# Initialize Configuration
# Load environment variables from .env
load_dotenv()

DEV_MODE = settings.dev_mode

# Fail-Closed Configuration Check
# Must have at least one upstream tool server configured, or a dynamic config source
TOOL_SERVER_CONFIG_SOURCE = os.getenv("TOOL_SERVER_CONFIG_SOURCE", "")
has_upstreams = len(MCP_REGISTRY) > 0 or TOOL_SERVER_CONFIG_SOURCE in {"file", "http", "k8s"}

if not has_upstreams:
    if not DEV_MODE:
        print("CRITICAL: No upstream tool servers configured in Production Mode. Exiting.")
        sys.exit(2)
    else:
        print("WARNING: Running in Dev Mode without upstreams. Mocking is disabled.")

print(
    f"Startup Config | Contracts: {settings.contracts_version} | Config: {settings.config_version} | Digest: {settings.config_digest[:8]}..."
)

# Fail-Closed Configuration Check


# Global background tasks reference
background_tasks: Set[asyncio.Task[Any]] = set()
TOOL_CHAT = "chat"


class ConnectorError(Exception):
    """Custom exception for connector failures."""

    pass


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
app.include_router(mcp.router)
app.include_router(admin.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Read build-time metadata from environment
GIT_SHA = os.getenv("GIT_SHA", "unknown")
VERSION = os.getenv("VERSION", "unknown")
BUILD_TIME = os.getenv("BUILD_TIME", "unknown")
# DEV_MODE already initialized above
TALOS_REGION = settings.region
START_TIME = time.time()
INSTANCE_ID = str(uuid.uuid4())
AUDIT_SERVICE_URL = settings.audit_url

# Prometheus metrics
# Custom metrics
REQUEST_COUNT = Counter(
    "gateway_requests_total", "Total requests", ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "gateway_request_duration_seconds", "Request latency in seconds", ["method", "endpoint"]
)

CAPABILITY_CHECKS = Counter(
    "gateway_capability_checks_total", "Capability verification attempts", ["result"]
)

ACTIVE_SESSIONS = Gauge("gateway_active_sessions", "Number of active sessions")

# Audit Forwarding counters
AUDIT_FORWARD_SUCCESS = Counter(
    "audit_forward_success_total", "Total audit events successfully forwarded"
)
AUDIT_FORWARD_FAILURE = Counter(
    "audit_forward_failure_total", "Total audit events that failed to forward"
)


class AuditEventCreate(BaseModel):
    """Request model for creating audit events."""

    event_type: str
    actor: str
    action: str
    resource: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AuditEventResponse(BaseModel):
    """Response model for audit events."""

    event_id: str
    timestamp: float
    event_type: str
    actor: str
    action: str
    resource: Optional[str] = None
    integrity_hash: str


# Schema version cache to avoid DB hammer


@lru_cache(maxsize=1)
def _check_schema_version_cached(timestamp: int) -> tuple[str, str]:
    """Cache schema check for 5 seconds to avoid DB hammer on readiness probes"""
    # In production this checks actual DB schema version
    # Since we are using SDK ports, we assume the port check is successful if resolve() works.
    try:
        container = get_app_container()
        store = container.resolve(cast(Any, IAuditStorePort))
        # Simple probe: stats(0, now) - if it results in error, schema might be wrong.
        store.stats(TimeRange(start=0, end=time.time()))
        return "v1", "v1"
    except Exception:
        return "unknown", "v1"


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    """Liveness probe - no dependency checks"""
    return {
        "status": "ok",
        "region": TALOS_REGION,
        "version": VERSION,
        "uptime": time.time() - START_TIME,
    }


@app.get("/health/ollama")
async def health_ollama() -> Union[Dict[str, Any], JSONResponse]:
    """Proxy health check to Ollama backend."""
    url = os.getenv("OLLAMA_URL", "http://ollama:11434")
    try:
        # Pydantic fetch is slow here, use requests or httpx.
        # Using requests for consistency with other parts of gateway.
        resp = requests.get(f"{url}/api/tags", timeout=2)
        if resp.status_code == 200:
            return {"status": "online"}
        return JSONResponse(
            status_code=503,
            content={"status": "offline", "error": f"Ollama returned {resp.status_code}"},
        )
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "offline", "error": str(e)})


@app.get("/health/tga")
async def health_tga() -> Union[Dict[str, Any], JSONResponse]:
    """Proxy health check to Governance Agent."""
    url = os.getenv("TGA_URL", "http://talos-governance-agent:8083")
    try:
        resp = requests.get(f"{url}/health", timeout=2)
        if resp.status_code == 200:
            return {"status": "online"}
        return JSONResponse(
            status_code=503,
            content={"status": "offline", "error": f"TGA returned {resp.status_code}"},
        )
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "offline", "error": str(e)})


@app.get("/readyz")
def readyz() -> Union[Dict[str, Any], JSONResponse]:
    """Readiness probe - checks critical dependencies"""
    if not DEV_MODE:
        # Use cached check to avoid DB hammer
        timestamp = int(time.time() / 5)  # 5-second buckets
        db_version, expected_version = _check_schema_version_cached(timestamp)
        if db_version != expected_version:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not ready",
                    "reason": f"Schema mismatch: {db_version} != {expected_version}",
                    "region": TALOS_REGION,
                },
            )

    return {"status": "ready", "dev_mode": DEV_MODE, "region": TALOS_REGION}


@app.get("/version")
def version() -> Dict[str, Any]:
    """Version information endpoint"""
    return {
        "version": VERSION,
        "git_sha": GIT_SHA,
        "build_time": BUILD_TIME,
        "service": "gateway",
        "dev_mode": DEV_MODE,
    }


def _get_metric_percentile(metric: Any, percentile: float) -> float:
    """Extract approximate percentile from Prometheus histogram buckets."""
    try:
        samples = list(metric.collect())[0].samples
        buckets = []
        total_count = 0
        for s in samples:
            if s.name.endswith("_bucket") and "le" in s.labels and s.labels["le"] != "+Inf":
                buckets.append((float(s.labels["le"]), s.value))
            elif s.name.endswith("_count"):
                total_count = s.value

        if total_count == 0 or not buckets:
            return 0.0

        buckets.sort()
        target = total_count * percentile
        prev_le = 0.0
        prev_count = 0.0
        for le, count in buckets:
            if count >= target:
                if count == prev_count:
                    return le * 1000.0
                ratio = (target - prev_count) / (count - prev_count)
                return float((prev_le + (le - prev_le) * ratio) * 1000.0)
            prev_le = le
            prev_count = count
        return float(buckets[-1][0] * 1000.0)
    except Exception:
        return 0.0


@app.get("/metrics/summary")
def metrics_summary() -> Dict[str, Any]:
    """Summary metrics for TUI/Dashboard"""
    # Extract total from counter
    samples = list(REQUEST_COUNT.collect())[0].samples
    total_reqs = sum(s.value for s in samples)

    return {
        "latency_p50_ms": round(_get_metric_percentile(REQUEST_LATENCY, 0.5), 2),
        "latency_p95_ms": round(_get_metric_percentile(REQUEST_LATENCY, 0.95), 2),
        "connected_peers": len(ws_manager.active_connections),
        "active_sessions": len(background_tasks),
        "total_requests": int(total_reqs),
    }


@app.get("/metrics")
async def metrics() -> Response:
    # Update gauge metrics
    ACTIVE_SESSIONS.set(len(background_tasks))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Deprecated /health endpoint for backward compatibility
@app.get("/health")
def health_check() -> Dict[str, Any]:
    """Health check endpoint (deprecated, use /healthz)"""
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/gateway/status")
def gateway_status() -> Dict[str, Any]:
    """Gateway status endpoint for integration tests."""
    uptime = int(time.time() - START_TIME)
    total_reqs = sum(s.value for s in list(REQUEST_COUNT.collect())[0].samples)

    return {
        "schema_version": "1",
        "gateway_instance_id": INSTANCE_ID,
        "status_seq": int(uptime / 10),
        "state": "RUNNING",
        "version": VERSION,
        "uptime_seconds": uptime,
        "requests_processed": int(total_reqs),
        "tenants": 1,  # Dedicated single-tenant instance
        "cache": {"capability_cache_size": 0, "hits": 0, "misses": 0, "evictions": 0},
        "sessions": {
            "active_sessions": len(ws_manager.active_connections) + len(background_tasks),
            "replay_rejections_1h": 0,
        },
    }


@app.post("/api/events", response_model=AuditEventResponse)
async def create_event(event: AuditEventCreate) -> Union[AuditEventResponse, JSONResponse]:
    """Create a new audit event (Proxies to Audit Service)."""
    # Patch 2: Lock down boundary
    if not DEV_MODE:
        return JSONResponse(
            status_code=403,
            content={
                "error": "Direct audit submission disabled in production. Audits are generated as side-effects."
            },
        )

    # Use UUIDv7 for time-ordered, cursor-compatible event IDs
    event_id = generate_uuid7()
    timestamp = int(time.time())

    # Map to Audit Service Event model
    # Note: Audit Service expects structured fields: ts (ISO string), request_id, surface_id, principal, http, meta, event_hash
    ts_iso = datetime.now(timezone.utc).isoformat()

    # Prepare internal payload for Audit Service
    # We follow the audit-service Event model
    internal_payload = {
        "schema_id": "talos.audit_event",
        "schema_version": "v1",
        "event_id": event_id,
        "ts": ts_iso,
        "request_id": str(uuid.uuid4()),
        "surface_id": "gateway-api",
        "outcome": "OK",
        "principal": {"id": event.actor, "type": "USER"},
        "http": {"method": "POST", "path": "/api/events"},
        "meta": {**(event.metadata or {}), "event_type": event.event_type},
        "resource": {"type": "event", "id": event.resource or "n/a"},
        "event_hash": "",
    }

    # Calculate canonical hash (RFC 8785 simulator)
    clean = {k: v for k, v in internal_payload.items() if k != "event_hash"}
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    internal_payload["event_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    logger.info(f"Forwarding audit event {event_id} to {AUDIT_SERVICE_URL}/api/events/ingest")

    def forward() -> requests.Response:
        return requests.post(
            f"{AUDIT_SERVICE_URL}/api/events/ingest", json=internal_payload, timeout=5.0
        )

    try:
        res = await run_in_threadpool(forward)
        if 200 <= res.status_code < 300:
            AUDIT_FORWARD_SUCCESS.inc()
            return AuditEventResponse(
                event_id=event_id,
                timestamp=timestamp,
                event_type=event.event_type,
                actor=event.actor,
                action=event.action,
                resource=event.resource,
                integrity_hash=str(internal_payload["event_hash"]),
            )
        else:
            AUDIT_FORWARD_FAILURE.inc()
            logger.error(f"Audit Service returned {res.status_code}: {res.text[:200]}")
            return JSONResponse(
                status_code=res.status_code,
                content={"error": "Audit service rejection", "details": res.text[:100]},
            )
    except Exception as e:
        AUDIT_FORWARD_FAILURE.inc()
        logger.error(f"Failed to forward audit event: {e}")
        return JSONResponse(status_code=503, content={"error": "Audit Service Unavailable"})


@app.get("/api/events")
def list_events(
    limit: int = 100,
    cursor: Optional[str] = None,
    session_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    outcome: Optional[str] = None,
) -> Dict[str, Any]:
    """List recent audit events with filters."""
    container = get_app_container()
    audit_store = container.resolve(cast(Any, IAuditStorePort))

    filters = {}
    if session_id:
        filters["session_id"] = session_id
    if correlation_id:
        filters["correlation_id"] = correlation_id
    if outcome:
        filters["outcome"] = outcome

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


class TimeRange(BaseModel):
    """Time window for stats query."""

    start: float
    end: float


@app.get("/api/events/stats")
def get_event_stats(
    from_ts: float = Query(..., alias="from"), to_ts: float = Query(..., alias="to")
) -> Dict[str, Any]:
    """Get audit statistics."""
    container = get_app_container()
    audit_store = container.resolve(cast(Any, IAuditStorePort))

    window = TimeRange(start=from_ts, end=to_ts)
    stats = audit_store.stats(window)
    return {"count": stats.count}


# In-memory session store for MVP
sessions = {}


class ChatRequest(BaseModel):
    session_id: str
    model: str
    messages: List[Dict[str, Any]]
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


def invoke_connector_chat(req: ChatRequest, correlation_id: str) -> Dict[str, Any]:
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

    return dict(res.json())


@app.post("/mcp/tools/chat")
async def chat_tool(req: ChatRequest) -> Union[Dict[str, Any], JSONResponse]:
    """Secure, audited chat tool endpoint."""
    container = get_app_container()
    audit_store = container.resolve(cast(Any, IAuditStorePort))
    hash_port = container.resolve(cast(Any, IHashPort))
    # ws_manager is imported globally

    correlation_id = req.client_request_id or str(uuid.uuid4())

    # 1. CHAT_REQUEST_RECEIVED
    await emit_audit_event(
        audit_store,
        hash_port,
        ws_manager,
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
        await emit_audit_event(
            audit_store,
            hash_port,
            ws_manager,
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
    await emit_audit_event(
        audit_store,
        hash_port,
        ws_manager,
        event_type="CHAT_TOOL_CALL",
        correlation_id=correlation_id,
        session_id=req.session_id,
        agent_id="gateway",
        method="invoke",
        resource="mcp-connector",
        metadata={"tool": "chat"},
    )

    try:
        mcp_res = await run_in_threadpool(invoke_connector_chat, req, correlation_id)
        outcome = "ERROR" if mcp_res.get("error") else "OK"

        await emit_audit_event(
            audit_store,
            hash_port,
            ws_manager,
            event_type="CHAT_TOOL_RESULT",
            correlation_id=correlation_id,
            session_id=req.session_id,
            agent_id="mcp-connector",
            method="return",
            resource=TOOL_CHAT,
            outcome=outcome,
            metadata={"has_error": bool(mcp_res.get("error"))},
        )

        await emit_audit_event(
            audit_store,
            hash_port,
            ws_manager,
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
        # Ensure strict Dict return
        result: Dict[str, Any] = mcp_res.get("result", {}) or {}
        return result

    except Exception as e:
        await emit_audit_event(
            audit_store,
            hash_port,
            ws_manager,
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


async def emit_audit_event(
    store: IAuditStorePort,
    hash_port: IHashPort,
    ws_manager: Any,
    event_type: str,
    correlation_id: str,
    session_id: str,
    agent_id: str,
    method: str,
    resource: str,
    outcome: str = "OK",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Internal side-effect audit emitter (Synchronous Proxy)."""
    logger = logging.getLogger("gateway-audit-internal")

    int(time.time())
    eid = generate_uuid7()
    ts_iso = datetime.now(timezone.utc).isoformat()

    internal_payload = {
        "schema_id": "talos.audit_event",
        "schema_version": "v1",
        "event_id": eid,
        "ts": ts_iso,
        "request_id": correlation_id,
        "surface_id": "gateway-internal",
        "outcome": outcome,
        "principal": {"id": agent_id, "type": "AGENT"},
        "http": {"method": "INTERNAL", "path": method},
        "meta": {
            **(metadata or {}),
            "session_id": session_id,
            "correlation_id": correlation_id,
            "event_type": event_type,
        },
        "resource": {"type": "tool", "id": resource or "n/a"},
        "event_hash": "",
    }

    # Calculate canonical hash
    clean = {k: v for k, v in internal_payload.items() if k != "event_hash"}
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    internal_payload["event_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def forward() -> requests.Response:
        return requests.post(
            f"{AUDIT_SERVICE_URL}/api/events/ingest", json=internal_payload, timeout=5.0
        )

    try:
        res = await run_in_threadpool(forward)
        if 200 <= res.status_code < 300:
            AUDIT_FORWARD_SUCCESS.inc()
            logger.info(f"✅ Side-effect audit {eid} forwarded successfully")
        else:
            AUDIT_FORWARD_FAILURE.inc()
            logger.error(f"❌ Side-effect audit {eid} failed with {res.status_code}")
    except Exception as e:
        AUDIT_FORWARD_FAILURE.inc()
        logger.error(f"❌ Critical failure forwarding internal audit: {e}")

    # Broadcast (Async) for local TUI/WS viewers
    await ws_manager.broadcast_event(internal_payload)
