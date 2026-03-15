"""Stage B – Query Lattice Generation.

Expands a single user query into a family of complementary queries,
each targeting a different coverage facet.  The lattice ensures the
final slate is *coverage-aware*, not a bag of near-duplicate results.

Fast mode:  2-3 families  (canonical + 1-2 supplements)
Deep mode:  5-7 families  (full facet coverage)
"""

from __future__ import annotations

from app.modules.search.pipeline.types import (
    CoverageFacet,
    NotebookContext,
    QueryFamily,
    QueryRole,
    TaskSpec,
    TimeSensitivity,
)

# Maps each coverage facet to a query-building strategy.
_FACET_TO_ROLE: dict[CoverageFacet, QueryRole] = {
    CoverageFacet.OVERVIEW: QueryRole.CANONICAL,
    CoverageFacet.RECENT: QueryRole.RECENT,
    CoverageFacet.PRIMARY: QueryRole.PRIMARY,
    CoverageFacet.CRITIQUE: QueryRole.CRITICAL,
    CoverageFacet.IMPLEMENTATION: QueryRole.IMPLEMENTATION,
}

# Suffix templates per role that get appended to the base query.
_ROLE_SUFFIXES: dict[QueryRole, list[str]] = {
    QueryRole.CANONICAL: [""],
    QueryRole.TERMINOLOGY: [
        "synonyms alternatives related concepts",
        "adjacent terminology equivalent terms neighboring topics",
    ],
    QueryRole.PRIMARY: [
        "official documentation specification paper",
        "technical report whitepaper benchmark",
        "author original source publication reference implementation",
    ],
    QueryRole.RECENT: [
        "latest 2025 2026 update",
        "recent news announcement release",
        "state of the art latest benchmark update",
    ],
    QueryRole.CRITICAL: [
        "limitations challenges risks criticism",
        "failure evaluation drawbacks",
        "critical review counterexample tradeoffs",
    ],
    QueryRole.IMPLEMENTATION: [
        "architecture implementation case study deployment",
        "tutorial how to build example",
        "production stack integration reference architecture",
    ],
    QueryRole.NOTEBOOK_GAP: [],
}

_MAX_FAMILIES_FAST = 4
_MAX_FAMILIES_DEEP = 9

# Per-family result caps (keeps total recall within budget).
_RESULTS_PER_FAMILY_FAST = 8
_RESULTS_PER_FAMILY_DEEP = 12


def generate_lattice(
    task: TaskSpec,
    user_query: str,
    *,
    search_mode: str,
    notebook: NotebookContext,
    freshness_hours: int | None = None,
) -> list[QueryFamily]:
    """Return an ordered list of ``QueryFamily`` covering the task facets."""

    is_deep = search_mode == "deep"
    max_families = _MAX_FAMILIES_DEEP if is_deep else _MAX_FAMILIES_FAST
    results_per = _RESULTS_PER_FAMILY_DEEP if is_deep else _RESULTS_PER_FAMILY_FAST

    families: list[QueryFamily] = []

    # 1. Always start with the canonical query.
    families.append(
        QueryFamily(
            role=QueryRole.CANONICAL,
            query_text=user_query.strip(),
            max_results=results_per,
            freshness_hours=freshness_hours,
        )
    )

    # 2. Walk the requested coverage facets and generate one family each.
    reserved_slots = 0
    if is_deep:
        reserved_slots += 1  # terminology
        if notebook.existing_article_titles:
            reserved_slots += 1  # notebook-gap

    for facet in task.coverage_facets:
        if len(families) >= max_families - reserved_slots:
            break
        role = _FACET_TO_ROLE.get(facet)
        if role is None or role == QueryRole.CANONICAL:
            continue  # already covered
        expanded_queries = _expand_queries(user_query, role, deep_mode=is_deep)
        if not expanded_queries:
            continue
        for expanded in expanded_queries:
            if len(families) >= max_families - reserved_slots:
                break
            families.append(
                QueryFamily(
                    role=role,
                    query_text=expanded,
                    max_results=results_per,
                    freshness_hours=_role_freshness(role, freshness_hours, task.time_sensitivity),
                )
            )

    # 3. In deep mode, ensure terminology expansion exists.
    if is_deep and len(families) < max_families and not _has_role(families, QueryRole.TERMINOLOGY):
        expanded_queries = _expand_queries(user_query, QueryRole.TERMINOLOGY, deep_mode=True)
        if expanded_queries:
            families.append(
                QueryFamily(
                    role=QueryRole.TERMINOLOGY,
                    query_text=expanded_queries[0],
                    max_results=results_per,
                    freshness_hours=freshness_hours,
                )
            )

    # 4. In deep mode, add notebook-gap query when notebook has articles.
    if (
        is_deep
        and len(families) < max_families
        and notebook.existing_article_titles
        and not _has_role(families, QueryRole.NOTEBOOK_GAP)
    ):
        gap_query = _build_notebook_gap_query(user_query, notebook)
        if gap_query:
            families.append(
                QueryFamily(
                    role=QueryRole.NOTEBOOK_GAP,
                    query_text=gap_query,
                    max_results=results_per,
                    freshness_hours=freshness_hours,
                )
            )

    return families


# ── helpers ────────────────────────────────────────────────────────────────

def _expand_queries(base: str, role: QueryRole, *, deep_mode: bool) -> list[str]:
    suffixes = _ROLE_SUFFIXES.get(role, [])
    if not suffixes:
        return []

    selected_suffixes = suffixes if deep_mode else suffixes[:1]
    queries: list[str] = []
    for suffix in selected_suffixes:
        if not suffix:
            queries.append(base.strip())
        else:
            queries.append(f"{base.strip()} {suffix}")
    return list(dict.fromkeys(queries))


def _role_freshness(
    role: QueryRole,
    default: int | None,
    sensitivity: TimeSensitivity,
) -> int | None:
    if role == QueryRole.RECENT:
        if sensitivity == TimeSensitivity.HIGH:
            return 72
        return 168  # 7 days
    return default


def _has_role(families: list[QueryFamily], role: QueryRole) -> bool:
    return any(f.role == role for f in families)


def _build_notebook_gap_query(
    base_query: str,
    notebook: NotebookContext,
) -> str | None:
    """Create a query that explicitly asks for content the notebook lacks."""
    if not notebook.existing_article_titles:
        return None
    existing_summary = ", ".join(notebook.existing_article_titles[:5])
    return (
        f"{base_query.strip()} NOT already covered: {existing_summary} "
        f"– find different perspectives or new sources"
    )
