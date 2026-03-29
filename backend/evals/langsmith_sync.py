from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import sleep
from typing import Any
from uuid import uuid4

import structlog
from langsmith import Client

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class LangSmithContext:
    enabled: bool
    message: str
    dataset_name: str | None = None
    dataset_id: str | None = None
    project_name: str | None = None
    project_id: str | None = None
    project_url: str | None = None
    baseline_project_name: str | None = None
    baseline_project_id: str | None = None
    error: str | None = None
    _client: Client | None = field(default=None, repr=False)

    def to_report(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "message": self.message,
            "dataset": {
                "name": self.dataset_name,
                "id": self.dataset_id,
            },
            "experiment": {
                "name": self.project_name,
                "id": self.project_id,
                "url": self.project_url,
            },
            "baseline": {
                "name": self.baseline_project_name,
                "id": self.baseline_project_id,
            },
            "error": self.error,
        }


def init_langsmith_context(
    *,
    bench_run_id: str,
    pipeline: str,
    profile: str,
    app_version: str,
    prompt_version: str,
    cases: list[dict[str, Any]],
) -> LangSmithContext:
    settings = get_settings()
    if not settings.langsmith_enabled:
        return LangSmithContext(enabled=False, message="LANGSMITH 未启用（langsmith_enabled=false）")
    if not settings.langsmith_api_key:
        return LangSmithContext(enabled=False, message="LANGSMITH 未配置 API Key")

    try:
        client = Client(
            api_url=settings.langsmith_endpoint,
            api_key=settings.langsmith_api_key,
            workspace_id=settings.langsmith_workspace_id,
        )
        dataset_name = f"notebooklm-eval-{pipeline}-{profile}"
        dataset = _ensure_dataset(client, dataset_name=dataset_name)
        _sync_dataset_examples(
            client,
            dataset_id=str(dataset.id),
            pipeline=pipeline,
            profile=profile,
            cases=cases,
        )
        project_name = f"notebooklm-eval-{bench_run_id}"
        project = client.create_project(
            project_name=project_name,
            description=f"NotebookLM eval run {bench_run_id}",
            upsert=True,
            reference_dataset_id=dataset.id,
            metadata={
                "bench_run_id": bench_run_id,
                "pipeline": pipeline,
                "profile": profile,
                "app_version": app_version,
                "prompt_version": prompt_version,
            },
        )
        baseline_project = _pick_baseline_project(
            client,
            dataset_id=str(dataset.id),
            exclude_project_name=project_name,
            pipeline=pipeline,
            profile=profile,
        )
        return LangSmithContext(
            enabled=True,
            message="LangSmith dataset + experiment 已同步",
            dataset_name=dataset_name,
            dataset_id=str(dataset.id),
            project_name=project_name,
            project_id=str(project.id),
            project_url=_build_project_url(
                endpoint=settings.langsmith_endpoint,
                project_id=str(project.id),
                workspace_id=settings.langsmith_workspace_id,
            ),
            baseline_project_name=baseline_project.get("name") if baseline_project else None,
            baseline_project_id=baseline_project.get("id") if baseline_project else None,
            _client=client,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("eval.langsmith_init_failed", error=str(exc))
        return LangSmithContext(
            enabled=False,
            message="LangSmith 初始化失败，已回退到本地评测",
            error=str(exc),
        )


def record_case_attempt(
    ctx: LangSmithContext,
    *,
    bench_run_id: str,
    pipeline: str,
    profile: str,
    case_id: str,
    repeat_index: int,
    case_input: dict[str, Any],
    expected: dict[str, Any] | None,
    judge: dict[str, Any] | None,
    output: dict[str, Any] | None,
    error_message: str | None,
    tags: list[str] | None,
    app_version: str,
    prompt_version: str,
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, str | None]:
    if not ctx.enabled or not ctx._client or not ctx.project_name:
        return {"run_id": None, "run_url": None}

    run_id = str(uuid4())
    metadata = {
        "bench_run_id": bench_run_id,
        "pipeline": pipeline,
        "profile": profile,
        "case_id": case_id,
        "repeat_index": repeat_index,
        "app_version": app_version,
        "prompt_version": prompt_version,
        "tags": tags or [],
    }
    try:
        ctx._client.create_run(
            id=run_id,
            project_name=ctx.project_name,
            name=f"{pipeline}:{case_id}:r{repeat_index}",
            run_type="chain",
            inputs={
                "case_id": case_id,
                "input": case_input,
                "expected": expected or {},
            },
            outputs=output or {"judge": judge or {}},
            error=error_message,
            start_time=started_at,
            end_time=ended_at,
            extra={"metadata": metadata},
            tags=[
                f"bench_run_id:{bench_run_id}",
                f"pipeline:{pipeline}",
                f"profile:{profile}",
                f"case_id:{case_id}",
                f"app_version:{app_version}",
                f"prompt_version:{prompt_version}",
            ],
        )
        if judge:
            ctx._client.create_feedback(
                run_id=run_id,
                key="lite_model_judge",
                score=judge.get("score"),
                comment=judge.get("reason"),
                source_info={"subscores": judge.get("subscores") or {}},
                session_id=ctx.project_id,
            )
            for sub_key, sub_value in (judge.get("subscores") or {}).items():
                ctx._client.create_feedback(
                    run_id=run_id,
                    key=f"judge_{sub_key}",
                    score=sub_value,
                    session_id=ctx.project_id,
                )

        run_url = None
        for _ in range(3):
            try:
                run = ctx._client.read_run(run_id)
                run_url = ctx._client.get_run_url(run=run, project_name=ctx.project_name)
                break
            except Exception:  # noqa: BLE001
                sleep(0.4)
        return {"run_id": run_id, "run_url": run_url}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "eval.langsmith_case_record_failed",
            project=ctx.project_name,
            case_id=case_id,
            repeat_index=repeat_index,
            error=str(exc),
        )
        return {"run_id": run_id, "run_url": None}


