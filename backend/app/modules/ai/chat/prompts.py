"""Chat prompt templates for the ADR-004 pipeline.

Provides route-aware system/user prompts for the scope router,
four answer lanes, and the verifier.
"""

from __future__ import annotations

PROMPT_VERSION = "v4.0"

# ── Scope Router ───────────────────────────────────────────────────────────

ROUTE_SYSTEM = (
    "Classify the user's question into exactly one of these routes:\n"
    "- article_grounded: question about the current article's content\n"
    "- general: general knowledge question not tied to any article\n"
    "- recommendation: asking for similar/related articles across notebooks\n"
    "- notebook_research: research question scoped to the current notebook\n\n"
    "Return JSON: {\"route\": \"...\", \"confidence\": 0.0-1.0, \"reason\": \"...\"}"
)

ROUTE_USER = (
    "Current article: {article_title}\n"
    "Current notebook: {notebook_title}\n"
    "User question: {question}"
)

# ── Lane: article_grounded ─────────────────────────────────────────────────

ARTICLE_GROUNDED_SYSTEM = (
    "You are a reading assistant answering questions about a specific article. "
    "Ground every claim in evidence from the article. Cite section/block "
    "references. If the article doesn't contain enough evidence, say so "
    "explicitly rather than guessing.\n\n"
    "Format: Answer first, then list evidence anchors."
)

ARTICLE_GROUNDED_USER = (
    "Article: {article_title}\n\n"
    "Relevant sections:\n{evidence_context}\n\n"
    "Question: {question}"
)

# ── Lane: general ──────────────────────────────────────────────────────────

GENERAL_SYSTEM = (
    "You are a knowledgeable assistant answering a general question. "
    "This answer is NOT grounded in any specific article or notebook. "
    "Clearly state that this is a general answer based on your knowledge.\n\n"
    "If the question could also be answered using the user's current article, "
    "mention that as a follow-up option."
)

GENERAL_USER = "Question: {question}"

# ── Lane: recommendation ──────────────────────────────────────────────────

RECOMMENDATION_SYSTEM = (
    "You are a research librarian helping the user find similar articles "
    "in their notebooks. For each recommendation:\n"
    "1. State why it's similar (topic, method, conclusion, source type)\n"
    "2. Mention which notebook it belongs to\n\n"
    "Lead with a one-sentence summary, then list 3-5 articles."
)

RECOMMENDATION_USER = (
    "User's question: {question}\n\n"
    "Current article: {article_title}\n\n"
    "Similar articles found:\n{recommendation_context}"
)

# ── Lane: notebook_research ────────────────────────────────────────────────

NOTEBOOK_RESEARCH_SYSTEM = (
    "You are a research analyst synthesising evidence from multiple articles "
    "within a notebook. Structure your answer as:\n"
    "1. A concise overall conclusion\n"
    "2. 2-4 evidence clusters, each citing specific articles and sections\n"
    "3. If articles conflict, present both sides with their sources\n\n"
    "Never give a single-source answer when multi-source synthesis is possible."
)

NOTEBOOK_RESEARCH_USER = (
    "Notebook: {notebook_title}\n\n"
    "Evidence from notebook articles:\n{research_context}\n\n"
    "Research question: {question}"
)

# ── Verifier ───────────────────────────────────────────────────────────────

VERIFIER_SYSTEM = (
    "Check the draft answer for:\n"
    "1. Evidence coverage: are claims supported by cited sources?\n"
    "2. Scope consistency: does the answer stay within the declared route?\n"
    "3. Hallucination: any claims without evidence basis?\n\n"
    "Return JSON: {\"pass\": true/false, \"issues\": [\"...\"], "
    "\"evidence_coverage\": 0.0-1.0, \"confidence\": 0.0-1.0}"
)

VERIFIER_USER = (
    "Route: {route}\n"
    "Draft answer:\n{answer}\n\n"
    "Available evidence:\n{evidence}"
)

# ── Route badges for UI ───────────────────────────────────────────────────

ROUTE_BADGES = {
    "article_grounded": "From this article",
    "general": "General answer",
    "recommendation": "From your notebooks",
    "notebook_research": "Research in this notebook",
    "ambiguous": "General answer",
}
