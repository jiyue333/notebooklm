from __future__ import annotations

from typing import Any

from app.infra.mq.rocketmq_client import RocketMQClientMixin, RocketMQMessage


class RocketMQProducer(RocketMQClientMixin):
    def __init__(self, group_id: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._group_id = group_id
        self._producer = None

    def _ensure_started(self):
        if self._producer is not None:
            return self._producer

        from rocketmq.client import Producer

        producer = Producer(self._group_id)
        producer.set_name_server_address(self.namesrv_addr)
        producer.start()
        self._producer = producer
        return producer

    def publish(self, message: RocketMQMessage) -> None:
        producer = self._ensure_started()

        from rocketmq.client import Message

        mq_message = Message(message.topic)
        mq_message.set_tags(message.tag)
        mq_message.set_body(message.serialize())
        for key in message.keys:
            mq_message.set_keys(key)

        producer.send_sync(mq_message)

    def shutdown(self) -> None:
        if self._producer is not None:
            self._producer.shutdown()
            self._producer = None
