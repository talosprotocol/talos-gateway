from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.post("/")
async def handle_rpc(request: Request):
    data = await request.json()
    method = data.get("method")
    req_id = data.get("id")
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "remote_echo",
                        "description": "Remote Echo Tool",
                        "inputSchema": {"type": "object"}
                    }
                ]
            }
        }
    elif method == "tools/call":
        params = data.get("params", {})
        args = params.get("arguments", {})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "output": f"Echo from upstream: {args}"
            }
        }
    
    return {"error": "Method not found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)
