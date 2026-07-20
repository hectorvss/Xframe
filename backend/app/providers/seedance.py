"""
ByteDance / Dreamina Seedance, vía la API de tareas de BytePlus ModelArk.

**Este adaptador está desactivado a propósito. `submit` falla en vez de llamar.**

La versión anterior tenía tres cosas mal a la vez, y las tres a la vez apuntaban a una
API que no existe: el host (`ark.ap-southeast.volces.com`, que es la marca Volcengine y
no la internacional), los model ids (`seedance-2-0-pro` y compañía, inventados) y el
esquema de parámetros (los flags `--resolution 1080p` pegados al prompt son de Seedance
1.x; la 2.0 usa campos JSON de primer nivel).

He podido corregir las tres contra fuentes concordantes —host
`ark.ap-southeast.bytepluses.com`, ids `dreamina-seedance-2-0-260128` y variantes,
parámetros `ratio`/`resolution`/`duration`/`generate_audio`— pero **no contra la
documentación oficial**: docs.byteplus.com sirve el contenido por JavaScript y devuelve
solo el árbol de navegación a cualquier cliente que no sea un navegador.

Seedance 2.0 es, con diferencia, el modelo más caro del catálogo (~$21 por job en 4K).
Con la traducción sin verificar de primera mano, el fallo probable no es un 400 limpio:
es una llamada que el proveedor acepta, factura y devuelve algo que no es lo que se
pidió. Por eso los modelos están sembrados como `deprecated` y `submit` falla con un
mensaje claro. La traducción corregida vive en `build_payload()`, probada y lista: para
activarlo basta confirmar el esquema en la consola de ModelArk, borrar el `raise` y
pasar los modelos a `active`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.providers._http import HttpAdapter, _money
from app.providers.base import (
    GenerationRequest,
    Modality,
    ModelSpec,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.tools.errors import XframeToolFatalError

# Host internacional (BytePlus ModelArk). El chino es `ark.cn-beijing.volces.com` y usa
# ids `doubao-*`: **base, id y clave van juntos o no funciona ninguno**. Mezclarlos da un
# fallo de autenticación, no un 404, que despista mucho más.
# NO VERIFICADO: no confirmado contra doc oficial legible por cliente HTTP. Ver docstring.
_ARK_BASE = "https://ark.ap-southeast.bytepluses.com"

# NO VERIFICADO: ids del catálogo internacional según fuentes concordantes, sin
# confirmación oficial. Los anteriores (`seedance-2-0-pro`) no existían en ningún sitio.
_MODEL_NAME: dict[str, str] = {
    "seedance-2.0": "dreamina-seedance-2-0-260128",
    "seedance-2.0-fast": "dreamina-seedance-2-0-fast-260128",
    "seedance-2.0-mini": "dreamina-seedance-2-0-mini-260615",
    "seedance-1.0-pro": "seedance-1-0-pro-250528",
}

#: Mensaje único para que el agente sepa qué hacer en vez de reintentar.
_DISABLED_MESSAGE = (
    "Seedance is disabled in this deployment: its request schema could not be verified "
    "against BytePlus official documentation, and it is the most expensive model in the "
    "catalogue (an unverified call is billed whether or not it does what we asked). "
    "Do not retry. Use kling-3.0 for a comparable cinematic look, or veo-3.1 if the shot "
    "needs native audio."
)

#: Seedance escala el precio con la resolución de forma agresiva; el rango declarado
#: (36-150 créditos/s de Runway) es 4x entre extremos.
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

    #: El `video_url` de Ark sale del object storage de BytePlus/Volcano, no de la API.
    output_domains = ("bytepluses.com", "byteplusapi.com", "volces.com", "volccdn.com")

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().bytedance_api_key, "BYTEDANCE_API_KEY")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        # Ver docstring. Fatal y no transitorio a propósito: reintentar no va a verificar
        # la documentación, y cada intento contra el modelo más caro del catálogo es
        # dinero real si por casualidad la llamada sale adelante.
        raise XframeToolFatalError(_DISABLED_MESSAGE)

    def build_payload(self, req: GenerationRequest) -> dict[str, Any]:
        """
        Traducción corregida al dialecto de Seedance 2.0. Hoy nadie la envía.

        Se mantiene probada y no borrada porque el trabajo caro no es escribirla, es
        averiguar qué campos son: dejarla aquí convierte la reactivación en "confirmar el
        esquema y quitar el raise" en vez de en rehacer la investigación.

        Dos cambios de fondo frente a la versión anterior:

        - **Los parámetros son campos JSON de primer nivel**, no flags `--clave valor`
          pegados al prompt. Esa convención es de Seedance 1.x; en 2.0 los flags se
          quedan dentro del texto del prompt y el modelo los interpreta como parte de la
          descripción del plano, que es peor que ignorarlos.
        - `duration` es un entero y `generate_audio` un booleano, ambos hermanos de
          `model` y `content`.
        """
        content: list[dict[str, Any]] = [{"type": "text", "text": self._styled_prompt(req)}]

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

        payload: dict[str, Any] = {
            "model": _MODEL_NAME.get(req.model_id, req.model_id),
            "content": content,
            "generate_audio": bool(req.audio),
            # El default de Ark es marcar el vídeo, y un watermark en un entregable de
            # cliente es un fallo de producto.
            "watermark": False,
        }
        if req.resolution:
            payload["resolution"] = req.resolution.lower()
        if req.aspect:
            payload["ratio"] = req.aspect
        if req.duration_s:
            payload["duration"] = round(req.duration_s)
        if req.seed is not None:
            payload["seed"] = req.seed
        return payload

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
        except Exception:
            return None

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        seconds = Decimal(str(req.duration_s or spec.min_duration_s or 5))
        multiplier = _RESOLUTION_MULTIPLIER.get(
            (req.resolution or "720p").lower(), Decimal("1.0")
        )
        return _money(Decimal(spec.cost_per_second) * seconds * multiplier)
