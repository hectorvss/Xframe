from __future__ import annotations

import json
import os

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-eleven")
os.environ.setdefault("SYNC_API_KEY", "test-sync")

from app.config import get_settings
from app.providers.base import GenerationRequest
from app.providers.elevenlabs import ElevenLabsAdapter
from app.providers.sync_labs import SyncLabsAdapter

pytestmark = pytest.mark.asyncio


async def test_elevenlabs_dialogue_preserves_exact_text_and_speakers() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url.path == "/v1/text-to-dialogue"
        assert request.headers["xi-api-key"] == "test-eleven"
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    get_settings.cache_clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ElevenLabsAdapter(client)
    req = GenerationRequest(
        modality="audio",
        model_id="eleven-v3-dialogue",
        prompt="ignored in favour of approved inputs",
        duration_s=4,
        extra={
            "audio_kind": "dialogue",
            "dialogue_inputs": [
                {"text": "No cambies esta frase.", "voice_id": "voice-a"},
                {"text": "Ni esta.", "voice_id": "voice-b"},
            ],
        },
    )
    ref = await adapter.submit(req)
    status = await adapter.poll(ref)
    await client.aclose()

    assert captured["inputs"][0]["text"] == "No cambies esta frase."
    assert [item["voice_id"] for item in captured["inputs"]] == ["voice-a", "voice-b"]
    assert status.state == "succeeded"
    assert status.output_urls[0].startswith("data:audio/mpeg;base64,")


async def test_sync_labs_sends_explicit_segment_face_mapping() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured.update(json.loads(request.content))
            return httpx.Response(201, json={"id": "sync-job-1", "status": "PENDING"})
        return httpx.Response(
            200,
            json={"id": "sync-job-1", "status": "COMPLETED", "outputUrl": "https://cdn.sync.so/out.mp4"},
        )

    get_settings.cache_clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = SyncLabsAdapter(client)
    adapter.min_poll_interval_s = 0
    req = GenerationRequest(
        modality="lipsync",
        model_id="sync-3",
        prompt="",
        duration_s=2,
        init_image_url="https://assets.example/source.mp4",
        extra={
            "sync_mode": "cut_off",
            "segments": [
                {
                    "start_s": 0,
                    "end_s": 2,
                    "audio_url": "https://assets.example/line.mp3",
                    "face": {"type": "bounding_box", "x": 0.2, "y": 0.1, "width": 0.3, "height": 0.4},
                }
            ],
        },
    )
    ref = await adapter.submit(req)
    status = await adapter.poll(ref)
    await client.aclose()

    assert captured["input"][1]["refId"] == "audio-1"
    assert captured["segments"][0]["audioInput"]["refId"] == "audio-1"
    assert captured["segments"][0]["optionsOverride"]["active_speaker_detection"]["x"] == 0.2
    assert status.state == "succeeded"
    assert status.output_urls == ["https://cdn.sync.so/out.mp4"]
