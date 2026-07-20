"""
Google Veo 3.1 y Gemini Omni Flash, vía Gemini API.

Google no devuelve un job id sino el *nombre* de una long-running operation
(`models/veo-3.1-generate-preview/operations/abc123`), que ya es la ruta de polling.
Por eso `poll_url` sale poblado desde el submit y este adaptador nunca construye URLs:
si Google cambia la topología, el ref guardado en BD sigue siendo válido.

La otra particularidad cara: los ficheros de salida tienen retención limitada y llegan
como URI de la File API, que exige la API key para descargarse. El asset hay que
copiarlo a nuestro storage antes de que caduque; esta capa solo devuelve la URL.
"""

from __future__ import annotations

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

#: Precio por segundo según resolución (informe 06 §2.1). Veo cobra distinto por 4K,
#: así que estimar con un único cost_per_second infravalora los planos en 4K.
_RESOLUTION_MULTIPLIER: dict[str, Decimal] = {
    "720p": Decimal("1.0"),
    "1080p": Decimal("1.0"),
    "4k": Decimal("1.5"),
}

#: Veo genera en bloques de ~8 s. Pedir 5 s no sale más barato que pedir 8.
_BILLED_BLOCK_S = Decimal("8")


class VeoAdapter(HttpAdapter):
    """Adaptador de la familia Google (Veo 3.1 y Gemini Omni Flash)."""

    provider_id = "google"
    supported_modalities: tuple[Modality, ...] = ("video",)
    base_url = "https://generativelanguage.googleapis.com"

    #: Google no documenta un mínimo. 5 s es el suelo transversal seguro del informe 06.
    min_poll_interval_s = 5.0

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().google_api_key, "GOOGLE_API_KEY")
        return {"x-goog-api-key": key, "Content-Type": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        instance: dict[str, Any] = {"prompt": self._styled_prompt(req)}

        if req.init_image_url:
            # NO VERIFICADO: la doc de Gemini muestra imágenes inline en base64
            # (`bytesBase64Encoded`). Que acepte `gcsUri`/URL remota en `image` está
            # confirmado solo para Vertex AI, no para generativelanguage. Si falla,
            # hay que descargar la referencia y mandarla inline.
            instance["image"] = {"gcsUri": req.init_image_url, "mimeType": "image/jpeg"}

        if req.last_frame_url:
            # Veo 3.1 documenta control de last-frame; el nombre exacto del campo en la
            # Gemini API no lo he podido confirmar.
            # NO VERIFICADO: nombre del campo `lastFrame`.
            instance["lastFrame"] = {"gcsUri": req.last_frame_url, "mimeType": "image/jpeg"}

        if req.elements:
            # NO VERIFICADO: `referenceImages` es el nombre usado en Vertex; en la
            # Gemini API pública no está documentado para Veo 3.1.
            instance["referenceImages"] = [
                {"image": {"gcsUri": e.image_url, "mimeType": "image/jpeg"}, "referenceType": "asset"}
                for e in req.elements[:3]
            ]

        parameters: dict[str, Any] = {"sampleCount": 1}
        if req.aspect:
            parameters["aspectRatio"] = req.aspect
        if req.resolution:
            parameters["resolution"] = req.resolution
        if req.duration_s:
            parameters["durationSeconds"] = round(req.duration_s)
        if req.negative_prompt:
            parameters["negativePrompt"] = req.negative_prompt
        if req.seed is not None:
            parameters["seed"] = req.seed
        # Veo 3.x lleva audio nativo; se apaga explícitamente porque generarlo y
        # descartarlo se paga igual.
        parameters["generateAudio"] = bool(req.audio)

        response = await self.request(
            "POST",
            f"/v1beta/models/{req.model_id}:predictLongRunning",
            json={"instances": [instance], "parameters": parameters},
            timeout=UPLOAD_TIMEOUT,
        )
        body = response.json()
        name = body.get("name")
        if not name:
            raise ProviderRejectedError(
                self.provider_id, f"submit returned no operation name: {body}"
            )
        return job_ref(self.provider_id, name, poll_url=f"/v1beta/{name}", raw=body)

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        response = await self.request("GET", ref.poll_url or f"/v1beta/{ref.external_id}")
        return self._read_operation(response.json())

    def _read_operation(self, body: dict[str, Any]) -> ProviderJobStatus:
        if not body.get("done"):
            # Google no expone porcentaje de progreso en la operación.
            return ProviderJobStatus(state="running", raw=body)

        if "error" in body:
            message = str(body["error"].get("message", "unknown error"))
            # La moderación de Google llega como error genérico; el marcador fiable es
            # el texto. Distinguirlo importa porque nsfw se reembolsa y failed no.
            lowered = message.lower()
            if any(w in lowered for w in ("safety", "blocked", "policy", "responsible ai")):
                return ProviderJobStatus(state="nsfw", error=message, raw=body)
            return ProviderJobStatus(state="failed", error=message, raw=body)

        urls = self._extract_urls(body.get("response", {}))
        if not urls:
            return ProviderJobStatus(
                state="failed", error="operation completed without any video URI", raw=body
            )
        return ProviderJobStatus(state="succeeded", progress=1.0, output_urls=urls, raw=body)

    @staticmethod
    def _extract_urls(response: dict[str, Any]) -> list[str]:
        """
        La forma de la respuesta ha cambiado entre versiones de la API, así que se
        buscan las dos que se han visto en vez de asumir una.
        """
        urls: list[str] = []
        for video in response.get("generatedVideos") or []:
            uri = (video.get("video") or {}).get("uri") or video.get("uri")
            if uri:
                urls.append(uri)
        for prediction in response.get("predictions") or []:
            uri = prediction.get("videoUri") or (prediction.get("video") or {}).get("uri")
            if uri:
                urls.append(uri)
        return urls

    # -- cancel ------------------------------------------------------------- #

    async def cancel(self, ref: ProviderJobRef) -> None:
        # NO VERIFICADO: la Gemini API expone `operations.cancel` en la superficie
        # estándar de LRO, pero no está documentado para Veo. Si devuelve 4xx se ignora:
        # cancelar es best-effort y no debe romper el flujo de limpieza.
        try:
            await self.request(
                "POST", f"/v1beta/{ref.external_id}:cancel", json={}, expected=(200, 202, 204)
            )
        except Exception:
            return None

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        """Se factura el bloque completo de 8 s aunque se pidan 5."""
        multiplier = _RESOLUTION_MULTIPLIER.get((req.resolution or "1080p").lower(), Decimal("1.0"))
        requested = Decimal(str(req.duration_s or spec.min_duration_s or 8))
        blocks = (requested / _BILLED_BLOCK_S).to_integral_value(rounding="ROUND_CEILING")
        billed = max(blocks, Decimal("1")) * _BILLED_BLOCK_S
        return _money(Decimal(spec.cost_per_second) * billed * multiplier)
