"""Kafka producer backed by aiokafka."""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog

from app.core.config import get_settings
from app.infra.mq.kafka_client import resolve_bootstrap_servers
from app.infra.mq.message import MQMessage
from app.infra.telemetry.metrics import observe_mq_publish

logger = structlog.get_logger(__name__)


class KafkaProducer:
    """Thin Kafka producer wrapper for NotebookLM jobs."""

    def __init__(self, client_id: str, **kwargs: Any) -> None:
        self._client_id = client_id
        self._producer = None
        self._producer_kwargs = kwargs

    async def _ensure_started(self):
        if self._producer is not None:
            return self._producer

        from aiokafka import AIOKafkaProducer

        settings = get_settings()
        producer = AIOKafkaProducer(
            bootstrap_servers=resolve_bootstrap_servers(settings),
            client_id=self._client_id,
            request_timeout_ms=settings.kafka_request_timeout_ms,
            enable_idempotence=True,
            **self._producer_kwargs,
        )
        await producer.start()
        self._producer = producer
        return producer

    async def publish(self, message: MQMessage) -> None:
        producer = await self._ensure_started()
        started_at = perf_counter()
        try:
            result = await producer.send_and_wait(
                message.topic,
                value=message.serialize(),
                key=message.kafka_key,
                headers=message.kafka_headers(),
            )
        except Exception:
            observe_mq_publish(
                topic=message.topic,
                tag=message.tag,
                status="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
            )
            raise

        observe_mq_publish(
            topic=message.topic,
            tag=message.tag,
            status="sent",
            duration_ms=(perf_counter() - started_at) * 1000,
        )
        logger.debug(
            "mq.message_sent",
            topic=message.topic,
            tag=message.tag,
            partition=result.partition,
            offset=result.offset,
        )

    async def shutdown(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
