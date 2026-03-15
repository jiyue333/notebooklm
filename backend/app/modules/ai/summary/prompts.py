"""Summary prompt templates for the ADR-003 pipeline.

Provides route-aware prompts for evidence extraction, candidate
generation (3 styles), and judge evaluation.
"""

from __future__ import annotations

PROMPT_VERSION = "v3.0"

# ── Evidence extraction ────────────────────────────────────────────────────

EVIDENCE_SYSTEM = (
    "You are an expert research analyst. Extract the most important "
    "factual claims, conclusions, and key points from the article. "
    "Return 8-12 bullet points. Each bullet should be a self-contained "
    "factual statement that could support a summary.\n"
    "Format: one bullet per line, starting with '- '."
)

EVIDENCE_USER = (
    "Article title: {title}\n\n"
    "Article type: {article_type}\n"
    "Focus on: {focus_areas}\n\n"
    "Article content:\n{content}"
)

# ── Summary generation (3 styles) ─────────────────────────────────────────

_SUMMARY_BASE_SYSTEM = (
    "You are a research assistant writing a concise one-paragraph summary "
    "of an article for a researcher who needs to quickly decide whether "
    "to read the full text.\n\n"
    "Requirements:\n"
    "- One paragraph, 3-6 sentences\n"
    "- Factually faithful to the source\n"
    "- Cover the most important points\n"
    "- Clear and professional tone\n"
    "- If language is specified, write in that language; otherwise match "
    "the article's language"
)

SUMMARY_CLAIM_FIRST_SYSTEM = (
    f"{_SUMMARY_BASE_SYSTEM}\n\n"
    "Style: Lead with the main claim or conclusion, then support with evidence."
)

SUMMARY_CONTRIBUTION_FIRST_SYSTEM = (
    f"{_SUMMARY_BASE_SYSTEM}\n\n"
    "Style: Lead with what this article contributes (new method, finding, "
    "perspective), then explain the significance."
)

SUMMARY_READER_FIRST_SYSTEM = (
    f"{_SUMMARY_BASE_SYSTEM}\n\n"
    "Style: Lead with why a reader would care, then deliver the key content."
)

SUMMARY_USER = (
    "Article title: {title}\n"
    "Article type: {article_type}\n"
    "Summary route: {route}\n\n"
    "Key evidence bullets:\n{evidence_bullets}\n\n"
    "Write the summary paragraph:"
)

# ── Conservative fallback (Route X) ───────────────────────────────────────

SUMMARY_CONSERVATIVE_SYSTEM = (
    "You are a cautious research assistant. The article's parse quality "
    "is low, so only summarise what you can confirm from the content. "
    "Write a brief, conservative one-paragraph summary covering:\n"
    "- Main topic\n"
    "- Most important conclusion or value\n"
    "- Applicable scope or limitations\n"
    "Do NOT invent details."
)

SUMMARY_CONSERVATIVE_USER = (
    "Article title: {title}\n\n"
    "Available content (may be incomplete):\n{content}"
)

# ── Judge / verifier ──────────────────────────────────────────────────────

JUDGE_SYSTEM = (
    "You are a summary quality evaluator. Score the summary on four "
    "dimensions (0.0-1.0 each):\n"
    "- fidelity: Are all claims supported by the source?\n"
    "- coverage: Does it cover the most important points?\n"
    "- clarity: Is it well-written and easy to understand?\n"
    "- concision: Is it appropriately brief without filler?\n\n"
    "Return JSON: {{\"fidelity\": X, \"coverage\": X, \"clarity\": X, \"concision\": X}}"
)

JUDGE_USER = (
    "Article title: {title}\n\n"
    "Evidence bullets:\n{evidence_bullets}\n\n"
    "Summary to evaluate:\n{summary_text}"
)

# ── Focus area templates per article type ──────────────────────────────────

FOCUS_AREAS = {
    "paper": "problem/question, method/setup, core results, limitations/implications",
    "report": "key conclusions, basis/evidence, policy implications",
    "tutorial": "what it teaches, key steps/ideas, target audience/limits",
    "blog": "main argument, supporting evidence, practical takeaway",
    "news": "what happened, who's involved, significance",
    "docs": "purpose, key functionality, usage context",
    "unknown": "main topic, key points, conclusions",
}
