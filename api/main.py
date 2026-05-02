"""Scouter FastAPI service — internal harness boundary.

Exposes the agent harness over HTTP so any client (Go gateway, tests, curl)
can drive it without importing Python modules directly. All agent logic stays
in src/; this module is thin wiring only.
"""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse

from api.deps import get_orchestrator
from api.streaming import serialize_block
from src.agent.orchestrator import Orchestrator
from src.models.agent import AgentRequest
from src.observability.context import request_id_var

app = FastAPI(title="Scouter API", version="0.1.0")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: object) -> object:
    """Propagate or generate a request ID for every inbound request.

    The Go gateway sets X-Request-ID on every proxied request. For direct
    calls (curl, tests), a UUID is generated. The ID is stored in a contextvar
    so it flows automatically to all coroutines spawned within this request.
    """
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_var.reset(token)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


@app.post("/ask")
async def ask(
    request: AgentRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),  # noqa: B008
) -> StreamingResponse:
    """Stream NarrativeBlocks as SSE events, one per sub-question.

    Each block is emitted as it completes so the client receives partial results
    immediately. A final 'done' event signals end of stream.

    SSE event shape:
        event: block
        data: <NarrativeBlock as JSON>

        event: done
        data: {}
    """

    async def event_stream() -> AsyncGenerator[str]:
        async for block in orchestrator.stream(request):
            yield f"event: block\ndata: {serialize_block(block)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
