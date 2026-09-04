import asyncio
import re
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Streaming PII Guardrail Gateway")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


class GenerationRequest(BaseModel):
    prompt: str | None = None
    mock_text: str = "Hello from the mock provider."


def redact_pii(text: str) -> str:
    text = EMAIL_RE.sub("[REDACTED]", text)
    text = SSN_RE.sub("[REDACTED]", text)
    text = CARD_RE.sub("[REDACTED]", text)
    return text


async def mock_provider_stream(text: str, chunk_size: int = 7) -> AsyncIterator[str]:
    for i in range(0, len(text), chunk_size):
        await asyncio.sleep(0.01)
        yield text[i : i + chunk_size]


def _matches(text: str):
    matches = []
    for regex in (EMAIL_RE, SSN_RE, CARD_RE):
        matches.extend(regex.finditer(text))
    return sorted(matches, key=lambda m: (m.start(), m.end()))


async def redact_stream(source: AsyncIterator[str], overlap: int = 256) -> AsyncIterator[bytes]:
    """Redact PII with a bounded rolling buffer.

    We keep an overlap so bounded sensitive patterns split across network chunks can
    be recognized. Before emitting a prefix, matches are evaluated over the *whole*
    buffer; if an identified match crosses the tentative emission boundary, that
    match is retained until a later chunk arrives.
    """
    buffer = ""
    async for chunk in source:
        buffer += chunk
        if len(buffer) <= overlap:
            continue

        emit_end = len(buffer) - overlap
        for match in _matches(buffer):
            if match.start() < emit_end < match.end():
                emit_end = match.start()
                break

        if emit_end > 0:
            prefix = buffer[:emit_end]
            yield redact_pii(prefix).encode("utf-8")
            buffer = buffer[emit_end:]

    if buffer:
        yield redact_pii(buffer).encode("utf-8")


@app.post("/v1/generate")
async def generate(req: GenerationRequest):
    stream = mock_provider_stream(req.mock_text)
    return StreamingResponse(redact_stream(stream), media_type="text/plain")
