"""Summary prompt 模板。

遵循「稳定前缀 + 变化后缀」结构以利用 prompt caching。
"""

PROMPT_VERSION = "v5.0"

# ── 稳定前缀（System） ──────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert document summarizer. Given a document, produce a comprehensive \
yet concise summary that captures all key information.

Rules:
1. Preserve factual accuracy — do NOT add information not present in the source.
2. Keep the summary between 150-400 words depending on source length.
3. Use bullet points for key findings / contributions when appropriate.
4. For research papers: include objective, methodology overview, key results, and conclusions.
5. For news: include who, what, when, where, why, and implications.
6. For tutorials: include the topic, prerequisites, key steps, and takeaways.
7. For code-heavy content: focus on purpose, architecture, and key APIs rather than code details.
8. Write clearly and professionally.
"""

# ── 变化后缀（User）按 article_type 分模板 ─────────────────────────

USER_PROMPT_RESEARCH = """\
Summarize this **research paper**.
Focus on: research question / hypothesis, methodology, key findings, limitations, and conclusions.

Title: {title}

Content:
{content}"""

USER_PROMPT_NEWS = """\
Summarize this **news article**.
Focus on: the main event, key people/organizations, timeline, impact, and context.

Title: {title}

Content:
{content}"""

USER_PROMPT_TUTORIAL = """\
Summarize this **tutorial / guide**.
Focus on: what is being taught, prerequisites, key steps / techniques, and practical takeaways.

Title: {title}

Content:
{content}"""

USER_PROMPT_CODE_HEAVY = """\
Summarize this **technical / code-heavy document**.
Focus on: purpose, architecture / design, key APIs or components, and usage patterns. \
Ignore implementation details like code syntax.

Title: {title}

Content:
{content}"""

USER_PROMPT_GENERAL = """\
Summarize this document.

Title: {title}

Content:
{content}"""

USER_PROMPTS = {
    "research": USER_PROMPT_RESEARCH,
    "news": USER_PROMPT_NEWS,
    "tutorial": USER_PROMPT_TUTORIAL,
    "code_heavy": USER_PROMPT_CODE_HEAVY,
    "general": USER_PROMPT_GENERAL,
}

# ── Map-Reduce ─────────────────────────────────────────────────────

MAP_PROMPT = """\
Summarize the following SECTION of a larger document in 80-150 words. \
Preserve key facts and data points.

Title: {title}

Section:
{chunk}"""

REDUCE_PROMPT = """\
You are given section summaries of a longer document. Combine them into \
a single coherent summary (150-400 words). Eliminate redundancy, preserve \
all key information, and maintain logical flow.

Title: {title}

Section summaries:
{summaries}"""

# ── Validate ───────────────────────────────────────────────────────

VALIDATE_PROMPT = """\
Evaluate this summary against the original title. Return a JSON object:
{{"passed": true/false, "issues": ["issue1", ...]}}

Checks:
1. Does the summary cover the main topic of "{title}"?
2. Is it between 100-500 words?
3. Does it contain any fabricated information not implied by the title?

Summary:
{summary}"""
