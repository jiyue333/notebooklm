from __future__ import annotations

import re
from typing import Iterable


TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def rouge_1_f1(reference: str, prediction: str) -> float:
    ref_tokens = tokenize(reference)
    pred_tokens = tokenize(prediction)
    if not ref_tokens or not pred_tokens:
        return 0.0
    overlap = _multiset_overlap(ref_tokens, pred_tokens)
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def rouge_l_f1(reference: str, prediction: str) -> float:
    ref_tokens = tokenize(reference)
    pred_tokens = tokenize(prediction)
    if not ref_tokens or not pred_tokens:
        return 0.0
    lcs = _lcs_length(ref_tokens, pred_tokens)
    precision = lcs / len(pred_tokens)
    recall = lcs / len(ref_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def exact_match_rate(expected: dict[str, str], actual: dict[str, str]) -> float:
    if not expected:
        return 0.0
    matched = 0
    for key, value in expected.items():
        actual_value = actual.get(key)
        if actual_value is not None and str(actual_value).strip() == str(value).strip():
            matched += 1
    return matched / len(expected)


def phrase_hit_rate(required_phrases: list[str], text: str) -> float:
    if not required_phrases:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for phrase in required_phrases if phrase.lower() in lowered)
    return hits / len(required_phrases)


def bertscore_f1_many(
    references: Iterable[str],
    predictions: Iterable[str],
    *,
    model_type: str = "bert-base-multilingual-cased",
) -> list[float]:
    try:
        from bert_score import score as bert_score
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "bert-score is not installed. Install backend eval extras before using --with-bert-score."
        ) from exc

    ref_list = [str(item) for item in references]
    pred_list = [str(item) for item in predictions]
    if not ref_list or not pred_list:
        return []
    _, _, f1 = bert_score(
        pred_list,
        ref_list,
        model_type=model_type,
        verbose=False,
        rescale_with_baseline=False,
    )
    return [float(value) for value in f1.tolist()]


def _multiset_overlap(left: list[str], right: list[str]) -> int:
    counts: dict[str, int] = {}
    for token in left:
        counts[token] = counts.get(token, 0) + 1
    overlap = 0
    for token in right:
        available = counts.get(token, 0)
        if available > 0:
            counts[token] = available - 1
            overlap += 1
    return overlap


def _lcs_length(left: list[str], right: list[str]) -> int:
    previous = [0] * (len(right) + 1)
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(current[-1], previous[index]))
        previous = current
    return previous[-1]
