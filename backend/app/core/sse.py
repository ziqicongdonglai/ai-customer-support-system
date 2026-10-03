import json
from typing import Any

def format_sse(
    event: str,
    data: dict[str, Any],
) -> str:
    """
    Format data as Server-Sent Events format.

    Example:

    event: token
    data: {"content":"hello"}

    """

    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    )