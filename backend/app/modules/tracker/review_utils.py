from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def is_sampled(*, key: str, sample_rate: float) -> bool:
    normalized_rate = min(max(sample_rate, 0.0), 1.0)
    threshold = int(normalized_rate * 10_000)
    bucket = int(sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 10_000
    return bucket < threshold


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = JSON_OBJECT_PATTERN.search(stripped)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(parsed, dict):
        return parsed
    return None
