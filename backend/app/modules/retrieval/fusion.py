from __future__ import annotations


def rrf_fuse(rankings: list[list[str]], *, k: int = 60, limit: int = 5) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for index, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + index)
    return [
        item_id
        for item_id, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]
