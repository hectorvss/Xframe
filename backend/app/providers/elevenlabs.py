"""ElevenLabs voice, dialogue, music and sound-effects adapter.

The endpoints are synchronous, but they still implement the common submit/poll
contract. The encoded payload lives in ``ProviderJobRef.raw`` until the worker stores
it; this mirrors the existing OpenAI image adapter and keeps provider bytes out of the
database.
"""

from __future__ import annotations

import base64
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


class ElevenLabsAdapter(HttpAdapter):
    provider_id = "elevenlabs"
    supported_modalities: tuple[Modality, ...] = ("audio",)
    base_url = "https://api.elevenlabs.io"
    min_poll_interval_s = 1.0
    output_domains: tuple[str, ...] = ()

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().elevenlabs_api_key, "ELEVENLABS_API_KEY")
        return {"xi-api-key": key, "Content-Type": "application/json"}

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        kind = str(req.extra.get("audio_kind") or "voice")
        params: dict[str, Any] = {"output_format": req.extra.get("output_format", "mp3_44100_128")}

        if kind == "dialogue":
            inputs = req.extra.get("dialogue_inputs")
            if not isinstance(inputs, list) or not inputs:
                raise ProviderRejectedError(self.provider_id, "dialogue requires dialogue_inputs")
            path = "/v1/text-to-dialogue"
            body = {"inputs": inputs, "model_id": req.extra.get("provider_model_id", "eleven_v3")}
        elif kind == "music":
            path = "/v1/music"
            plan = req.extra.get("composition_plan")
            body = (
                {"composition_plan": plan}
                if isinstance(plan, dict) and plan
                else {"prompt": req.prompt, "music_length_ms": int((req.duration_s or 30) * 1000)}
            )
            body["model_id"] = req.extra.get("provider_model_id", "music_v2")
        elif kind in ("sfx", "ambience"):
            path = "/v1/sound-generation"
            body = {
                "text": req.prompt,
                "duration_seconds": req.duration_s,
                "prompt_influence": float(req.extra.get("prompt_influence", 0.5)),
                "loop": bool(req.extra.get("loop", kind == "ambience")),
            }
            body = {k: v for k, v in body.items() if v is not None}
        else:
            voice_id = str(req.extra.get("voice_id") or "").strip()
            if not voice_id:
                raise ProviderRejectedError(self.provider_id, "voice generation requires voice_id")
            path = f"/v1/text-to-speech/{voice_id}"
            body = {
                "text": req.prompt,
                "model_id": req.extra.get("provider_model_id", "eleven_v3"),
                "voice_settings": req.extra.get("voice_settings") or {},
            }

        response = await self.request(
            "POST", path, json=body, params=params, timeout=UPLOAD_TIMEOUT
        )
        mime = (response.headers.get("content-type") or "audio/mpeg").split(";")[0]
        if not response.content:
            raise ProviderRejectedError(self.provider_id, "generation returned an empty audio file")
        raw = {"audio_b64": base64.b64encode(response.content).decode(), "mime_type": mime}
        return job_ref(self.provider_id, "synchronous", raw=raw)

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        encoded = (ref.raw or {}).get("audio_b64")
        if not encoded:
            return ProviderJobStatus(
                state="failed",
                error="synchronous audio result was lost before it could be stored",
                raw=ref.raw,
            )
        mime = (ref.raw or {}).get("mime_type") or "audio/mpeg"
        return ProviderJobStatus(
            state="succeeded",
            progress=1.0,
            output_urls=[f"data:{mime};base64,{encoded}"],
            raw=ref.raw,
        )

    async def cancel(self, ref: ProviderJobRef) -> None:
        return None

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        # Catalogue rates are normalized to seconds for reservations. Text generation
        # uses the expected duration supplied by the screenplay/audio plan.
        return _money(Decimal(spec.cost_per_second) * Decimal(str(req.duration_s or 5)))
