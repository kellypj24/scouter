"""Pydantic response models — the atomic unit of a Scouter response.

Every agent response is a list of NarrativeBlocks. Never a raw string.
"""

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field


class ChartSpec(BaseModel):
    """Specification for a Plotly chart, produced by the narrative agent.

    Attributes:
        chart_type: One of 'line', 'bar', 'scatter', 'area', 'histogram'.
        x_col: Column name for the x-axis.
        y_col: Column name (or list) for the y-axis.
        title: Chart title.
        annotations: Optional list of point annotations {x, y, text}.
        color_col: Optional column to use for color grouping.
    """

    chart_type: str
    x_col: str
    y_col: str | list[str]
    title: str
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    color_col: str | None = None


class QueryResult(BaseModel):
    """Result of a SQL query executed against DuckDB.

    Attributes:
        sql: The exact SQL that was executed.
        row_count: Number of rows returned.
        columns: Column names in result order.
    """

    sql: str
    row_count: int
    columns: list[str]

    model_config = {"arbitrary_types_allowed": True}


class NarrativeBlock(BaseModel):
    """Atomic unit of a Scouter response.

    Each block corresponds to one question → query → chart → prose cycle.
    A full agent response is a list of NarrativeBlocks.

    Attributes:
        question: The sub-question this block answers.
        query_result: SQL and metadata from DuckDB execution.
        data: The actual query result as a DataFrame.
        chart_spec: Visualization specification (may be None if data not chartable).
        prose: Plain-English interpretation of the data.
        follow_ups: Suggested follow-up questions to continue the narrative.
    """

    question: str
    query_result: QueryResult
    data: Any  # pd.DataFrame — arbitrary_types_allowed
    chart_spec: ChartSpec | None = None
    prose: str
    follow_ups: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}
