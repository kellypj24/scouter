"""Async news fetcher using yfinance.

Runs yfinance calls in a thread pool so the agent's async event loop is never
blocked. Returns empty results on any failure so callers always proceed.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

_DEFAULT_MAX_AGE_DAYS = 7
_DEFAULT_MAX_PER_TICKER = 3
_FETCH_TIMEOUT_SECONDS = 5.0


@dataclass
class NewsItem:
    """A single news headline for a ticker."""

    ticker: str
    title: str
    summary: str
    publisher: str
    published_at: datetime


def _parse_raw(ticker: str, raw: list[dict[str, Any]], cutoff: datetime, limit: int) -> list[NewsItem]:
    """Parse the yfinance news list into NewsItem objects.

    Handles both the legacy flat format (providerPublishTime as int) and the
    current nested format (content.pubDate as ISO string).
    """
    items: list[NewsItem] = []
    for entry in raw or []:
        content = entry.get("content") or entry
        title = (content.get("title") or "").strip()
        if not title:
            continue

        pub_raw = content.get("pubDate") or content.get("providerPublishTime") or ""
        try:
            if isinstance(pub_raw, (int, float)):
                pub_date = datetime.fromtimestamp(pub_raw, tz=UTC)
            else:
                pub_date = datetime.fromisoformat(str(pub_raw).replace("Z", "+00:00"))
        except (ValueError, AttributeError, OSError):
            pub_date = datetime.now(tz=UTC)

        if pub_date < cutoff:
            continue

        provider = content.get("provider") or {}
        publisher = (provider.get("displayName") or content.get("publisher") or "").strip()

        raw_summary = content.get("summary") or content.get("description") or ""
        summary = re.sub(r"<[^>]+>", "", raw_summary).strip()

        items.append(
            NewsItem(
                ticker=ticker,
                title=title,
                summary=summary[:200],
                publisher=publisher,
                published_at=pub_date,
            )
        )
        if len(items) >= limit:
            break
    return items


async def fetch_news(
    tickers: list[str],
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    max_per_ticker: int = _DEFAULT_MAX_PER_TICKER,
) -> list[NewsItem]:
    """Fetch recent news headlines for a list of tickers.

    Args:
        tickers: Ticker symbols to fetch news for.
        max_age_days: Ignore headlines older than this many days.
        max_per_ticker: Maximum headlines to return per ticker.

    Returns:
        Flat list of NewsItem ordered by ticker input order, most recent first.
        Returns [] on any failure so callers can always proceed without news.
    """
    if not tickers:
        return []

    cutoff = datetime.now(tz=UTC) - timedelta(days=max_age_days)
    loop = asyncio.get_running_loop()

    async def _one(ticker: str) -> list[NewsItem]:
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: yf.Ticker(ticker).news),
                timeout=_FETCH_TIMEOUT_SECONDS,
            )
            return _parse_raw(ticker, raw or [], cutoff, max_per_ticker)
        except Exception as exc:
            logger.debug("News fetch failed for %s: %s", ticker, exc)
            return []

    batches = await asyncio.gather(*[_one(t) for t in tickers], return_exceptions=True)
    return [item for batch in batches if isinstance(batch, list) for item in batch]
