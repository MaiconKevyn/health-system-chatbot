from __future__ import annotations

from .config import ChatbotConfig


def build_openai_llm(config: ChatbotConfig):
    if not config.has_openai_key:
        raise RuntimeError("OPENAI_API_KEY is required for LlamaIndex OpenAI generation")

    from llama_index.llms.openai import OpenAI

    kwargs = {}
    if config.llm_reasoning_effort:
        kwargs["reasoning_effort"] = config.llm_reasoning_effort
    return OpenAI(
        model=config.llm_model,
        temperature=0,
        timeout=float(config.query_timeout_seconds),
        api_key=config.openai_api_key,
        **kwargs,
    )

