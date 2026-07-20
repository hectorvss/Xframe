"""
Fontanería HTTP compartida por todos los adaptadores.

Está aquí y no en cada adaptador porque las tres decisiones difíciles son idénticas
para los ocho proveedores, y duplicarlas ocho veces garantiza que ocho veces salgan
distintas:

1. **Qué es transitorio.** Reintentar un 400 quema cuota sin arreglar nada; no
   reintentar un 503 pierde un job que habría salido. La clasificación vive en un solo
   sitio y se expresa en la jerarquía de `app.tools.errors`, que es lo que el ejecutor
   lee para decidir.
2. **Cuánto esperar.** Backoff exponencial con jitter. El jitter no es cosmético: sin
   él, seis planos lanzados a la vez reintentan a la vez y reconstruyen el pico que
   provocó el 429.
3. **Cada cuánto se puede poletear.** Runway documenta 1 req/5 s y Higgsfield poletea a
   2 s. Es un dato del proveedor, así que el throttle se aplica aquí y no se deja a la
   disciplina del llamante.

El cliente es compartido a propósito: reusar conexiones TLS contra ocho hosts durante
jobs de minutos importa más que el aislamiento entre adaptadores.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

import httpx

from app.providers.base import (
    GenerationAdapter,
    GenerationRequest,
    ModelSpec,
    ProviderJobRef,
)
from app.tools.errors import (
    ProviderError,
    ProviderRejectedError,
    XframeToolFatalError,
)

#: Timeouts explícitos, nunca el default de httpx (5 s en todo), que corta submits
#: legítimos. `read` es generoso porque algunos submits hacen trabajo antes de encolar;
#: `connect` es corto porque un proveedor que no acepta la conexión en 10 s está caído.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

#: Un submit que sube referencias puede tardar bastante más que un poll.
UPLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=180.0, pool=10.0)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Cliente proceso-global. `close_client()` en el shutdown de la app."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    """
    Reintentos solo en transitorios. `max_attempts` cuenta el intento inicial.

    Cuatro intentos con base 0.8 s dan ~0.8 + 1.6 + 3.2 ≈ 5.6 s de espera acumulada en
    el peor caso, que cabe holgadamente dentro del timeout de un job de vídeo.
    """

    max_attempts: int = 4
    base_delay_s: float = 0.8
    max_delay_s: float = 20.0

    def delay_for(self, attempt: int, retry_after_s: float | None = None) -> float:
        """`attempt` es 0-based. `Retry-After` del proveedor gana siempre que exista."""
        if retry_after_s is not None:
            return min(retry_after_s, self.max_delay_s)
        raw = min(self.base_delay_s * (2**attempt), self.max_delay_s)
        # Jitter completo (no ±10%): es lo que descorrelaciona de verdad un lote de
        # reintentos simultáneos. Se conserva un suelo para no martillear.
        return raw * (0.5 + random.random() * 0.5)


#: Códigos que valen la pena reintentar. 409 se excluye a propósito: en estas APIs
#: significa "ya existe / estado incompatible", y reintentarlo nunca converge.
_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 522, 524})


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # Formato HTTP-date. No merece parseo: el backoff normal es un fallback correcto.
        return None


def classify_http_error(
    provider: str, response: httpx.Response, body: str | None = None
) -> Exception:
    """
    Traduce un status HTTP a nuestra jerarquía. La clase elegida *es* la política de
    reintento, así que equivocarse aquí se paga en créditos o en jobs perdidos.
    """
    detail = (body if body is not None else _safe_text(response))[:400]
    status = response.status_code

    if status in (401, 403):
        return XframeToolFatalError(
            f"Provider '{provider}' rejected our credentials (HTTP {status}). "
            f"This is a server configuration problem, not something to retry. "
            f"Tell the user this provider is unavailable right now. Detail: {detail}"
        )
    if status == 404:
        return XframeToolFatalError(
            f"Provider '{provider}' returned 404 for a resource we expected to exist. "
            f"Likely a retired model or a changed endpoint. Detail: {detail}"
        )
    if status in _TRANSIENT_STATUS:
        return ProviderError(
            provider, f"HTTP {status}: {detail}", retry_after_s=_retry_after(response.headers)
        )
    if 400 <= status < 500:
        # 4xx restantes = la petición está mal formada o el contenido fue moderado.
        # Es ajustable por el LLM, así que retryable-con-cambios, no transitorio.
        return ProviderRejectedError(provider, f"HTTP {status}: {detail}")
    return ProviderError(provider, f"HTTP {status}: {detail}")


def _safe_text(response: httpx.Response) -> str:
    try:
        return response.text
    except Exception:  # noqa: BLE001 - cuerpo binario o stream ya consumido
        return "<unreadable body>"


class HttpAdapter(GenerationAdapter):
    """
    Base de los adaptadores que hablan HTTP, que son todos.

    Aporta el ciclo petición-con-reintentos, el throttle de polling y una estimación de
    coste por defecto. Los subtipos solo traducen vocabulario.
    """

    base_url: str = ""
    retry_policy: RetryPolicy = RetryPolicy()

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        # Inyectable para poder montar `httpx.MockTransport` en los tests sin parchear
        # nada global.
        self._injected = client
        self._last_poll_at: dict[str, float] = {}

    @property
    def client(self) -> httpx.AsyncClient:
        return self._injected if self._injected is not None else get_client()

    # -- credenciales ------------------------------------------------------- #

    def auth_headers(self) -> dict[str, str]:
        """Cada proveedor tiene su dialecto de auth. Sin default razonable posible."""
        raise NotImplementedError

    def _require(self, value: str, env_name: str) -> str:
        """
        Falla en el submit y no al importar: un despliegue sin la clave de Kling debe
        seguir sirviendo Veo, no caerse entero al arrancar.
        """
        if not value:
            raise XframeToolFatalError(
                f"Provider '{self.provider_id}' is not configured: {env_name} is empty. "
                f"Do not retry; tell the user this model is unavailable and suggest another."
            )
        return value

    # -- transporte --------------------------------------------------------- #

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: Any | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        expected: tuple[int, ...] = (200, 201, 202),
    ) -> httpx.Response:
        """
        Una petición con reintentos. Devuelve la respuesta cruda; parsearla es del
        adaptador, porque el formato es justamente lo que cambia entre proveedores.
        """
        full_url = url if url.startswith("http") else f"{self.base_url}{url}"
        merged = {**self.auth_headers(), **(headers or {})}
        last: Exception | None = None

        for attempt in range(self.retry_policy.max_attempts):
            try:
                response = await self.client.request(
                    method,
                    full_url,
                    json=json,
                    params=dict(params) if params else None,
                    headers=merged,
                    timeout=timeout or DEFAULT_TIMEOUT,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # La red no llegó a hablar con el proveedor: siempre transitorio.
                last = ProviderError(self.provider_id, f"{type(exc).__name__}: {exc}")
            else:
                if response.status_code in expected:
                    return response
                error = classify_http_error(self.provider_id, response)
                if not isinstance(error, ProviderError):
                    raise error  # fatal o ajustable: reintentar no cambia el resultado
                last = error

            if attempt + 1 < self.retry_policy.max_attempts:
                retry_after = getattr(last, "retry_after_s", None)
                await asyncio.sleep(self.retry_policy.delay_for(attempt, retry_after))

        raise last or ProviderError(self.provider_id, "request failed with no diagnosis")

    async def throttled_poll_gate(self, key: str) -> None:
        """
        Espera lo que falte para respetar `min_poll_interval_s`.

        Se aplica aquí y no en el orquestador porque el límite es del proveedor: si un
        worker y un reintento manual poletean el mismo job, el contrato se sigue
        cumpliendo sin que ninguno de los dos lo sepa.
        """
        previous = self._last_poll_at.get(key)
        now = time.monotonic()
        if previous is not None:
            wait = self.min_poll_interval_s - (now - previous)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_poll_at[key] = time.monotonic()

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        """
        Duración × precio por segundo, o precio por imagen. Los adaptadores con tarifa
        escalonada por resolución (Veo, Sora) lo sobrescriben.
        """
        if spec.modality == "image":
            per_image = getattr(spec, "cost_per_image", None) or spec.cost_per_second
            return _money(Decimal(per_image))
        duration = Decimal(str(req.duration_s or spec.min_duration_s or 5))
        return _money(Decimal(spec.cost_per_second) * duration)

    # -- utilidades de traducción ------------------------------------------- #

    def _ref_urls(self, req: GenerationRequest) -> list[str]:
        """
        URLs de referencia visual en orden de prioridad: el frame inicial manda sobre
        los elements, porque si hay init_image el encuadre ya está decidido.
        """
        urls: list[str] = []
        if req.init_image_url:
            urls.append(req.init_image_url)
        urls.extend(e.image_url for e in req.elements if e.image_url)
        return urls

    def _styled_prompt(self, req: GenerationRequest) -> str:
        """
        Aplana estilo y cámara en el prompt.

        Es el camino de peor calidad y por eso solo se usa donde el proveedor no expone
        control de cámara estructurado. Higgsfield DoP, que sí lo expone por UUID, no
        pasa por aquí: esa es exactamente su ventaja.
        """
        parts = [req.prompt.strip()]
        parts.extend(v for v in req.style.values() if v)
        if req.camera_motion:
            strength = req.camera_motion_strength
            if strength is not None and strength < 0.4:
                parts.append(f"subtle {req.camera_motion} camera move")
            elif strength is not None and strength > 0.75:
                parts.append(f"pronounced {req.camera_motion} camera move")
            else:
                parts.append(f"{req.camera_motion} camera move")
        return ", ".join(p for p in parts if p)

    def normalize_error(self, exc: Exception) -> Exception:
        """Los errores que nacen aquí ya están en la jerarquía; se dejan intactos."""
        from app.tools.errors import XframeToolError

        if isinstance(exc, XframeToolError):
            return exc
        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return ProviderError(self.provider_id, f"{type(exc).__name__}: {exc}")
        return ProviderError(self.provider_id, str(exc))


def _money(value: Decimal) -> Decimal:
    """Cuatro decimales, que es la precisión de `cost_per_second` en la BD."""
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def job_ref(
    provider: str, external_id: str, *, poll_url: str | None = None, raw: dict[str, Any] | None = None
) -> ProviderJobRef:
    return ProviderJobRef(
        provider=provider, external_id=str(external_id), poll_url=poll_url, raw=raw or {}
    )
