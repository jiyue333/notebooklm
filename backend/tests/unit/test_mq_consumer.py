from __future__ import annotations

import asyncio
import json

from app.infra.mq.consumer import RocketMQConsumer


class FakeMessage:
    def __init__(self, message_id: str, tag: str, body: dict[str, str]) -> None:
        self.message_id = message_id
        self.tag = tag
        self.body = json.dumps(body).encode("utf-8")


class FakeSimpleConsumer:
    def __init__(self, owner: RocketMQConsumer, batches: list[list[FakeMessage]]) -> None:
        self._owner = owner
        self._batches = list(batches)
        self.acked: list[str] = []
        self.receive_calls = 0

    def receive(self, max_message_num: int, invisible_duration: int):  # noqa: ARG002
        self.receive_calls += 1
        if self._batches:
            return self._batches.pop(0)
        self._owner._running = False
        return []

    def ack(self, message: FakeMessage) -> None:
        self.acked.append(message.message_id)


def test_consumer_reuses_single_event_loop_for_async_handlers() -> None:
    consumer = RocketMQConsumer(group_id="test", topic="topic")
    loop_ids: list[int] = []

    async def handler(payload: dict[str, str]) -> None:  # noqa: ARG001
        loop_ids.append(id(asyncio.get_running_loop()))

    consumer.register_handler("article.ingest", handler)
    consumer._consumer = FakeSimpleConsumer(
        consumer,
        [
            [
                FakeMessage("m1", "article.ingest", {"jobId": "job-1"}),
                FakeMessage("m2", "article.ingest", {"jobId": "job-2"}),
            ]
        ],
    )
    consumer._running = True

    consumer.poll_loop()

    assert len(loop_ids) == 2
    assert loop_ids[0] == loop_ids[1]
    assert consumer._consumer.acked == ["m1", "m2"]


def test_consumer_does_not_ack_failed_handler_messages() -> None:
    consumer = RocketMQConsumer(group_id="test", topic="topic")

    async def handler(payload: dict[str, str]) -> None:  # noqa: ARG001
        raise RuntimeError("boom")

    consumer.register_handler("article.ingest", handler)
    consumer._consumer = FakeSimpleConsumer(
        consumer,
        [[FakeMessage("m1", "article.ingest", {"jobId": "job-1"})]],
    )
    consumer._running = True

    consumer.poll_loop()

    assert consumer._consumer.acked == []
