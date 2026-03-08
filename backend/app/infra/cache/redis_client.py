from __future__ import annotations

from collections.abc import Awaitable
from functools import lru_cache
from typing import cast

from redis.asyncio import Redis

from app.core.config import Settings, get_settings


class RedisClientFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Redis | None = None

    @property
    def client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(
                self._settings.redis_url,
                decode_responses=self._settings.redis_decode_responses,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def ping(self) -> bool:
        return bool(await cast(Awaitable[bool], self.client.ping()))


@lru_cache
def get_redis_factory() -> RedisClientFactory:
    return RedisClientFactory(get_settings())

