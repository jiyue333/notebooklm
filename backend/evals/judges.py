from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class JudgeResult:
    score: float
    subscores: dict[str, float]
    passed: bool
    reason: str


def judge_search(result_count: int, min_results: int) -> JudgeResult:
    passed = result_count >= min_results
    score = 1.0 if passed else 0.0
    return JudgeResult(score=score, subscores={"result_count": float(result_count)}, passed=passed, reason="结果数量达标" if passed else "结果数量不足")


def judge_ingest(chunk_count: int, min_chunks: int) -> JudgeResult:
    passed = chunk_count >= min_chunks
    score = 1.0 if passed else 0.0
    return JudgeResult(score=score, subscores={"chunk_count": float(chunk_count)}, passed=passed, reason="分块数量达标" if passed else "分块数量不足")


def judge_text_length(text: str, min_chars: int, label: str) -> JudgeResult:
    length = len((text or '').strip())
    passed = length >= min_chars
    score = 1.0 if passed else 0.0
    return JudgeResult(score=score, subscores={"text_length": float(length)}, passed=passed, reason=f"{label}长度达标" if passed else f"{label}长度不足")
