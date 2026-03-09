from __future__ import annotations

from prometheus_client import start_http_server

_STARTED_PORTS: set[tuple[str, int]] = set()


def ensure_metrics_server(*, port: int, addr: str = "127.0.0.1") -> None:
    key = (addr, port)
    if key in _STARTED_PORTS:
        return
    start_http_server(port, addr=addr)
    _STARTED_PORTS.add(key)
