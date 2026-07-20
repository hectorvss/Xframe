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

#: Multiplicador de precio por resolución, **por variante**. Verificado contra
#: https://ai.google.dev/gemini-api/docs/veo (20 jul 2026): 720p es el default de las
#: tres, 1080p y 4K solo salen en clips de 8 s, y Lite no ofrece 4K en absoluto.
#:
#: Una única tabla plana (el 1.5 anterior) era falsa dos veces: aplicaba el salto de 4K
#: de Standard a Fast, cuyo salto real es el doble, y ofrecía 4K en Lite, donde pedirlo
#: es un 400. Ambas se pagan en dinero, no en errores.
_RESOLUTION_MULTIPLIER: dict[str, dict[str, Decimal]] = {
    "standard": {"720p": Decimal("1.0"), "1080p": Decimal("1.0"), "4k": Decimal("1.5")},
    "fast": {"720p": Decimal("1.0"), "1080p": Decimal("1.0"), "4k": Decimal("3.0")},
    "lite": {"720p": Decimal("1.0"), "1080p": Decimal("1.0")},
}

#: Veo genera en bloques de ~8 s. Pedir 5 s no sale más barato que pedir 8.
_BILLED_BLOCK_S = Decimal("8")

#: `durationSeconds` es un **string** y de un conjunto cerrado [V].
_ALLOWED_DURATIONS = ("4", "6", "8")

#: Veo solo acepta estos dos ratios [V]. Cualquier otro es un 400.
_ALLOWED_ASPECTS = ("16:9", "9:16")

#: Con `referenceImages` la API impone tres restricciones duras a la vez [V]. No están
#: en un `if` sino aquí arriba porque las tres se violan a la vez o ninguna.
_REFERENCE_MAX = 3
_REFERENCE_ASPECT = "16:9"
_REFERENCE_DURATION = "8"


def _variant(model_id: str) -> str:
    """Familia de precio a partir del id de modelo. `-lite-` gana a `-fast-`."""
    lowered = model_id.lower()
    if "lite" in lowered:
        return "lite"
    if "fast" in lowered:
        return "fast"
    return "standard"


