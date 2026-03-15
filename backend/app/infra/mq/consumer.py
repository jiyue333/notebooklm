"""Kafka consumer backed by aiokafka."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from typing import Any

import structlog

from app.core.config import get_settings
from app.infra.mq.kafka_client import decode_header, resolve_bootstrap_servers
from app.infra.mq.message import KAFKA_HEADER_TAG
from app.infra.telemetry.metrics import observe_mq_consume

logger = structlog.get_logger(__name__)

MessageHandler = Callable[[dict[str, Any]], Any]


class KafkaConsumer:
    """Kafka consumer that dispatches messages by tag header."""

    def __init__(self, group_id: str, topic: str, **kwargs: Any) -> None:
        self._group_id = group_id
        self._topic = topic
        self._handlers: dict[str, MessageHandler] = {}
        self._consumer = None
        self._running = False
        self._poll_timeout_ms = int(kwargs.pop("poll_timeout_ms", 1000))
        self._max_records = int(kwargs.pop("max_records", 16))
        self._consumer_kwargs = kwargs

    def register_handler(self, tag: str, handler: MessageHandler) -> None:
        self._handlers[tag] = handler

    async def _ensure_started(self):
        if self._consumer is not None:
            return self._consumer

        from aiokafka import AIOKafkaConsumer

        settings = get_settings()
        consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=resolve_bootstrap_servers(settings),
            group_id=self._group_id,
            client_id=f"{self._group_id}-consumer",
            enable_auto_commit=False,
            auto_offset_reset=settings.kafka_auto_offset_reset,
            request_timeout_ms=settings.kafka_request_timeout_ms,
            session_timeout_ms=settings.kafka_session_timeout_ms,
            max_poll_interval_ms=settings.kafka_max_poll_interval_ms,
            **self._consumer_kwargs,
        )
        await consumer.start()
        self._consumer = consumer
        return consumer

    async def start(self) -> None:
        await self._ensure_started()
        self._running = True

    def request_shutdown(self) -> None:
        self._running = False

    async def poll_loop(self) -> None:
        consumer = self._consumer
        if consumer is None:
            return

        from aiokafka.structs import OffsetAndMetadata

        while self._running:
            try:
                records = await consumer.getmany(
                    timeout_ms=self._poll_timeout_ms,
                    max_records=self._max_records,
                )
                if not records:
                    continue

                for topic_partition, batch in records.items():
                    for msg in batch:
                        tag = decode_header(msg.headers, KAFKA_HEADER_TAG) or ""
                        should_commit = False
                        try:
                            if msg.value is None:
                                continue
                            if isinstance(msg.value, (bytes, bytearray)):
                                raw_body = msg.value.decode("utf-8")
                            elif isinstance(msg.value, str):
                                raw_body = msg.value
                            else:
                                raw_body = str(msg.value)
                            body = json.loads(raw_body)
                        except (AttributeError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                            observe_mq_consume(
                                topic=msg.topic,
                                tag=tag or "unknown",
                                status="decode_failed",
                            )
                            logger.warning(
                                "mq.decode_failed",
                                topic=msg.topic,
                                partition=msg.partition,
                                offset=msg.offset,
                                tag=tag,
                            )
                            should_commit = True
                        else:
                            handler = self._handlers.get(tag)
                            if handler is None:
                                observe_mq_consume(
                                    topic=msg.topic,
                                    tag=tag or "unknown",
                                    status="no_handler",
                                )
                                logger.warning(
                                    "mq.no_handler",
                                    topic=msg.topic,
                                    partition=msg.partition,
                                    offset=msg.offset,
                                    tag=tag,
                                )
                                should_commit = True
                            else:
                                try:
                                    result = handler(body)
                                    if inspect.isawaitable(result):
                                        await result
                                    observe_mq_consume(
                                        topic=msg.topic,
                                        tag=tag or "unknown",
                                        status="handled",
                                    )
                                    should_commit = True
                                except Exception:
                                    observe_mq_consume(
                                        topic=msg.topic,
                                        tag=tag or "unknown",
                                        status="handler_error",
                                    )
                                    logger.exception(
                                        "mq.handler_error",
                                        topic=msg.topic,
                                        partition=msg.partition,
                                        offset=msg.offset,
                                        tag=tag,
                                    )

                        if should_commit:
                            try:
                                await consumer.commit(
                                    {
                                        topic_partition: OffsetAndMetadata(
                                            msg.offset + 1,
                                            "",
                                        )
                                    }
                                )
                            except Exception:
                                observe_mq_consume(
                                    topic=msg.topic,
                                    tag=tag or "unknown",
                                    status="commit_failed",
                                )
                                logger.exception(
                                    "mq.commit_failed",
                                    topic=msg.topic,
                                    partition=msg.partition,
                                    offset=msg.offset,
                                    tag=tag,
                                )
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._running:
                    logger.exception("mq.poll_error")
                    await asyncio.sleep(1)

    async def shutdown(self) -> None:
        self._running = False
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