def finalize_langsmith_context(
    ctx: LangSmithContext,
    *,
    summary: dict[str, Any],
) -> None:
    if not ctx.enabled or not ctx._client or not ctx.project_id:
        return
    try:
        ctx._client.update_project(
            project_id=ctx.project_id,
            metadata={
                **(summary or {}),
                "finalized_at": datetime.now(UTC).isoformat(),
            },
            end_time=datetime.now(UTC),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("eval.langsmith_finalize_failed", project_id=ctx.project_id, error=str(exc))


def _ensure_dataset(client: Client, *, dataset_name: str):
    if client.has_dataset(dataset_name=dataset_name):
        return client.read_dataset(dataset_name=dataset_name)
    return client.create_dataset(
        dataset_name=dataset_name,
        description=f"NotebookLM eval dataset ({dataset_name})",
    )


def _sync_dataset_examples(
    client: Client,
    *,
    dataset_id: str,
    pipeline: str,
    profile: str,
    cases: list[dict[str, Any]],
) -> None:
    existing_ids = [str(example.id) for example in client.list_examples(dataset_id=dataset_id)]
    if existing_ids:
        client.delete_examples(existing_ids)

    examples: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id") or "")
        payload = {k: v for k, v in case.items() if k not in {"expected", "rubric", "evidence"}}
        examples.append(
            {
                "inputs": {
                    "case_id": case_id,
                    "input": payload,
                },
                "outputs": {
                    "expected": case.get("expected") or {},
                    "rubric": case.get("rubric") or {},
                },
                "metadata": {
                    "pipeline": pipeline,
                    "profile": profile,
                    "case_id": case_id,
                    "tags": case.get("tags") or [],
                    "evidence": case.get("evidence") or [],
                },
            }
        )
    if examples:
        client.create_examples(dataset_id=dataset_id, examples=examples)


def _pick_baseline_project(
    client: Client,
    *,
    dataset_id: str,
    exclude_project_name: str,
    pipeline: str,
    profile: str,
) -> dict[str, str] | None:
    candidates: list[Any] = []
    for project in client.list_projects(reference_dataset_id=dataset_id, limit=50):
        if project.name == exclude_project_name:
            continue
        meta = project.metadata or {}
        if meta.get("pipeline") != pipeline or meta.get("profile") != profile:
            continue
        candidates.append(project)
    if not candidates:
        return None
    candidates.sort(
        key=lambda proj: getattr(proj, "end_time", None)
        or getattr(proj, "start_time", None)
        or datetime.fromtimestamp(0, tz=UTC),
        reverse=True,
    )
    baseline = candidates[0]
    return {"id": str(baseline.id), "name": baseline.name}


def _build_project_url(*, endpoint: str, project_id: str, workspace_id: str | None) -> str:
    root = endpoint.rstrip("/")
    if "api.smith.langchain.com" in root:
        root = "https://smith.langchain.com"
    elif root.endswith("/api"):
        root = root[:-4]
    if workspace_id:
        return f"{root}/o/{workspace_id}/projects/p/{project_id}"
    return f"{root}/projects/p/{project_id}"
