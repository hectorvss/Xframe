"""
Alibaba Wan, vía DashScope.

DashScope es la única API del set donde el modo asíncrono es **opt-in por cabecera**
(`X-DashScope-Async: enable`). Sin ella la petición se queda colgada hasta que el vídeo
está listo y revienta el timeout de lectura: es un fallo silencioso y caro, por eso la
cabecera se pone en `auth_headers()` y no en el submit, donde sería más fácil olvidarla
al añadir un endpoint.

El otro detalle propio: el payload separa `input` (lo semántico) de `parameters` (lo
técnico), y el endpoint de polling es genérico (`/tasks/{id}`), no específico del
modelo, así que el `poll_url` es trivialmente derivable.

Wan es el más barato del catálogo con audio nativo ($0.05/s en 480p), lo que lo
convierte en el destino por defecto de las pruebas de encuadre antes de gastar en Veo.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.providers._http import UPLOAD_TIMEOUT, HttpAdapter, job_ref
from app.providers.base import (
    GenerationRequest,
    Modality,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.tools.errors import ProviderRejectedError

# NO VERIFICADO: `dashscope-intl` es el host internacional; las cuentas creadas en China
# usan `dashscope.aliyuncs.com`. La clave no es intercambiable entre ambos.
_DASHSCOPE_BASE = "https://dashscope-intl.aliyuncs.com"

_MODEL_NAME: dict[str, str] = {
    "wan-2.7": "wan2.7-t2v-plus",
    "wan-2.5": "wan2.5-t2v-preview",
    "wan-2.2-turbo": "wan2.2-t2v-turbo",
}

#: Variante image-to-video del mismo modelo. DashScope las trata como modelos
#: distintos, no como un flag, así que el i2v cambia el nombre del modelo.
_MODEL_NAME_I2V: dict[str, str] = {
    "wan-2.7": "wan2.7-i2v-plus",
    "wan-2.5": "wan2.5-i2v-preview",
    "wan-2.2-turbo": "wan2.2-i2v-turbo",
}


class WanAdapter(HttpAdapter):
    provider_id = "wan"
    supported_modalities: tuple[Modality, ...] = ("video",)
    base_url = _DASHSCOPE_BASE

    min_poll_interval_s = 5.0

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().wan_api_key, "WAN_API_KEY")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Ver docstring: sin esto la llamada es síncrona y muere por timeout.
            "X-DashScope-Async": "enable",
        }

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        is_i2v = bool(req.init_image_url)
        table = _MODEL_NAME_I2V if is_i2v else _MODEL_NAME
        model = table.get(req.model_id, req.model_id)

        payload_input: dict[str, Any] = {"prompt": self._styled_prompt(req)}
        if req.negative_prompt:
            payload_input["negative_prompt"] = req.negative_prompt
        if is_i2v:
            payload_input["img_url"] = req.init_image_url
        if req.last_frame_url:
            # NO VERIFICADO: `last_frame_url` está documentado para la familia
            # `wan-*-flf2v` (first-last-frame). Puede exigir cambiar de modelo en vez
            # de añadir el campo.
            payload_input["last_frame_url"] = req.last_frame_url

        parameters: dict[str, Any] = {}
        if req.resolution:
            parameters["resolution"] = req.resolution.upper()
        if req.duration_s:
            parameters["duration"] = int(round(req.duration_s))
        if req.aspect:
            # DashScope quiere píxeles, no ratio; se traduce con la resolución elegida.
            parameters["size"] = self._size_for(req)
        if req.seed is not None:
            parameters["seed"] = req.seed
        parameters["audio"] = bool(req.audio)
        # Igual que en Seedance: reescribir el prompt rompe la continuidad de serie.
        parameters["prompt_extend"] = bool(req.extra.get("prompt_extend", False))

        response = await self.request(
            "POST",
            "/api/v1/services/aigc/video-generation/video-synthesis",
            json={"model": model, "input": payload_input, "parameters": parameters},
            timeout=UPLOAD_TIMEOUT,
        )
        body = response.json()
        task_id = (body.get("output") or {}).get("task_id")
        if not task_id:
            message = body.get("message") or body.get("code") or body
            raise ProviderRejectedError(self.provider_id, f"submit returned no task_id: {message}")
        return job_ref(self.provider_id, task_id, poll_url=f"/api/v1/tasks/{task_id}", raw=body)

    @staticmethod
    def _size_for(req: GenerationRequest) -> str:
        base = {"480p": 480, "720p": 720, "1080p": 1080}.get((req.resolution or "720p").lower(), 720)
        ratio = req.aspect or "16:9"
        if ratio == "9:16":
            return f"{base}*{int(base * 16 / 9)}"
        if ratio == "1:1":
            return f"{base}*{base}"
        return f"{int(base * 16 / 9)}*{base}"

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        response = await self.request("GET", ref.poll_url or f"/api/v1/tasks/{ref.external_id}")
        body = response.json()

        output = body.get("output") or {}
        status = str(output.get("task_status", "")).upper()

        if status == "PENDING":
            return ProviderJobStatus(state="queued", raw=body)
        if status == "RUNNING":
            return ProviderJobStatus(state="running", raw=body)
        if status == "SUCCEEDED":
            url = output.get("video_url")
            if not url:
                return ProviderJobStatus(
                    state="failed", error="succeeded with no video_url", raw=body
                )
            return ProviderJobStatus(state="succeeded", progress=1.0, output_urls=[url], raw=body)
        if status in ("FAILED", "UNKNOWN"):
            code = str(output.get("code") or "")
            message = str(output.get("message") or "generation failed")
            if "DataInspection" in code or "InappropriateContent" in code:
                # DashScope nombra su moderación `DataInspectionFailed`.
                return ProviderJobStatus(state="nsfw", error=message, raw=body)
            return ProviderJobStatus(state="failed", error=message, raw=body)
        if status == "CANCELED":
            return ProviderJobStatus(state="cancelled", raw=body)

        return ProviderJobStatus(state="running", raw=body)

    async def cancel(self, ref: ProviderJobRef) -> None:
        # NO VERIFICADO: DashScope documenta cancelación solo para tareas en PENDING.
        # Sobre una tarea ya RUNNING devuelve 4xx, que aquí se traga a propósito.
        try:
            await self.request(
                "POST", f"/api/v1/tasks/{ref.external_id}/cancel", json={}, expected=(200, 202, 204)
            )
        except Exception:  # noqa: BLE001
            return None
