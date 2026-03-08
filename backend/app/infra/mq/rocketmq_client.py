from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class RocketMQMessage:
    topic: str
    tag: str
    body: dict[str, Any]
    keys: list[str] = field(default_factory=list)

    def serialize(self) -> bytes:
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


class RocketMQClientMixin:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def namesrv_addr(self) -> str:
        return self._settings.rocketmq_namesrv_addr
