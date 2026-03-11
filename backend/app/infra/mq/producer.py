"""RocketMQ 5.x gRPC producer."""

from __future__ import annotations

from typing import Any

import structlog

from app.infra.mq.rocketmq_client import RocketMQMessage, _build_client_config

logger = structlog.get_logger(__name__)


class RocketMQProducer:
    """Wraps the rocketmq-python-client v5 ``Producer``."""

    def __init__(self, group_id: str, topics: tuple[str, ...] | None = None, **kwargs: Any) -> None:
        self._group_id = group_id
        self._topics = topics
        self._producer = None
        self._kwargs = kwargs

    def _ensure_started(self):
        if self._producer is not None:
            return self._producer

        from rocketmq import Producer
        from app.core.config import get_settings

        config = _build_client_config()
        # Producer requires declaring which topics it intends to publish to.
        topics = self._topics if self._topics is not None else (get_settings().rocketmq_topic,)
        producer = Producer(config, topics=topics)
        producer.startup()
        self._producer = producer
        return producer

    def publish(self, message: RocketMQMessage) -> None:
        producer = self._ensure_started()

        from rocketmq import Message as RMQMessage

        msg = RMQMessage()
        msg.topic = message.topic
        msg.body = message.serialize()
        msg.tag = message.tag
        if message.keys:
            msg.keys = message.keys[0] if len(message.keys) == 1 else ",".join(message.keys)

        result = producer.send(msg)
        logger.debug(
            "mq.message_sent",
            topic=message.topic,
            tag=message.tag,
            message_id=str(result),
        )

    def shutdown(self) -> None:
        if self._producer is not None:
            self._producer.shutdown()
            self._producer = None
