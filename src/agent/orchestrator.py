"""Orchestrator: decomposes a question and drives the query + narrative pipeline.

Responsibilities:
  1. Decompose the user's question into ≤ max_blocks focused sub-questions.
  2. For each sub-question: run QueryAgent → NarrativeAgent → NarrativeBlock.
  3. Return an AgentResponse with all blocks and a fallback flag.
  4. Degrade gracefully at every layer — never surface a raw error to the caller.
"""

from __future__ import annotations

import logging
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

        fallback_used = any(b.query_result.sql == _FALLBACK_SQL for b in blocks)
        return AgentResponse(blocks=blocks, fallback_used=fallback_used)

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
