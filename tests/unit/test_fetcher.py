"""Unit tests for src/data/fetcher.py.

External HTTP and yfinance calls are fully mocked — no network required.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.fetcher import (
    _batched,
    _safe_float,
    _safe_int,
    fetch_historical_prices,
    fetch_market_snapshots,
    get_sp500_constituents,
)

# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestBatched:
    def test_even_split(self):
        assert _batched([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_uneven_split(self):
        assert _batched([1, 2, 3], 2) == [[1, 2], [3]]

    def test_empty(self):
        assert _batched([], 10) == []

    def test_batch_larger_than_list(self):
        assert _batched([1, 2], 10) == [[1, 2]]


class TestSafeFloat:
    def test_valid(self):
        assert _safe_float(1.5) == pytest.approx(1.5)

    def test_string_number(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_non_numeric_string(self):
        assert _safe_float("abc") is None


class TestSafeInt:
    def test_valid(self):
        assert _safe_int(42) == 42

    def test_float_truncates(self):
        assert _safe_int(3.9) == 3

    def test_none(self):
        assert _safe_int(None) is None

    def test_string(self):
        assert _safe_int("abc") is None


# ---------------------------------------------------------------------------
# get_sp500_constituents
# ---------------------------------------------------------------------------


class TestGetSp500Constituents:
    def _mock_response(self):
        df = pd.DataFrame(
            {
                "Symbol": ["AAPL", "MSFT", "GOOG"],
                "Security": ["Apple Inc.", "Microsoft Corporation", "Alphabet Inc."],
                "GICS Sector": [
                    "Information Technology",
                    "Information Technology",
                    "Communication Services",
                ],
                "GICS Sub-Industry": ["Tech Hardware", "Systems Software", "Interactive Media"],
                "Headquarters Location": ["Cupertino, CA", "Redmond, WA", "Mountain View, CA"],
                "Date added": ["1982-11-30", "1994-06-01", "2006-04-03"],
                "CIK": [320193, 789019, 1652044],
                "Founded": [1976, 1975, 1998],
            }
        )
        mock_resp = MagicMock()
        mock_resp.text = "<html></html>"
        mock_resp.raise_for_status = MagicMock()
        return mock_resp, df

    def test_returns_dataframe_with_expected_columns(self):
        mock_resp, wiki_df = self._mock_response()
        with (
            patch("src.data.fetcher.requests.get", return_value=mock_resp),
            patch("src.data.fetcher.pd.read_html", return_value=[wiki_df]),
        ):
            result = get_sp500_constituents()

        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) >= {"symbol", "long_name", "sector", "industry"}

    def test_symbols_are_uppercased(self):
        mock_resp, wiki_df = self._mock_response()
        wiki_df["Symbol"] = ["aapl", "msft", "goog"]
        with (
            patch("src.data.fetcher.requests.get", return_value=mock_resp),
            patch("src.data.fetcher.pd.read_html", return_value=[wiki_df]),
        ):
            result = get_sp500_constituents()

        assert all(result["symbol"] == result["symbol"].str.upper())

    def test_raises_on_http_failure(self):
        with (
            patch("src.data.fetcher.requests.get", side_effect=Exception("timeout")),
            pytest.raises(RuntimeError, match="Failed to fetch S&P 500"),
        ):
            get_sp500_constituents()

    def test_row_count_matches_source(self):
        mock_resp, wiki_df = self._mock_response()
        with (
            patch("src.data.fetcher.requests.get", return_value=mock_resp),
            patch("src.data.fetcher.pd.read_html", return_value=[wiki_df]),
        ):
            result = get_sp500_constituents()

        assert len(result) == 3


# ---------------------------------------------------------------------------
# fetch_historical_prices
# ---------------------------------------------------------------------------


class TestFetchHistoricalPrices:
    def _make_download_result(self, tickers: list[str]) -> pd.DataFrame:
        """Build a minimal MultiIndex DataFrame like yf.download() returns.

        Explicitly assigns the named MultiIndex to columns after construction
        because pandas loses names when building a DataFrame from a tuple-keyed dict.
        """
        import itertools

        from pandas import MultiIndex

        dates = pd.DatetimeIndex(["2026-01-02", "2026-01-03"], name="Date")
        fields = ["Close", "High", "Low", "Open", "Volume"]
        cols = MultiIndex.from_tuples(
            [(f, t) for f, t in itertools.product(fields, tickers)],
            names=["Price", "Ticker"],
        )
        data = {col: [100.0 + i, 101.0 + i] for i, col in enumerate(cols)}
        df = pd.DataFrame(data, index=dates)
        df.columns = cols  # re-assign to preserve level names
        return df

    def test_returns_expected_columns(self):
        download_result = self._make_download_result(["AAPL"])
        with (
            patch("src.data.fetcher.yf.download", return_value=download_result),
            patch("src.data.fetcher.time.sleep"),
        ):
            result = fetch_historical_prices(["AAPL"])

        assert set(result.columns) >= {"symbol", "date", "open", "high", "low", "close", "volume"}

    def test_drops_null_close(self):
        download_result = self._make_download_result(["AAPL"])
        # Force close to NaN for second row
        download_result[("Close", "AAPL")] = [None, 101.0]
        with (
            patch("src.data.fetcher.yf.download", return_value=download_result),
            patch("src.data.fetcher.time.sleep"),
        ):
            result = fetch_historical_prices(["AAPL"])

        assert result["close"].notna().all()

    def test_returns_empty_df_on_all_failures(self):
        with (
            patch("src.data.fetcher.yf.download", side_effect=Exception("API down")),
            patch("src.data.fetcher.time.sleep"),
        ):
            result = fetch_historical_prices(["AAPL"])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_batches_large_ticker_lists(self):
        tickers = [f"T{i:03d}" for i in range(250)]
        call_args: list = []

        def mock_download(batch, **kwargs):
            call_args.append(len(batch))
            return self._make_download_result(batch[:1])  # return minimal data

        with (
            patch("src.data.fetcher.yf.download", side_effect=mock_download),
            patch("src.data.fetcher.time.sleep"),
        ):
            fetch_historical_prices(tickers)

        # With default batch size 100, should be 3 calls for 250 tickers
        assert len(call_args) == 3
        assert max(call_args) <= 100


# ---------------------------------------------------------------------------
# fetch_market_snapshots
# ---------------------------------------------------------------------------


class TestFetchMarketSnapshots:
    def _mock_fast_info(self, price: float = 150.0) -> MagicMock:
        fi = MagicMock()
        fi.last_price = price
        fi.day_high = price + 2
        fi.day_low = price - 2
        fi.last_volume = 1_000_000
        fi.market_cap = 2_000_000_000_000.0
        fi.year_high = price + 20
        fi.year_low = price - 30
        return fi

    def test_returns_expected_columns(self):
        mock_ticker = MagicMock()
        mock_ticker.fast_info = self._mock_fast_info()
        with (
            patch("src.data.fetcher.yf.Ticker", return_value=mock_ticker),
            patch("src.data.fetcher.time.sleep"),
        ):
            result = fetch_market_snapshots(["AAPL"])

        assert set(result.columns) >= {
            "symbol",
            "current_price",
            "market_cap",
            "week_52_high",
            "week_52_low",
        }

    def test_skips_failed_tickers(self):
        def side_effect(symbol):
            if symbol == "BAD":
                raise ValueError("not found")
            m = MagicMock()
            m.fast_info = self._mock_fast_info()
            return m

        with (
            patch("src.data.fetcher.yf.Ticker", side_effect=side_effect),
            patch("src.data.fetcher.time.sleep"),
        ):
            result = fetch_market_snapshots(["AAPL", "BAD", "MSFT"])

        assert len(result) == 2
        assert "BAD" not in result["symbol"].values

    def test_returns_empty_df_when_all_fail(self):
        with (
            patch("src.data.fetcher.yf.Ticker", side_effect=Exception("down")),
            patch("src.data.fetcher.time.sleep"),
        ):
            result = fetch_market_snapshots(["AAPL"])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_drops_zero_price(self):
        mock_ticker = MagicMock()
        mock_ticker.fast_info = self._mock_fast_info(price=0.0)
        with (
            patch("src.data.fetcher.yf.Ticker", return_value=mock_ticker),
            patch("src.data.fetcher.time.sleep"),
        ):
            result = fetch_market_snapshots(["AAPL"])

        assert len(result) == 0
