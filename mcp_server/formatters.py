import json
from typing import Any


def format_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
