"""Sync Labs production lipsync adapter with explicit multi-speaker segments."""

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


class SyncLabsAdapter(HttpAdapter):
    provider_id = "sync"
    supported_modalities: tuple[Modality, ...] = ("lipsync",)
    base_url = "https://api.sync.so"
    min_poll_interval_s = 3.0
    output_domains = ("sync.so",)

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().sync_api_key, "SYNC_API_KEY")
        return {"x-api-key": key, "Content-Type": "application/json"}

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        if not req.init_image_url:
            raise ProviderRejectedError(self.provider_id, "lipsync requires a source video")

        raw_segments = req.extra.get("segments") or []
        audio_inputs: list[dict[str, Any]] = []
        ref_for_url: dict[str, str] = {}

        def audio_ref(url: str) -> str:
            if url not in ref_for_url:
                ref_for_url[url] = f"audio-{len(ref_for_url) + 1}"
                audio_inputs.append({"type": "audio", "url": url, "refId": ref_for_url[url]})
            return ref_for_url[url]

        segments: list[dict[str, Any]] = []
        for item in raw_segments if isinstance(raw_segments, list) else []:
            if not isinstance(item, dict) or not item.get("audio_url"):
                continue
            segment: dict[str, Any] = {
                "startTime": item["start_s"],
                "endTime": item["end_s"],
                "audioInput": {"refId": audio_ref(str(item["audio_url"]))},
            }
            face = item.get("face")
            if isinstance(face, dict) and face:
                segment["optionsOverride"] = {"active_speaker_detection": face}
            segments.append(segment)

        if not audio_inputs:
            audio_url = str(req.extra.get("audio_url") or "").strip()
            if not audio_url:
                raise ProviderRejectedError(self.provider_id, "lipsync requires an audio asset")
            audio_ref(audio_url)

        payload: dict[str, Any] = {
            "model": req.model_id,
            "input": [{"type": "video", "url": req.init_image_url}, *audio_inputs],
            "options": {"sync_mode": req.extra.get("sync_mode", "cut_off")},
        }
        if segments:
            payload["segments"] = segments

        response = await self.request("POST", "/v2/generate", json=payload, timeout=UPLOAD_TIMEOUT)
        body = response.json()
        external_id = body.get("id")
        if not external_id:
            raise ProviderRejectedError(self.provider_id, f"submit returned no id: {body}")
        return job_ref(self.provider_id, str(external_id), poll_url=f"/v2/generate/{external_id}", raw=body)

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        await self.throttled_poll_gate(ref.external_id)
        response = await self.request("GET", ref.poll_url or f"/v2/generate/{ref.external_id}")
        body = response.json()
        state = str(body.get("status") or body.get("state") or "").upper()
        if state in ("PENDING", "QUEUED", "CREATED"):
            return ProviderJobStatus(state="queued", raw=body)
        if state in ("PROCESSING", "RUNNING"):
            return ProviderJobStatus(state="running", progress=body.get("progress"), raw=body)
        if state == "COMPLETED":
            url = body.get("outputUrl") or body.get("output_url")
            if not url:
                return ProviderJobStatus(state="failed", error="completed without outputUrl", raw=body)
            return ProviderJobStatus(state="succeeded", progress=1, output_urls=[url], raw=body)
        if state in ("FAILED", "REJECTED"):
            return ProviderJobStatus(state="failed", error=str(body.get("error") or state), raw=body)
        if state == "CANCELLED":
            return ProviderJobStatus(state="cancelled", raw=body)
        return ProviderJobStatus(state="running", raw=body)

    async def cancel(self, ref: ProviderJobRef) -> None:
        # Sync does not document a cancellation endpoint for v2 generation.
        return None

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        return _money(Decimal(spec.cost_per_second) * Decimal(str(req.duration_s or 5)))
