"""Async-safe observability logger backed by SQLite.

Design:
  - All SQLite writes are synchronous (sqlite3 stdlib) but dispatched via
    asyncio.to_thread so the event loop is never blocked.
  - Each write creates and immediately closes its own connection — safe for
    concurrent async tasks writing to the same WAL-mode database.
  - Every public method swallows exceptions: logging must never break the pipeline.
  - The request_id is read from the contextvars set by FastAPI middleware, so
    callers don't need to thread it through manually.

Storage layout (SQLite):
  requests  — one row per request (question, domain, timing, outcome)
  spans     — one row per pipeline stage per request (sql_gen, sql_exec,
              narrative, news) with per-stage latency and metadata
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.observability.context import request_id_var

logger = logging.getLogger(__name__)

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS requests (
    request_id  TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    domain      TEXT,
    started_at  TEXT NOT NULL,
    completed_at TEXT,
    latency_ms  INTEGER,
    block_count INTEGER,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS spans (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id         TEXT    NOT NULL,
    stage              TEXT    NOT NULL,
    attempt            INTEGER NOT NULL DEFAULT 1,
    started_at         TEXT    NOT NULL,
    latency_ms         INTEGER,
    success            INTEGER NOT NULL DEFAULT 1,
    error              TEXT,
    sql_length         INTEGER,
    row_count          INTEGER,
    chart_source       TEXT,
    news_items         INTEGER,
    domain             TEXT,
    sub_question_count INTEGER
);
"""

_DEFAULT_DB = Path(os.getenv("SCOUTER_LOGS_DB", "logs/scouter_logs.db"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ObservabilityLogger:
    """Append-only telemetry writer.

    Args:
        db_path: Path to the SQLite database file. Created on first use.
    """

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        self._db_path = db_path
        self._enabled = self._setup()

    def _setup(self) -> bool:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                conn.executescript(_DDL)
            self._migrate_schema()
            return True
        except Exception as exc:
            logger.warning("Observability logging disabled — could not initialise db: %s", exc)
            return False

    def _migrate_schema(self) -> None:
        """Add columns introduced after the initial schema was created."""
        with self._connect() as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(spans)")}
            if "sub_question_count" not in existing:
                conn.execute("ALTER TABLE spans ADD COLUMN sub_question_count INTEGER")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    # ------------------------------------------------------------------
    # Synchronous write helpers (run in thread pool)
    # ------------------------------------------------------------------

    def _sync_start_request(self, request_id: str, question: str, domain: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO requests (request_id, question, domain, started_at)"
                " VALUES (?, ?, ?, ?)",
                (request_id, question, domain, _now()),
            )

    def _sync_finish_request(
        self,
        request_id: str,
        block_count: int,
        fallback_used: bool,
        latency_ms: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE requests"
                " SET completed_at = ?, latency_ms = ?, block_count = ?, fallback_used = ?"
                " WHERE request_id = ?",
                (_now(), latency_ms, block_count, int(fallback_used), request_id),
            )

    def _sync_write_span(
        self,
        request_id: str,
        stage: str,
        latency_ms: int,
        success: bool,
        attempt: int,
        metadata: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO spans"
                " (request_id, stage, attempt, started_at, latency_ms, success,"
                "  error, sql_length, row_count, chart_source, news_items, domain,"
                "  sub_question_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    stage,
                    attempt,
                    _now(),
                    latency_ms,
                    int(success),
                    metadata.get("error"),
                    metadata.get("sql_length"),
                    metadata.get("row_count"),
                    metadata.get("chart_source"),
                    metadata.get("news_items"),
                    metadata.get("domain"),
                    metadata.get("sub_question_count"),
                ),
            )

    # ------------------------------------------------------------------
    # Public async API — fire-and-forget, never raise
    # ------------------------------------------------------------------

    async def start_request(
        self,
        request_id: str,
        question: str,
        domain: str | None = None,
    ) -> None:
        """Record a new request. Should be called at the start of orchestrator.run/stream."""
        if not self._enabled or not request_id:
            return
        with contextlib.suppress(Exception):
            asyncio.create_task(
                asyncio.to_thread(self._sync_start_request, request_id, question, domain)
            )

    async def finish_request(
        self,
        request_id: str,
        block_count: int,
        fallback_used: bool,
        latency_ms: int,
    ) -> None:
        """Update the request row with completion data."""
        if not self._enabled or not request_id:
            return
        with contextlib.suppress(Exception):
            asyncio.create_task(
                asyncio.to_thread(
                    self._sync_finish_request,
                    request_id,
                    block_count,
                    fallback_used,
                    latency_ms,
                )
            )

    async def log_span(
        self,
        stage: str,
        latency_ms: int,
        *,
        success: bool = True,
        attempt: int = 1,
        **metadata: Any,
    ) -> None:
        """Record a pipeline stage span. Reads request_id from contextvar automatically.

        Args:
            stage: Stage name — sql_gen | sql_exec | narrative | news | decompose.
            latency_ms: Wall-clock duration of the stage in milliseconds.
            success: Whether the stage completed without error.
            attempt: Retry attempt number (1-indexed).
            **metadata: Optional fields — error, sql_length, row_count,
                chart_source (llm|inferred|none), news_items, domain,
                sub_question_count (decompose stage only).
        """
        if not self._enabled:
            return
        with contextlib.suppress(Exception):
            rid = request_id_var.get()
            if not rid:
                return
            asyncio.create_task(
                asyncio.to_thread(
                    self._sync_write_span,
                    rid,
                    stage,
                    latency_ms,
                    success,
                    attempt,
                    metadata,
                )
            )


_obs_logger: ObservabilityLogger | None = None


def get_obs_logger() -> ObservabilityLogger:
    """Return the process-wide ObservabilityLogger singleton.

    Initialised lazily on first call. Path from SCOUTER_LOGS_DB env var,
    defaulting to logs/scouter_logs.db relative to the working directory.
    """
    global _obs_logger
    if _obs_logger is None:
        db_path = Path(os.getenv("SCOUTER_LOGS_DB", "logs/scouter_logs.db"))
        _obs_logger = ObservabilityLogger(db_path=db_path)
    return _obs_logger
