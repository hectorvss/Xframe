"""
Higgsfield: Soul (texto→imagen) y DoP (imagen→vídeo).

Este adaptador es distinto de los demás por una razón de producto, no técnica: **DoP es
el único proveedor del catálogo donde el movimiento de cámara es un parámetro del
modelo y no un adjetivo del prompt** (informe 06 §1.1). Por eso aquí no se llama a
`_styled_prompt` para la cámara: el motion viaja como `motions_id` (UUID) con su
`motions_strength`, que es exactamente la taxonomía que `camera_motions.provider_ref`
guarda. Aplanarlo en el prompt como hacen los demás adaptadores tiraría a la basura la
única capacidad que no se puede replicar comprando otro modelo.

El catálogo de motions es dinámico y se identifica por UUID, no por nombre, así que
`get_motions()` es parte del contrato de este adaptador y no un detalle: los UUIDs se
resuelven en runtime y se cachean en `camera_motions.provider_ref`.

Créditos: Higgsfield reembolsa en `failed` y `nsfw` [V]. Nuestro `ProviderJobStatus`
ya modela ambos estados por separado precisamente para poder reflejarlo.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.providers._http import UPLOAD_TIMEOUT, HttpAdapter, _money, job_ref
from app.providers.base import (
    GenerationRequest,
    Modality,
    ModelSpec,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.tools.errors import ProviderRejectedError

_MOTIONS_CACHE_TTL_S = 900.0

#: Nuestro id → variante del modelo DoP. `dop-turbo` es el default porque es el mejor
#: punto calidad/precio de los tres ($0.083/s frente a $0.115 del preview).
_DOP_MODEL: dict[str, str] = {
    "higgsfield-dop-lite": "dop-lite",
    "higgsfield-dop-turbo": "dop-turbo",
    "higgsfield-dop-preview": "dop-preview",
}

#: Enums de tamaño del SDK. Higgsfield no acepta ratios, solo estos nombres.
_SOUL_SIZE: dict[str, str] = {
    "1:1": "SQUARE_1536x1536",
    "9:16": "PORTRAIT_1536x2048",
    "16:9": "LANDSCAPE_2048x1536",
}


class HiggsfieldAdapter(HttpAdapter):
    provider_id = "higgsfield"
    supported_modalities: tuple[Modality, ...] = ("image", "video")
    base_url = "https://platform.higgsfield.ai"

    #: El SDK oficial poletea a 2 s [V]; no hay razón para ir más lento que el propio
    #: proveedor cuando él marca el ritmo.
    min_poll_interval_s = 2.0

    def __init__(self, client: Any | None = None) -> None:
        super().__init__(client)
        self._motions: dict[str, str] = {}
        self._motions_fetched_at: float = 0.0

    def auth_headers(self) -> dict[str, str]:
        settings = get_settings()
        key_id = self._require(settings.higgsfield_key_id, "HIGGSFIELD_KEY_ID")
        secret = self._require(settings.higgsfield_key_secret, "HIGGSFIELD_KEY_SECRET")
        # Formato literal del SDK: `Authorization: Key KEY_ID:KEY_SECRET` [V].
        return {"Authorization": f"Key {key_id}:{secret}", "Content-Type": "application/json"}

    # -- catálogo de motions ------------------------------------------------ #

    async def get_motions(self) -> dict[str, str]:
        """
        Nombre de preset → UUID.

        Se cachea 15 min: el catálogo cambia con los lanzamientos de Higgsfield, pero no
        durante una sesión. Sin caché, cada plano con cámara pagaría un round-trip extra.
        """
        if self._motions and time.monotonic() - self._motions_fetched_at < _MOTIONS_CACHE_TTL_S:
            return self._motions

        # NO VERIFICADO: el SDK expone `client.getMotions()`, pero la ruta HTTP concreta
        # no está documentada públicamente. `/v1/motions` es la inferencia coherente con
        # el resto de rutas del SDK.
        response = await self.request("GET", "/v1/motions")
        body = response.json()
        items = body if isinstance(body, list) else body.get("items") or body.get("motions") or []
        self._motions = {
            str(item.get("name", "")).strip().lower(): str(item.get("id"))
            for item in items
            if item.get("id") and item.get("name")
        }
        self._motions_fetched_at = time.monotonic()
        return self._motions

    async def _resolve_motion(self, motion: str) -> str | None:
        """
        Acepta ya un UUID (lo que guarda `camera_motions.provider_ref`) o un nombre.

        Si no resuelve devuelve None en vez de fallar: perder el movimiento de cámara
        degrada el plano, pero abortar la generación por un preset renombrado sería una
        respuesta desproporcionada.
        """
        if "-" in motion and len(motion) >= 32:
            return motion
        try:
            catalogue = await self.get_motions()
        except Exception:
            return None
        return catalogue.get(motion.strip().lower())

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        if req.modality == "image":
            path, params = "/v1/text2image/soul", await self._soul_params(req)
        else:
            path, params = "/v1/image2video/dop", await self._dop_params(req)

        response = await self.request(
            "POST", path, json={"params": params}, timeout=UPLOAD_TIMEOUT
        )
        body = response.json()
        request_id = body.get("id") or body.get("request_id") or (body.get("job_set") or {}).get("id")
        if not request_id:
            raise ProviderRejectedError(self.provider_id, f"submit returned no id: {body}")
        return job_ref(
            self.provider_id,
            request_id,
            poll_url=f"/v1/requests/{request_id}/status",
            raw=body,
        )

    async def _soul_params(self, req: GenerationRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "prompt": self._styled_prompt(req),
            "width_and_height": _SOUL_SIZE.get(req.aspect or "16:9", "SQUARE_1536x1536"),
            "quality": req.extra.get("quality", "1080p"),
            "batch_size": req.extra.get("batch_size", "SINGLE"),
            "enhance_prompt": bool(req.extra.get("enhance_prompt", False)),
        }
        if req.seed is not None:
            params["seed"] = req.seed
        if req.negative_prompt:
            params["negative_prompt"] = req.negative_prompt

        soul_id = req.extra.get("soul_id") or next(
            (e.element_id for e in req.elements if e.role == "character"), None
        )
        if soul_id:
            # Soul ID es la identidad entrenada de un personaje. Es lo que sostiene la
            # continuidad facial entre planos y no tiene equivalente en el resto de
            # proveedores: si existe para este element, tiene prioridad sobre mandar
            # la imagen como referencia suelta.
            # NO VERIFICADO: nombre del campo (`custom_reference_id` en algunos
            # revendedores, `soul_id` en otros).
            params["soul_id"] = soul_id
        elif req.elements:
            params["image_reference"] = [{"image_url": e.image_url} for e in req.elements[:4]]
        return params

    async def _dop_params(self, req: GenerationRequest) -> dict[str, Any]:
        references = self._ref_urls(req)
        if not references:
            raise ProviderRejectedError(
                self.provider_id,
                "DoP is image-to-video only: it needs an init image or at least one element "
                "reference. Generate a still with Soul or Flux first, then animate it.",
            )

        params: dict[str, Any] = {
            "model": _DOP_MODEL.get(req.model_id, "dop-turbo"),
            # A diferencia del resto de adaptadores, el prompt va limpio: la cámara la
            # lleva el modelo, no el texto.
            "prompt": ", ".join([req.prompt.strip(), *(v for v in req.style.values() if v)]),
            "input_images": [{"type": "image_url", "image_url": references[0]}],
            "enhance_prompt": bool(req.extra.get("enhance_prompt", False)),
            "check_nsfw": True,
        }
        if req.seed is not None:
            params["seed"] = req.seed
        if req.last_frame_url:
            params["input_images_end"] = [
                {"type": "image_url", "image_url": req.last_frame_url}
            ]
        if req.camera_motion:
            motion_id = await self._resolve_motion(req.camera_motion)
            if motion_id:
                params["motions"] = [{"id": motion_id}]
                params["motions_strength"] = req.camera_motion_strength or 0.6
        return params

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        path = ref.poll_url or f"/v1/requests/{ref.external_id}/status"
        response = await self.request("GET", path)
        body = response.json()

        status = str(body.get("status", "")).lower()
        if status in ("queued", "in_queue"):
            return ProviderJobStatus(state="queued", raw=body)
        if status in ("in_progress", "processing"):
            return ProviderJobStatus(state="running", raw=body)
        if status == "completed":
            urls = self._extract_urls(body)
            if not urls:
                return ProviderJobStatus(
                    state="failed", error="completed with no result url", raw=body
                )
            return ProviderJobStatus(state="succeeded", progress=1.0, output_urls=urls, raw=body)
        if status == "nsfw":
            # Estado propio de Higgsfield, y reembolsable [V]. Mapearlo a `failed`
            # costaría créditos del usuario en cada plano moderado.
            return ProviderJobStatus(
                state="nsfw", error="content flagged as NSFW by the provider", raw=body
            )
        if status == "failed":
            return ProviderJobStatus(
                state="failed", error=str(body.get("error") or "generation failed"), raw=body
            )
        if status == "cancelled":
            return ProviderJobStatus(state="cancelled", raw=body)

        return ProviderJobStatus(state="running", raw=body)

    @staticmethod
    def _extract_urls(body: dict[str, Any]) -> list[str]:
        """
        Un `jobSet` contiene N `jobs` (batch QUAD produce cuatro salidas), así que la
        respuesta es siempre una lista aunque casi siempre tenga un elemento.
        """
        urls: list[str] = []
        for job in body.get("jobs") or []:
            results = job.get("results") or {}
            raw = results.get("raw") or {}
            url = raw.get("url") or results.get("url")
            if url:
                urls.append(url)
        if not urls:
            direct = (body.get("results") or {}).get("raw", {}).get("url")
            if direct:
                urls.append(direct)
        return urls

    async def cancel(self, ref: ProviderJobRef) -> None:
        # NO VERIFICADO: el SDK no expone cancelación. Se intenta por simetría con el
        # patrón fal, que Higgsfield copia casi literalmente.
        try:
            await self.request(
                "POST", f"/v1/requests/{ref.external_id}/cancel", json={}, expected=(200, 202, 204)
            )
        except Exception:
            return None

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        """
        DoP se factura por clip de ~5 s, no por segundo (precios de revendedor, [S]).
        Se redondea al alza por bloques para no infravalorar clips más largos.
        """
        if spec.modality == "image":
            batch = 4 if req.extra.get("batch_size") == "QUAD" else 1
            per_image = getattr(spec, "cost_per_image", None) or spec.cost_per_second
            return _money(Decimal(per_image) * batch)

        seconds = Decimal(str(req.duration_s or 5))
        blocks = max((seconds / 5).to_integral_value(rounding="ROUND_CEILING"), Decimal("1"))
        return _money(Decimal(spec.cost_per_second) * blocks * 5)