class VeoAdapter(HttpAdapter):
    """Adaptador de la familia Google (Veo 3.1 y Gemini Omni Flash)."""

    provider_id = "google"
    supported_modalities: tuple[Modality, ...] = ("video",)
    base_url = "https://generativelanguage.googleapis.com"

    #: Google no documenta un mínimo. 5 s es el suelo transversal seguro del informe 06.
    min_poll_interval_s = 5.0

    #: El `video.uri` de la operación apunta al Files API de Gemini.
    output_domains = ("googleapis.com", "googleusercontent.com")

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().google_api_key, "GOOGLE_API_KEY")
        return {"x-goog-api-key": key, "Content-Type": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        instance: dict[str, Any] = {"prompt": self._styled_prompt(req)}
        parameters: dict[str, Any] = {"sampleCount": 1}

        use_references = bool(req.elements)
        if use_references and (req.init_image_url or req.last_frame_url):
            # Se rechaza aquí y no en el proveedor porque el mensaje del 400 de Google no
            # explica la alternativa, y el agente necesita saber cuál de los dos caminos
            # elegir para reintentar con sentido.
            raise ProviderRejectedError(
                self.provider_id,
                "Veo cannot combine character references with a start or end frame: "
                "referenceImages is mutually exclusive with image/lastFrame. Either drop "
                "the elements and animate the frame, or drop the frames and let the "
                "references drive continuity.",
            )

        if use_references:
            # Tres restricciones duras y simultáneas [V]: como máximo 3 referencias, solo
            # 16:9 y exactamente 8 s. Se fuerzan en vez de reenviar lo que pidió el
            # llamante: un 400 aquí cuesta un turno entero del agente y no cuesta nada
            # evitarlo, y salir en 9:16 sin avisar sería peor todavía.
            instance["referenceImages"] = [
                {
                    "image": await self._inline(element.image_url),
                    "referenceType": "asset",
                }
                for element in req.elements[:_REFERENCE_MAX]
            ]
            parameters["aspectRatio"] = _REFERENCE_ASPECT
            parameters["durationSeconds"] = _REFERENCE_DURATION
        else:
            if req.init_image_url:
                instance["image"] = await self._inline(req.init_image_url)
            if req.last_frame_url:
                instance["lastFrame"] = await self._inline(req.last_frame_url)
            if req.aspect:
                parameters["aspectRatio"] = self._aspect_for(req)
            parameters["durationSeconds"] = self._duration_for(req)

        if req.resolution:
            parameters["resolution"] = req.resolution
            if req.resolution.lower() != "720p":
                # 1080p y 4K **solo existen en clips de 8 s** [V]: pedirlos con 4 o 6 es
                # un 400. Se sube la duración en vez de bajar la resolución porque la
                # resolución es lo que el usuario pidió explícitamente, y porque Veo
                # factura el bloque de 8 s de todos modos: el plano más largo sale gratis.
                parameters["durationSeconds"] = "8"
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

    async def _inline(self, url: str) -> dict[str, Any]:
        """
        Referencia visual en el formato que exige la Gemini API [V].

        `gcsUri` es de Vertex AI y en `generativelanguage` se ignora en silencio: el
        modelo generaba sin la referencia y devolvía 200, que es la peor forma posible de
        fallar. Aquí se descarga y se manda en base64 inline.
        """
        mime, data = await self.fetch_image_inline(url)
        return {"inlineData": {"mimeType": mime, "data": data}}

    @staticmethod
    def _aspect_for(req: GenerationRequest) -> str:
        return req.aspect if req.aspect in _ALLOWED_ASPECTS else "16:9"

    @staticmethod
    def _duration_for(req: GenerationRequest) -> str:
        """
        String, no int [V], y de un conjunto cerrado.

        Se redondea hacia arriba: recortar el plano del usuario para ahorrar dos segundos
        que además se facturan igual (bloque de 8 s) sería el peor de los dos errores.
        """
        wanted = round(req.duration_s or 8)
        for option in _ALLOWED_DURATIONS:
            if int(option) >= wanted:
                return option
        return _ALLOWED_DURATIONS[-1]

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
        Ruta real de la salida [V]:
        `.response.generateVideoResponse.generatedSamples[].video.uri`.

        La versión anterior buscaba `generatedVideos` y `predictions`, que no existen en
        esta API: **toda** generación correcta se leía como sin salida y se marcaba
        `failed`. Se pagaba el vídeo y se tiraba. Los dos alias de más abajo se conservan
        por si Google reordena la envoltura, pero el camino canónico va primero y es el
        único que está verificado.
        """
        urls: list[str] = []
        samples = (response.get("generateVideoResponse") or {}).get("generatedSamples") or []
        for sample in samples:
            uri = (sample.get("video") or {}).get("uri") or sample.get("uri")
            if uri:
                urls.append(uri)
        if urls:
            return urls

        # Tolerancia defensiva: variantes vistas en clientes y en Vertex. Nunca deberían
        # dispararse contra la Gemini API.
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
        table = _RESOLUTION_MULTIPLIER[_variant(req.model_id)]
        resolution = (req.resolution or "1080p").lower()
        # Una resolución que la variante no ofrece (4K en Lite) se estima con el
        # multiplicador más alto que sí tiene. Sobreestimar reserva de más y se devuelve
        # en el cierre; subestimar deja el job sin saldo a mitad de camino.
        multiplier = table.get(resolution) or max(table.values())
        requested = Decimal(str(req.duration_s or spec.min_duration_s or 8))
        blocks = (requested / _BILLED_BLOCK_S).to_integral_value(rounding="ROUND_CEILING")
        billed = max(blocks, Decimal("1")) * _BILLED_BLOCK_S
        return _money(Decimal(spec.cost_per_second) * billed * multiplier)
