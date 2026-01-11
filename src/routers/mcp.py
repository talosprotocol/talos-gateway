import os
import requests
import uuid
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])

# Configuration (MVP: Hardcoded or Env)
# Registry maps server_id -> internal endpoint URL
MCP_REGISTRY = {
    "git": os.getenv("MCP_GIT_URL", "http://localhost:8082"),
    "weather": os.getenv("MCP_WEATHER_URL", "http://localhost:8082")
}

# --- Models ---
class ToolCallRequest(BaseModel):
    input: Dict

class ToolCallResponse(BaseModel):
    request_id: str
    output: Dict
    error: Optional[Dict] = None

# --- Helpers ---
def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    # MVP: Check for "Bearer <token>"
    token = authorization.split(" ")[1] if " " in authorization else authorization
    # TODO: Verify token against Identity/Auth service
    if token == "invalid-token":
        raise HTTPException(status_code=403, detail="Invalid token")
    return token

def get_upstream_url(server_id: str) -> str:
    url = MCP_REGISTRY.get(server_id)
    if not url:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found in gateway registry")
    return url

# --- Routes ---

@router.get("/servers")
def list_servers(token: str = Depends(verify_token)):
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
def list_tools(server_id: str, token: str = Depends(verify_token)):
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
def get_tool_schema(server_id: str, tool_name: str, token: str = Depends(verify_token)):
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
                "schema_hash": "mock-hash", # TODO: Compute
                "version": "1.0.0"
            }
            
    raise HTTPException(status_code=404, detail="Tool not found")

@router.post("/servers/{server_id}/tools/{tool_name}:call")
def call_tool(server_id: str, tool_name: str, req: ToolCallRequest, token: str = Depends(verify_token)):
    """Invoke a tool (proxied)."""
    base_url = get_upstream_url(server_id)
    
    # Audit Log (Placeholder - integrate with IAuditStorePort if accessible)
    # print(f"AUDIT: Invoking {server_id}/{tool_name} by {token[:8]}...")
    
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
