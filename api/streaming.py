"""SSE serialization helpers for NarrativeBlock."""

import json

from src.models.response import NarrativeBlock


def serialize_block(block: NarrativeBlock) -> str:
    """Serialize a NarrativeBlock to a JSON string suitable for an SSE data field.

    Converts the pd.DataFrame in block.data to a list of row dicts so the payload
    is JSON-serializable over the wire. All other fields are Pydantic models and
    serialize cleanly via model_dump().

    Args:
        block: The NarrativeBlock to serialize.

    Returns:
        JSON string ready to embed in an SSE 'data:' line.
    """
    return json.dumps(
        {
            "question": block.question,
            "query_result": block.query_result.model_dump(),
            "data": block.data.to_dict(orient="records") if not block.data.empty else [],
            "chart_spec": block.chart_spec.model_dump() if block.chart_spec else None,
            "prose": block.prose,
            "follow_ups": block.follow_ups,
        }
    )
