from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import delete

from app.infra.db.session import get_session_manager
from app.infra.telemetry.langsmith import configure_langsmith
from app.infra.telemetry.metrics import bind_eval_event_sink, reset_eval_event_sink
from app.modules.agent.chat.prompts import PROMPT_VERSION as CHAT_PROMPT_VERSION
from app.modules.agent.chat.service import stream_message
from app.modules.agent.search.service import get_search_session, start_agent_search
from app.modules.agent.summary.prompts import PROMPT_VERSION as SUMMARY_PROMPT_VERSION
from app.modules.agent.summary.service import generate_summary
from app.modules.ingest.service import build_article_chunk_rows, build_article_fields, ingest
from app.modules.ingest.types import IngestInput, InputType
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.models import Article, ArticleChunk
from app.modules.notebooks.service import create_notebook
from app.modules.settings.runtime import resolve_search_api_key, resolve_tavily_api_key
from evals.judges import judge_chat, judge_ingest, judge_search, judge_summary
from evals.langsmith_sync import (
    finalize_langsmith_context,
    init_langsmith_context,
    record_case_attempt,
)
from evals.reporters import write_report_bundle

BASE_DIR = Path(__file__).resolve().parent
CASES_DIR = BASE_DIR / "cases"
RUNS_DIR = BASE_DIR / "runs"
PIPELINES = ("search", "ingest", "summary", "chat")
DEFAULT_REPEAT_BY_PROFILE = {
    "smoke": 5,
    "stable": 3,
    "full": 1,
}
PROMPT_VERSION_BY_PIPELINE = {
    "search": "search.v1",
    "ingest": "ingest.v1",
    "summary": SUMMARY_PROMPT_VERSION,
    "chat": CHAT_PROMPT_VERSION,
}


class EvalUser:
    id = "00000000-0000-0000-0000-000000000001"
    settings_json = {}
    llm_api_key_ciphertext = None
    llm_api_key_last4 = None
    exa_api_key_ciphertext = None
    exa_api_key_last4 = None
    embedding_api_key_ciphertext = None
    embedding_api_key_last4 = None


EVAL_USER = EvalUser()


def load_cases(pipeline: str, profile: str) -> list[dict[str, Any]]:
    path = CASES_DIR / pipeline / f"{profile}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"cases not found: {path}")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    requested_case_ids = {
        item.strip()
        for item in (os.getenv("EVAL_CASE_IDS") or "").split(",")
        if item.strip()
    }
    if requested_case_ids:
        rows = [row for row in rows if str(row.get("case_id")) in requested_case_ids]
    max_cases = os.getenv("EVAL_MAX_CASES")
    if max_cases and max_cases.isdigit() and int(max_cases) > 0:
        rows = rows[: int(max_cases)]
    if not rows:
        raise ValueError(f"cases empty: {path}")
    case_ids = [str(row.get("case_id") or "").strip() for row in rows]
    if any(not case_id for case_id in case_ids):
        raise ValueError(f"invalid case_id in {path}")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError(f"duplicate case_id in {path}")
    if profile == "smoke" and not (requested_case_ids or max_cases) and len(rows) < 5:
        raise ValueError(f"{pipeline}/{profile} requires at least 5 cases for reproducibility")
    return rows


def _resolve_repeat(profile: str, cases: list[dict[str, Any]]) -> int:
    env_override = os.getenv("EVAL_REPEAT_OVERRIDE")
    if env_override and env_override.isdigit() and int(env_override) > 0:
        return int(env_override)
    if cases:
        override = cases[0].get("repeat")
        if isinstance(override, int) and override > 0:
            return override
    return DEFAULT_REPEAT_BY_PROFILE.get(profile, 5)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _git_sha() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return output or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 2)
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(sorted_values[int(rank)], 2)
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    interpolated = lower_value + (upper_value - lower_value) * (rank - lower)
    return round(interpolated, 2)


def _distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"samples": 0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0}
    avg = statistics.fmean(values)
    return {
        "samples": len(values),
        "avg": round(avg, 2),
        "p50": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
        "p95": _percentile(values, 0.95),
    }


async def _create_eval_notebook(session, *, pipeline: str, case_id: str) -> dict[str, Any]:
    return await create_notebook(
        session,
        user_id=EVAL_USER.id,
        title=f"Eval {pipeline} {case_id} {datetime.now(UTC).strftime('%H%M%S')}",
        emoji="🧪",
        color="#2563eb",
        tags=["eval", pipeline],
    )


async def _delete_eval_notebook(session, *, notebook_id: str) -> None:
    notebook = await notebooks_repo.get_notebook(
        session,
        user_id=EVAL_USER.id,
        notebook_id=notebook_id,
    )
    if notebook is None:
        return
    await notebooks_repo.delete_notebook(session, notebook)
    await session.commit()


