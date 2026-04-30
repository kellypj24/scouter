"""Agent-level request/response models."""

from pydantic import BaseModel

from src.models.response import NarrativeBlock


class AgentRequest(BaseModel):
    """Incoming request to the agent harness.

    Attributes:
        question: Natural language question from the user.
        conversation_id: Optional session ID for context continuity.
        max_blocks: Max number of NarrativeBlocks to return (default 3).
    """

    question: str
    conversation_id: str | None = None
    max_blocks: int = 2


class AgentResponse(BaseModel):
    """Full response from the agent harness.

    Attributes:
        blocks: Ordered list of NarrativeBlocks composing the response.
        fallback_used: True if rule-based fallback was triggered.
    """

    blocks: list[NarrativeBlock]
    fallback_used: bool = False
