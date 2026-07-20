"""
Capa de proveedores de generación.

Contrato uniforme para APIs heterogéneas. `GenerationRequest` es **nuestro** vocabulario;
cada adaptador lo traduce al dialecto de su proveedor. El agente nunca ve un payload de
proveedor, y por tanto nunca se acopla a uno.

Esto no es purismo: el informe de APIs (`docs/posthog-agent-research/06`) documenta que
Veo 3.0 ya está apagado, Runway Gen-3/Gen-4 se apagan el 30 de julio de 2026 y Sora 2 el
24 de septiembre. Tres de cuatro proveedores tier-1 con fecha de caducidad conocida. Con
esta capa, apagar uno es marcarlo `retired` en la tabla `gen_models`.

Ningún proveedor tier-1 es síncrono: el contrato es siempre submit → poll/webhook.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

Modality = Literal["image", "video", "audio", "lipsync"]


@dataclass(slots=True)
class ElementRef:
    """Un personaje, localización u objeto del proyecto usado como referencia visual."""

    element_id: str
    name: str
    role: str
    image_url: str
    """URL accesible por el proveedor (firmada y con TTL suficiente para el job)."""


@dataclass(slots=True)
class GenerationRequest:
    """Petición en vocabulario Xframe. Ningún campo es específico de un proveedor."""

    modality: Modality
    model_id: str
    prompt: str

    negative_prompt: str | None = None
    duration_s: float | None = None
    aspect: str | None = None
    resolution: str | None = None
    seed: int | None = None

    # imagen → vídeo
    init_image_url: str | None = None
    last_frame_url: str | None = None

    # continuidad
    elements: list[ElementRef] = field(default_factory=list)

    # lenguaje cinematográfico
    camera_motion: str | None = None
    camera_motion_strength: float | None = None
    style: dict[str, str] = field(default_factory=dict)

    audio: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderJobRef:
    provider: str
    external_id: str
    poll_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderJobStatus:
    state: Literal["queued", "running", "succeeded", "failed", "nsfw", "cancelled"]
    progress: float | None = None
    output_urls: list[str] = field(default_factory=list)
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in ("succeeded", "failed", "nsfw", "cancelled")

    @property
    def should_refund(self) -> bool:
        """
        Si no llegó a producir nada, el usuario no paga.

        Higgsfield reembolsa en `failed` y `nsfw`, pero no todos los proveedores lo
        hacen: si no lo modelamos nosotros, perdemos dinero en silencio.
        """
        return self.state in ("failed", "nsfw", "cancelled")


@dataclass(slots=True)
class ModelSpec:
    """
    Capacidades declaradas de un modelo. Se sincroniza contra la tabla `gen_models`,
    que es la fuente de verdad que ven las herramientas.
    """

    id: str
    family: str
    provider: str
    modality: Modality
    cost_per_second: Decimal
    max_duration_s: float | None = None
    min_duration_s: float | None = None
    resolutions: tuple[str, ...] = ()
    aspects: tuple[str, ...] = ()
    supports_i2v: bool = False
    supports_last_frame: bool = False
    supports_char_ref: bool = False
    supports_audio: bool = False
    description_llm: str = ""


class GenerationAdapter(ABC):
    """
    Un adaptador por proveedor. Añadir un proveedor es escribir esto y nada más.

    Nota de diseño: un agregador (fal.ai, Replicate) encaja aquí como un adaptador más.
    La decisión de ir con APIs directas no queda cerrada — cubrir la cola larga con un
    agregador más adelante no obliga a tocar nada por encima de esta capa.
    """

    provider_id: str
    supported_modalities: tuple[Modality, ...] = ()

    #: Mínimo intervalo entre peticiones de polling. Runway throttlea por encima de
    #: 1 req/5 s, así que esto es un dato del proveedor, no una preferencia nuestra.
    min_poll_interval_s: float = 5.0

    @abstractmethod
    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        """Encola el trabajo. No espera al resultado."""

    @abstractmethod
    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        """Consulta el estado. Debe ser barata e idempotente."""

    async def cancel(self, ref: ProviderJobRef) -> None:
        """Cancela si el proveedor lo soporta. Por defecto, no-op."""
        return None

    @abstractmethod
    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        """Coste en USD. Base sobre la que se calculan los créditos que se cobran."""

    def normalize_error(self, exc: Exception) -> Exception:
        """
        Traduce el error del proveedor a nuestra jerarquía, que es la que decide si se
        reintenta. Cada adaptador lo afina; esto es solo el defecto razonable.
        """
        from app.tools.errors import ProviderError

        return ProviderError(self.provider_id, str(exc))


class AdapterRegistry(Protocol):
    def get(self, provider_id: str) -> GenerationAdapter: ...
    def for_model(self, model_id: str) -> GenerationAdapter: ...