def _build_simple_pdf_bytes(text: str) -> bytes:
    safe_text = (text or "NotebookLM eval PDF sample").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream_text = f"BT /F1 16 Tf 72 720 Td ({safe_text[:180]}) Tj ET\n"
    stream_bytes = stream_text.encode("latin-1", errors="ignore")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream_bytes)).encode("ascii") + b" >>\nstream\n" + stream_bytes + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    chunks: list[bytes] = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii"))
        chunks.append(body + b"\n")
        chunks.append(b"endobj\n")
    xref_start = sum(len(chunk) for chunk in chunks)
    xref = [b"xref\n", f"0 {len(objects) + 1}\n".encode("ascii"), b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("ascii")
        + b"startxref\n"
        + f"{xref_start}\n".encode("ascii")
        + b"%%EOF\n"
    )
    return b"".join(chunks + xref + [trailer])


def _build_simple_png_bytes() -> bytes:
    # 1x1 transparent PNG
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
        "0000000A49444154789C636000000200015E0202A50000000049454E44AE426082"
    )


def _normalize_ingest_case(case: dict[str, Any]) -> tuple[IngestInput, dict[str, Any]]:
    artifact = (case.get("artifact_type") or "pasted_text").strip()
    title = str(case.get("title") or f"Ingest case {case['case_id']}")
    notebook_title = str(case.get("notebook_title") or "Eval Notebook")
    content = str(case.get("content") or "")
    input_payload = {
        "artifact_type": artifact,
        "title": title,
    }

    if artifact in {"pasted_text", "long_markdown"}:
        ingest_input = IngestInput(
            input_type=InputType.TEXT,
            notebook_id="",
            user_id=EVAL_USER.id,
            title=title,
            notebook_title=notebook_title,
            raw_text=content,
            file_name="input.md",
        )
    elif artifact == "html":
        ingest_input = IngestInput(
            input_type=InputType.FILE,
            notebook_id="",
            user_id=EVAL_USER.id,
            title=title,
            notebook_title=notebook_title,
            file_name="sample.html",
            file_mime="text/html",
            file_bytes=content.encode("utf-8"),
        )
    elif artifact == "pdf":
        ingest_input = IngestInput(
            input_type=InputType.FILE,
            notebook_id="",
            user_id=EVAL_USER.id,
            title=title,
            notebook_title=notebook_title,
            file_name="sample.pdf",
            file_mime="application/pdf",
            file_bytes=_build_simple_pdf_bytes(content),
        )
    elif artifact == "scanned_pdf":
        ingest_input = IngestInput(
            input_type=InputType.FILE,
            notebook_id="",
            user_id=EVAL_USER.id,
            title=title,
            notebook_title=notebook_title,
            file_name="scan.png",
            file_mime="image/png",
            file_bytes=_build_simple_png_bytes(),
        )
    elif artifact == "unsupported_binary":
        ingest_input = IngestInput(
            input_type=InputType.FILE,
            notebook_id="",
            user_id=EVAL_USER.id,
            title=title,
            notebook_title=notebook_title,
            file_name="payload.bin",
            file_mime="application/octet-stream",
            file_bytes=bytes(range(256)),
        )
    elif artifact == "url":
        ingest_input = IngestInput(
            input_type=InputType.URL,
            notebook_id="",
            user_id=EVAL_USER.id,
            title=title,
            notebook_title=notebook_title,
            source_url=content,
        )
    else:
        ingest_input = IngestInput(
            input_type=InputType.TEXT,
            notebook_id="",
            user_id=EVAL_USER.id,
            title=title,
            notebook_title=notebook_title,
            raw_text=content,
            file_name="input.md",
        )

    input_payload["input_type"] = ingest_input.input_type.value
    return ingest_input, input_payload


async def _ingest_article_from_input(
    session,
    *,
    notebook_id: str,
    notebook_title: str,
    ingest_input: IngestInput,
    dedupe_seed: str,
) -> tuple[Article, Any]:
    ingest_input.notebook_id = notebook_id
    ingest_input.notebook_title = notebook_title
    raw_text_input = ingest_input.raw_text if ingest_input.input_type == InputType.TEXT else None
    preview = (
        f"# {ingest_input.title}\n\n{(ingest_input.raw_text or '')[:180]}"
        if ingest_input.input_type == InputType.TEXT
        else None
    )
    article = Article(
        user_id=EVAL_USER.id,
        notebook_id=notebook_id,
        input_type=ingest_input.input_type.value,
        dedupe_key=f"eval:{ingest_input.input_type.value}:{hashlib.sha256(dedupe_seed.encode('utf-8')).hexdigest()}",
        title=ingest_input.title or "Eval ingest",
        raw_text_input=raw_text_input,
        preview_markdown=preview,
        parse_status="queued",
        chunk_status="not_started",
        index_status="not_started",
    )
    session.add(article)
    await session.flush()

    result = await ingest(
        session,
        ingest_input=ingest_input,
        article_id=article.id,
        user=EVAL_USER,
    )

    fields = build_article_fields(result)
    for key, value in fields.items():
        if hasattr(article, key):
            setattr(article, key, value)

    await session.execute(delete(ArticleChunk).where(ArticleChunk.article_id == article.id))
    for row in build_article_chunk_rows(result):
        session.add(ArticleChunk(article_id=article.id, **row))
    article.chunk_status = "completed" if result.chunks else "failed"
    article.index_status = "completed" if result.chunks else "failed"
    await session.commit()
    await session.refresh(article)
    return article, result


