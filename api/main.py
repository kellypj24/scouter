"""Scouter FastAPI service — internal harness boundary.

Exposes the agent harness over HTTP so any client (Go gateway, tests, curl)
can drive it without importing Python modules directly. All agent logic stays
in src/; this module is thin wiring only.
"""

from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse

from api.deps import get_orchestrator
from api.streaming import serialize_block
from src.agent.orchestrator import Orchestrator
from src.models.agent import AgentRequest

app = FastAPI(title="Scouter API", version="0.1.0")


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
