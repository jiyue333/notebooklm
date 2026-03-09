from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RRFHit:
    item_id: str
    score: float
    matched_by: list[str]
    ranks: dict[str, int]


def rrf_fuse(rankings: list[list[str]], *, k: int = 60, limit: int = 5) -> list[str]:
    return [
        hit.item_id
        for hit in rrf_fuse_with_details(
            {f"ranking_{index}": ranking for index, ranking in enumerate(rankings, start=1)},
            k=k,
            limit=limit,
        )
    ]


def rrf_fuse_with_details(
    rankings: dict[str, list[str]],
    *,
    k: int = 60,
    limit: int = 5,
) -> list[RRFHit]:
    scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    rank_positions: dict[str, dict[str, int]] = {}

    for source_name, ranking in rankings.items():
        for index, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + index)
            sources.setdefault(item_id, set()).add(source_name)
            rank_positions.setdefault(item_id, {})[source_name] = index

    sorted_items = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        RRFHit(
            item_id=item_id,
            score=score,
            matched_by=sorted(sources.get(item_id, set())),
            ranks=rank_positions.get(item_id, {}),
        )
        for item_id, score in sorted_items
    ]