async def _poll_search_until_done(session, *, notebook_id: str, search_session_id: str):
    latest = None
    for attempt in range(120):
        latest = await get_search_session(
            session,
            user_id=EVAL_USER.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
        )
        if latest.run.status in {"completed", "partial", "failed", "expired", "cancelled"}:
            return latest
        await asyncio.sleep(2 if attempt > 0 else 1)
    raise TimeoutError("search session did not finish within timeout")


async def _run_search_case(session, case: dict[str, Any]) -> dict[str, Any]:
    notebook = await _create_eval_notebook(session, pipeline="search", case_id=case["case_id"])
    exa_api_key, _ = resolve_search_api_key(EVAL_USER)
    tavily_api_key, _ = resolve_tavily_api_key()
    try:
        response = await start_agent_search(
            session,
            user=EVAL_USER,
            notebook_id=notebook["id"],
            query=case["query"],
            mode=case.get("mode", "auto"),
            max_results=int(case.get("max_results", 10)),
            exa_api_key=exa_api_key,
            tavily_api_key=tavily_api_key,
            notebook_title=notebook["title"],
            existing_article_urls=[],
            notebook_article_summaries=[],
            preferred_sites=case.get("preferred_sites") or [],
        )
        latest = response
        if response.run.id and response.run.status not in {"completed", "partial", "failed", "expired", "cancelled"}:
            latest = await _poll_search_until_done(
                session,
                notebook_id=notebook["id"],
                search_session_id=response.run.id,
            )
        items = [
            {
                "title": item.title,
                "url": item.url,
                "domain": item.domain,
                "highlights": (item.highlights or [])[:2],
                "why_selected": item.whySelected,
            }
            for item in latest.items
        ]
        judge = judge_search(
            items=items,
            expected=case.get("expected") or {},
            rubric=case.get("rubric") or {},
            query=str(case.get("query") or ""),
        )
        return {
            "case_id": case["case_id"],
            "judge": {
                "score": judge.score,
                "subscores": judge.subscores,
                "pass": judge.passed,
                "reason": judge.reason,
                "details": judge.details,
            },
            "meta": {
                "searchSessionId": latest.run.id,
                "status": latest.run.status,
                "resultCount": len(latest.items),
                "providerCallsUsed": int((latest.debug or {}).get("providerCallsUsed") or 0),
                "providerCallBudget": int((latest.debug or {}).get("providerCallBudget") or 0),
                "providerAllFailed": bool((latest.debug or {}).get("providerAllFailed")),
                "providerAttempts": int((latest.debug or {}).get("providerAttempts") or 0),
                "providerFailures": int((latest.debug or {}).get("providerFailures") or 0),
                "scoreMode": str((latest.debug or {}).get("scoreMode") or ""),
                "notebookTitle": notebook["title"],
            },
            "output": {
                "items": items[:10],
                "recallSummary": latest.recallSummary,
                "debug": latest.debug or {},
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook["id"])


async def _run_ingest_case(session, case: dict[str, Any]) -> dict[str, Any]:
    notebook = await _create_eval_notebook(session, pipeline="ingest", case_id=case["case_id"])
    try:
        ingest_input, input_payload = _normalize_ingest_case(case)
        article, result = await _ingest_article_from_input(
            session,
            notebook_id=notebook["id"],
            notebook_title=notebook["title"],
            ingest_input=ingest_input,
            dedupe_seed=f"{case['case_id']}:{case.get('artifact_type')}:{case.get('content', '')}",
        )
        judge = judge_ingest(
            clean_markdown=result.clean_markdown or "",
            chunk_count=len(result.chunks),
            parse_error_tag=getattr(result, "parse_error_tag", None),
            expected=case.get("expected") or {},
            rubric=case.get("rubric") or {},
        )
        return {
            "case_id": case["case_id"],
            "judge": {
                "score": judge.score,
                "subscores": judge.subscores,
                "pass": judge.passed,
                "reason": judge.reason,
            },
            "meta": {
                "articleId": article.id,
                "chunkCount": len(result.chunks),
                "parser": result.parser_name,
                "inputType": input_payload.get("artifact_type"),
                "remarkFixesApplied": int(getattr(result, "remark_fixes_applied", 0)),
                "notebookTitle": notebook["title"],
                "parseErrorTag": getattr(result, "parse_error_tag", None),
            },
            "output": {
                "title": article.title,
                "tocSize": len(result.toc),
                "chunkCount": len(result.chunks),
                "contentPreview": (result.clean_markdown or "")[:480],
                "parseErrorMessage": getattr(result, "parse_error_message", None),
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook["id"])


async def _run_summary_case(session, case: dict[str, Any]) -> dict[str, Any]:
    notebook = await _create_eval_notebook(session, pipeline="summary", case_id=case["case_id"])
    try:
        ingest_input = IngestInput(
            input_type=InputType.TEXT,
            notebook_id=notebook["id"],
            user_id=EVAL_USER.id,
            title=case["title"],
            notebook_title=notebook["title"],
            raw_text=case["content"],
            file_name="summary-source.md",
        )
        article, _ = await _ingest_article_from_input(
            session,
            notebook_id=notebook["id"],
            notebook_title=notebook["title"],
            ingest_input=ingest_input,
            dedupe_seed=f"{case['case_id']}:{case['content']}",
        )
        result = await generate_summary(
            session,
            article_id=article.id,
            title=article.title,
            clean_markdown=article.clean_markdown or case["content"],
            language=case.get("language", "中文"),
            user=EVAL_USER,
        )
        summary_text = str(result.get("summary_text") or "")
        judge = judge_summary(
            summary_text=summary_text,
            source_text=case["content"],
            expected=case.get("expected") or {},
            rubric=case.get("rubric") or {},
        )
        return {
            "case_id": case["case_id"],
            "judge": {
                "score": judge.score,
                "subscores": judge.subscores,
                "pass": judge.passed,
                "reason": judge.reason,
            },
            "meta": {
                "articleId": article.id,
                "cached": bool(result.get("cached")),
                "notebookTitle": notebook["title"],
            },
            "output": {
                "summary_text": summary_text,
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook["id"])


async def _run_chat_case(session, case: dict[str, Any]) -> dict[str, Any]:
    notebook = await _create_eval_notebook(session, pipeline="chat", case_id=case["case_id"])
    try:
        grounding_input = IngestInput(
            input_type=InputType.TEXT,
            notebook_id=notebook["id"],
            user_id=EVAL_USER.id,
            title="Chat grounding article",
            notebook_title=notebook["title"],
            raw_text=case.get(
                "grounding_content",
                (
                    "# 引用能力\n\n"
                    "研究笔记本系统需要引用能力，因为回答必须能回到原始证据，"
                    "让用户核验结论来自哪一篇文章、哪一段内容，并区分本地资料与网络补充。"
                ),
            ),
            file_name="chat-grounding.md",
        )
        article, _ = await _ingest_article_from_input(
            session,
            notebook_id=notebook["id"],
            notebook_title=notebook["title"],
            ingest_input=grounding_input,
            dedupe_seed=f"{case['case_id']}:{case.get('grounding_content', '')}",
        )
        ttfb_ms: float | None = None
        done_data: dict[str, Any] = {}
        started = perf_counter()
        async for event in stream_message(
            session,
            user_id=EVAL_USER.id,
            notebook_id=notebook["id"],
            question=case["question"],
            article_id=article.id,
            conversation_id=None,
            user=EVAL_USER,
        ):
            if event.get("type") == "token" and ttfb_ms is None:
                ttfb_ms = round((perf_counter() - started) * 1000, 2)
            if event.get("type") == "done":
                done_data = event.get("data") or {}
        answer = str(done_data.get("answer") or "")
        evidence = done_data.get("evidence") or []
        judge = judge_chat(
            question=case["question"],
            answer=answer,
            evidence_count=len(evidence),
            route=str(done_data.get("route") or "general"),
            web_searched=bool(done_data.get("webSearched")),
            expected=case.get("expected") or {},
            rubric=case.get("rubric") or {},
        )
        return {
            "case_id": case["case_id"],
            "judge": {
                "score": judge.score,
                "subscores": judge.subscores,
                "pass": judge.passed,
                "reason": judge.reason,
            },
            "meta": {
                "conversationId": done_data.get("conversationId"),
                "route": done_data.get("route"),
                "citationCount": len(evidence),
                "ttfbMs": ttfb_ms or 0.0,
                "notebookTitle": notebook["title"],
            },
            "output": {
                "answer": answer,
                "evidence": evidence[:5],
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook["id"])


async def run_pipeline_case(pipeline: str, case: dict[str, Any]) -> dict[str, Any]:
    async for session in get_session_manager().session():
        if pipeline == "search":
            return await _run_search_case(session, case)
        if pipeline == "ingest":
            return await _run_ingest_case(session, case)
        if pipeline == "summary":
            return await _run_summary_case(session, case)
        if pipeline == "chat":
            return await _run_chat_case(session, case)
    raise RuntimeError("session unavailable")


def _normalize_case_input(pipeline: str, case: dict[str, Any]) -> dict[str, Any]:
    if pipeline == "search":
        return {
            "query": case.get("query"),
            "mode": case.get("mode"),
            "preferred_sites": case.get("preferred_sites") or [],
        }
    if pipeline == "ingest":
        return {
            "artifact_type": case.get("artifact_type"),
            "title": case.get("title"),
            "content_preview": str(case.get("content") or "")[:240],
        }
    if pipeline == "summary":
        return {
            "title": case.get("title"),
            "language": case.get("language", "中文"),
            "content_preview": str(case.get("content") or "")[:240],
        }
    return {
        "question": case.get("question"),
    }


def _summarize_events(pipeline: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    stage_samples: dict[str, list[float]] = defaultdict(list)
    counters: Counter[str] = Counter()
    token_cost = 0

    for event in events:
        name = str(event.get("event") or "")
        duration = event.get("duration_ms")
        stage = str(event.get("stage") or "")

        if pipeline == "search":
            if name == "search_stage" and isinstance(duration, (int, float)):
                stage_samples[stage].append(float(duration))
            if name == "search_dedup":
                counters["dedup_hits"] += int(event.get("count", 1))
            if name == "search_empty_slate":
                counters["empty_result_count"] += int(event.get("count", 1))
            if name == "search_stage" and stage == "expand_recall":
                counters["expand_recall_triggers"] += 1

        if pipeline == "ingest":
            if name == "ingest_stage" and isinstance(duration, (int, float)):
                stage_samples[stage].append(float(duration))
            if name == "ingest_parse_success":
                if event.get("result") == "ok":
                    counters["parse_success"] += int(event.get("count", 1))
                else:
                    counters["parse_failure"] += int(event.get("count", 1))
            if name == "ingest_fallback":
                counters["fallback_count"] += int(event.get("count", 1))
            if name == "ingest_block_completeness":
                block = str(event.get("block_type") or "unknown")
                counters[f"block_{block}"] += int(event.get("count", 1))

        if pipeline == "summary":
            if name == "summary_stage" and isinstance(duration, (int, float)):
                stage_samples[stage].append(float(duration))
            if name == "summary_cache_hit":
                counters["cache_hit"] += int(event.get("count", 1))
            if name == "summary_route_mix":
                route = str(event.get("route") or "unknown")
                counters[f"route_{route}"] += int(event.get("count", 1))
            if name == "summary_fallback":
                counters["fallback_count"] += int(event.get("count", 1))
            if name == "summary_stage" and stage == "validate" and event.get("status") == "error":
                counters["retry_like_error"] += 1
            if name == "summary_token_cost":
                token_cost += int(event.get("tokens") or 0)

        if pipeline == "chat":
            if name == "chat_stage" and isinstance(duration, (int, float)):
                stage_name = "answer_stream" if stage == "answer_generator" else stage
                stage_samples[stage_name].append(float(duration))
            if name == "retrieval_stage" and isinstance(duration, (int, float)):
                stage_samples[f"retrieval_{stage}"].append(float(duration))
            if name == "chat_web_search":
                reason = str(event.get("reason") or "").strip().lower()
                if reason and reason != "not_needed":
                    counters["web_search_trigger"] += int(event.get("count", 1))
            if name == "chat_citation_count":
                counters["citation_total"] += int(event.get("count", 0))
                if int(event.get("count", 0)) > 0:
                    counters["citation_positive_attempts"] += 1
            if name == "chat_token_cost":
                token_cost += int(event.get("tokens") or 0)

    return {
        "stage_samples": {key: values for key, values in stage_samples.items()},
        "counters": dict(counters),
        "token_cost": token_cost,
    }


def _aggregate_case_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(item["duration_ms"]) for item in attempts]
    ttfb_values = [
        float(item["meta"].get("ttfbMs"))
        for item in attempts
        if isinstance(item.get("meta"), dict) and isinstance(item["meta"].get("ttfbMs"), (int, float))
    ]
    scores = [float(item["judge"]["score"]) for item in attempts]
    pass_count = sum(1 for item in attempts if item["judge"]["pass"])
    errors = [item.get("error") for item in attempts if item.get("error")]
    return {
        "attempts": len(attempts),
        "success_rate": round(sum(1 for item in attempts if item.get("success")) / max(len(attempts), 1), 4),
        "judge_pass_rate": round(pass_count / max(len(attempts), 1), 4),
        "judge_score": _distribution(scores),
        "latency_ms": _distribution(durations),
        "ttfb_ms": _distribution(ttfb_values) if ttfb_values else {"samples": 0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0},
        "error_count": len(errors),
        "latest_error": errors[-1] if errors else None,
    }


def _aggregate_pipeline(
    *,
    pipeline: str,
    case_results: list[dict[str, Any]],
    repeat: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    all_attempts = [attempt for case in case_results for attempt in case["attempts"]]
    durations = [float(item["duration_ms"]) for item in all_attempts]
    ttfb_values = [
        float(item["meta"].get("ttfbMs"))
        for item in all_attempts
        if isinstance(item.get("meta"), dict) and isinstance(item["meta"].get("ttfbMs"), (int, float))
    ]
    score_values = [float(item["judge"]["score"]) for item in all_attempts]
    pass_rate = sum(1 for item in all_attempts if item["judge"]["pass"]) / max(len(all_attempts), 1)
    success_rate = sum(1 for item in all_attempts if item.get("success")) / max(len(all_attempts), 1)

    stage_samples: dict[str, list[float]] = defaultdict(list)
    counter_totals: Counter[str] = Counter()
    subscore_values: dict[str, list[float]] = defaultdict(list)
    failure_cases: list[dict[str, Any]] = []
    token_cost_total = 0
    remark_fixes_total = 0
    notebook_title_missing = 0
    citation_positive_attempts = 0

    for case in case_results:
        for attempt in case["attempts"]:
            telemetry = attempt.get("telemetry") or {}
            for stage, values in (telemetry.get("stage_samples") or {}).items():
                stage_samples[stage].extend(float(value) for value in values)
            counter_totals.update(telemetry.get("counters") or {})
            token_cost_total += int(telemetry.get("token_cost") or 0)
            meta = attempt.get("meta") or {}
            remark_fixes_total += int(meta.get("remarkFixesApplied") or 0)
            citation_positive_attempts += 1 if int(meta.get("citationCount") or 0) > 0 else 0
            if not str(meta.get("notebookTitle") or "").strip():
                notebook_title_missing += 1
            for key, value in (attempt["judge"].get("subscores") or {}).items():
                subscore_values[key].append(float(value))
            if attempt.get("error") or not attempt["judge"]["pass"]:
                failure_cases.append(
                    {
                        "case_id": case["case_id"],
                        "repeat_index": attempt["repeat_index"],
                        "judge_pass": attempt["judge"]["pass"],
                        "judge_reason": attempt["judge"]["reason"],
                        "error": attempt.get("error"),
                        "langsmith_url": (attempt.get("langsmith") or {}).get("run_url"),
                    }
                )

    total_attempts = max(len(all_attempts), 1)
    cache_hit_rate = round(counter_totals.get("cache_hit", 0) / total_attempts, 4)
    citation_pass_rate = round(citation_positive_attempts / total_attempts, 4)
    web_search_trigger_rate = round(counter_totals.get("web_search_trigger", 0) / total_attempts, 4)
    parse_failure_rate = round(counter_totals.get("parse_failure", 0) / total_attempts, 4)
    retry_count = int(counter_totals.get("retry_like_error", 0))

    stage_metrics = {stage: _distribution(values) for stage, values in sorted(stage_samples.items())}
    subscore_stats: dict[str, dict[str, float | int]] = {}
    data_quality_warnings: list[str] = []
    for key, values in sorted(subscore_values.items()):
        if not values:
            continue
        avg = float(statistics.fmean(values))
        std = float(statistics.pstdev(values)) if len(values) > 1 else 0.0
        min_value = float(min(values))
        max_value = float(max(values))
        sat_high_rate = float(sum(1 for value in values if value >= 0.95) / len(values))
        sat_low_rate = float(sum(1 for value in values if value <= 0.05) / len(values))
        subscore_stats[key] = {
            "samples": len(values),
            "avg": round(avg, 4),
            "stddev": round(std, 4),
            "min": round(min_value, 4),
            "max": round(max_value, 4),
            "sat_high_rate": round(sat_high_rate, 4),
            "sat_low_rate": round(sat_low_rate, 4),
        }
        if sat_high_rate >= 0.8 and std <= 0.03 and avg >= 0.95:
            data_quality_warnings.append(f"{key} 长期接近满分，缺少区分度（sat_high={sat_high_rate:.2f}）")
        if sat_low_rate >= 0.8 and std <= 0.03 and avg <= 0.05:
            data_quality_warnings.append(f"{key} 长期接近 0 分，缺少区分度（sat_low={sat_low_rate:.2f}）")
    if pipeline == "search":
        relevance_stats = subscore_stats.get("relevance") or {}
        authority_stats = subscore_stats.get("authority") or {}
        if relevance_stats and float(relevance_stats.get("avg", 0.0)) >= 0.95 and float(relevance_stats.get("stddev", 1.0)) <= 0.03:
            data_quality_warnings.append("search.relevance 过于饱和，建议检查 query 匹配与语义判别策略。")
        if authority_stats and float(authority_stats.get("avg", 1.0)) <= 0.25:
            data_quality_warnings.append("search.authority 偏低，建议补充权威域名映射与来源类型识别。")

    quality = {
        "avg_score": round(statistics.fmean(score_values), 4) if score_values else 0.0,
        "stddev": round(statistics.pstdev(score_values), 4) if len(score_values) > 1 else 0.0,
        "pass_rate": round(pass_rate, 4),
        "subscores": {
            key: round(statistics.fmean(values), 4)
            for key, values in sorted(subscore_values.items())
            if values
        },
        "subscore_stats": subscore_stats,
        "warnings": data_quality_warnings,
    }
    summary = {
        "total_cases": len(case_results),
        "repeat_per_case": repeat,
        "total_attempts": len(all_attempts),
        "success_rate": round(success_rate, 4),
        "latency_ms": _distribution(durations),
        "ttfb_ms": _distribution(ttfb_values) if ttfb_values else {"samples": 0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0},
        "cache_hit_rate": cache_hit_rate,
        "retry_count": retry_count,
        "citation_pass_rate": citation_pass_rate,
        "web_search_trigger_rate": web_search_trigger_rate,
        "parse_failure_rate": parse_failure_rate,
        "notebook_title_missing_rate": round(notebook_title_missing / total_attempts, 4),
        "quality": quality,
        "token_cost": {
            "total": token_cost_total,
            "avg": round(token_cost_total / max(len(all_attempts), 1), 2),
            "estimated_usd": round((token_cost_total / 1000.0) * 0.0003, 6),
        },
        "remark_fixes_total": remark_fixes_total,
        "counters": dict(counter_totals),
        "data_quality_warnings": data_quality_warnings,
    }
    return summary, stage_metrics, quality, failure_cases


def _build_baseline_diff(
    pipeline: str,
    profile: str,
    current_bench_run_id: str,
    current_summary: dict[str, Any],
) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for path in RUNS_DIR.glob("*/report.json"):
        try:
            report = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            continue
        if report.get("pipeline") != pipeline:
            continue
        if report.get("profile") != profile:
            continue
        if report.get("bench_run_id") == current_bench_run_id:
            continue
        if "summary" not in report:
            continue
        reports.append(report)

    if not reports:
        return {"available": False}

    reports.sort(key=lambda item: item.get("generated_at", ""), reverse=True)
    baseline = reports[0]
    base_summary = baseline.get("summary") or {}
    base_latency = base_summary.get("latency_ms") or {}
    base_quality = base_summary.get("quality") or {}
    current_latency = current_summary.get("latency_ms") or {}
    current_quality = current_summary.get("quality") or {}
    return {
        "available": True,
        "bench_run_id": baseline.get("bench_run_id"),
        "metrics": {
            "success_rate_delta": round(
                float(current_summary.get("success_rate") or 0.0) - float(base_summary.get("success_rate") or 0.0),
                4,
            ),
            "latency_p95_delta_ms": round(
                float(current_latency.get("p95") or 0.0) - float(base_latency.get("p95") or 0.0),
                2,
            ),
            "quality_avg_delta": round(
                float(current_quality.get("avg_score") or 0.0) - float(base_quality.get("avg_score") or 0.0),
                4,
            ),
        },
    }


async def run_pipeline_benchmark(
    *,
    pipeline: str,
    profile: str,
    run_started_at: datetime,
    bench_run_id: str,
    app_version: str,
) -> dict[str, Any]:
    prompt_version = PROMPT_VERSION_BY_PIPELINE[pipeline]
    cases = load_cases(pipeline, profile)
    repeat = _resolve_repeat(profile, cases)
    langsmith_context = init_langsmith_context(
        bench_run_id=bench_run_id,
        pipeline=pipeline,
        profile=profile,
        app_version=app_version,
        prompt_version=prompt_version,
        cases=cases,
    )

    case_results: list[dict[str, Any]] = []
    for case in cases:
        attempts: list[dict[str, Any]] = []
        case_input = _normalize_case_input(pipeline, case)
        expected = case.get("expected") or {}
        tags = case.get("tags") or []
        for repeat_index in range(1, repeat + 1):
            events: list[dict[str, Any]] = []
            token = bind_eval_event_sink(events.append)
            started_at = datetime.now(UTC)
            t0 = perf_counter()
            error_message: str | None = None
            result: dict[str, Any]
            success = False
            try:
                result = await run_pipeline_case(pipeline, case)
                success = True
            except Exception as exc:  # noqa: BLE001
                error_message = str(exc)
                result = {
                    "case_id": case["case_id"],
                    "judge": {
                        "score": 0.0,
                        "subscores": {},
                        "pass": False,
                        "reason": "runtime_error",
                    },
                    "meta": {},
                    "output": {},
                }
            finally:
                reset_eval_event_sink(token)
            ended_at = datetime.now(UTC)
            duration_ms = round((perf_counter() - t0) * 1000, 2)
            telemetry = _summarize_events(pipeline, events)
            langsmith = record_case_attempt(
                langsmith_context,
                bench_run_id=bench_run_id,
                pipeline=pipeline,
                profile=profile,
                case_id=case["case_id"],
                repeat_index=repeat_index,
                case_input=case_input,
                expected=expected,
                judge=result.get("judge"),
                output=result.get("output"),
                error_message=error_message,
                tags=tags,
                app_version=app_version,
                prompt_version=prompt_version,
                started_at=started_at,
                ended_at=ended_at,
            )
            attempts.append(
                {
                    "repeat_index": repeat_index,
                    "started_at": started_at.isoformat(),
                    "ended_at": ended_at.isoformat(),
                    "duration_ms": duration_ms,
                    "success": success,
                    "judge": result["judge"],
                    "meta": result.get("meta") or {},
                    "output": result.get("output") or {},
                    "error": error_message,
                    "telemetry": telemetry,
                    "langsmith": langsmith,
                }
            )
        case_results.append(
            {
                "case_id": case["case_id"],
                "tags": tags,
                "input": case_input,
                "expected": expected,
                "rubric": case.get("rubric") or {},
                "evidence": case.get("evidence") or [],
                "attempts": attempts,
                "aggregate": _aggregate_case_attempts(attempts),
            }
        )

    summary, stage_metrics, quality, failure_cases = _aggregate_pipeline(
        pipeline=pipeline,
        case_results=case_results,
        repeat=repeat,
    )
    baseline_diff = _build_baseline_diff(
        pipeline,
        profile,
        bench_run_id,
        summary,
    )

    report = {
        "bench_run_id": bench_run_id,
        "pipeline": pipeline,
        "profile": profile,
        "app_version": app_version,
        "prompt_version": prompt_version,
        "generated_at": _now_iso(),
        "run_started_at": run_started_at.isoformat(),
        "summary": summary,
        "stage_metrics": stage_metrics,
        "quality": quality,
        "baseline_diff": baseline_diff,
        "langsmith": langsmith_context.to_report(),
        "cases": case_results,
        "failures": failure_cases,
    }
    finalize_langsmith_context(
        langsmith_context,
        summary={
            "success_rate": summary["success_rate"],
            "quality_avg_score": (summary.get("quality") or {}).get("avg_score"),
            "attempts": summary["total_attempts"],
        },
    )
    write_report_bundle(RUNS_DIR / bench_run_id, report)
    return report


def _build_all_report(bench_run_id: str, profile: str, reports: list[dict[str, Any]], app_version: str) -> dict[str, Any]:
    success_rates = [float((item.get("summary") or {}).get("success_rate") or 0.0) for item in reports]
    quality_scores = [float((item.get("summary") or {}).get("quality", {}).get("avg_score") or 0.0) for item in reports]
    latencies = [float((item.get("summary") or {}).get("latency_ms", {}).get("p95") or 0.0) for item in reports]
    combined = {
        "bench_run_id": bench_run_id,
        "pipeline": "all",
        "profile": profile,
        "app_version": app_version,
        "generated_at": _now_iso(),
        "summary": {
            "pipelines": len(reports),
            "success_rate_avg": round(statistics.fmean(success_rates), 4) if success_rates else 0.0,
            "quality_avg": round(statistics.fmean(quality_scores), 4) if quality_scores else 0.0,
            "latency_p95_avg_ms": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        },
        "pipelines": [
            {
                "pipeline": item["pipeline"],
                "bench_run_id": item["bench_run_id"],
                "summary": item.get("summary") or {},
                "quality": item.get("quality") or {},
                "langsmith": item.get("langsmith") or {},
            }
            for item in reports
        ],
    }
    write_report_bundle(RUNS_DIR / bench_run_id, combined)
    return combined


async def main_async(pipeline: str, profile: str) -> dict[str, Any]:
    configure_langsmith()
    run_started_at = datetime.now(UTC)
    app_version = _git_sha()
    if pipeline == "all":
        parent_bench_run_id = f"all-{profile}-{run_started_at.strftime('%Y%m%d%H%M%S')}"
        reports: list[dict[str, Any]] = []
        for single_pipeline in PIPELINES:
            bench_run_id = f"{single_pipeline}-{profile}-{run_started_at.strftime('%Y%m%d%H%M%S')}"
            reports.append(
                await run_pipeline_benchmark(
                    pipeline=single_pipeline,
                    profile=profile,
                    run_started_at=run_started_at,
                    bench_run_id=bench_run_id,
                    app_version=app_version,
                )
            )
        return _build_all_report(parent_bench_run_id, profile, reports, app_version)

    bench_run_id = f"{pipeline}-{profile}-{run_started_at.strftime('%Y%m%d%H%M%S')}"
    return await run_pipeline_benchmark(
        pipeline=pipeline,
        profile=profile,
        run_started_at=run_started_at,
        bench_run_id=bench_run_id,
        app_version=app_version,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pipeline", choices=["search", "ingest", "summary", "chat", "all"])
    parser.add_argument("profile", default="smoke")
    args = parser.parse_args()
    asyncio.run(main_async(args.pipeline, args.profile))


if __name__ == "__main__":
    main()
