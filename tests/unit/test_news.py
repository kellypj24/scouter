"""Unit tests for src/data/news.py."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from src.data.news import _parse_raw, fetch_news


def _ts(days_ago: int = 1) -> str:
    """Return an ISO timestamp N days ago."""
    return (datetime.now(tz=UTC) - timedelta(days=days_ago)).isoformat()


_SAMPLE_ENTRY = {
    "content": {
        "title": "Apple beats Q2 earnings estimates",
        "summary": "Apple reported Q2 earnings that beat analyst estimates across the board.",
        "pubDate": _ts(1),
        "provider": {"displayName": "Reuters"},
    }
}

_LEGACY_ENTRY = {
    "title": "Apple Q1 results",
    "providerPublishTime": (datetime.now(tz=UTC) - timedelta(days=2)).timestamp(),
    "publisher": "Bloomberg",
    "summary": "Legacy format without nested content.",
}


class TestParseRaw:
    def test_parses_new_format(self):
        cutoff = datetime.now(tz=UTC) - timedelta(days=7)
        items = _parse_raw("AAPL", [_SAMPLE_ENTRY], cutoff, limit=5)
        assert len(items) == 1
        assert items[0].title == "Apple beats Q2 earnings estimates"
        assert items[0].publisher == "Reuters"
        assert items[0].ticker == "AAPL"

    def test_parses_legacy_format(self):
        cutoff = datetime.now(tz=UTC) - timedelta(days=7)
        items = _parse_raw("AAPL", [_LEGACY_ENTRY], cutoff, limit=5)
        assert len(items) == 1
        assert items[0].title == "Apple Q1 results"
        assert items[0].publisher == "Bloomberg"

    def test_filters_old_news(self):
        cutoff = datetime.now(tz=UTC) - timedelta(days=1)
        old_entry = {
            "content": {
                "title": "Old news",
                "pubDate": _ts(5),  # 5 days ago, beyond 1-day cutoff
                "provider": {},
            }
        }
        items = _parse_raw("AAPL", [old_entry], cutoff, limit=5)
        assert items == []

    def test_respects_limit(self):
        cutoff = datetime.now(tz=UTC) - timedelta(days=7)
        items = _parse_raw("AAPL", [_SAMPLE_ENTRY, _SAMPLE_ENTRY, _SAMPLE_ENTRY], cutoff, limit=2)
        assert len(items) == 2

    def test_skips_entries_without_title(self):
        cutoff = datetime.now(tz=UTC) - timedelta(days=7)
        no_title = {"content": {"pubDate": _ts(1), "provider": {}}}
        items = _parse_raw("AAPL", [no_title], cutoff, limit=5)
        assert items == []

    def test_strips_html_from_summary(self):
        cutoff = datetime.now(tz=UTC) - timedelta(days=7)
        html_entry = {
            "content": {
                "title": "Test",
                "summary": "<p>Apple reported <b>strong</b> results.</p>",
                "pubDate": _ts(1),
                "provider": {},
            }
        }
        items = _parse_raw("AAPL", [html_entry], cutoff, limit=5)
        assert "<" not in items[0].summary
        assert "Apple reported strong results." in items[0].summary


class TestFetchNews:
    async def test_returns_empty_for_no_tickers(self):
        result = await fetch_news([])
        assert result == []

    async def test_fetches_and_parses_news(self):
        mock_ticker = MagicMock()
        mock_ticker.news = [_SAMPLE_ENTRY]
        with patch("src.data.news.yf.Ticker", return_value=mock_ticker):
            result = await fetch_news(["AAPL"])
        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].title == "Apple beats Q2 earnings estimates"

    async def test_returns_empty_on_network_failure(self):
        mock_ticker = MagicMock()
        mock_ticker.news = property(lambda self: (_ for _ in ()).throw(ConnectionError("timeout")))
        with patch("src.data.news.yf.Ticker", side_effect=ConnectionError("timeout")):
            result = await fetch_news(["AAPL"])
        assert result == []

    async def test_fetches_multiple_tickers_concurrently(self):
        def make_ticker(news_list):
            m = MagicMock()
            m.news = news_list
            return m

        aapl_news = [
            {**_SAMPLE_ENTRY, "content": {**_SAMPLE_ENTRY["content"], "title": "AAPL news"}}
        ]
        msft_news = [
            {**_SAMPLE_ENTRY, "content": {**_SAMPLE_ENTRY["content"], "title": "MSFT news"}}
        ]

        with patch(
            "src.data.news.yf.Ticker", side_effect=[make_ticker(aapl_news), make_ticker(msft_news)]
        ):
            result = await fetch_news(["AAPL", "MSFT"])

        tickers = {item.ticker for item in result}
        assert tickers == {"AAPL", "MSFT"}

    async def test_partial_failure_returns_successful_tickers(self):
        def make_ticker_fail():
            m = MagicMock()
            m.news = property(lambda self: (_ for _ in ()).throw(RuntimeError("fail")))
            return m

        good_ticker = MagicMock()
        good_ticker.news = [_SAMPLE_ENTRY]

        with patch("src.data.news.yf.Ticker", side_effect=[RuntimeError("fail"), good_ticker]):
            result = await fetch_news(["FAIL", "MSFT"])

        assert all(item.ticker == "MSFT" for item in result)
