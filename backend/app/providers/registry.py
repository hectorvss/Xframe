"""
Resolución de proveedor y de modelo.

Dos resoluciones distintas con orígenes distintos, y ahí está todo el diseño:

- `get(provider_id)` mira una tabla en código. Los adaptadores **son** código; no tiene
  sentido que vengan de la BD.
- `for_model(model_id)` consulta `gen_models`. Qué modelos existen, cuáles están vivos y
  quién los sirve **son datos**, porque cambian sin desplegar. Apagar Sora el 24 de
  septiembre debe ser un UPDATE, no un release.

La caché tiene TTL corto (60 s) a propósito. No está para ahorrar la consulta —es
trivial— sino para que un `UPDATE gen_models SET status='retired'` surta efecto en un
minuto sin reiniciar los workers. Un TTL largo convertiría la ventaja de tener esto en
datos en una desventaja operativa.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from app.providers.base import GenerationAdapter, ModelSpec

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 60.0

#: provider_id → fábrica del adaptador. Import perezoso para que un fallo de import en
#: un proveedor no impida arrancar con los otros siete.
_FACTORIES: dict[str, Callable[[], GenerationAdapter]] = {}


def _register_defaults() -> None:
    from app.providers.flux import FluxAdapter
    from app.providers.hailuo import HailuoAdapter
    from app.providers.higgsfield import HiggsfieldAdapter
    from app.providers.kling import KlingAdapter
    from app.providers.openai_image import OpenAIImageAdapter
    from app.providers.seedance import SeedanceAdapter
    from app.providers.sora import SoraAdapter
    from app.providers.veo import VeoAdapter
    from app.providers.wan import WanAdapter

    for adapter_cls in (
        VeoAdapter,
        SoraAdapter,
        KlingAdapter,
        HailuoAdapter,
        SeedanceAdapter,
        WanAdapter,
        HiggsfieldAdapter,
        FluxAdapter,
        # `openai_image` es un provider_id distinto de `openai` (Sora) a propósito: este
        # dict se indexa por provider_id y compartirlo haría que una familia machacara a
        # la otra. Comparten la clave OPENAI_API_KEY, que es lo único que se comparte.
        OpenAIImageAdapter,
    ):
        _FACTORIES[adapter_cls.provider_id] = adapter_cls


class UnknownProviderError(RuntimeError):
    """
    No es un `XframeToolError` a propósito: que un modelo apunte a un proveedor sin
    adaptador es un bug de la semilla, no algo que el LLM pueda corregir reintentando.
    """


class DbAdapterRegistry:
    """
    Implementación de `AdapterRegistry` respaldada por `gen_models`.

    Los adaptadores se instancian una vez y se reutilizan porque tienen estado que vale
    la pena conservar entre jobs: el JWT cacheado de Kling, el catálogo de motions de
    Higgsfield y los timestamps del throttle de polling.
    """

    def __init__(self, *, ttl_s: float = _CACHE_TTL_S) -> None:
        if not _FACTORIES:
            _register_defaults()
        self._ttl_s = ttl_s
        self._instances: dict[str, GenerationAdapter] = {}
        self._models: dict[str, ModelSpec] = {}
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()

    # -- proveedores -------------------------------------------------------- #

    def get(self, provider_id: str) -> GenerationAdapter:
        adapter = self._instances.get(provider_id)
        if adapter is not None:
            return adapter
        factory = _FACTORIES.get(provider_id)
        if factory is None:
            raise UnknownProviderError(
                f"No adapter registered for provider '{provider_id}'. "
                f"Known: {', '.join(sorted(_FACTORIES))}"
            )
        adapter = factory()
        self._instances[provider_id] = adapter
        return adapter

    def for_model(self, model_id: str) -> GenerationAdapter:
        """
        Versión síncrona del contrato `AdapterRegistry`. Solo sirve si la caché ya está
        caliente; si no, hay que pasar por `resolve()`, que sí puede cargarla.
        """
        spec = self._models.get(model_id)
        if spec is None:
            raise UnknownProviderError(
                f"Model '{model_id}' is not in the cached catalogue. "
                f"Call `await registry.resolve(model_id)` instead — it can load it."
            )
        return self.get(spec.provider)

    # -- modelos ------------------------------------------------------------ #

    async def resolve(self, model_id: str) -> tuple[GenerationAdapter, ModelSpec]:
        """
        Punto de entrada normal. Devuelve adaptador y spec juntos porque quien va a
        hacer submit necesita el spec para estimar coste: separarlos garantiza dos
        consultas donde basta una.
        """
        catalogue = await self.models()
        spec = catalogue.get(model_id)
        if spec is None:
            from app.tools.errors import UnknownEntityError

            raise UnknownEntityError(
                "model", model_id, sorted(m.id for m in catalogue.values())
            )
        return self.get(spec.provider), spec

    async def models(self, *, force: bool = False) -> dict[str, ModelSpec]:
        """Catálogo activo, cacheado con TTL."""
        if not force and self._models and time.monotonic() - self._loaded_at < self._ttl_s:
            return self._models

        async with self._lock:
            # Otra corrutina pudo recargar mientras esperábamos el lock.
            if not force and self._models and time.monotonic() - self._loaded_at < self._ttl_s:
                return self._models
            self._models = await self._load()
            self._loaded_at = time.monotonic()
        return self._models

    async def _load(self) -> dict[str, ModelSpec]:
        from app import db

        rows = await db.fetch(
            """
            select id, family, provider, modality, cost_per_second, cost_per_image,
                   min_duration_s, max_duration_s, resolutions, aspects,
                   supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
                   description_llm
              from public.gen_models
             where status = 'active'
             order by sort, id
            """
        )
        return {row["id"]: _to_spec(row) for row in rows}

    def invalidate(self) -> None:
        """Para el hook de post-seed: no tiene sentido esperar el TTL tras un reseed."""
        self._loaded_at = 0.0


def _to_spec(row: Any) -> ModelSpec:
    spec = ModelSpec(
        id=row["id"],
        family=row["family"],
        provider=row["provider"],
        modality=row["modality"],
        cost_per_second=Decimal(str(row["cost_per_second"])),
        max_duration_s=float(row["max_duration_s"]) if row["max_duration_s"] is not None else None,
        min_duration_s=float(row["min_duration_s"]) if row["min_duration_s"] is not None else None,
        resolutions=tuple(row["resolutions"] or ()),
        aspects=tuple(row["aspects"] or ()),
        supports_i2v=row["supports_i2v"],
        supports_last_frame=row["supports_last_frame"],
        supports_char_ref=row["supports_char_ref"],
        supports_audio=row["supports_audio"],
        description_llm=row["description_llm"] or "",
    )
    # `ModelSpec` usa slots y no declara cost_per_image; se cuelga como atributo suelto
    # solo si el dataclass lo permite. Si no, los adaptadores caen a cost_per_second,
    # que es el fallback que ya implementan.
    per_image = row["cost_per_image"]
    if per_image is not None:
        try:
            spec.cost_per_image = Decimal(str(per_image))  # type: ignore[attr-defined]
        except AttributeError:
            pass
    return spec


_default: DbAdapterRegistry | None = None


def get_registry() -> DbAdapterRegistry:
    global _default
    if _default is None:
        _default = DbAdapterRegistry()
    return _default
