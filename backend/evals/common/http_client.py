from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class NotebooklmClient:
    base_url: str
    token: str

    @classmethod
    def from_env(cls) -> "NotebooklmClient":
        base_url = os.environ.get("NOTEBOOKLM_BASE_URL", "http://127.0.0.1:8080/api").rstrip("/")
        token = os.environ.get("NOTEBOOKLM_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("NOTEBOOKLM_API_TOKEN is required")
        return cls(base_url=base_url, token=token)

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, body=body)

    def patch(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("PATCH", path, body=body)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            method=method,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - operational helper
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc
        return json.loads(payload) if payload else {}
