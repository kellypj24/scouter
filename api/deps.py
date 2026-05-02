"""FastAPI dependency providers for the Scouter API."""

from src.agent.narrative_agent import NarrativeAgent
from src.agent.orchestrator import Orchestrator
from src.agent.providers.base import get_provider
from src.agent.query_agent import QueryAgent
from src.data.db import get_read_connection
from src.data.news import fetch_news


def get_orchestrator() -> Orchestrator:
    """Construct a fresh Orchestrator per request using shared singletons.

    The provider and DB connection are module-level singletons (one per process).
    The Orchestrator itself is intentionally created fresh per request to avoid
    async session state leaking between calls.

    Returns:
        Orchestrator wired with the active provider and read-only DB connection.
    """
    provider = get_provider()
    conn = get_read_connection()
    return Orchestrator(
        provider=provider,
        query_agent=QueryAgent(provider=provider, conn=conn),
        narrative_agent=NarrativeAgent(provider=provider, news_fetcher=fetch_news),
    )
