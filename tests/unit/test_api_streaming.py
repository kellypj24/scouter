"""Unit tests for api/streaming.py."""

import json
from datetime import date, datetime

import pandas as pd

from api.streaming import serialize_block
from src.models.response import ChartSpec, NarrativeBlock, QueryResult

_DEFAULT_CHART = ChartSpec(chart_type="bar", x_col="ticker", y_col="ytd_return", title="Top")
_DEFAULT_DATA = pd.DataFrame({"ticker": ["AAPL", "MSFT"], "ytd_return": [0.15, 0.12]})


def _make_block(
    data: pd.DataFrame = _DEFAULT_DATA,
    chart_spec: ChartSpec | None = _DEFAULT_CHART,
) -> NarrativeBlock:
    return NarrativeBlock(
        question="Which stocks performed best?",
        query_result=QueryResult(sql="SELECT 1", row_count=2, columns=["ticker", "ytd_return"]),
        data=data,
        chart_spec=chart_spec,
        prose="AAPL and MSFT led YTD.",
        follow_ups=["What about tech sector?"],
    )


class TestSerializeBlock:
    def test_returns_valid_json(self):
        result = json.loads(serialize_block(_make_block()))
        assert isinstance(result, dict)

    def test_includes_all_top_level_keys(self):
        result = json.loads(serialize_block(_make_block()))
        assert set(result.keys()) == {
            "question",
            "query_result",
            "data",
            "chart_spec",
            "prose",
            "follow_ups",
        }

    def test_data_serialized_as_records(self):
        data = pd.DataFrame({"ticker": ["AAPL"], "ytd_return": [0.15]})
        result = json.loads(serialize_block(_make_block(data=data)))
        assert result["data"] == [{"ticker": "AAPL", "ytd_return": 0.15}]

    def test_empty_dataframe_serializes_as_empty_list(self):
        result = json.loads(serialize_block(_make_block(data=pd.DataFrame())))
        assert result["data"] == []

    def test_timestamp_columns_serialize_as_iso_string(self):
        data = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-15"), pd.Timestamp("2024-01-16")],
                "close": [150.0, 151.5],
            }
        )
        result = json.loads(serialize_block(_make_block(data=data)))
        assert result["data"][0]["date"] == "2024-01-15T00:00:00"
        assert result["data"][1]["date"] == "2024-01-16T00:00:00"

    def test_datetime_columns_serialize_as_iso_string(self):
        data = pd.DataFrame(
            {
                "ts": pd.array([datetime(2024, 3, 1, 9, 30, 0)], dtype=object),
                "value": [42.0],
            }
        )
        result = json.loads(serialize_block(_make_block(data=data)))
        assert result["data"][0]["ts"] == "2024-03-01T09:30:00"

    def test_date_columns_serialize_as_iso_string(self):
        data = pd.DataFrame(
            {
                "d": pd.array([date(2024, 6, 1)], dtype=object),
                "v": [1.0],
            }
        )
        result = json.loads(serialize_block(_make_block(data=data)))
        assert result["data"][0]["d"] == "2024-06-01"

    def test_no_chart_spec_serializes_as_null(self):
        result = json.loads(serialize_block(_make_block(chart_spec=None)))
        assert result["chart_spec"] is None

    def test_chart_spec_serialized_when_present(self):
        spec = ChartSpec(chart_type="line", x_col="date", y_col="close", title="Price")
        result = json.loads(serialize_block(_make_block(chart_spec=spec)))
        assert result["chart_spec"]["chart_type"] == "line"
        assert result["chart_spec"]["x_col"] == "date"
        assert result["chart_spec"]["y_col"] == "close"

    def test_question_and_prose_preserved(self):
        block = _make_block()
        result = json.loads(serialize_block(block))
        assert result["question"] == block.question
        assert result["prose"] == block.prose
        assert result["follow_ups"] == block.follow_ups

    def test_query_result_fields_present(self):
        result = json.loads(serialize_block(_make_block()))
        qr = result["query_result"]
        assert "sql" in qr
        assert "row_count" in qr
        assert "columns" in qr
