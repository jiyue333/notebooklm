from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


@dataclass(slots=True)
class MinifluxClientError(Exception):
    status_code: int
    message: str
    details: Any = None

    def __str__(self) -> str:
        return f"{self.status_code}: {self.message}"


class MinifluxClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = (api_token or "").strip() or None
        self.username = (username or "").strip() or None
        self.password = password
        self.timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "MinifluxClient":
        if not self.api_token and not (self.username and self.password):
            raise MinifluxClientError(500, "MinifluxClient 未配置鉴权信息")

        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        auth: tuple[str, str] | None = None
        if self.api_token:
            headers["X-Auth-Token"] = self.api_token
        else:
            auth = (self.username or "", self.password or "")

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers=headers,
            auth=auth,
            trust_env=False,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def discover(self, url: str) -> list[dict]:
        data = await self._request("POST", "/v1/discover", json={"url": url}, expected_statuses={200})
        return data if isinstance(data, list) else []

    async def list_feeds(self) -> list[dict]:
        data = await self._request("GET", "/v1/feeds", expected_statuses={200})
        return data if isinstance(data, list) else []

    async def get_feed(self, feed_id: int) -> dict:
        data = await self._request("GET", f"/v1/feeds/{feed_id}", expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def get_user(self, user_ref: int | str) -> dict:
        encoded_ref = quote(str(user_ref), safe="")
        data = await self._request("GET", f"/v1/users/{encoded_ref}", expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def create_user(self, *, username: str, password: str, is_admin: bool = False) -> dict:
        payload: dict[str, Any] = {
            "username": username,
            "password": password,
            "is_admin": bool(is_admin),
        }
        data = await self._request("POST", "/v1/users", json=payload, expected_statuses={201})
        return data if isinstance(data, dict) else {}

    async def update_user(
        self,
        user_ref: int | str,
        *,
        username: str | None = None,
        password: str | None = None,
        is_admin: bool | None = None,
    ) -> dict:
        encoded_ref = quote(str(user_ref), safe="")
        payload: dict[str, Any] = {}
        if username is not None:
            payload["username"] = username
        if password is not None:
            payload["password"] = password
        if is_admin is not None:
            payload["is_admin"] = bool(is_admin)
        data = await self._request("PUT", f"/v1/users/{encoded_ref}", json=payload, expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def create_feed(
        self,
        *,
        feed_url: str,
        category_id: int | None = None,
        crawler: bool = False,
    ) -> int:
        payload: dict[str, Any] = {
            "feed_url": feed_url,
            "crawler": crawler,
        }
        if category_id is not None:
            payload["category_id"] = category_id
        data = await self._request("POST", "/v1/feeds", json=payload, expected_statuses={201})
        if not isinstance(data, dict) or "feed_id" not in data:
            raise MinifluxClientError(500, "Miniflux 返回了无效的 feed_id", data)
        return int(data["feed_id"])

    async def refresh_feed(self, feed_id: int) -> None:
        await self._request("PUT", f"/v1/feeds/{feed_id}/refresh", expected_statuses={204})

    async def delete_feed(self, feed_id: int) -> None:
        await self._request("DELETE", f"/v1/feeds/{feed_id}", expected_statuses={204})

    async def list_feed_entries(self, feed_id: int, *, params: dict[str, Any] | None = None) -> dict:
        data = await self._request("GET", f"/v1/feeds/{feed_id}/entries", params=params or {}, expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def list_entries(self, *, params: dict[str, Any] | None = None) -> dict:
        data = await self._request("GET", "/v1/entries", params=params or {}, expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def get_feed_entry(self, feed_id: int, entry_id: int) -> dict:
        data = await self._request("GET", f"/v1/feeds/{feed_id}/entries/{entry_id}", expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def get_entry(self, entry_id: int) -> dict:
        data = await self._request("GET", f"/v1/entries/{entry_id}", expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def update_entries_status(self, *, entry_ids: list[int], status: str) -> None:
        await self._request(
            "PUT",
            "/v1/entries",
            json={"entry_ids": entry_ids, "status": status},
            expected_statuses={204},
        )

    async def toggle_bookmark(self, entry_id: int) -> None:
        await self._request("PUT", f"/v1/entries/{entry_id}/bookmark", expected_statuses={201, 204})

    async def list_categories(self) -> list[dict]:
        data = await self._request("GET", "/v1/categories", expected_statuses={200})
        return data if isinstance(data, list) else []

    async def create_category(self, title: str, *, hide_globally: bool = False) -> dict:
        payload: dict[str, Any] = {"title": title}
        payload["hide_globally"] = bool(hide_globally)
        data = await self._request("POST", "/v1/categories", json=payload, expected_statuses={201})
        return data if isinstance(data, dict) else {}

    async def delete_category(self, category_id: int) -> None:
        await self._request("DELETE", f"/v1/categories/{category_id}", expected_statuses={204})

    async def get_feed_counters(self) -> dict:
        data = await self._request("GET", "/v1/feeds/counters", expected_statuses={200})
        return data if isinstance(data, dict) else {"reads": {}, "unreads": {}}

    async def get_me(self) -> dict:
        data = await self._request("GET", "/v1/me", expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def get_version(self) -> dict:
        data = await self._request("GET", "/v1/version", expected_statuses={200})
        return data if isinstance(data, dict) else {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        expected_statuses: set[int],
    ) -> Any:
        if self._client is None:
            raise RuntimeError("MinifluxClient 必须在 async with 语句中使用")

        try:
            response = await self._client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise MinifluxClientError(503, "无法连接 Miniflux 服务") from exc

        if response.status_code not in expected_statuses:
            details: Any = None
            message = f"Miniflux 请求失败（{response.status_code}）"
            try:
                details = response.json()
                if isinstance(details, dict):
                    message = str(details.get("error_message") or details.get("message") or message)
            except ValueError:
                details = response.text
                if response.text:
                    message = response.text
            raise MinifluxClientError(response.status_code, message, details)

        if response.status_code == 204:
            return None

        if "application/json" in (response.headers.get("content-type") or ""):
            try:
                return response.json()
            except ValueError:
                return None

        return response.text
