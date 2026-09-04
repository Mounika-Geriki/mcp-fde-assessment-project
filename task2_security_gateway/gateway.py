from typing import Any, Dict

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

app = FastAPI(title="MCP Security Gateway")
DOWNSTREAM_URL = "http://127.0.0.1:8001/mcp"

TOKENS = {
    "admin-token": "admin",
    "viewer-token": "viewer",
}


def jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def role_from_authorization(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return TOKENS.get(token)


@app.post("/mcp")
async def mcp_proxy(payload: Dict[str, Any], authorization: str | None = Header(default=None)):
    request_id = payload.get("id")
    method = payload.get("method")
    role = role_from_authorization(authorization)

    if role is None:
        return JSONResponse(jsonrpc_error(request_id, -32000, "Invalid or missing Bearer token"), status_code=401)

    if method == "tools/call":
        params = payload.get("params") or {}
        tool_name = params.get("name", "")
        if isinstance(tool_name, str) and tool_name.startswith("admin_") and role != "admin":
            return JSONResponse(
                jsonrpc_error(request_id, -32001, "Unauthorized Tool Call"),
                status_code=403,
            )

    # tools/list passes through transparently; other methods are also proxied.
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(DOWNSTREAM_URL, json=payload)
        return JSONResponse(response.json(), status_code=response.status_code)
    except httpx.HTTPError:
        return JSONResponse(jsonrpc_error(request_id, -32002, "Downstream MCP server unavailable"), status_code=502)
