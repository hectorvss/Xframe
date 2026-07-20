"""
OpenAI Sora 2 / Sora 2 Pro, vía la Videos API.

Patrón job + poll + **download**: a diferencia del resto, OpenAI no devuelve una URL
pública del vídeo. El contenido se sirve en `GET /v1/videos/{id}/content` y exige la
API key, así que la "URL de salida" que devolvemos no es consumible por el navegador
del usuario ni por otro proveedor. El orquestador tiene que descargar y republicar.

Se marca en `raw["requires_download"]` en vez de descargar aquí: este adaptador no
conoce el bucket, y meterle storage lo convertiría en otra cosa.

Toda la Videos API se apaga el 24 de septiembre de 2026 (informe 06 §2.2). El modelo
está sembrado como `deprecated` con `sunset_at`, que es lo que hace que la herramienta
deje de ofrecerlo sin tocar este fichero.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.providers._http import UPLOAD_TIMEOUT, HttpAdapter, _money, job_ref
from app.providers.base import (
    GenerationRequest,
    ModelSpec,
    Modality,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.tools.errors import ProviderRejectedError

#: Sora acepta un conjunto cerrado de tamaños; cualquier otro es un 400. Se corrige
#: antes de enviar en vez de dejar que el proveedor lo rechace, porque un rechazo
#: cuesta un turno completo del agente.
_SIZE_BY_ASPECT: dict[str, str] = {
    "16:9": "1280x720",
    "9:16": "720x1280",
}

#: Duraciones permitidas por variante (informe 06 §2.1).
_ALLOWED_SECONDS: dict[str, tuple[int, ...]] = {
    "sora-2": (4, 8, 12),
    "sora-2-pro": (10, 15, 25),
}

_PRICE_BY_SIZE: dict[str, Decimal] = {
    "1280x720": Decimal("1.0"),
    "720x1280": Decimal("1.0"),
    "1024x1792": Decimal("1.667"),  # $0.50/s sobre la base $0.30/s de Pro
    "1792x1024": Decimal("1.667"),
    "1920x1080": Decimal("2.333"),  # $0.70/s sobre $0.30/s
}


class SoraAdapter(HttpAdapter):
    provider_id = "openai"
    supported_modalities: tuple[Modality, ...] = ("video",)
    base_url = "https://api.openai.com"

    #: OpenAI publica límites por tier (25–375 req/min). 5 s deja margen incluso en
    #: tier 1 con varios planos en vuelo.
    min_poll_interval_s = 5.0

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().openai_api_key, "OPENAI_API_KEY")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        payload: dict[str, Any] = {
            "model": req.model_id,
            "prompt": self._styled_prompt(req),
            "size": self._size_for(req),
            "seconds": str(self._seconds_for(req)),
        }

        reference = req.init_image_url or next(
            (e.image_url for e in req.elements if e.image_url), None
        )
        if reference:
            # NO VERIFICADO: `input_reference` está documentado como upload multipart de
            # un fichero. Que acepte una URL remota como string es una suposición. Si el
            # proveedor devuelve 400 aquí, hay que pasar a multipart descargando antes.
            payload["input_reference"] = reference

        if req.seed is not None:
            # NO VERIFICADO: la Videos API no documenta `seed`. Se manda porque no
            # estorba si se ignora, y da reproducibilidad si existe.
            payload["seed"] = req.seed

        response = await self.request(
            "POST", "/v1/videos", json=payload, timeout=UPLOAD_TIMEOUT
        )
        body = response.json()
        job_id = body.get("id")
        if not job_id:
            raise ProviderRejectedError(self.provider_id, f"submit returned no id: {body}")
        return job_ref(
            self.provider_id,
            job_id,
            poll_url=f"/v1/videos/{job_id}",
            raw={"requires_download": True, "content_url": f"/v1/videos/{job_id}/content"},
        )

    def _size_for(self, req: GenerationRequest) -> str:
        if req.resolution and "x" in req.resolution:
            return req.resolution
        return _SIZE_BY_ASPECT.get(req.aspect or "16:9", "1280x720")

    def _seconds_for(self, req: GenerationRequest) -> int:
        """Se ajusta al valor permitido más cercano por arriba: recortar un plano es
        peor que pagar unos segundos de más."""
        allowed = _ALLOWED_SECONDS.get(req.model_id, (4, 8, 12))
        wanted = req.duration_s or allowed[0]
        for option in allowed:
            if option >= wanted:
                return option
        return allowed[-1]

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        response = await self.request("GET", ref.poll_url or f"/v1/videos/{ref.external_id}")
        body = response.json()

        status = str(body.get("status", "")).lower()
        progress = body.get("progress")
        progress_f = float(progress) / 100.0 if isinstance(progress, (int, float)) else None

        if status in ("queued", "in_queue"):
            return ProviderJobStatus(state="queued", progress=progress_f, raw=body)
        if status in ("in_progress", "processing", "running"):
            return ProviderJobStatus(state="running", progress=progress_f, raw=body)
        if status == "completed":
            content = f"{self.base_url}/v1/videos/{ref.external_id}/content"
            return ProviderJobStatus(
                state="succeeded", progress=1.0, output_urls=[content], raw=body
            )
        if status in ("failed", "error"):
            error = body.get("error") or {}
            message = str(error.get("message") or error.get("code") or "unknown error")
            code = str(error.get("code", "")).lower()
            if "moderation" in code or "content_policy" in code or "safety" in code:
                return ProviderJobStatus(state="nsfw", error=message, raw=body)
            return ProviderJobStatus(state="failed", error=message, raw=body)
        if status == "cancelled":
            return ProviderJobStatus(state="cancelled", raw=body)

        # Estado desconocido: se trata como running para no dar por muerto un job vivo.
        return ProviderJobStatus(state="running", progress=progress_f, raw=body)

    async def cancel(self, ref: ProviderJobRef) -> None:
        # NO VERIFICADO: no he confirmado que exista DELETE /v1/videos/{id} como
        # cancelación (podría ser solo borrado del recurso ya terminado).
        try:
            await self.request(
                "DELETE", f"/v1/videos/{ref.external_id}", expected=(200, 202, 204)
            )
        except Exception:  # noqa: BLE001
            return None

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        seconds = Decimal(self._seconds_for(req))
        multiplier = _PRICE_BY_SIZE.get(self._size_for(req), Decimal("1.0"))
        return _money(Decimal(spec.cost_per_second) * seconds * multiplier)
