import asyncio
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Rate Limit + Model Fallback Gateway")

DB_PATH = Path(__file__).with_name("rate_limit.db")
WINDOW_SECONDS = 60
TOKEN_LIMIT = 50_000
PRIMARY_TIMEOUT_SECONDS = 3.0


class CompletionRequest(BaseModel):
    prompt: str
    estimated_tokens: int = Field(gt=0)
    simulate_primary: Literal["ok", "429", "timeout", "error"] = "ok"


@contextmanager
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token_events (
                api_key TEXT NOT NULL,
                ts REAL NOT NULL,
                tokens INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_token_events_key_ts ON token_events(api_key, ts)")
        conn.commit()
        yield conn
    finally:
        conn.close()


def consume_tokens(api_key: str, tokens: int) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - WINDOW_SECONDS
    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM token_events WHERE ts < ?", (cutoff,))
        current = conn.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM token_events WHERE api_key = ? AND ts >= ?",
            (api_key, cutoff),
        ).fetchone()[0]
        if current + tokens > TOKEN_LIMIT:
            conn.rollback()
            return False, current
        conn.execute("INSERT INTO token_events(api_key, ts, tokens) VALUES (?, ?, ?)", (api_key, now, tokens))
        conn.commit()
        return True, current + tokens


async def primary_provider(req: CompletionRequest) -> dict:
    if req.simulate_primary == "429":
        return {"status": 429}
    if req.simulate_primary == "timeout":
        await asyncio.sleep(PRIMARY_TIMEOUT_SECONDS + 1)
    if req.simulate_primary == "error":
        raise RuntimeError("Sensitive upstream stack trace should never be exposed")
    return {"status": 200, "provider": "primary", "text": f"Primary response to: {req.prompt}"}


async def backup_provider(req: CompletionRequest) -> dict:
    await asyncio.sleep(0.05)
    return {"status": 200, "provider": "backup", "text": f"Backup response to: {req.prompt}"}


def gateway_error(code: str, message: str, status_code: int):
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status_code,
    )


@app.post("/v1/completions")
async def completions(req: CompletionRequest, x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        return gateway_error("missing_api_key", "X-API-Key header is required", 401)

    allowed, used = consume_tokens(x_api_key, req.estimated_tokens)
    if not allowed:
        return gateway_error("rate_limit_exceeded", "Tenant token rate limit exceeded", 429)

    try:
        try:
            primary = await asyncio.wait_for(primary_provider(req), timeout=PRIMARY_TIMEOUT_SECONDS)
            if primary.get("status") == 429:
                return await backup_provider(req)
            return {**primary, "tokens_in_window": used}
        except asyncio.TimeoutError:
            backup = await backup_provider(req)
            return {**backup, "fallback_reason": "primary_timeout", "tokens_in_window": used}
    except Exception:
        return gateway_error("upstream_failure", "Model provider request failed", 502)
