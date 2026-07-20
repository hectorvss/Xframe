"""
Fábrica de modelos de lenguaje.

Un solo sitio donde se decide qué modelo razona. Antes la construcción estaba repetida
en `agent/executables.py`, `agent/compaction.py` y `memory/collector.py`, cada una con
su `api_key` y sus parámetros: cambiar de proveedor obligaba a tocar tres ficheros y a
acordarse de los tres.

Es el equivalente a `ee/hogai/llm.py` de PostHog, y por el mismo motivo: no hay un router
central que elija modelo por tarea —cada llamante pide el suyo por propósito— pero sí un
único punto donde se construye.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.language_models import BaseChatModel

from app.config import get_settings

Purpose = Literal["root", "fast", "summarize"]


def chat_model(
    purpose: Purpose = "root",
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    streaming: bool | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """
    Modelo para un propósito dado.

    `purpose` no es el nombre del modelo: es para qué se usa. `root` razona y decide,
    `fast` hace tareas mecánicas baratas (destilar memoria), `summarize` compacta. Qué
    modelo concreto sirve cada propósito se configura por entorno, así que ajustar coste
    o calidad no toca código.
    """
    settings = get_settings()
    name = {
        "root": settings.model_root,
        "fast": settings.model_fast,
        "summarize": settings.model_summarize,
    }[purpose]

    provider = settings.llm_provider
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        # `use_responses_api=True` no es opcional con la familia GPT-5.6, y lo comprobamos
        # contra la API real: `/v1/chat/completions` responde
        #
        #   400 — "Function tools with reasoning_effort are not supported for gpt-5.6-sol
        #          in /v1/chat/completions. To use function tools, use /v1/responses or
        #          set reasoning_effort to 'none'."
        #
        # Es decir: por el camino por defecto de LangChain hay que elegir entre razonar y
        # usar herramientas. Un agente que no puede hacer las dos cosas no es un agente,
        # así que se va por `/v1/responses`, que soporta ambas.
        #
        # `temperature` no viaja: los modelos de razonamiento la rechazan.
        return ChatOpenAI(
            model=name,
            api_key=settings.openai_api_key,
            use_responses_api=True,
            max_tokens=max_tokens,
            streaming=streaming if streaming is not None else True,
            **kwargs,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=name,
            api_key=settings.anthropic_api_key,
            max_tokens=max_tokens or 8192,
            temperature=temperature,
            streaming=streaming if streaming is not None else True,
            **kwargs,
        )

    raise ValueError(
        f"LLM_PROVIDER='{provider}' no soportado. Valores válidos: 'openai', 'anthropic'."
    )
