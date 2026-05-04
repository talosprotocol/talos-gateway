from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from bootstrap import get_app_container
from src.adapters.postgres_admin_store import PostgresAdminStore
from src.routers.mcp import MCP_REGISTRY
from src.auth import require_auth

router = APIRouter(prefix="/admin/v1/config", tags=["config"])

@router.get(":export")
async def export_config(_: str = Depends(require_auth)) -> Dict[str, Any]:
    """Export current platform configuration."""
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    
    # 1. Collect Upstreams (from MCP Registry)
    upstreams = []
    for sid, url in MCP_REGISTRY.items():
        upstreams.append({
            "id": sid,
            "url": url,
            "transport": "http"
        })
        
    # 2. Collect RBAC Roles
    roles = store.list_roles()
    
    # 3. Collect RBAC Bindings
    bindings = store.list_bindings()
    
    # 4. Wrap in export format
    config = {
        "version": "1.0",
        "timestamp": 0, # Should be real timestamp
        "upstreams": upstreams,
        "rbac": {
            "roles": roles,
            "bindings": bindings
        },
        "metadata": {
            "origin": "talos-gateway-v1"
        }
    }
    
    # Save a snapshot to DB as well for history
    store.save_config(config)
    
    return config

@router.post(":apply")
async def apply_config(config: Dict[str, Any], _: str = Depends(require_auth)) -> Dict[str, Any]:
    """Apply platform configuration from snapshot."""
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    
    # Validation logic (simplified for MVP)
    if not config.get("upstreams") and not config.get("rbac"):
        raise HTTPException(status_code=400, detail="Invalid config snapshot")
        
    # 1. Apply RBAC Roles
    if "rbac" in config and "roles" in config["rbac"]:
        for role in config["rbac"]["roles"]:
            store.upsert_role(
                role["role_id"], 
                role["name"], 
                role.get("description", ""), 
                role["permissions"],
                role.get("built_in", False)
            )
            
    # 2. Apply RBAC Bindings
    if "rbac" in config and "bindings" in config["rbac"]:
        for binding in config["rbac"]["bindings"]:
            store.upsert_binding(binding["principal_id"], binding["bindings"])
            
    # 3. Apply Upstreams (This currently only updates the memory registry)
    if "upstreams" in config:
        for u in config["upstreams"]:
            MCP_REGISTRY[u["id"]] = u["url"]
            
    # Save as current config
    store.save_config(config)
    
    return {"status": "success", "message": "Configuration applied"}
