"""Unit tests for src/viz/charts.py."""

import pandas as pd
import plotly.graph_objects as go
import pytest

from src.models.response import ChartSpec
from src.viz.charts import build_chart


@pytest.fixture
def time_df():
    return pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "close": [150.0, 152.5, 151.0],
            "sector": ["Tech", "Tech", "Tech"],
        }
    )


@pytest.fixture
def category_df():
    return pd.DataFrame(
        {
            "sector": ["Tech", "Finance", "Energy"],
            "ytd_return": [0.25, 0.10, 0.05],
            "volatility": [0.30, 0.20, 0.15],
        }
    )


def _spec(**kwargs) -> ChartSpec:
    defaults = dict(
        chart_type="bar",
        x_col="sector",
        y_col="ytd_return",
        title="Sector Returns",
    )
    defaults.update(kwargs)
    return ChartSpec(**defaults)


class TestBuildChart:
    def test_returns_figure(self, category_df):
        fig = build_chart(_spec(), category_df)
        assert isinstance(fig, go.Figure)

    def test_unsupported_type_returns_none(self, category_df):
        fig = build_chart(_spec(chart_type="pie"), category_df)
        assert fig is None

    def test_missing_x_col_returns_none(self, category_df):
        fig = build_chart(_spec(x_col="nonexistent"), category_df)
        assert fig is None

    def test_missing_y_col_returns_none(self, category_df):
        fig = build_chart(_spec(y_col="nonexistent"), category_df)
        assert fig is None

    def test_invalid_color_col_is_ignored(self, category_df):
        fig = build_chart(_spec(color_col="bad_col"), category_df)
        assert isinstance(fig, go.Figure)

    def test_valid_color_col_accepted(self, category_df):
        df = category_df.copy()
        df["group"] = ["A", "B", "A"]
        fig = build_chart(_spec(color_col="group"), df)
        assert isinstance(fig, go.Figure)


class TestLineChart:
    def test_builds_figure(self, time_df):
        fig = build_chart(_spec(chart_type="line", x_col="date", y_col="close"), time_df)
        assert isinstance(fig, go.Figure)

    def test_with_color(self, time_df):
        fig = build_chart(
            _spec(chart_type="line", x_col="date", y_col="close", color_col="sector"),
            time_df,
        )
        assert isinstance(fig, go.Figure)


class TestBarChart:
    def test_builds_figure(self, category_df):
        fig = build_chart(_spec(chart_type="bar"), category_df)
        assert isinstance(fig, go.Figure)


class TestScatterChart:
    def test_builds_figure(self, category_df):
        fig = build_chart(
            _spec(chart_type="scatter", x_col="ytd_return", y_col="volatility"),
            category_df,
        )
        assert isinstance(fig, go.Figure)


class TestAreaChart:
    def test_builds_figure(self, time_df):
        fig = build_chart(_spec(chart_type="area", x_col="date", y_col="close"), time_df)
        assert isinstance(fig, go.Figure)


class TestHistogram:
    def test_builds_figure(self, category_df):
        # Histogram only needs x_col — y_col is unused but required by ChartSpec
        fig = build_chart(
            _spec(chart_type="histogram", x_col="ytd_return", y_col="ytd_return"),
            category_df,
        )
        assert isinstance(fig, go.Figure)

    def test_missing_x_col_returns_none(self, category_df):
        fig = build_chart(
            _spec(chart_type="histogram", x_col="missing", y_col="ytd_return"),
            category_df,
        )
        assert fig is None
