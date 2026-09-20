"""Parse structured model output. Reject malformed / hallucinated tools."""

from __future__ import annotations

import json
import re
from typing import Any

FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


class ParseError(ValueError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    if not text or not str(text).strip():
        raise ParseError("empty model output")
    raw = text.strip()
    m = FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ParseError("no JSON object")
    blob = raw[start : end + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        raise ParseError(f"malformed JSON: {e}") from e
    if not isinstance(data, dict):
        raise ParseError("JSON root must be an object")
    return data
