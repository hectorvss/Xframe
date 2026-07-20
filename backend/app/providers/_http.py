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
import base64
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

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

    #: Techo del `Retry-After` **del proveedor**, deliberadamente altísimo y distinto de
    #: `max_delay_s`. Recortar un `Retry-After: 300` a 20 s no es "ser eficiente": es
    #: reintentar cuando el proveedor ha dicho explícitamente que no, y así es como un
    #: rate limit temporal se convierte en un baneo de la cuenta. Este tope existe solo
    #: como red contra una cabecera absurda (o maliciosa) que colgaría el worker una hora.
    max_retry_after_s: float = 900.0

    def delay_for(self, attempt: int, retry_after_s: float | None = None) -> float:
        """
        `attempt` es 0-based. `Retry-After` del proveedor gana siempre que exista, y se
        respeta **íntegro**: es un dato del proveedor sobre su propio estado, no una
        sugerencia que podamos negociar a la baja.
        """
        if retry_after_s is not None:
            return min(max(retry_after_s, 0.0), self.max_retry_after_s)
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
    except Exception:
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
        #: Un único instante por adaptador, no un dict por job. Ver `throttled_poll_gate`.
        self._last_poll_at: float | None = None
        self._poll_lock: asyncio.Lock | None = None
        self._poll_lock_loop: asyncio.AbstractEventLoop | None = None

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
        data: Mapping[str, Any] | None = None,
        files: Any | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,  # noqa: ASYNC109 - se reenvía a httpx, que ya lo implementa
        expected: tuple[int, ...] = (200, 201, 202),
    ) -> httpx.Response:
        """
        Una petición con reintentos. Devuelve la respuesta cruda; parsearla es del
        adaptador, porque el formato es justamente lo que cambia entre proveedores.

        `data` + `files` son para los endpoints `multipart/form-data` (hoy solo el de
        edición de imagen de OpenAI, que no acepta URLs de referencia y exige subir los
        ficheros). Se aceptan aquí en vez de dejar que ese adaptador hable con `httpx`
        por su cuenta porque lo que se perdería es justamente lo caro: la clasificación de
        transitorios y el backoff con jitter.
        """
        full_url = url if url.startswith("http") else f"{self.base_url}{url}"
        merged = {**self.auth_headers(), **(headers or {})}
        if files is not None:
            # httpx tiene que poner su propio `Content-Type` con el `boundary` del
            # multipart. Dejar el `application/json` que casi todos los `auth_headers()`
            # declaran hace que el servidor intente parsear el cuerpo como JSON y
            # devuelva un 400 que no menciona el content-type por ningún lado.
            merged = {k: v for k, v in merged.items() if k.lower() != "content-type"}
        last: Exception | None = None

        for attempt in range(self.retry_policy.max_attempts):
            try:
                response = await self.client.request(
                    method,
                    full_url,
                    json=json,
                    data=dict(data) if data else None,
                    files=files,
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

    def _gate_lock(self) -> asyncio.Lock:
        """
        Cerrojo del gate, creado perezosamente y re-creado si cambia el bucle.

        Construirlo en `__init__` ataría el adaptador al bucle que lo instanció; el
        registry reusa instancias durante toda la vida del proceso y los tests abren un
        bucle por caso, así que esa atadura fallaría en los dos sitios.
        """
        loop = asyncio.get_running_loop()
        if self._poll_lock is None or self._poll_lock_loop is not loop:
            self._poll_lock = asyncio.Lock()
            self._poll_lock_loop = loop
        return self._poll_lock

    async def throttled_poll_gate(self, key: str | None = None) -> None:
        """
        Espera lo que falte para respetar `min_poll_interval_s` **del proveedor**.

        El límite es por proveedor, no por job: llevar la cuenta por `external_id` hacía
        que doce planos en vuelo poletearan doce veces el ritmo permitido, que es
        exactamente el escenario que dispara el 429. Por eso el estado es un único
        instante por adaptador (el registry mantiene una instancia por proveedor) y el
        cerrojo se sostiene *durante* la espera: así N pollers concurrentes se ordenan en
        cola de uno por intervalo en vez de pasar todos a la vez tras leer el mismo valor.

        `key` se acepta y se ignora a propósito: los adaptadores ya lo pasan y quitarlo de
        ocho llamadas no aporta nada. De paso desaparece el dict que nunca se purgaba, que
        en un proceso de larga vida era una fuga de memoria proporcional a los jobs
        atendidos.
        """
        async with self._gate_lock():
            if self._last_poll_at is not None:
                wait = self.min_poll_interval_s - (time.monotonic() - self._last_poll_at)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_poll_at = time.monotonic()

    # -- referencias visuales ------------------------------------------------ #

    async def fetch_image_inline(self, url: str) -> tuple[str, str]:
        """
        Descarga una referencia y la devuelve como `(mime_type, base64)`.

        Existe porque no todos los proveedores aceptan una URL remota: la Gemini API
        exige la imagen inline. Se descarga con el cliente compartido pero **sin nuestras
        cabeceras de auth**, que van dirigidas al proveedor y no al bucket de donde sale
        la referencia; mandárselas a un tercero sería filtrar la clave.
        """
        try:
            response = await self.client.get(url, timeout=UPLOAD_TIMEOUT, follow_redirects=True)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderError(
                self.provider_id, f"could not download reference image {url}: {exc}"
            ) from exc
        if response.status_code != 200:
            raise ProviderRejectedError(
                self.provider_id,
                f"reference image {url} is not reachable (HTTP {response.status_code}). "
                f"The signed URL may have expired; regenerate it and retry.",
            )
        mime = (response.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        return mime, base64.b64encode(response.content).decode()

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        """
        Duración x precio por segundo, o precio por imagen. Los adaptadores con tarifa
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
