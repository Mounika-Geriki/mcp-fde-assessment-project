# FDE Assessment Project

Python implementation of the Forward Deployed Engineer assessment tasks described in the supplied PDF.

## What is Included

- **Task 1:** MCP server with strict Pydantic validation and stdio transport.
- **Task 2:** MCP security gateway with Bearer-role authorization for `admin_` tools.
- **Task 3:** Streaming LLM gateway with PII redaction across chunk boundaries.
- **Task 4:** Token-aware sliding-window rate limiter backed by SQLite, with primary-model timeout and `429` fallback.

<!-- > Note: The supplied PDF says there are 5 tasks, but the provided three pages only contain detailed requirements for Tasks 1–4. This repository implements those four tasks. -->

---

## Requirements

- Python 3.10+
- Recommended: Python 3.12

---

## Setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Task 1: MCP Server

This task implements an MCP server using the official Python MCP SDK.

The server exposes two tools:

- `get_customer_record`
- `trigger_refund`

The implementation includes:

- strict Pydantic validation
- customer IDs in the format `CUST-XXXXX`
- positive refund amount validation
- minimum refund reason length validation
- stdio transport
- stdout reserved for MCP JSON-RPC traffic
- logs written to stderr

### Run Task 1

```bash
python task1_mcp_server/server.py
```

Because this is a stdio MCP server, the process will wait for MCP JSON-RPC input after startup.

No normal application logs should be written to stdout.

---

## Task 2: MCP Security Gateway

This task implements a lightweight HTTP/JSON-RPC security gateway between an MCP client and a downstream mock MCP server.

The gateway:

- reads the Bearer token from the HTTP `Authorization` header
- extracts the user's role
- forwards `tools/list` requests
- inspects `tools/call` requests
- checks `params.name`
- blocks non-admin users from tools beginning with `admin_`
- returns JSON-RPC error code `-32001` for unauthorized admin tool calls
- forwards authorized requests to the downstream MCP server

### Start the Downstream Mock Server

In Terminal 1:

```bash
python -m uvicorn task2_security_gateway.mock_downstream:app --port 8001
```

The downstream server should start on:

```text
http://127.0.0.1:8001
```

### Start the Security Gateway

In Terminal 2:

```bash
python -m uvicorn task2_security_gateway.gateway:app --port 8000
```

The gateway should start on:

```text
http://127.0.0.1:8000
```

### Test Viewer Authorization

A viewer attempting to call an admin tool should be rejected:

```bash
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer viewer-token' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"admin_reset_key","arguments":{}}}'
```

Expected response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32001,
    "message": "Unauthorized Tool Call"
  }
}
```

### Test Admin Authorization

An admin user should be allowed to call the same tool:

```bash
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer admin-token' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"admin_reset_key","arguments":{}}}'
```

The request should be forwarded successfully to the downstream server.

Example response:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "ok": true,
    "tool": "admin_reset_key"
  }
}
```

---

## Task 3: Streaming PII Guardrail

This task implements an LLM gateway endpoint that streams generated text while detecting and redacting PII.

The guardrail supports:

- email addresses
- SSNs
- credit card numbers

Sensitive values are replaced with:

```text
[REDACTED]
```

The implementation uses a bounded rolling buffer so that sensitive patterns split across streaming chunks can still be detected before potentially sensitive text is emitted.

A mock provider is included so the streaming behavior can be tested without requiring a real LLM API key.

### Start Task 3

```bash
python -m uvicorn task3_streaming_guardrail.gateway:app --port 8002
```

The service should start on:

```text
http://127.0.0.1:8002
```

### Test PII Redaction

```bash
curl -N -X POST http://localhost:8002/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{"mock_text":"Contact alice@example.com. My SSN is 123-45-6789 and card is 4111 1111 1111 1111."}'
```

Expected output:

```text
Contact [REDACTED]. My SSN is [REDACTED] and card is [REDACTED].
```

---

## Task 4: Rate Limiter and Model Fallback Router

