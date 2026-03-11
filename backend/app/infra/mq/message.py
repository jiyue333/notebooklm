from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

KAFKA_HEADER_TAG = "notebooklm-tag"
KAFKA_HEADER_KEYS = "notebooklm-keys"


@dataclass(slots=True)
class MQMessage:
    topic: str
    tag: str
    body: dict[str, Any]
    keys: list[str] = field(default_factory=list)

    def serialize(self) -> bytes:
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")

    def kafka_headers(self) -> list[tuple[str, bytes]]:
        headers = [(KAFKA_HEADER_TAG, self.tag.encode("utf-8"))]
        cleaned_keys = [item for item in self.keys if item]
        if cleaned_keys:
            headers.append(
                (KAFKA_HEADER_KEYS, ",".join(dict.fromkeys(cleaned_keys)).encode("utf-8"))
            )
        return headers

    @property
    def kafka_key(self) -> bytes | None:
        for item in self.keys:
            if item:
                return item.encode("utf-8")
        return None
