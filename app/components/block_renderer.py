"""NarrativeBlock renderer for Streamlit."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from src.models.response import NarrativeBlock
from src.viz.charts import build_chart


def render_block(
    block: NarrativeBlock,
    key_prefix: str,
    on_follow_up: Callable[[str], None],
) -> None:
    """Render a single NarrativeBlock: prose, chart, SQL, and follow-up buttons.

    Args:
        block: The NarrativeBlock to render.
        key_prefix: Unique prefix for all widget keys in this block (prevents
            key collisions when the same follow-up text appears across blocks).
        on_follow_up: Called with the follow-up question string when a button
            is clicked.
    """
    st.markdown(f"**{block.question}**")
    st.write(block.prose)

    if block.chart_spec is not None:
        fig = build_chart(block.chart_spec, block.data)
        if fig is not None:
            st.plotly_chart(fig, width="stretch")

    with st.expander("SQL", expanded=False):
        st.code(block.query_result.sql, language="sql")
        st.caption(
            f"{block.query_result.row_count} rows · "
            f"columns: {', '.join(block.query_result.columns)}"
        )

    if block.follow_ups:
        st.markdown("**Follow-up questions:**")
        cols = st.columns(len(block.follow_ups))
        for i, (col, follow_up) in enumerate(zip(cols, block.follow_ups, strict=True)):
            with col:
                if st.button(follow_up, key=f"{key_prefix}_fu_{i}"):
                    on_follow_up(follow_up)
