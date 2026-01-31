import os
import requests
import uuid
from typing import Optional, Dict, Any, cast
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])

import hashlib
import json
import time
from bootstrap import get_app_container
from talos_sdk.ports.audit_store import IAuditStorePort
from src.auth import require_auth, verify_token_header

# Configuration
# Default to cluster-local DNS for MCP Connector
DEFAULT_CONNECTOR_URL = os.getenv("MCP_CONNECTOR_URL", "http://talos-mcp-connector:8082")

MCP_REGISTRY = {
    # Allow dynamic extension via env
    **{k.replace("MCP_SERVER_", "").lower(): v 
       for k, v in os.environ.items() if k.startswith("MCP_SERVER_")}
}

# --- Models ---
class ToolCallRequest(BaseModel):
    input: Dict[str, Any]

class ToolCallResponse(BaseModel):
    request_id: str
    output: Dict[str, Any]
    error: Optional[Dict[str, Any]] = None

# --- Helpers ---
def get_upstream_url(server_id: str) -> str:
    url = MCP_REGISTRY.get(server_id)
    if not url:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found in gateway registry")
    return url

def _compute_hash(data: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

# --- Routes ---

@router.get("/servers")
def list_servers(token: str = Depends(verify_token_header)) -> Dict[str, Any]:
    """List available MCP servers (gated by capability)."""
    # MVP: Return static registry
    servers = []
    for sid, url in MCP_REGISTRY.items():
        servers.append({
            "id": sid,
            "name": sid.capitalize(),
            "transport": "http",
            "metadata": {"upstream": url}
        })
    return {"servers": servers}

@router.get("/servers/{server_id}/tools")
@router.get("/servers/{server_id}/tools")
def list_tools(server_id: str, token: str = Depends(verify_token_header)) -> Dict[str, Any]:
    """List tools for a specific server (proxied)."""
    base_url = get_upstream_url(server_id)
    
    # Proxy to upstream: expects JSON-RPC "tools/list" or similar
    # Assuming upstream exposes a simple /tools endpoint or we wrap JSON-RPC
    # Let's assume upstream is standard MCP-over-HTTP which receives JSON-RPC POSTs.
    
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": str(uuid.uuid4())
    }
    
    try:
        # Assuming upstream listens at base_url for JSON-RPC
        # e.g. http://localhost:8082/
        # Or maybe http://localhost:8082/jsonrpc
        # We need a standard contract for the upstream internal service.
        # Let's assume base_url IS the endpoint.
        
        resp = requests.post(base_url, json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        if "error" in data:
            raise HTTPException(status_code=502, detail=f"Upstream error: {data['error']}")
            
        return {"tools": data.get("result", {}).get("tools", [])}
        
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch tools: {str(e)}")

@router.get("/servers/{server_id}/tools/{tool_name}/schema")
def get_tool_schema(server_id: str, tool_name: str, token: str = Depends(verify_token_header)) -> Dict[str, Any]:
    """Get schema for a specific tool."""
    # Optimization: Call list_tools and filter
    # Or strict upstream call if supported.
    # We will reuse list_tools logic for MVP.
    
    tools_resp = list_tools(server_id, token)
    tools = tools_resp.get("tools", [])
    
    for t in tools:
        if t["name"] == tool_name:
            # Construct response matching schema_fetch.schema.json
            return {
                "server_id": server_id,
                "tool_name": tool_name,
                "json_schema": t.get("inputSchema", {}),
                "schema_hash": _compute_hash(t.get("inputSchema", {})),
                "version": "1.0.0"
            }
            
    raise HTTPException(status_code=404, detail="Tool not found")

@router.post("/servers/{server_id}/tools/{tool_name}:call")
def call_tool(server_id: str, tool_name: str, req: ToolCallRequest, token: str = Depends(verify_token_header)) -> Dict[str, Any]:
    """Invoke a tool (proxied)."""
    base_url = get_upstream_url(server_id)
    
    
    # Live Audit Log
    try:
        container = get_app_container()
        store = container.resolve(cast(Any, IAuditStorePort))
        
        # We construct a basic event. In a full system, we'd use 'AuditEventCreate' model
        # and rely on the Audit Store's structured logging.
        # But 'append' takes an AuditEvent protocol.
        # Minimal object satisfying Protocol:
        class AuditEntry:
            def __init__(self, **kwargs: Any) -> None:
                self.__dict__.update(kwargs)
                
        event: Any = AuditEntry(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            # Required fields for Postgres store:
            cursor=None, # Auto-assigned by store usually, or optional in append
            event_type="mcp_tool_call",
            outcome="PENDING",
            session_id="gateway-mcp",
            correlation_id=str(uuid.uuid4()),
            agent_id="user", # Derived from token in real implementation
            tool=tool_name,
            method="call",
            resource=server_id,
            metadata={"input_keys": list(req.input.keys())},
            metrics={},
            hashes={},
            integrity={},
            integrity_hash=""
        )
        store.append(event)
    except Exception as e:
        # Non-blocking audit failure
        print(f"WARN: Failed to audit tool call: {e}")
    
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": req.input
        },
        "id": str(uuid.uuid4())
    }
    
    try:
        resp = requests.post(base_url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        if "error" in data:
            # Gateway shouldn't crash, return error in body
            return {
                "request_id": payload["id"],
                "error": data["error"]
            }
            
        return {
            "request_id": payload["id"],
            "output": data.get("result", {})
        }
        
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Invocation failed: {str(e)}")
