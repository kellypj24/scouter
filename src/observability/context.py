"""Request-scoped context variables.

Set by FastAPI middleware; automatically propagated to all coroutines and
asyncio tasks spawned within the same request lifecycle.
"""

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
