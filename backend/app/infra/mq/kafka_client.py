from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import lru_cache

from app.core.config import Settings, get_settings


def resolve_bootstrap_servers(settings: Settings | None = None) -> str:
    runtime_settings = settings or get_settings()
    return ",".join(
        item.strip()
        for item in runtime_settings.kafka_bootstrap_servers.split(",")
        if item.strip()
    )


def decode_header(headers: Sequence[tuple[str, bytes | None]], key: str) -> str | None:
    for header_key, raw_value in headers:
        if header_key != key or raw_value is None:
            continue
        if isinstance(raw_value, bytes):
            return raw_value.decode("utf-8", errors="ignore")
        return str(raw_value)
    return None


@lru_cache(maxsize=1)
def probe_kafka_client() -> tuple[bool, str | None]:
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # noqa: F401
    except Exception as exc:  # pragma: no cover
        return False, str(exc)
    return True, None


async def probe_kafka_broker(
    settings: Settings | None = None,
) -> tuple[bool, str | None]:
    runtime_settings = settings or get_settings()
    client_available, error = probe_kafka_client()
    if not client_available:
        return False, error

    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(
        bootstrap_servers=resolve_bootstrap_servers(runtime_settings),
        client_id="notebooklm-readiness-probe",
        request_timeout_ms=runtime_settings.kafka_request_timeout_ms,
    )
    try:
        await asyncio.wait_for(producer.start(), timeout=3.0)
    except Exception as exc:  # pragma: no cover
        return False, str(exc)
    finally:
        try:
            await producer.stop()
        except Exception:
            pass
    return True, None
