"""
ByteDance Seedance, vía la API de tareas de Volcengine Ark.

Ark tiene un dialecto propio que no se parece a ningún otro del set: **los parámetros
no van en campos JSON, van como flags de texto pegados al prompt** (`--resolution 1080p
--duration 5 --ratio 16:9`). El contenido se manda como una lista tipo chat
(`{"type": "text"}` / `{"type": "image_url"}`), heredada de su API de LLM.

Traducir eso es todo el valor de este fichero: arriba de esta capa nadie debería saber
que existe una convención de flags en el prompt.

Seedance 2 es el modelo más caro del catálogo con diferencia ($0.36–1.50/s según el
informe 06). El `estimate_cost` importa aquí más que en ningún otro adaptador.
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

# NO VERIFICADO: el host de Ark depende de la región de la cuenta. `ark.ap-southeast.
# volces.com` es el internacional y `ark.cn-beijing.volces.com` el chino; el informe 06
# no cubre ByteDance directo (sus cifras son de Seedance revendido por Runway). Si la
# cuenta es china hay que cambiar esta base.
_ARK_BASE = "https://ark.ap-southeast.volces.com"

_MODEL_NAME: dict[str, str] = {
    "seedance-2.0": "seedance-2-0-pro",
    "seedance-2.0-mini": "seedance-2-0-mini",
    "seedance-2.0-fast": "seedance-2-0-fast",
    "seedance-1.0-pro": "seedance-1-0-pro-250528",
}

#: Seedance escala el precio con la resolución de forma agresiva; el rango declarado
#: (36–150 créditos/s de Runway) es 4x entre extremos.
_RESOLUTION_MULTIPLIER: dict[str, Decimal] = {
    "480p": Decimal("0.5"),
    "720p": Decimal("1.0"),
    "1080p": Decimal("2.0"),
    "4k": Decimal("4.0"),
}


class SeedanceAdapter(HttpAdapter):
    provider_id = "bytedance"
    supported_modalities: tuple[Modality, ...] = ("video",)
    base_url = _ARK_BASE

    min_poll_interval_s = 5.0

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().bytedance_api_key, "BYTEDANCE_API_KEY")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        content: list[dict[str, Any]] = [{"type": "text", "text": self._prompt_with_flags(req)}]

        # El orden importa: Ark interpreta la primera imagen como frame inicial y, si
        # hay `role`, la última como final. Reordenarlo cambia el plano.
        if req.init_image_url:
            content.append(
                {"type": "image_url", "image_url": {"url": req.init_image_url}, "role": "first_frame"}
            )
        if req.last_frame_url:
            content.append(
                {"type": "image_url", "image_url": {"url": req.last_frame_url}, "role": "last_frame"}
            )
        for element in req.elements[:4]:
            # NO VERIFICADO: `role: "reference_image"` para continuidad de personaje en
            # Seedance 2 viene de notas de release, no de la doc de la API.
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": element.image_url},
                    "role": "reference_image",
                }
            )

        response = await self.request(
            "POST",
            "/api/v3/contents/generations/tasks",
            json={"model": _MODEL_NAME.get(req.model_id, req.model_id), "content": content},
            timeout=UPLOAD_TIMEOUT,
        )
        body = response.json()
        task_id = body.get("id")
        if not task_id:
            raise ProviderRejectedError(self.provider_id, f"submit returned no id: {body}")
        return job_ref(
            self.provider_id,
            task_id,
            poll_url=f"/api/v3/contents/generations/tasks/{task_id}",
            raw=body,
        )

    def _prompt_with_flags(self, req: GenerationRequest) -> str:
        """
        Convención de Ark: los parámetros son sufijos `--clave valor` del prompt.

        Se construye aquí y no en el llamante porque es exactamente el tipo de detalle
        que esta capa existe para esconder.
        """
        prompt = self._styled_prompt(req)
        flags: list[str] = []
        if req.resolution:
            flags.append(f"--resolution {req.resolution}")
        if req.duration_s:
            flags.append(f"--duration {int(round(req.duration_s))}")
        if req.aspect:
            flags.append(f"--ratio {req.aspect}")
        if req.seed is not None:
            flags.append(f"--seed {req.seed}")
        # `watermark false` explícito: el default de Ark es marcar el vídeo, y un
        # watermark en un entregable de cliente es un fallo de producto.
        flags.append("--watermark false")
        return f"{prompt} {' '.join(flags)}".strip()

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        path = ref.poll_url or f"/api/v3/contents/generations/tasks/{ref.external_id}"
        response = await self.request("GET", path)
        body = response.json()

        status = str(body.get("status", "")).lower()
        if status == "queued":
            return ProviderJobStatus(state="queued", raw=body)
        if status == "running":
            return ProviderJobStatus(state="running", raw=body)
        if status == "succeeded":
            url = (body.get("content") or {}).get("video_url")
            if not url:
                return ProviderJobStatus(
                    state="failed", error="succeeded with no video_url", raw=body
                )
            return ProviderJobStatus(state="succeeded", progress=1.0, output_urls=[url], raw=body)
        if status in ("failed", "cancelled"):
            error = body.get("error") or {}
            code = str(error.get("code", "")).lower()
            message = str(error.get("message") or status)
            if status == "cancelled":
                return ProviderJobStatus(state="cancelled", raw=body)
            if "sensitive" in code or "risk" in code or "moderation" in code:
                return ProviderJobStatus(state="nsfw", error=message, raw=body)
            return ProviderJobStatus(state="failed", error=message, raw=body)

        return ProviderJobStatus(state="running", raw=body)

    async def cancel(self, ref: ProviderJobRef) -> None:
        # NO VERIFICADO: existencia del endpoint de cancelación en Ark. Best-effort.
        try:
            await self.request(
                "DELETE",
                f"/api/v3/contents/generations/tasks/{ref.external_id}",
                expected=(200, 202, 204),
            )
        except Exception:  # noqa: BLE001
            return None

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        seconds = Decimal(str(req.duration_s or spec.min_duration_s or 5))
        multiplier = _RESOLUTION_MULTIPLIER.get(
            (req.resolution or "720p").lower(), Decimal("1.0")
        )
        return _money(Decimal(spec.cost_per_second) * seconds * multiplier)
