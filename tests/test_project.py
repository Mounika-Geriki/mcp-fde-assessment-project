import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_task1_validation():
    mod = load("task1server", "task1_mcp_server/server.py")
    assert mod.CustomerRecordInput(customer_id="CUST-12345").customer_id == "CUST-12345"
    with pytest.raises(ValidationError):
        mod.CustomerRecordInput(customer_id="BAD-123")
    with pytest.raises(ValidationError):
        mod.RefundInput(customer_id="CUST-12345", amount=-1, reason="too short")


def test_task2_roles():
    mod = load("task2gateway", "task2_security_gateway/gateway.py")
    assert mod.role_from_authorization("Bearer admin-token") == "admin"
    assert mod.role_from_authorization("Bearer viewer-token") == "viewer"
    assert mod.role_from_authorization("Bearer nope") is None


def test_task3_redaction():
    mod = load("task3gateway", "task3_streaming_guardrail/gateway.py")
    text = "Email a@b.com SSN 123-45-6789 card 4111 1111 1111 1111"
    redacted = mod.redact_pii(text)
    assert "a@b.com" not in redacted
    assert "123-45-6789" not in redacted
    assert "4111 1111 1111 1111" not in redacted


@pytest.mark.asyncio
async def test_task3_chunk_boundary():
    mod = load("task3gateway2", "task3_streaming_guardrail/gateway.py")

    async def src():
        for part in ["alice@", "example.", "com hello"]:
            yield part

    out = b""
    async for chunk in mod.redact_stream(src(), overlap=64):
        out += chunk
    assert b"alice@example.com" not in out
    assert b"[REDACTED]" in out


def test_task4_rate_limiter(tmp_path):
    mod = load("task4gateway", "task4_model_router/gateway.py")
    mod.DB_PATH = tmp_path / "rate_limit.db"
    allowed, used = mod.consume_tokens("tenant", 49_000)
    assert allowed and used == 49_000
    allowed, used = mod.consume_tokens("tenant", 2_000)
    assert not allowed


@pytest.mark.asyncio
async def test_task4_fallback_provider():
    mod = load("task4gateway2", "task4_model_router/gateway.py")
    req = mod.CompletionRequest(prompt="hi", estimated_tokens=10, simulate_primary="429")
    result = await mod.primary_provider(req)
    assert result["status"] == 429
    backup = await mod.backup_provider(req)
    assert backup["provider"] == "backup"
