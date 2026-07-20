"""
MiniMax Hailuo.

Dos peculiaridades que condicionan el adaptador:

1. **El poll no devuelve el vídeo, devuelve un `file_id`.** Hay un tercer salto
   (`/v1/files/retrieve`) para obtener la URL de descarga. Se hace aquí, dentro de
   `poll`, porque un `succeeded` sin URL utilizable no es un `succeeded`: el
   orquestador marcaría el job como listo y el asset llegaría vacío.
2. **Los errores de negocio viajan en HTTP 200** dentro de `base_resp.status_code`.
   Sin traducirlos, un fallo de moderación pasaría por éxito.

MiniMax factura por vídeo y no por segundo (informe 06 §2.1, cifras [S]), así que el
`cost_per_second` sembrado es una división nuestra, no su tarifa.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.providers._http import UPLOAD_TIMEOUT, HttpAdapter, job_ref
from app.providers.base import (
    GenerationRequest,
    Modality,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.tools.errors import ProviderError, ProviderRejectedError

_MODEL_NAME: dict[str, str] = {
    "hailuo-2.3": "MiniMax-Hailuo-2.3",
    "hailuo-2.3-fast": "MiniMax-Hailuo-2.3-Fast",
    "hailuo-02": "MiniMax-Hailuo-02",
    "hailuo-02-fast": "MiniMax-Hailuo-02-Fast",
}

#: Códigos de negocio que significan "el contenido no pasa", no "el servicio falló".
#: NO VERIFICADO: los códigos exactos de MiniMax no están en la doc que he podido leer.
#: 1027 (content moderation) y 2013 (parámetro inválido) son los citados en fuentes
#: secundarias; conviene contrastarlos contra una respuesta real antes de fiar el
#: reembolso a esta lista.
_MODERATION_CODES = frozenset({1027, 2013, 2049})

#: Límite de ritmo, no de contenido: aquí sí se reintenta.
_RATE_LIMIT_CODES = frozenset({1002, 1039})


class HailuoAdapter(HttpAdapter):
    provider_id = "minimax"
    supported_modalities: tuple[Modality, ...] = ("video",)
    base_url = "https://api.minimax.io"

    min_poll_interval_s = 5.0

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().minimax_api_key, "MINIMAX_API_KEY")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        payload: dict[str, Any] = {
            "model": _MODEL_NAME.get(req.model_id, req.model_id),
            "prompt": self._styled_prompt(req),
            "duration": int(round(req.duration_s or 6)),
        }
        if req.resolution:
            payload["resolution"] = req.resolution.upper()
        if req.init_image_url:
            payload["first_frame_image"] = req.init_image_url
        if req.last_frame_url:
            # NO VERIFICADO: `last_frame_image` aparece en fuentes secundarias para
            # Hailuo 2.3; la doc oficial que he podido leer solo documenta first frame.
            payload["last_frame_image"] = req.last_frame_url
        if req.elements:
            # Subject reference (S2V): MiniMax solo admite **un** sujeto, así que se
            # manda el primer element y el resto se pierde. Es una limitación real del
            # proveedor y hay que reflejarla al elegir modelo, no taparla aquí.
            payload["subject_reference"] = [
                {"type": "character", "image": [req.elements[0].image_url]}
            ]
        # MiniMax reescribe el prompt por defecto, lo que rompe la continuidad entre
        # planos de una misma secuencia. Se apaga salvo petición explícita.
        payload["prompt_optimizer"] = bool(req.extra.get("prompt_optimizer", False))

        response = await self.request(
            "POST", "/v1/video_generation", json=payload, timeout=UPLOAD_TIMEOUT
        )
        body = response.json()
        self._raise_on_business_error(body)

        task_id = body.get("task_id")
        if not task_id:
            raise ProviderRejectedError(self.provider_id, f"submit returned no task_id: {body}")
        return job_ref(self.provider_id, task_id, poll_url="/v1/query/video_generation", raw=body)

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        response = await self.request(
            "GET", ref.poll_url or "/v1/query/video_generation", params={"task_id": ref.external_id}
        )
        body = response.json()

        status = str(body.get("status", "")).lower()
        if status in ("queueing", "preparing"):
            return ProviderJobStatus(state="queued", raw=body)
        if status == "processing":
            return ProviderJobStatus(state="running", raw=body)
        if status == "success":
            file_id = body.get("file_id")
            if not file_id:
                return ProviderJobStatus(
                    state="failed", error="success without file_id", raw=body
                )
            url = await self._download_url(file_id)
            return ProviderJobStatus(
                state="succeeded", progress=1.0, output_urls=[url], raw=body
            )
        if status == "fail":
            code = (body.get("base_resp") or {}).get("status_code")
            message = str((body.get("base_resp") or {}).get("status_msg") or "generation failed")
            if code in _MODERATION_CODES:
                return ProviderJobStatus(state="nsfw", error=message, raw=body)
            return ProviderJobStatus(state="failed", error=message, raw=body)

        return ProviderJobStatus(state="running", raw=body)

    async def _download_url(self, file_id: str) -> str:
        """El tercer salto. La URL que devuelve tiene TTL: hay que copiarla ya."""
        response = await self.request(
            "GET", "/v1/files/retrieve", params={"file_id": file_id}
        )
        body = response.json()
        url = (body.get("file") or {}).get("download_url")
        if not url:
            raise ProviderError(self.provider_id, f"file {file_id} has no download_url")
        return url

    # -- errores ------------------------------------------------------------ #

    def _raise_on_business_error(self, body: dict[str, Any]) -> None:
        base = body.get("base_resp") or {}
        code = base.get("status_code")
        if code in (0, None):
            return
        message = str(base.get("status_msg") or code)
        if code in _MODERATION_CODES:
            raise ProviderRejectedError(self.provider_id, f"content rejected: {message}")
        if code in _RATE_LIMIT_CODES:
            raise ProviderError(self.provider_id, f"rate limited: {message}")
        raise ProviderRejectedError(self.provider_id, f"code {code}: {message}")
