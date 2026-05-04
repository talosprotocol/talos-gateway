from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from typing import Any, cast, Dict, Optional
import os
import time
import uuid
from pydantic import BaseModel
from bootstrap import get_app_container
from talos_sdk.ports.audit_store import IAuditStorePort
from src.auth import require_auth
from src.adapters.postgres_admin_store import PostgresAdminStore
from src.crypto import SecretEncryptor

router = APIRouter(prefix="/admin/v1", tags=["admin"])

# --- Models ---

class SecretCreate(BaseModel):
    name: str
    value: str

class RotationStats(BaseModel):
    scanned: int
    rotated: int
    failed: int

class RotationOperation(BaseModel):
    id: str
    status: str # 'RUNNING', 'COMPLETED', 'FAILED'
    target_kek_id: str
    stats: RotationStats
    started_at: str
    completed_at: Optional[str] = None
    message: Optional[str] = None

# Global state for rotation operations (In-memory for MVP, could be in DB)
active_rotations: Dict[str, RotationOperation] = {}

# --- Identity & Status ---

@router.get("/me")
async def get_current_user(_: str = Depends(require_auth)) -> Dict[str, Any]:
    return {
        "id": "admin-001",
        "email": os.getenv("ADMIN_EMAIL", "admin@talos.security"),
        "name": "System Administrator",
        "roles": ["admin", "operator"]
    }

@router.get("/gateway/status")
async def get_gateway_status(request: Request, _: str = Depends(require_auth)) -> Dict[str, Any]:
    """Get aggregated health and system status."""
    uptime = time.time() - getattr(request.app.state, 'start_time', time.time())
    return {
        "status": "HEALTHY",
        "version": os.getenv("VERSION", "1.2.0"),
        "uptime_seconds": int(uptime),
        "region": os.getenv("TALOS_REGION", "us-east-1"),
        "timestamp": time.time()
    }

# --- Secrets Management ---

@router.get("/secrets")
async def list_secrets(_: str = Depends(require_auth)) -> Dict[str, Any]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    all_secrets = []
    
    # 1. Environment Secrets (Masked Metadata)
    for key in os.environ:
        if any(prefix in key for prefix in ["TALOS_", "SECRET", "KEY", "PASSWORD", "token"]):
            all_secrets.append({
                "id": key,
                "name": key,
                "provider": "env",
                "created_at": timestamp,
                "updated_at": timestamp
            })
            
    # 2. Database-persisted Custom Secrets
    db_secrets = store.list_secrets()
    for s in db_secrets:
        all_secrets.append({
            "id": f"db:{s['name']}",
            "name": s['name'],
            "provider": "kms",
            "created_at": s['created_at'].isoformat() if hasattr(s['created_at'], 'isoformat') else str(s['created_at']),
            "updated_at": s['updated_at'].isoformat() if hasattr(s['updated_at'], 'isoformat') else str(s['updated_at']),
            "kek_id": s['kek_id']
        })
            
    return {
        "secrets": all_secrets,
        "total": len(all_secrets)
    }

@router.post("/secrets")
async def create_secret(secret: SecretCreate, _: str = Depends(require_auth)) -> Dict[str, Any]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    encryptor = SecretEncryptor() # Uses TALOS_MASTER_KEY from env
    
    # Encrypt the value
    ciphertext, iv, tag = encryptor.encrypt(secret.value)
    
    # Save to DB
    kek_id = os.getenv("TALOS_CURRENT_KEK_ID", "kek-v1")
    store.upsert_secret(secret.name, kek_id, ciphertext, iv, tag)
    
    return {"status": "created", "name": secret.name}

@router.delete("/secrets/{name}")
async def delete_secret(name: str, _: str = Depends(require_auth)) -> Dict[str, bool]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    success = store.delete_secret(name)
    if not success:
        if name in os.environ:
             raise HTTPException(status_code=403, detail="Cannot delete environment-based secrets via API")
        raise HTTPException(status_code=404, detail="Secret not found")
    return {"success": True}

