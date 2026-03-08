from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.infra.mq.rocketmq_client import RocketMQClientMixin

MessageHandler = Callable[[dict[str, Any]], None]


class RocketMQConsumer(RocketMQClientMixin):
    def __init__(self, group_id: str, topic: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._group_id = group_id
        self._topic = topic
        self._handlers: dict[str, MessageHandler] = {}
        self._consumer = None

    def register_handler(self, tag: str, handler: MessageHandler) -> None:
        self._handlers[tag] = handler

    def _ensure_started(self):
        if self._consumer is not None:
            return self._consumer

        from rocketmq.client import PushConsumer

        consumer = PushConsumer(self._group_id)
        consumer.set_name_server_address(self.namesrv_addr)
        consumer.subscribe(self._topic, self._dispatch)
        consumer.start()
        self._consumer = consumer
        return consumer

    def _dispatch(self, message):
        from rocketmq.client import ConsumeStatus

        tag = message.get_property("TAGS") or ""
        body = json.loads(message.body.decode("utf-8"))
        handler = self._handlers.get(tag)
        if handler is not None:
            handler(body)
        return ConsumeStatus.CONSUME_SUCCESS

    def start(self) -> None:
        self._ensure_started()

    def shutdown(self) -> None:
        if self._consumer is not None:
            self._consumer.shutdown()
            self._consumer = None
