from __future__ import annotations


def extract_llm_text_and_usage(result) -> tuple[str, dict[str, int]]:
    content = getattr(result, "content", None)
    if isinstance(content, list):
        text = "\n".join(str(item) for item in content)
    else:
        text = str(content or "")

    usage = getattr(result, "usage_metadata", None) or {}
    response_metadata = getattr(result, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or {}

    prompt_tokens = _coerce_int(
        usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
        or response_metadata.get("prompt_eval_count")
    )
    completion_tokens = _coerce_int(
        usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or response_metadata.get("eval_count")
    )
    total_tokens = _coerce_int(
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
        or (prompt_tokens + completion_tokens if prompt_tokens or completion_tokens else 0)
    )
    return text.strip(), {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _coerce_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
