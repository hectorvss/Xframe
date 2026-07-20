"""
Kling (Kuaishou), vía la Open Platform API.

Único proveedor del set que no usa una API key estática: exige un **JWT HS256 firmado
en cliente** con el access key como issuer y una ventana de validez corta. El token se
cachea hasta poco antes de expirar porque firmar en cada poll es gasto puro, pero no se
cachea "para siempre" porque un token vencido devuelve 401, que nuestra clasificación
trata como fatal y mataría el job.

Kling es el modelo con mejor soporte declarado de continuidad (start+end frame,
multi-image ref y correferencia de varios personajes), y por eso es el destino natural
cuando el plano tiene elements. El endpoint cambia según haya imagen de partida o no,
lo que obliga a que `poll_url` se derive del submit y se persista.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
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
from app.tools.errors import ProviderRejectedError

_TOKEN_TTL_S = 1800
_TOKEN_REFRESH_MARGIN_S = 120

#: Nuestro id de modelo → `model_name` de Kling. La tabla existe porque nuestros ids
#: llevan la familia delante y los suyos no.
_MODEL_NAME: dict[str, str] = {
    "kling-3.0": "kling-v3",
    "kling-3.0-turbo": "kling-v3-turbo",
    "kling-3.0-motion-control": "kling-v3-motion",
    "kling-2.5-turbo": "kling-v2-5-turbo",
    "kling-2.1-master": "kling-v2-1-master",
}

#: Kling factura por modo, no por segundo: `std` frente a `pro` es aproximadamente 2x.
_MODE_MULTIPLIER: dict[str, Decimal] = {"std": Decimal("1.0"), "pro": Decimal("2.0")}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class KlingAdapter(HttpAdapter):
    provider_id = "kling"
    supported_modalities: tuple[Modality, ...] = ("video",)
    base_url = "https://api.klingai.com"

    min_poll_interval_s = 5.0

    def __init__(self, client: Any | None = None) -> None:
        super().__init__(client)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # -- auth --------------------------------------------------------------- #

    def _jwt(self) -> str:
        """
        JWT HS256 firmado a mano.

        Se firma aquí en vez de con PyJWT para no arrastrar una dependencia por un
        algoritmo de doce líneas, y porque el header que espera Kling incluye `typ: JWT`
        en un orden concreto que algunas librerías reordenan.
        """
        now = time.time()
        if self._token and now < self._token_expires_at - _TOKEN_REFRESH_MARGIN_S:
            return self._token

        settings = get_settings()
        access = self._require(settings.kling_access_key, "KLING_ACCESS_KEY")
        secret = self._require(settings.kling_secret_key, "KLING_SECRET_KEY")

        expires_at = now + _TOKEN_TTL_S
        header = {"alg": "HS256", "typ": "JWT"}
        # `nbf` va 5 s en el pasado a propósito: el reloj de nuestro contenedor y el de
        # Kling no están sincronizados, y un desfase de milisegundos rechaza el token.
        payload = {"iss": access, "exp": int(expires_at), "nbf": int(now) - 5}

        signing_input = ".".join(
            _b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, payload)
        ).encode()
        signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()

        self._token = f"{signing_input.decode()}.{_b64url(signature)}"
        self._token_expires_at = expires_at
        return self._token

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._jwt()}", "Content-Type": "application/json"}

    # -- submit ------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        is_i2v = bool(req.init_image_url or req.elements)
        path = "/v1/videos/image2video" if is_i2v else "/v1/videos/text2video"

        payload: dict[str, Any] = {
            "model_name": _MODEL_NAME.get(req.model_id, req.model_id),
            "prompt": self._styled_prompt(req),
            "mode": self._mode_for(req),
            "duration": str(int(round(req.duration_s or 5))),
        }
        if req.negative_prompt:
            payload["negative_prompt"] = req.negative_prompt
        if req.aspect and not is_i2v:
            # En i2v el aspect lo fija la imagen; mandarlo provoca un rechazo.
            payload["aspect_ratio"] = req.aspect

        if is_i2v:
            references = self._ref_urls(req)
            payload["image"] = references[0]
            if req.last_frame_url:
                payload["image_tail"] = req.last_frame_url
            if len(references) > 1:
                # NO VERIFICADO: `image_list` para multi-referencia de personaje está
                # documentado para Kling 3.0 en fuentes secundarias, no en la doc oficial
                # que haya podido leer. El formato de cada entrada podría ser
                # {"image": url} en vez de la URL suelta.
                payload["image_list"] = [{"image": url} for url in references[1:5]]

        if req.camera_motion:
            # Kling expone control de cámara estructurado solo en la variante
            # motion-control; en el resto el movimiento va en el prompt (ya inyectado
            # por _styled_prompt).
            if req.model_id == "kling-3.0-motion-control":
                payload["camera_control"] = {
                    "type": req.camera_motion,
                    # NO VERIFICADO: la doc describe `config` con ejes numéricos
                    # (horizontal, vertical, pan, tilt, roll, zoom) y no un `type`
                    # nominal más intensidad. Este mapeo puede necesitar traducir cada
                    # movimiento a sus ejes.
                    "config": {"strength": req.camera_motion_strength or 0.5},
                }

        response = await self.request("POST", path, json=payload, timeout=UPLOAD_TIMEOUT)
        body = response.json()
        self._raise_on_business_error(body)

        task_id = (body.get("data") or {}).get("task_id")
        if not task_id:
            raise ProviderRejectedError(self.provider_id, f"submit returned no task_id: {body}")
        return job_ref(self.provider_id, task_id, poll_url=f"{path}/{task_id}", raw=body)

    def _mode_for(self, req: GenerationRequest) -> str:
        """1080p y 4K solo salen en `pro`; pedirlos en `std` devuelve 720p callado."""
        resolution = (req.resolution or "").lower()
        return "pro" if resolution in ("1080p", "4k") else "std"

    # -- poll --------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        path = ref.poll_url or f"/v1/videos/text2video/{ref.external_id}"
        response = await self.request("GET", path)
        body = response.json()

        data = body.get("data") or {}
        status = str(data.get("task_status", "")).lower()
        message = str(data.get("task_status_msg") or "")

        if status == "submitted":
            return ProviderJobStatus(state="queued", raw=body)
        if status == "processing":
            return ProviderJobStatus(state="running", raw=body)
        if status == "succeed":
            videos = (data.get("task_result") or {}).get("videos") or []
            urls = [v["url"] for v in videos if v.get("url")]
            if not urls:
                return ProviderJobStatus(
                    state="failed", error="succeeded with no video url", raw=body
                )
            return ProviderJobStatus(state="succeeded", progress=1.0, output_urls=urls, raw=body)
        if status == "failed":
            lowered = message.lower()
            if any(w in lowered for w in ("risk", "sensitive", "violat", "audit")):
                # Kling reporta la moderación como un fallo más; separarlo es lo que
                # dispara el reembolso.
                return ProviderJobStatus(state="nsfw", error=message, raw=body)
            return ProviderJobStatus(state="failed", error=message, raw=body)

        return ProviderJobStatus(state="running", raw=body)

    # Kling no expone cancelación de tarea en la doc consultada: se hereda el no-op de
    # la base, que es honesto. Un cancel silenciosamente inexistente sería peor.

    # -- coste -------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: Any) -> Decimal:
        from app.providers._http import _money

        seconds = Decimal(str(req.duration_s or spec.min_duration_s or 5))
        multiplier = _MODE_MULTIPLIER[self._mode_for(req)]
        return _money(Decimal(spec.cost_per_second) * seconds * multiplier)

    # -- errores ------------------------------------------------------------ #

    def _raise_on_business_error(self, body: dict[str, Any]) -> None:
        """
        Kling devuelve 200 con `code != 0` en errores de negocio. Sin esto, un rechazo
        por moderación se leería como un submit correcto y el job quedaría colgado
        esperando un task_id que no existe.
        """
        code = body.get("code")
        if code in (0, None):
            return
        message = str(body.get("message") or code)
        raise ProviderRejectedError(self.provider_id, f"code {code}: {message}")
