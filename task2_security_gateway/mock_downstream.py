from typing import Any, Dict
from fastapi import FastAPI

app = FastAPI(title="Mock Downstream MCP Server")


@app.post("/mcp")
async def mcp(payload: Dict[str, Any]):
    method = payload.get("method")
    request_id = payload.get("id")

    if method == "tools/list":
        result = {
            "tools": [
                {"name": "get_customer_record"},
                {"name": "admin_reset_key"},
            ]
        }
    elif method == "tools/call":
        result = {"ok": True, "tool": (payload.get("params") or {}).get("name")}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}

    return {"jsonrpc": "2.0", "id": request_id, "result": result}
