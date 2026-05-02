# src/viz/ — Chart Builders

Plotly chart construction keyed to `ChartSpec`. No data fetching or LLM calls.

## charts.py

`build_chart(spec: ChartSpec, data: pd.DataFrame) -> go.Figure | None`

Takes a `ChartSpec` (type + x_col + y_col + optional groupby) and a DataFrame and returns a Plotly figure. Returns `None` if the spec can't be satisfied by the data (e.g. column doesn't exist).

## Chart types

Chart type is determined by `NarrativeAgent` during LLM inference — it picks from the `ChartType` enum based on the shape of the data. The viz layer just renders; it doesn't decide what to draw.

## Adding a chart type

1. Add the type to the `ChartType` enum in `src/models/response.py`
2. Add a builder branch in `charts.py`
3. Update the narrative prompt in `src/agent/prompts/narrative.py` so the LLM knows the new type exists
