"""RocketMQ 5.x gRPC consumer using SimpleConsumer (long-polling)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import structlog

from app.infra.mq.rocketmq_client import _build_client_config

logger = structlog.get_logger(__name__)

MessageHandler = Callable[[dict[str, Any]], None]


class RocketMQConsumer:
    """Wraps the rocketmq-python-client v5 ``SimpleConsumer``.

    The v5 Python SDK does NOT provide PushConsumer; only SimpleConsumer
    (long-polling) is available.  We poll in a loop inside ``start()``.
    """

    def __init__(self, group_id: str, topic: str, **kwargs: Any) -> None:
        self._group_id = group_id
        self._topic = topic
        self._handlers: dict[str, MessageHandler] = {}
        self._consumer = None
        self._running = False
        self._kwargs = kwargs

    def register_handler(self, tag: str, handler: MessageHandler) -> None:
        self._handlers[tag] = handler

    def _ensure_started(self):
        if self._consumer is not None:
            return self._consumer

        from rocketmq import SimpleConsumer

        config = _build_client_config()
        consumer = SimpleConsumer(config, self._group_id)
        consumer.startup()
        consumer.subscribe(self._topic)
        self._consumer = consumer
        return consumer

    def start(self) -> None:
        """Start the consumer (creates and subscribes).

        Callers should run ``poll_loop()`` in a thread to process messages.
        """
        self._ensure_started()
        self._running = True

    def poll_loop(self) -> None:
        """Blocking loop that polls for messages and dispatches to handlers.

        Should be run in a dedicated thread.
        """
        consumer = self._consumer
        if consumer is None:
            return

        while self._running:
            try:
                messages = consumer.receive(max_message_num=16, invisible_duration=30)
                if not messages:
                    continue
                for msg in messages:
                    tag = msg.tag or ""
                    try:
                        body = json.loads(msg.body.decode("utf-8") if isinstance(msg.body, bytes) else msg.body)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        logger.warning(
                            "mq.decode_failed",
                            message_id=msg.message_id,
                            tag=tag,
                        )
                        consumer.ack(msg)
                        continue

                    handler = self._handlers.get(tag)
                    if handler is not None:
                        try:
                            handler(body)
                        except Exception:
                            logger.exception(
                                "mq.handler_error",
                                message_id=msg.message_id,
                                tag=tag,
                            )
                    else:
                        logger.warning(
                            "mq.no_handler",
                            message_id=msg.message_id,
                            tag=tag,
                        )

                    consumer.ack(msg)
            except Exception:
                if self._running:
                    logger.exception("mq.poll_error")
                    import time
                    time.sleep(1)

    def shutdown(self) -> None:
        self._running = False
        if self._consumer is not None:
            self._consumer.shutdown()
            self._consumer = None
