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


async def test_elevenlabs_speech_to_speech_uploads_reference_and_targets_voice() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        return httpx.Response(200, content=b"ID3converted", headers={"content-type": "audio/mpeg"})

    get_settings.cache_clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ElevenLabsAdapter(client)
    # Fuente como data URI: es exactamente el formato en que se guardan los audios.
    source = "data:audio/mpeg;base64," + __import__("base64").b64encode(b"take-audio").decode()
    req = GenerationRequest(
        modality="audio",
        model_id="eleven-multilingual-v2",
        prompt="ignored; the words come from the recording",
        duration_s=3,
        extra={
            "audio_kind": "voice",
            "voice_id": "voice-target",
            "voice_settings": {"stability": 0.4},
            "speech_to_speech": True,
            "source_audio_url": source,
        },
    )
    ref = await adapter.submit(req)
    status = await adapter.poll(ref)
    await client.aclose()

    assert captured["path"] == "/v1/speech-to-speech/voice-target"
    assert captured["content_type"].startswith("multipart/form-data")
    assert b"eleven_multilingual_sts_v2" in captured["body"]
    assert b"take-audio" in captured["body"]
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
