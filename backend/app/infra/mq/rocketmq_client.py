"""RocketMQ 5.x gRPC client utilities.

Uses the ``rocketmq-python-client`` (v5) SDK which communicates over gRPC
and does NOT require a native C++ dynamic library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import json

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class RocketMQMessage:
    """Application-level message abstraction."""

    topic: str
    tag: str
    body: dict[str, Any]
    keys: list[str] = field(default_factory=list)

    def serialize(self) -> bytes:
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


def _build_client_config(settings: Settings | None = None):
    """Build a ``ClientConfiguration`` for the gRPC proxy endpoint."""
    from rocketmq import ClientConfiguration, Credentials

    settings = settings or get_settings()
    credentials = Credentials()  # No auth for local dev
    return ClientConfiguration(settings.rocketmq_proxy_endpoint, credentials)


@lru_cache(maxsize=1)
def probe_rocketmq_client() -> tuple[bool, str | None]:
    """Check whether the v5 Python gRPC client library is importable."""
    try:
        from rocketmq import ClientConfiguration  # noqa: F401
    except Exception as exc:  # pragma: no cover
        return False, str(exc)
    return True, None
