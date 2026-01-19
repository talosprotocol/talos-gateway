"""
Admin API Router for Talos Gateway

Provides administrative endpoints for user profile, secrets, and statistics.
Must enforce authentication in production mode.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Any
import os

router = APIRouter(prefix="/admin/v1", tags=["admin"])

# Check if running in dev mode
def is_dev_mode() -> bool:
    mode = os.getenv("MODE", "").lower()
    return mode == "dev" or mode == "development"

# Auth dependency (TODO: implement real auth)
async def require_auth():
    """
    PRODUCTION: Must validate JWT and extract principal.
    DEV MODE: Can bypass for testing.
    """
    if not is_dev_mode():
        # TODO: Implement real auth validation
        # from src.auth import validate_token
        # principal = await validate_token(token)
        # return principal
        pass
    return None

@router.get("/me")
async def get_current_user(_: Any = Depends(require_auth)):
    """
    Get current user profile.
    
    Returns:
        User profile with id, email, name
    
    Errors:
        401: Unauthorized (missing or invalid auth)
    """
    # TODO: Return actual user from auth context
    return {
        "id": "user-dev-001",
        "email": "dev@talosprotocol.com",
        "name": "Development User",
        "roles": ["admin"]
    }

@router.get("/secrets")
async def list_secrets(_: Any = Depends(require_auth)):
    """
    List secret keys (metadata only, not values).
    
    Returns:
        List of secret metadata
    """
    # TODO: Fetch from secrets manager
    return {
        "items": [
            {
                "id": "secret-001",
                "name": "DATABASE_URL",
                "created_at": "2026-01-18T00:00:00Z",
                "updated_at": "2026-01-18T00:00:00Z"
            }
        ],
        "total": 1
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
    # TODO: Query from metrics store
    return {
        "requests_total": 0,
        "tokens_total": 0,
        "cost_usd": 0.0,
        "latency_avg_ms": 0.0
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
    # TODO: Query from audit service
    return {
        "requests_24h": 0,
        "denial_reason_counts": {},
        "request_volume_series": []
    }
