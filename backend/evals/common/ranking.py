from __future__ import annotations

from math import log2


def recall_at_k(predicted: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = len(set(predicted[:k]) & relevant)
    return hits / len(relevant)


def precision_at_k(predicted: list[str], relevant: set[str], k: int) -> float:
    top_k = predicted[:k]
    if not top_k:
        return 0.0
    hits = len(set(top_k) & relevant)
    return hits / len(top_k)


def reciprocal_rank(predicted: list[str], relevant: set[str]) -> float:
    for index, doc_id in enumerate(predicted, start=1):
        if doc_id in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(predicted: list[str], graded_relevance: dict[str, float], k: int) -> float:
    dcg = 0.0
    for index, doc_id in enumerate(predicted[:k], start=1):
        relevance = graded_relevance.get(doc_id, 0.0)
        if relevance:
            dcg += relevance / log2(index + 1)
    ideal_scores = sorted((score for score in graded_relevance.values() if score > 0), reverse=True)[:k]
    if not ideal_scores:
        return 0.0
    idcg = sum(score / log2(index + 1) for index, score in enumerate(ideal_scores, start=1))
    return dcg / idcg if idcg else 0.0
