from __future__ import annotations

from app.infra.telemetry import logging as telemetry_logging


class DummySpanContext:
    def __init__(self, *, trace_id: int, span_id: int, is_valid: bool = True) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.is_valid = is_valid


class DummySpan:
    def __init__(self, context: DummySpanContext) -> None:
        self._context = context

    def get_span_context(self) -> DummySpanContext:
        return self._context


class DummyTraceApi:
    def __init__(self, span: DummySpan | None) -> None:
        self._span = span

    def get_current_span(self) -> DummySpan | None:
        return self._span


def test_inject_current_trace_context_adds_trace_and_span_ids(monkeypatch) -> None:
    span = DummySpan(
        DummySpanContext(
            trace_id=int("1234567890abcdef1234567890abcdef", 16),
            span_id=int("1234567890abcdef", 16),
        )
    )
    monkeypatch.setattr(telemetry_logging, "trace", DummyTraceApi(span))

    event = telemetry_logging._inject_current_trace_context(None, None, {})

    assert event["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert event["span_id"] == "1234567890abcdef"


def test_inject_current_trace_context_keeps_existing_ids(monkeypatch) -> None:
    span = DummySpan(
        DummySpanContext(
            trace_id=int("ffffffffffffffffffffffffffffffff", 16),
            span_id=int("ffffffffffffffff", 16),
        )
    )
    monkeypatch.setattr(telemetry_logging, "trace", DummyTraceApi(span))

    event = telemetry_logging._inject_current_trace_context(
        None,
        None,
        {"trace_id": "kept-trace", "span_id": "kept-span"},
    )

    assert event["trace_id"] == "kept-trace"
    assert event["span_id"] == "kept-span"
