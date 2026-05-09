"""Unit tests for src/models/request_state.py."""

import time

from src.models.agent import DomainClassification
from src.models.request_state import RequestState


def _make_classification(domains=None, confidence=0.85) -> DomainClassification:
    return DomainClassification(domains=domains, confidence=confidence)


class TestRequestState:
    def test_domain_str_with_domains(self):
        state = RequestState(
            request_id="req-1",
            original_question="Q",
            classification=_make_classification(domains=["core", "equity"]),
        )
        assert state.domain_str == "core,equity"

    def test_domain_str_no_match(self):
        state = RequestState(
            request_id="req-1",
            original_question="Q",
            classification=_make_classification(domains=None),
        )
        assert state.domain_str == "all"

    def test_sub_questions_defaults_empty(self):
        state = RequestState(
            request_id="req-1",
            original_question="Q",
            classification=_make_classification(),
        )
        assert state.sub_questions == []

    def test_t0_set_automatically(self):
        before = time.perf_counter()
        state = RequestState(
            request_id="req-1",
            original_question="Q",
            classification=_make_classification(),
        )
        after = time.perf_counter()
        assert before <= state.t0 <= after

    def test_elapsed_ms_non_negative(self):
        state = RequestState(
            request_id="req-1",
            original_question="Q",
            classification=_make_classification(),
        )
        assert state.elapsed_ms >= 0

    def test_sub_questions_mutable(self):
        state = RequestState(
            request_id="req-1",
            original_question="Q",
            classification=_make_classification(),
        )
        state.sub_questions = ["Q1", "Q2"]
        assert state.sub_questions == ["Q1", "Q2"]

    def test_fields_stored_correctly(self):
        clf = _make_classification(domains=["core", "risk"], confidence=0.7)
        state = RequestState(
            request_id="abc-123",
            original_question="What is volatility?",
            classification=clf,
        )
        assert state.request_id == "abc-123"
        assert state.original_question == "What is volatility?"
        assert state.classification is clf
