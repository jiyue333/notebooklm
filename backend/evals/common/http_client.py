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

    def post_stream(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request_stream("POST", path, body=body)

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

    def _request_stream(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            method=method,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - operational helper
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc
        return _extract_sse_done_payload(payload)


def _extract_sse_done_payload(payload: str) -> Any:
    normalized = payload.replace("\r\n", "\n")
    final_payload = None
    for raw_event in normalized.split("\n\n"):
        raw_event = raw_event.strip()
        if not raw_event:
            continue
        event, event_payload = _parse_sse_event(raw_event)
        if event == "done":
            final_payload = event_payload
        elif event == "error":
            if isinstance(event_payload, dict):
                message = event_payload.get("message") or "stream request failed"
                code = event_payload.get("code")
                status = event_payload.get("status")
                meta = event_payload.get("meta") or {}
                detail = meta.get("detail")
                suffix = " ".join(str(part) for part in (status, code) if part)
                detail_suffix = f": {detail}" if detail and detail != message else ""
                raise RuntimeError(f"{message}{f' ({suffix})' if suffix else ''}{detail_suffix}")
            raise RuntimeError(str(event_payload))
    if final_payload is None:
        raise RuntimeError("stream response ended without a done event")
    return final_payload


def _parse_sse_event(raw_event: str) -> tuple[str, Any]:
    event = "message"
    data_lines: list[str] = []
    for line in raw_event.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    raw_data = "\n".join(data_lines)
    if not raw_data:
        return event, None
    try:
        return event, json.loads(raw_data)
    except json.JSONDecodeError:
        return event, raw_data
