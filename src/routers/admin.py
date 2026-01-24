from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Any
import os
import time
from bootstrap import get_app_container
from talos_sdk.ports.audit_store import IAuditStorePort
from src.auth import require_auth, is_dev_mode

router = APIRouter(prefix="/admin/v1", tags=["admin"])

@router.get("/me")
async def get_current_user(_: Any = Depends(require_auth)):
    """
    Get current user profile.
    
    Returns:
        User profile with id, email, name
    
    Errors:
        401: Unauthorized (missing or invalid auth)
    """
    """
    Get current user profile.
    """
    # Simple profile based on auth context
    return {
        "id": "admin-001",
        "email": os.getenv("ADMIN_EMAIL", "admin@talos.security"),
        "name": "System Administrator",
        "roles": ["admin", "operator"]
    }

@router.get("/secrets")
async def list_secrets(_: Any = Depends(require_auth)):
    """
    List secret keys (metadata only, not values).
    
    Returns:
        List of secret metadata
    """
    """
    List secret keys (metadata only, not values).
    Scans environment variables for sensitive prefixes.
    """
    secrets = []
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    # 1. Environment Secrets (Masked)
    for key in os.environ:
        if any(prefix in key for prefix in ["TALOS_", "SECRET", "KEY", "PASSWORD", "token"]):
            secrets.append({
                "id": key,
                "name": key,
                "created_at": timestamp,
                "updated_at": timestamp,
                "provider": "env"
            })
            
    return {
        "items": secrets,
        "total": len(secrets)
    }

@router.get("/telemetry/stats")
async def telemetry_stats(
    window_hours: int = 24,
    _: Any = Depends(require_auth)
):
    """
    Get telemetry statistics for time window.
    
    Args:
        window_hours: Time window in hours (default 24)
    
    Returns:
        Aggregated metrics
    """
    """
    Get telemetry statistics for time window.
    """
    container = get_app_container()
    store = container.resolve(IAuditStorePort)
    
    # Calculate window
    now = time.time()
    start_ts = now - (window_hours * 3600)
    
    # Get stats from store
    stats_data = store.stats(start_ts, now)
    
    requests_count = stats_data.get("requests_24h", 0)
    
    # Telemetry Calculations using real data from AuditStore
    return {
        "requests_total": requests_count,
        "tokens_total": stats_data.get("tokens_total", 0), 
        "cost_usd": stats_data.get("cost_usd", 0.0),
        "latency_avg_ms": stats_data.get("latency_avg_ms", 0.0) 
    }

@router.get("/audit/stats")
async def audit_stats(
    window_hours: int = 24,
    _: Any = Depends(require_auth)
):
    """
    Get audit event statistics for time window.
    
    Args:
        window_hours: Time window in hours (default 24)
    
    Returns:
        Audit event aggregates
    """
    """
    Get audit event statistics for time window.
    """
    container = get_app_container()
    store = container.resolve(IAuditStorePort)
    
    # Calculate window
    now = time.time()
    start_ts = now - (window_hours * 3600)
    
    return store.stats(start_ts, now)
