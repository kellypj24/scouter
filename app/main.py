"""Scouter — Streamlit app.

UI wiring only. Drives the agent harness via the Go gateway HTTP API.
No direct agent imports — all logic lives behind the gateway boundary.

Start the full stack first:  just serve
"""

from __future__ import annotations

import json
import logging
import os

import httpx
import pandas as pd
import streamlit as st

from app.components.block_renderer import render_block
from src.models.agent import AgentRequest, AgentResponse
from src.models.response import ChartSpec, NarrativeBlock, QueryResult

logger = logging.getLogger(__name__)

_GATEWAY_URL = os.getenv("SCOUTER_GATEWAY_URL", "http://localhost:8080")

st.set_page_config(
    page_title="Scouter",
    page_icon="🔭",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Drive the harness via the Go gateway SSE stream.
# Each 'block' event is deserialized into a NarrativeBlock as it arrives,
# so the caller receives results progressively rather than waiting for all.
# Raises RuntimeError if the gateway is unreachable.
# ---------------------------------------------------------------------------


def _run_question(question: str) -> AgentResponse:
    request = AgentRequest(question=question)
    blocks: list[NarrativeBlock] = []

    with (
        httpx.Client(timeout=120.0) as client,
        client.stream("POST", f"{_GATEWAY_URL}/ask", json=request.model_dump()) as resp,
    ):
        resp.raise_for_status()
        event_type: str | None = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:") and event_type == "block":
                d = json.loads(line[5:].strip())
                blocks.append(
                    NarrativeBlock(
                        question=d["question"],
                        query_result=QueryResult(**d["query_result"]),
                        data=pd.DataFrame(d["data"]),
                        chart_spec=ChartSpec(**d["chart_spec"]) if d["chart_spec"] else None,
                        prose=d["prose"],
                        follow_ups=d["follow_ups"],
                    )
                )

    return AgentResponse(blocks=blocks)


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

if "history" not in st.session_state:
    st.session_state.history = []  # list[{"question": str, "response": AgentResponse}]

if "pending_question" not in st.session_state:
    st.session_state.pending_question = None


# ---------------------------------------------------------------------------
# Process any pending question (new input or follow-up click) before rendering
# ---------------------------------------------------------------------------


def _on_follow_up(question: str) -> None:
    st.session_state.pending_question = question
    st.rerun()


if st.session_state.pending_question:
    question: str = st.session_state.pending_question
    st.session_state.pending_question = None
    with st.spinner("Thinking…"):
        try:
            response = _run_question(question)
        except httpx.ConnectError:
            st.error(
                f"Cannot reach the Scouter gateway at {_GATEWAY_URL}. "
                "Run `just serve` to start the API and gateway, "
                "or set SCOUTER_GATEWAY_URL to point at a running instance.",
                icon="🔌",
            )
            st.stop()
    st.session_state.history.append({"question": question, "response": response})


# ---------------------------------------------------------------------------
# Render full conversation history
# ---------------------------------------------------------------------------

st.title("Scouter")
st.caption("It's over 9000. — reads the power level of your data.")

for e_idx, entry in enumerate(st.session_state.history):
    st.chat_message("user").write(entry["question"])
    with st.chat_message("assistant"):
        if entry["response"].fallback_used:
            st.warning(
                "Rule-based fallback query used — LLM was unavailable.",
                icon="⚠️",
            )
        for b_idx, block in enumerate(entry["response"].blocks):
            render_block(block, key_prefix=f"{e_idx}_{b_idx}", on_follow_up=_on_follow_up)
            if b_idx < len(entry["response"].blocks) - 1:
                st.divider()


# ---------------------------------------------------------------------------
# New question input
# ---------------------------------------------------------------------------

if new_question := st.chat_input("Ask a question about your financial data…"):
    st.session_state.pending_question = new_question
    st.rerun()
