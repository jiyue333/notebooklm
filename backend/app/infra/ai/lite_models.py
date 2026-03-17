"""Lite LLM – system-level lightweight model for low-latency tasks.

Uses LITE_LLM_* config (task parsing, rerank, HTML extraction fallback, etc.).
No user-specific settings; reads from app config only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings, get_settings
from app.core.constant import PROVIDER_OPENAI
from app.infra.ai.factory import build_chat_model

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def build_lite_llm(settings: Settings | None = None) -> BaseChatModel | None:
    """Build a LangChain chat model from LITE_LLM_* config.

    Returns ``None`` if API key is not configured.
    """
    s = settings or get_settings()
    api_key = s.lite_llm_api_key
    if not api_key:
        return None

    return build_chat_model(
        provider=s.lite_llm_provider or PROVIDER_OPENAI,
        model_name=s.lite_llm_model,
        base_url=s.lite_llm_base_url,
        api_key=api_key,
        timeout=float(s.lite_llm_timeout),
        metadata={"config_scope": "lite_llm"},
    )