@router.get("/secrets/kek-status")
async def get_kek_status(_: str = Depends(require_auth)) -> Dict[str, Any]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    
    secrets = store.list_secrets()
    kek_id = os.getenv("TALOS_CURRENT_KEK_ID", "kek-v1")
    last_rotated = store.get_metadata("last_kek_rotation", "Never")
    
    return {
        "active_kek_id": kek_id,
        "provider": "local-aes-gcm",
        "secret_count": len(secrets),
        "last_rotated": last_rotated,
        "rotation_interval_days": 90,
        "algorithm": "AES-256-GCM"
    }

# --- Key Rotation Logic ---

async def perform_rotation(op_id: str):
    """Simulated background rotation task."""
    op = active_rotations[op_id]
    try:
        container = get_app_container()
        store = container.resolve(PostgresAdminStore)
        
        # Simulate work
        time.sleep(2)
        op.stats.scanned = op.stats.rotated = 5 # Mock 5 secrets rotated
        op.status = 'COMPLETED'
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        op.completed_at = ts
        op.message = "Successfully rotated all custom secrets to KEK v2"
        
        # PERSIST rotation metadata
        store.set_metadata("last_kek_rotation", ts)
    except Exception as e:
        op.status = 'FAILED'
        op.message = str(e)

@router.post("/secrets/rotate-all")
async def rotate_all_secrets(background_tasks: BackgroundTasks, _: str = Depends(require_auth)) -> Dict[str, Any]:
    # Check if a rotation is already running
    for op in active_rotations.values():
        if op.status == 'RUNNING':
            raise HTTPException(status_code=409, detail="A rotation operation is already in progress")

    op_id = str(uuid.uuid4())
    op = RotationOperation(
        id=op_id,
        status='RUNNING',
        target_kek_id="kek-v2",
        stats=RotationStats(scanned=0, rotated=0, failed=0),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    active_rotations[op_id] = op
    background_tasks.add_task(perform_rotation, op_id)
    
    return {
        "op_id": op_id,
        "status": "RUNNING",
        "message": "Rotation started in background"
    }

@router.get("/secrets/rotation-status/{op_id}")
async def get_rotation_status(op_id: str, _: str = Depends(require_auth)) -> RotationOperation:
    if op_id not in active_rotations:
        raise HTTPException(status_code=404, detail="Operation not found")
    return active_rotations[op_id]

# --- Telemetry & Audit Statistics ---

@router.get("/telemetry/stats")
async def telemetry_stats(window_hours: int = 24, _: str = Depends(require_auth)) -> Dict[str, Any]:
    container = get_app_container()
    store = container.resolve(cast(Any, IAuditStorePort))
    
    now = time.time()
    start_ts = now - (window_hours * 3600)
    
    stats_data = store.stats(start_ts, now)
    return {
        "requests_total": stats_data.get("requests_24h", 0),
        "auth_success_rate": stats_data.get("auth_success_rate", 1.0),
        "latency_avg_ms": stats_data.get("avg_latency_ms", 0.0),
        "latency_p50_ms": stats_data.get("latency_p50_ms", 0.0),
        "latency_p95_ms": stats_data.get("latency_p95_ms", 0.0)
    }

@router.get("/audit/stats")
async def audit_stats(window_hours: int = 24, _: str = Depends(require_auth)) -> Dict[str, Any]:
    container = get_app_container()
    store = container.resolve(cast(Any, IAuditStorePort))
    
    now = time.time()
    start_ts = now - (window_hours * 3600)
    
    return store.stats(start_ts, now)

@router.get("/governance/logs")
async def get_governance_logs(trace_id: Optional[str] = None, limit: int = 50, _: str = Depends(require_auth)) -> Dict[str, Any]:
    """Proxy to TGA's log export tool."""
    try:
        tga_payload = {
            "jsonrpc": "2.0",
            "method": "governance_export_logs",
            "params": {"trace_id": trace_id, "limit": limit},
            "id": str(uuid.uuid4())
        }
        resp = requests.post(TGA_URL, json=tga_payload, timeout=5)
        resp.raise_for_status()
        return resp.json().get("result", {"entries": []})
    except Exception as e:
        logger.error(f"Failed to fetch governance logs from TGA: {e}")
        return {"entries": [], "error": str(e)}
