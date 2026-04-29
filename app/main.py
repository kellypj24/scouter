"""Scouter — Streamlit app.

UI wiring only. All agent logic lives in src/.
"""

from __future__ import annotations

import asyncio

import streamlit as st

from app.components.block_renderer import render_block
from src.agent.narrative_agent import NarrativeAgent
from src.agent.orchestrator import Orchestrator
from src.agent.providers.base import get_provider
from src.agent.query_agent import QueryAgent
from src.data.db import get_read_connection
from src.models.agent import AgentRequest, AgentResponse

st.set_page_config(
    page_title="Scouter",
    page_icon="🔭",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Orchestrator — built once per session, cached in session state
# ---------------------------------------------------------------------------


def _build_orchestrator() -> Orchestrator:
    provider = get_provider()
    conn = get_read_connection()
    return Orchestrator(
        provider=provider,
        query_agent=QueryAgent(provider=provider, conn=conn),
        narrative_agent=NarrativeAgent(provider=provider),
    )


def _get_orchestrator() -> Orchestrator:
    if "orchestrator" not in st.session_state:
        st.session_state.orchestrator = _build_orchestrator()
    return st.session_state.orchestrator  # type: ignore[no-any-return]


def _run_question(question: str) -> AgentResponse:
    orchestrator = _get_orchestrator()
    return asyncio.run(orchestrator.run(AgentRequest(question=question)))


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
        response = _run_question(question)
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
