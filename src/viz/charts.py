"""Plotly chart builders keyed to ChartSpec.chart_type.

Each builder returns a go.Figure. build_chart() is the single public entry point —
it validates column references and dispatches to the right builder, returning None
on any failure so callers can degrade gracefully without crashing.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.models.response import ChartSpec

logger = logging.getLogger(__name__)

_VALID_TYPES = frozenset({"line", "bar", "scatter", "area", "histogram"})


def build_chart(spec: ChartSpec, df: pd.DataFrame) -> go.Figure | None:
    """Build a Plotly figure from a ChartSpec and DataFrame.

    Validates all column references before building. Returns None (rather than
    raising) so the caller can render prose-only when the chart is unavailable.

    Args:
        spec: Chart specification produced by the narrative agent.
        df: DataFrame containing the query result.

    Returns:
        Plotly Figure, or None if the spec is invalid or the build fails.
    """
    if spec.chart_type not in _VALID_TYPES:
        logger.warning("Unsupported chart type: %r", spec.chart_type)
        return None

    col_set = set(df.columns)
    required = {spec.x_col}
    if spec.chart_type != "histogram":
        if isinstance(spec.y_col, str):
            required.add(spec.y_col)
        else:
            required.update(spec.y_col)

    missing = required - col_set
    if missing:
        logger.warning("Chart columns not in DataFrame: %s", missing)
        return None

    color_col = spec.color_col if spec.color_col in col_set else None

    # Guard: line charts with multiple entities must use color or they draw a single
    # zigzag line through all data points. Auto-apply ticker/company_name if not set.
    if spec.chart_type == "line" and color_col is None:
        for candidate in ("ticker", "company_name", "sector"):
            if candidate in col_set and df[candidate].nunique() > 1:
                color_col = candidate
                logger.debug("Auto-applied color_col=%r for multi-entity line chart", color_col)
                break

    try:
        return _BUILDERS[spec.chart_type](spec, df, color_col)
    except Exception as exc:
        logger.warning("Chart build failed for type %r: %s", spec.chart_type, exc)
        return None


def _build_line(spec: ChartSpec, df: pd.DataFrame, color_col: str | None) -> go.Figure:
    return px.line(df, x=spec.x_col, y=spec.y_col, color=color_col, title=spec.title)


def _build_bar(spec: ChartSpec, df: pd.DataFrame, color_col: str | None) -> go.Figure:
    return px.bar(df, x=spec.x_col, y=spec.y_col, color=color_col, title=spec.title)


def _build_scatter(spec: ChartSpec, df: pd.DataFrame, color_col: str | None) -> go.Figure:
    return px.scatter(df, x=spec.x_col, y=spec.y_col, color=color_col, title=spec.title)


def _build_area(spec: ChartSpec, df: pd.DataFrame, color_col: str | None) -> go.Figure:
    return px.area(df, x=spec.x_col, y=spec.y_col, color=color_col, title=spec.title)


def _build_histogram(spec: ChartSpec, df: pd.DataFrame, color_col: str | None) -> go.Figure:
    return px.histogram(df, x=spec.x_col, color=color_col, title=spec.title)


_BUILDERS: dict[str, Any] = {
    "line": _build_line,
    "bar": _build_bar,
    "scatter": _build_scatter,
    "area": _build_area,
    "histogram": _build_histogram,
}
