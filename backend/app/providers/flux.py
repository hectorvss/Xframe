"""
Black Forest Labs FLUX.2 (imagen).

Es el adaptador con más peso estratégico del bloque de imagen: FLUX.2 admite hasta 8
imágenes de referencia en una sola llamada y permite **combinar el personaje de una
referencia con la pose de otra** (informe 06 §3). Es el equivalente más cercano a Soul
ID sin entrenar nada, y por tanto el camino barato a la continuidad de personaje cuando
el proyecto no justifica pagar Soul ID.

Tres rarezas de BFL frente al resto del set:

- **Auth por `x-key`**, no por `Authorization`.
- **El submit devuelve `polling_url` absoluta y regional.** Hay que usarla tal cual:
  construir la URL a partir del id contra `api.bfl.ai` falla si la cuenta está en otra
  región. Por eso `poll_url` se persiste y nunca se recalcula.
- **La moderación no es un error, es un estado** (`Request Moderated` /
  `Content Moderated`), y además el resultado **se consume al leerlo**: la URL de
  salida caduca en ~10 minutos.

Se factura por megapíxel de salida, así que el coste depende de la resolución pedida y
`estimate_cost` no puede ser un precio plano por imagen.
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

_ENDPOINT: dict[str, str] = {
    "flux-2-pro": "/v1/flux-2-pro",
    "flux-2-max": "/v1/flux-2-max",
    "flux-kontext-pro": "/v1/flux-kontext-pro",
}

#: Píxeles por lado según resolución pedida. BFL acepta width/height explícitos y
#: redondea a múltiplos de 32 por su cuenta.
_DIMENSIONS: dict[tuple[str, str], tuple[int, int]] = {
    ("1080p", "16:9"): (1920, 1088),
    ("1080p", "9:16"): (1088, 1920),
    ("1080p", "1:1"): (1440, 1440),
    ("720p", "16:9"): (1280, 720),
    ("720p", "9:16"): (720, 1280),
    ("720p", "1:1"): (1024, 1024),
}

#: `input_image` … `input_image_8` [V]. Ocho campos numerados, no una lista.
_MAX_REFERENCES = 8


class FluxAdapter(HttpAdapter):
    provider_id = "bfl"
    supported_modalities: tuple[Modality, ...] = ("image",)
    base_url = "https://api.bfl.ai"

    #: La imagen sale en segundos, no en minutos: poletear a 5 s multiplicaría la
    #: latencia percibida de un storyboard de 10 viñetas.
    min_poll_interval_s = 1.5

    #: BFL entrega en `delivery-<region>.bfl.ai`, un host distinto del de la API y con
    #: TTL de ~10 min. Se cubre el dominio entero porque la región la elige el proveedor.
    output_domains = ("bfl.ai", "bfl.ml")

    #: BFL acepta `webhook_url` + `webhook_secret` en el propio submit, y firma con ese
    #: secreto. Es el único de los ocho que nos deja elegir el secreto por petición, así
    #: que aquí el webhook sí puede ser fuente de verdad si está configurado.
    webhook_url_field = "webhook_url"
    webhook_secret_field = "webhook_secret"

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().bfl_api_key, "BFL_API_KEY")
        return {"x-key": key, "Content-Type": "application/json", "accept": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        width, height = self._dimensions(req)
        payload: dict[str, Any] = {
            "prompt": self._styled_prompt(req),
            "width": width,
            "height": height,
            "output_format": "png",
            # `strict` frente al default: en un storyboard, una viñeta moderada obliga a
            # regenerar la secuencia entera, así que preferimos enterarnos pronto.
            "safety_tolerance": int(req.extra.get("safety_tolerance", 2)),
            # Flux reescribe (upsamplea) el prompt por defecto. Para una imagen suelta es
            # una mejora; para un storyboard es veneno, porque cada viñeta recibe una
            # reescritura distinta del mismo brief y la serie deja de parecer la misma
            # película. Aquí la continuidad manda sobre el acabado individual.
            # NO VERIFICADO: `disable_pup` no aparece en la referencia pública de BFL que
            # he podido leer (docs.bfl.ml solo documenta el flujo de edición). Si el
            # proveedor lo ignora, el efecto es el comportamiento actual, no un error.
            "disable_pup": True,
        }
        if req.seed is not None:
            payload["seed"] = req.seed

        # Callback: le decimos a BFL dónde avisarnos y con qué secreto firmar. Es opcional
        # en los dos sentidos —sin `PUBLIC_BASE_URL` alcanzable no se manda nada, y sin
        # secreto configurado el receptor ignorará el cuerpo y reconsultará con `poll()`—
        # así que activar esto solo puede acelerar el cierre, nunca cambiar su resultado.
        # El polling sigue siendo el camino que siempre funciona.
        if self.webhook_url_field:
            from app.jobs.webhooks import callback_url

            if url := callback_url(self.provider_id):
                payload[self.webhook_url_field] = url
                secret = get_settings().bfl_webhook_secret
                if secret and self.webhook_secret_field:
                    payload[self.webhook_secret_field] = secret

        # `negative_prompt` **no existe** en FLUX.2 pro: mandarlo no negaba nada, solo
        # daba la impresión de que sí. La negación va en el prompt o no va.

        payload.update(self._reference_fields(req))

        response = await self.request(
            "POST", _ENDPOINT.get(req.model_id, f"/v1/{req.model_id}"),
            json=payload, timeout=UPLOAD_TIMEOUT,
        )
        body = response.json()
        request_id = body.get("id")
        polling_url = body.get("polling_url")
        if not request_id:
            raise ProviderRejectedError(self.provider_id, f"submit returned no id: {body}")
        # Ver docstring: la polling_url es regional y no reconstruible.
        # `cost` y `megapixels` vienen ya calculados por BFL en el propio submit: son la
        # cifra real facturada, frente a la estimación de `estimate_cost`, que solo puede
        # adivinar los megapíxeles de las referencias. Se propagan en `raw` para que el
        # cierre del job cobre el delta contra el importe verdadero en vez del estimado.
        raw = dict(body)
        if body.get("cost") is not None:
            raw["actual_cost_usd"] = body["cost"]
        if body.get("megapixels") is not None:
            raw["actual_megapixels"] = body["megapixels"]
        return job_ref(self.provider_id, request_id, poll_url=polling_url, raw=raw)

    def _reference_fields(self, req: GenerationRequest) -> dict[str, Any]:
        """
        Referencias visuales: `input_image`, `input_image_2` … `input_image_8` [V].

        No hay ningún campo de lista. El adaptador mandaba `image_prompt` +
        `reference_images`, que FLUX.2 ignora sin quejarse: la llamada devolvía 200 y una
        imagen bonita **sin una sola referencia aplicada**. Es el fallo más engañoso del
        set porque invita a concluir que la continuidad de personaje no funciona, cuando
        lo que pasaba es que nunca se pidió.

        El orden importa: el prompt puede referirse a "image 1", "image 2"…, y ese índice
        es la posición en esta numeración.
        """
        fields: dict[str, Any] = {}
        for index, url in enumerate(self._ref_urls(req)[:_MAX_REFERENCES], start=1):
            fields["input_image" if index == 1 else f"input_image_{index}"] = url
        return fields

    @staticmethod
    def _dimensions(req: GenerationRequest) -> tuple[int, int]:
        key = ((req.resolution or "1080p").lower(), req.aspect or "16:9")
        return _DIMENSIONS.get(key, (1440, 1440))

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        url = ref.poll_url or "/v1/get_result"
        params = None if ref.poll_url else {"id": ref.external_id}
        response = await self.request("GET", url, params=params)
        body = response.json()

        status = str(body.get("status", ""))
        if status in ("Pending", "Queued"):
            return ProviderJobStatus(state="queued", raw=body)
        if status in ("Processing", "Running"):
            return ProviderJobStatus(state="running", raw=body)
        if status == "Ready":
            result = body.get("result") or {}
            url_out = result.get("sample")
            if not url_out:
                return ProviderJobStatus(
                    state="failed", error="Ready without a sample url", raw=body
                )
            # La URL caduca en ~10 min: quien reciba esto tiene que copiarla ya.
            return ProviderJobStatus(
                state="succeeded", progress=1.0, output_urls=[url_out], raw=body
            )
        if status in ("Request Moderated", "Content Moderated"):
            return ProviderJobStatus(
                state="nsfw",
                error=f"{status}: the prompt or a reference image was flagged by BFL",
                raw=body,
            )
        if status in ("Error", "Failed"):
            return ProviderJobStatus(
                state="failed", error=str(body.get("details") or status), raw=body
            )
        if status == "Task not found":
            # Ya consumido o expirado. Terminal: seguir poleteando no lo resucita.
            return ProviderJobStatus(
                state="failed", error="task not found (already consumed or expired)", raw=body
            )

        return ProviderJobStatus(state="running", raw=body)

    # BFL no expone cancelación: la generación de imagen dura segundos y cancelarla no
    # ahorraría nada. Se hereda el no-op.

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        """
        Por megapíxel de salida, más los megapíxeles de las referencias de entrada.

        Las referencias no son gratis (~$0.03/MP de entrada), y en este producto casi
        toda generación lleva elements adjuntos: ignorarlas subestimaría el coste de
        forma sistemática justo en el caso normal.
        """
        width, height = self._dimensions(req)
        megapixels = Decimal(width * height) / Decimal(1_000_000)

        per_mp = Decimal(spec.cost_per_second)  # se siembra como $/MP en modelos imagen
        cost = per_mp * megapixels

        references = len(self._ref_urls(req)[:_MAX_REFERENCES])
        if references:
            # NO VERIFICADO: se asume 1 MP por referencia de entrada. BFL cobra por los
            # MP reales, que no conocemos sin descargar la imagen. Es una estimación
            # previa a la llamada; el importe exacto llega en `cost` del submit y es el
            # que debe cerrar el job (ver `submit`).
            cost += Decimal("0.03") * references
        return _money(cost)