This task implements a resilient model-routing module for an LLM gateway.

The implementation includes:

- per-tenant token-aware rate limiting
- 50,000 tokens per minute per tenant
- sliding-window rate limiting
- SQLite-backed rate-limit state stored on disk
- primary-model routing
- automatic fallback when the primary returns HTTP `429`
- automatic fallback when the primary exceeds the 3000 ms timeout
- standardized gateway error responses
- no raw upstream stack traces exposed to clients

### Start Task 4

```bash
python -m uvicorn task4_model_router.gateway:app --port 8003
```

The service should start on:

```text
http://127.0.0.1:8003
```

### Test Normal Primary Routing

```bash
curl -X POST http://localhost:8003/v1/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tenant-a' \
  -d '{"prompt":"hello","estimated_tokens":100,"simulate_primary":"ok"}'
```

Expected result:

```json
{
  "status": 200,
  "provider": "primary"
}
```

### Test 429 Fallback

```bash
curl -X POST http://localhost:8003/v1/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tenant-b' \
  -d '{"prompt":"hello","estimated_tokens":100,"simulate_primary":"429"}'
```

Expected result:

```json
{
  "status": 200,
  "provider": "backup"
}
```

### Test Timeout Fallback

```bash
time curl -X POST http://localhost:8003/v1/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tenant-c' \
  -d '{"prompt":"hello","estimated_tokens":100,"simulate_primary":"timeout"}'
```

Expected behavior:

- the primary request times out after approximately 3 seconds
- the request is automatically routed to the backup provider
- the response contains `"provider": "backup"`

### Test Token Rate Limiting

The per-tenant limit is:

```text
50,000 tokens per minute
```

Use a fresh tenant key.

First request:

```bash
curl -X POST http://localhost:8003/v1/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tenant-rate' \
  -d '{"prompt":"hello","estimated_tokens":49000,"simulate_primary":"ok"}'
```

Second request:

```bash
curl -X POST http://localhost:8003/v1/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tenant-rate' \
  -d '{"prompt":"hello","estimated_tokens":1000,"simulate_primary":"ok"}'
```

These two requests reach exactly 50,000 tokens and should be allowed.

A third request:

```bash
curl -X POST http://localhost:8003/v1/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tenant-rate' \
  -d '{"prompt":"hello","estimated_tokens":1,"simulate_primary":"ok"}'
```

should be rejected with:

```text
HTTP 429 Too Many Requests
```

Example standardized error:

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Tenant token rate limit exceeded"
  }
}
```

---

## Tests

Run the full automated test suite:

```bash
python -m pytest -q
```

Expected result:

```text
6 passed
```

---

## Project Structure

```text
fde_assessment_project/
├── task1_mcp_server/
│   ├── __init__.py
│   └── server.py
├── task2_security_gateway/
│   ├── __init__.py
│   ├── gateway.py
│   └── mock_downstream.py
├── task3_streaming_guardrail/
│   ├── __init__.py
│   └── gateway.py
├── task4_model_router/
│   ├── __init__.py
│   └── gateway.py
├── tests/
│   └── test_project.py
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Dependencies

```text
fastapi==0.115.0
uvicorn>=0.31.1
httpx==0.27.2
pydantic>=2.11,<3
mcp>=1.28,<2
pytest==8.3.3
pytest-asyncio==0.24.0
```

The MCP dependency is restricted to version 1.x because this implementation uses the `FastMCP` API.

---

## Verification Summary

Verified behavior includes:

- MCP server startup
- strict validation
- stdio transport
- viewer/admin authorization
- unauthorized `admin_` tool blocking
- downstream request forwarding
- email redaction
- SSN redaction
- credit card redaction
- chunk-boundary streaming redaction
- primary model routing
- HTTP `429` fallback
- approximately 3-second timeout fallback
- 50,000 token-per-minute rate limiting
- standardized rate-limit errors
- automated test coverage

Current automated test result:

```text
6 passed
```