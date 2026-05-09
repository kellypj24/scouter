"""Request-scoped state object for the orchestrator pipeline.

Carries the fields that are created at the start of a request and referenced
across multiple orchestrator methods, replacing scattered local variables.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.models.agent import DomainClassification


@dataclass
class RequestState:
    """State created at the start of each orchestrator request.

    Attributes:
        request_id: Propagated from the request_id ContextVar (set by FastAPI
            middleware). Empty string for requests outside the HTTP path.
        original_question: The user's original question before decomposition.
        classification: Domain routing result for the original question.
        sub_questions: Populated by _decompose(); empty until decomposition runs.
        t0: perf_counter value at request start, used for latency calculation.
    """

    request_id: str
    original_question: str
    classification: DomainClassification
    sub_questions: list[str] = field(default_factory=list)
    t0: float = field(default_factory=time.perf_counter)

    @property
    def domain_str(self) -> str:
        """Comma-joined domain names for observability logging."""
        return ",".join(self.classification.domains) if self.classification.domains else "all"

    @property
    def elapsed_ms(self) -> int:
        """Wall-clock milliseconds since request start."""
        return int((time.perf_counter() - self.t0) * 1000)
