"""
Medición de tokens del agente → créditos.

El agente razona con un LLM que nos cuesta dinero por token. Ese coste hay que cobrarlo
en la misma moneda que la generación (créditos) y con el mismo margen, o la parte más
cara de un proyecto —el razonamiento— sale gratis y se come el margen de la suscripción
antes de generar un solo fotograma.

La conversión es la misma ley que la de generación: `usd_to_credits(coste)`, que aplica
K (créditos por USD de coste real). Lo único propio de aquí es traducir tokens a USD, y
para eso hace falta el precio del modelo concreto que respondió.

Precios en USD por millón de tokens. Los de Anthropic están verificados (jul 2026); el
del modelo de razonamiento actual (`gpt-5.6-*`) es una estimación conservadora marcada
como tal. Un modelo que no esté en la tabla cae al precio por defecto de la config
(`llm_price_*_per_mtok`): así, cambiar de modelo nunca lo mide a 0 por descuido.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class TokenPrice:
    """USD por millón de tokens. `cached_input` es el precio de una lectura cacheada."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cached_input_per_mtok: Decimal | None = None


# La clave se busca como subcadena del nombre del modelo (case-insensitive), así que
# 'claude-opus' cubre 'claude-opus-4-8-20260101' y similares.
TOKEN_PRICES: dict[str, TokenPrice] = {
    # Anthropic, verificado jul 2026 (docs oficiales).
    "claude-opus": TokenPrice(Decimal("5"), Decimal("25"), Decimal("0.5")),
    "claude-sonnet": TokenPrice(Decimal("3"), Decimal("15"), Decimal("0.3")),
    "claude-haiku": TokenPrice(Decimal("1"), Decimal("5"), Decimal("0.1")),
    # Modelo de razonamiento actual (caro). ESTIMADO: ajustar al precio real, o borrar
    # esta fila para que caiga al default de la config cuando se cambie de modelo.
    "gpt-5.6-sol": TokenPrice(Decimal("10"), Decimal("30")),
    "gpt-5.6-luna": TokenPrice(Decimal("1.5"), Decimal("6")),
}


def price_for(model_name: str) -> TokenPrice:
    """Precio del modelo por nombre; default de la config si no está en la tabla."""
    name = (model_name or "").lower()
    for key, price in TOKEN_PRICES.items():
        if key in name:
            return price
    settings = get_settings()
    return TokenPrice(
        Decimal(str(settings.llm_price_input_per_mtok)),
        Decimal(str(settings.llm_price_output_per_mtok)),
    )


def _usage_of(response: Any) -> dict[str, Any]:
    """
    Extrae el uso de tokens de una respuesta de LangChain de forma defensiva.

    LangChain normaliza `usage_metadata` en el AIMessage, pero no todos los proveedores
    la rellenan igual; si falta, se intenta `response_metadata`. Sin uso, se devuelve
    vacío y el metering sale a 0 (nunca revienta el turno por no saber cobrar).
    """
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict) and usage:
        return usage
    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage")
        if isinstance(token_usage, dict):
            return token_usage
    return {}


def token_cost_usd(model_name: str, usage: dict[str, Any]) -> Decimal:
    """
    Coste en USD de un uso de tokens. Descuenta las lecturas cacheadas del input, que se
    facturan a su tarifa reducida (y a 0.1x del input si el proveedor no la publica).
    """
    price = price_for(model_name)
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)

    details = usage.get("input_token_details") or {}
    cached = int(details.get("cache_read") or details.get("cached_tokens") or 0)
    cached = min(cached, input_tokens)
    billable_input = input_tokens - cached

    cached_price = price.cached_input_per_mtok
    if cached_price is None:
        cached_price = price.input_per_mtok / 10  # sin tarifa publicada: 0.1x, prudente

    cost = (
        Decimal(billable_input) * price.input_per_mtok
        + Decimal(cached) * cached_price
        + Decimal(output_tokens) * price.output_per_mtok
    ) / _MILLION
    return cost if cost > 0 else Decimal(0)


async def meter_tokens(
    response: Any,
    *,
    profile_id: str,
    model_name: str,
    purpose: str,
    project_id: str | None = None,
) -> int:
    """
    Cobra al perfil los créditos del uso de tokens de `response`. Devuelve los créditos
    cobrados (0 si no hubo uso medible). No propaga errores: un fallo al cobrar no debe
    tumbar el turno del agente —se registra y se sigue— porque perder una respuesta ya
    generada es peor que perder su cobro.
    """
    from app.jobs.credits import debit_tokens, usd_to_credits

    try:
        usage = _usage_of(response)
        if not usage:
            return 0
        cost = token_cost_usd(model_name, usage)
        credits = usd_to_credits(cost) if cost > 0 else 0
        if credits <= 0:
            return 0
        note = (
            f"tokens {purpose} {model_name}: "
            f"{usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out"
        )
        await debit_tokens(profile_id, credits, note, project_id=project_id)
        return credits
    except Exception:  # noqa: BLE001 - el cobro nunca debe romper el razonamiento
        logger.exception(
            "token_metering_failed",
            extra={"profile_id": profile_id, "model": model_name, "purpose": purpose},
        )
        return 0
