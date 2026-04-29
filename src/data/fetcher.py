"""yfinance data fetcher.

Three public functions:
  get_sp500_constituents()   — scrape ticker universe + metadata from Wikipedia
  fetch_historical_prices()  — batch OHLCV download via yf.download()
  fetch_market_snapshots()   — per-ticker snapshot via yf.Ticker.fast_info

Synchronous by design — runs inside Dagster assets (batch context, not request loop).
Rate limiting and retry logic baked in to respect yfinance's informal limits.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from io import StringIO
from typing import Any

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

LOOKBACK_YEARS = int(os.getenv("SCOUTER_LOOKBACK_YEARS", "5"))
BATCH_SIZE_PRICES = int(os.getenv("SCOUTER_BATCH_SIZE_PRICES", "100"))
BATCH_SIZE_SNAPSHOTS = int(os.getenv("SCOUTER_BATCH_SIZE_SNAPSHOTS", "50"))
RATE_LIMIT_DELAY = 0.3  # seconds between batch calls
MAX_RETRIES = 3
RETRY_DELAY = 2.0

_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_WIKIPEDIA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_sp500_constituents() -> pd.DataFrame:
    """Scrape S&P 500 constituent list from Wikipedia.

    Returns a DataFrame with one row per ticker including sector and industry
    metadata. Used to populate the raw ``companies`` table.

    Returns:
        DataFrame with columns: symbol, company_name, sector, industry,
        exchange, long_name, market_cap, last_updated.

    Raises:
        RuntimeError: If Wikipedia cannot be reached or the table is not found.
    """
    logger.info("Fetching S&P 500 constituent list from Wikipedia")
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                _WIKIPEDIA_URL,
                headers=_WIKIPEDIA_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            tables = pd.read_html(StringIO(resp.text))
            break
        except Exception as exc:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Failed to fetch S&P 500 constituents after {MAX_RETRIES} attempts: {exc}"
                ) from exc
            logger.warning("Wikipedia fetch attempt %d failed: %s — retrying", attempt + 1, exc)
            time.sleep(RETRY_DELAY)

    raw = tables[0]

    # Wikipedia columns: Symbol, Security, GICS Sector, GICS Sub-Industry, ...
    constituents = pd.DataFrame(
        {
            "symbol": raw["Symbol"].str.upper().str.strip(),
            "long_name": raw["Security"],
            "sector": raw["GICS Sector"],
            "industry": raw["GICS Sub-Industry"],
            # Exchange not in Wikipedia table — filled by yfinance info later
            "exchange": None,
            "market_cap": None,
            "last_updated": datetime.now(),
        }
    )

    logger.info("Found %d S&P 500 constituents", len(constituents))
    return constituents


def fetch_historical_prices(
    tickers: list[str],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> pd.DataFrame:
    """Batch-download daily OHLCV data for a list of tickers.

    Uses ``yf.download()`` in batches of BATCH_SIZE_PRICES to avoid timeouts.
    Tickers that return no data are skipped with a warning.

    Args:
        tickers: List of ticker symbols.
        start_date: Start of history window. Defaults to LOOKBACK_YEARS ago.
        end_date: End of history window. Defaults to today.

    Returns:
        DataFrame with columns: symbol, date, open, high, low, close,
        volume, last_updated. Sorted by symbol, date.
    """
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=365 * LOOKBACK_YEARS)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    logger.info(
        "Downloading historical prices for %d tickers from %s to %s",
        len(tickers),
        start_str,
        end_str,
    )

    all_frames: list[pd.DataFrame] = []
    batches = _batched(tickers, BATCH_SIZE_PRICES)
    failed: list[str] = []

    for i, batch in enumerate(batches):
        logger.info(
            "Downloading batch %d/%d (%d tickers)",
            i + 1,
            -(-len(tickers) // BATCH_SIZE_PRICES),
            len(batch),
        )
        for attempt in range(MAX_RETRIES):
            try:
                raw = yf.download(
                    batch,
                    start=start_str,
                    end=end_str,
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                break
            except Exception as exc:
                if attempt == MAX_RETRIES - 1:
                    logger.error("Batch %d failed after %d retries: %s", i + 1, MAX_RETRIES, exc)
                    failed.extend(batch)
                    raw = pd.DataFrame()
                else:
                    logger.warning(
                        "Batch %d attempt %d failed: %s — retrying", i + 1, attempt + 1, exc
                    )
                    time.sleep(RETRY_DELAY * (attempt + 1))

        if raw.empty:
            continue

        # Reshape MultiIndex (field, ticker) → long format
        long = raw.stack(level=1, future_stack=True).reset_index()
        long.columns = [c.lower() for c in long.columns]
        long = long.rename(columns={"price": "date", "ticker": "symbol"})

        # Normalise date to date only (remove time component)
        long["date"] = pd.to_datetime(long["date"]).dt.date
        long["last_updated"] = datetime.now()

        all_frames.append(
            long[["symbol", "date", "open", "high", "low", "close", "volume", "last_updated"]]
        )
        time.sleep(RATE_LIMIT_DELAY)

    if failed:
        logger.warning("Failed to download %d tickers: %s", len(failed), failed)

    if not all_frames:
        return pd.DataFrame(
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "last_updated"]
        )

    result = pd.concat(all_frames, ignore_index=True)
    result = result.dropna(subset=["close"])
    result = result[result["close"] > 0]
    result = result.sort_values(["symbol", "date"])

    logger.info(
        "Downloaded %d rows of price data across %d tickers",
        len(result),
        result["symbol"].nunique(),
    )
    return result


def fetch_market_snapshots(tickers: list[str]) -> pd.DataFrame:
    """Fetch current market snapshot for each ticker via yf.Ticker.fast_info.

    Calls are made individually (no batch API for snapshots) with rate limiting.
    Tickers that fail are skipped with a warning.

    Args:
        tickers: List of ticker symbols.

    Returns:
        DataFrame with columns: symbol, current_price, day_high, day_low,
        volume, market_cap, week_52_high, week_52_low, last_updated.
    """
    logger.info("Fetching market snapshots for %d tickers", len(tickers))
    rows: list[dict[str, Any]] = []
    failed: list[str] = []

    for i, symbol in enumerate(tickers):
        if i > 0 and i % BATCH_SIZE_SNAPSHOTS == 0:
            logger.info("Snapshots progress: %d/%d", i, len(tickers))
            time.sleep(RATE_LIMIT_DELAY * 2)

        try:
            fi = yf.Ticker(symbol).fast_info
            rows.append(
                {
                    "symbol": symbol,
                    "current_price": _safe_float(fi.last_price),
                    "day_high": _safe_float(fi.day_high),
                    "day_low": _safe_float(fi.day_low),
                    "volume": _safe_int(fi.last_volume),
                    "market_cap": _safe_float(fi.market_cap),
                    "week_52_high": _safe_float(fi.year_high),
                    "week_52_low": _safe_float(fi.year_low),
                    "last_updated": datetime.now(),
                }
            )
            time.sleep(RATE_LIMIT_DELAY)
        except Exception as exc:
            logger.warning("Snapshot failed for %s: %s", symbol, exc)
            failed.append(symbol)

    if failed:
        logger.warning("Failed snapshots for %d tickers: %s", len(failed), failed[:10])

    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "current_price",
                "day_high",
                "day_low",
                "volume",
                "market_cap",
                "week_52_high",
                "week_52_low",
                "last_updated",
            ]
        )

    result = pd.DataFrame(rows)
    result = result.dropna(subset=["current_price"])
    result = result[result["current_price"] > 0]
    logger.info("Fetched %d snapshots", len(result))
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _batched(items: list[str], size: int) -> list[list[str]]:
    """Split a list into chunks of at most ``size``."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _safe_float(value: object) -> float | None:
    """Return float or None for missing/invalid values."""
    try:
        v = float(value)  # type: ignore[arg-type]
        return v if v == v else None  # NaN check
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    """Return int or None for missing/invalid values."""
    try:
        return int(value)  # type: ignore[no-any-return, call-overload]
    except (TypeError, ValueError):
        return None
