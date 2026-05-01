"""Orchestrator: decomposes a question and drives the query + narrative pipeline.

Responsibilities:
  1. Decompose the user's question into ≤ max_blocks focused sub-questions.
  2. For each sub-question: run QueryAgent → NarrativeAgent → NarrativeBlock.
  3. Return an AgentResponse with all blocks and a fallback flag.
  4. Degrade gracefully at every layer — never surface a raw error to the caller.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

from src.agent.narrative_agent import NarrativeAgent
from src.agent.prompts.orchestrator import SYSTEM, USER
from src.agent.providers.base import LLMError, LLMProvider
from src.agent.query_agent import _FALLBACK_SQL, QueryAgent
from src.models.agent import AgentRequest, AgentResponse
from src.models.response import NarrativeBlock, QueryResult

logger = logging.getLogger(__name__)


class DecompositionResponse(BaseModel):
    """Structured LLM output for question decomposition."""

    sub_questions: list[str] = Field(min_length=1)


class Orchestrator:
    """Drives the end-to-end pipeline: question → list of NarrativeBlocks.

    Args:
        provider: LLM provider used for decomposition (injected).
        query_agent: Handles SQL generation and DuckDB execution (injected).
        narrative_agent: Handles prose and chart generation (injected).
    """

    def __init__(
        self,
        provider: LLMProvider,
        query_agent: QueryAgent,
        narrative_agent: NarrativeAgent,
    ) -> None:
        self._provider = provider
        self._query_agent = query_agent
        self._narrative_agent = narrative_agent

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the full pipeline for a user request.

        Decomposes the question, runs each sub-question through query + narrative,
        and assembles the final AgentResponse. Gracefully handles failures at
        decomposition and per-block levels.

        Args:
            request: Incoming agent request with question and config.

        Returns:
            AgentResponse with one NarrativeBlock per sub-question.
        """
        sub_questions = await self._decompose(request.question, request.max_blocks)

        blocks: list[NarrativeBlock] = []
        for question in sub_questions:
            block = await self._run_block(question)
            blocks.append(block)

        # When multiple blocks were generated, suppress any that returned no data —
        # they're artefacts of over-decomposition and confuse the user. Always keep
        # at least one block so the response is never empty.
        if len(blocks) > 1:
            populated = [b for b in blocks if b.query_result.row_count > 0]
            if populated:
                blocks = populated

        fallback_used = any(b.query_result.sql == _FALLBACK_SQL for b in blocks)
        return AgentResponse(blocks=blocks, fallback_used=fallback_used)

    async def stream(self, request: AgentRequest) -> AsyncGenerator[NarrativeBlock, None]:
        """Yield NarrativeBlocks one at a time as each sub-question completes.

        Designed for SSE transport — the caller receives partial results immediately
        rather than waiting for all blocks. Empty blocks are not filtered here; the
        client decides what to render.

        Args:
            request: Incoming agent request with question and config.

        Yields:
            NarrativeBlock for each sub-question, in order.
        """
        sub_questions = await self._decompose(request.question, request.max_blocks)
        for question in sub_questions:
            yield await self._run_block(question)

    async def _decompose(self, question: str, max_blocks: int) -> list[str]:
        """Break a question into focused sub-questions via the LLM.

        Falls back to [question] if the LLM is unavailable or returns an
        invalid response, so the pipeline always has at least one sub-question.

        Args:
            question: The original user question.
            max_blocks: Maximum number of sub-questions to return.

        Returns:
            List of 1–max_blocks sub-questions.
        """
        messages = [
            {
                "role": "system",
                "content": SYSTEM.format(max_blocks=max_blocks),
            },
            {
                "role": "user",
                "content": USER.format(question=question, max_blocks=max_blocks),
            },
        ]
        try:
            raw: Any = await self._provider.complete_structured(messages, DecompositionResponse)
            if isinstance(raw, DecompositionResponse):
                result = raw
            else:
                result = DecompositionResponse.model_validate(raw)
            # Trim to max_blocks in case the LLM ignored the limit.
            return result.sub_questions[:max_blocks]
        except (LLMError, Exception) as exc:
            logger.warning("Decomposition failed — treating as single question: %s", exc)
            return [question]

    async def _run_block(self, question: str) -> NarrativeBlock:
        """Run a single sub-question through query + narrative.

        Catches DuckDB errors and returns a graceful error block so the
        caller always gets a complete NarrativeBlock regardless of failures.

        Args:
            question: A focused sub-question.

        Returns:
            NarrativeBlock with results or an error placeholder.
        """
        try:
            query_result, data = await self._query_agent.run(question)
            return await self._narrative_agent.run(question, query_result, data)
        except duckdb.Error as exc:
            logger.error("Query execution failed for %r: %s", question, exc)
            return _error_block(question, str(exc))
        except ValueError as exc:
            logger.warning("Query could not be generated for %r: %s", question, exc)
            logger.info("FEEDBACK_NEEDED question=%r — log this to improve data coverage", question)
            return _unanswerable_block(question, str(exc))


def _unanswerable_block(question: str, detail: str) -> NarrativeBlock:
    """NarrativeBlock returned when the requested metric is not in the schema."""
    import re as _re
    col_match = _re.search(r"Column '(\w+)' does not exist", detail)
    metric = col_match.group(1).replace("_", " ") if col_match else "that metric"
    return NarrativeBlock(
        question=question,
        query_result=QueryResult(sql="", row_count=0, columns=[]),
        data=pd.DataFrame(),
        chart_spec=None,
        prose=(
            f"This dataset doesn't contain {metric} data, so that question can't be answered directly. "
            "The available data covers stock prices, daily and YTD returns, volatility, Sharpe ratio, "
            "drawdown from 52-week highs, and sector-level aggregates. "
            "Income-statement metrics (revenue, earnings, margins) are not currently ingested."
        ),
        follow_ups=[
            f"What price and return data is available instead?",
            "Which stocks have the highest YTD return?",
            "What does the volatility profile look like for this stock?",
        ],
    )


def _error_block(question: str, detail: str) -> NarrativeBlock:
    """NarrativeBlock returned when a query fails at the database level."""
    return NarrativeBlock(
        question=question,
        query_result=QueryResult(sql="", row_count=0, columns=[]),
        data=pd.DataFrame(),
        chart_spec=None,
        prose=(
            "This question could not be answered due to a data retrieval error. "
            "The underlying tables may not be available or the query could not be executed."
        ),
        follow_ups=["Can you rephrase the question?", "Is the data pipeline up to date?"],
    )
