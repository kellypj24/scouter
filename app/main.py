"""Scouter — Streamlit app shell.

PoC UI. All agent logic lives in src/. This file is UI wiring only.
"""

import streamlit as st

st.set_page_config(
    page_title="Scouter",
    page_icon="🔭",
    layout="wide",
)

st.title("Scouter")
st.caption("It's over 9000. — reads the power level of your data.")

st.info("Phase 1 in progress. Agent harness not yet connected.")

question = st.chat_input("Ask a question about your financial data...")

if question:
    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        st.write("_(Agent harness coming in Phase 1.)_")
