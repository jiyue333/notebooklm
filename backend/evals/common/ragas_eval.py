from __future__ import annotations

import os
from typing import Any


def run_ragas_evaluation(
    *,
    dataset_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    embedding_model: str | None = None,
) -> dict[str, float]:
    try:
        from datasets import Dataset
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import context_precision, context_recall, faithfulness
        try:
            from ragas.metrics import answer_relevancy
        except ImportError:
            from ragas.metrics import answer_relevance as answer_relevancy
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Ragas dependencies are not installed. Install backend eval extras before using --with-ragas."
        ) from exc

    configured_api_key = api_key or os.environ.get("RAGAS_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not configured_api_key:
        raise RuntimeError("RAGAS_API_KEY or OPENAI_API_KEY is required for --with-ragas")

    configured_base_url = base_url or os.environ.get("RAGAS_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    configured_model = model or os.environ.get("RAGAS_MODEL") or "gpt-4o-mini"
    configured_embedding_model = embedding_model or os.environ.get("RAGAS_EMBEDDING_MODEL") or "text-embedding-3-small"

    prediction_map = {row["case_id"]: row for row in prediction_rows}
    payload = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": [],
    }
    for row in dataset_rows:
        prediction = prediction_map.get(row["case_id"], {})
        contexts = prediction.get("retrieved_contexts") or prediction.get("contexts") or []
        if not contexts:
            contexts = [", ".join(prediction.get("retrieved_context_ids", []))]
        payload["question"].append(str(row.get("question", "")).strip())
        payload["answer"].append(str(prediction.get("answer", "")).strip())
        payload["contexts"].append([str(item) for item in contexts if str(item).strip()])
        payload["ground_truth"].append(str(row.get("reference_answer", "")).strip())

    llm = ChatOpenAI(
        model=configured_model,
        api_key=configured_api_key,
        base_url=configured_base_url,
        temperature=0,
    )
    embeddings = OpenAIEmbeddings(
        model=configured_embedding_model,
        api_key=configured_api_key,
        base_url=configured_base_url,
    )
    result = evaluate(
        Dataset.from_dict(payload),
        metrics=[context_precision, context_recall, faithfulness, answer_relevancy],
        llm=LangchainLLMWrapper(llm),
        embeddings=LangchainEmbeddingsWrapper(embeddings),
    )
    if hasattr(result, "to_dict"):
        raw = result.to_dict()
    elif hasattr(result, "__dict__"):
        raw = dict(result.__dict__)
    else:
        raw = dict(result)

    normalized: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, (int, float)):
            normalized[str(key)] = round(float(value), 4)
    return normalized
