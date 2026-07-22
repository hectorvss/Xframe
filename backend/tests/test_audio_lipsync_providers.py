from __future__ import annotations

import base64
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-eleven")
os.environ.setdefault("SYNC_API_KEY", "test-sync")

from app.config import get_settings
from app.jobs.queue import EnqueueResult
from app.providers.base import GenerationRequest, ModelSpec
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


async def test_speech_to_speech_end_to_end_from_tool_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: la tool generate_audio construye la petición desde una línea del
    guion con voz asignada + un asset de audio de referencia, y esa MISMA petición pasa
    por el adaptador real de ElevenLabs, que hace la conversión de voz (speech-to-speech).
    Se comprueban los dos empalmes: lo que la tool mete en `extra` y lo que el proveedor
    recibe en el multipart.
    """
    from tests.test_tools import FakeDB, make_ctx, make_model, make_snapshot

    import app.jobs.queue as queue_mod
    import app.jobs.resume as resume_mod
    import app.providers.registry as registry_mod
    import app.tools.generation as generation_mod
    from app.tools.generation import GenerateAudioTool

    scene_id = "55555555-5555-5555-5555-555555555555"
    line_id = "66666666-6666-6666-6666-666666666666"
    ref_asset_id = "77777777-7777-7777-7777-777777777777"
    source = "data:audio/mpeg;base64," + base64.b64encode(b"original-take").decode()

    fake_db = FakeDB(
        {
            "from public.script_lines": [
                {
                    "id": line_id,
                    "scene_id": scene_id,
                    "shot_id": None,
                    "text": "Esta frase la dijo otra voz.",
                    "target_duration_ms": 3000,
                    "emotion": None,
                    "direction": None,
                    "voice_profile_id": "voice-profile-1",
                    "provider_voice_id": "voice-target",
                    "settings": {"stability": 0.4},
                }
            ],
            "from public.assets": {
                "id": ref_asset_id,
                "name": "Take original",
                "type": "audio",
                "url": source,
                "status": "ready",
                "shot_id": None,
                "params": {"duration_s": 3},
            },
            "from public.script_scenes": {"id": scene_id, "timeline_start_ms": 0},
        }
    )
    monkeypatch.setattr(generation_mod, "db", fake_db, raising=False)

    # El adaptador real de ElevenLabs, con transporte simulado, hace de cotizador Y de
    # destino de la generación: la misma instancia recorre todo el camino.
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        return httpx.Response(200, content=b"ID3revoiced", headers={"content-type": "audio/mpeg"})

    get_settings.cache_clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ElevenLabsAdapter(client)

    spec = ModelSpec(
        id="eleven-multilingual-v2",
        family="ElevenLabs",
        provider="elevenlabs",
        modality="audio",
        cost_per_second=Decimal("0.10"),
    )

    class _Registry:
        async def resolve(self, model_id: str) -> tuple[Any, ModelSpec]:
            return adapter, spec

    monkeypatch.setattr(registry_mod, "get_registry", lambda: _Registry())

    enqueued: dict = {}

    async def fake_enqueue(request, *, project_id, shot_id=None, adapter, conversation_id=None):
        enqueued["request"] = request
        return EnqueueResult(
            job_id="job-sts-1",
            status="queued",
            idempotency_key="key-sts-1",
            credits_reserved=1,
            reused=False,
        )

    async def fake_mark_awaiting(**_: Any) -> None:
        return None

    monkeypatch.setattr(queue_mod, "enqueue", fake_enqueue)
    monkeypatch.setattr(resume_mod, "mark_awaiting", fake_mark_awaiting)

    snap = make_snapshot(models=[make_model("eleven-multilingual-v2", "audio")])
    tool = await GenerateAudioTool.create(make_ctx("production"), snap)
    assert tool is not None

    content, payload = await tool._arun_impl(
        kind="voice",
        model_id="eleven-multilingual-v2",
        script_line_ids=[line_id],
        reference_asset_id=ref_asset_id,
    )

    # (A) La tool tradujo "usa este audio" a los campos de speech-to-speech.
    request = enqueued["request"]
    assert request.extra["speech_to_speech"] is True
    assert request.extra["source_audio_url"] == source
    assert request.extra["voice_id"] == "voice-target"
    assert payload["job_id"] == "job-sts-1"

    # (B) Esa misma petición, por el adaptador real, hace la conversión de voz.
    ref = await adapter.submit(request)
    status = await adapter.poll(ref)
    await client.aclose()

    assert captured["path"] == "/v1/speech-to-speech/voice-target"
    assert captured["content_type"].startswith("multipart/form-data")
    assert b"eleven_multilingual_sts_v2" in captured["body"]
    assert b"original-take" in captured["body"]
    assert status.state == "succeeded"
    assert status.output_urls[0].startswith("data:audio/mpeg;base64,")


async def test_generate_audio_rejects_reference_for_non_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un audio de referencia en música/SFX/ambiente se rechaza con un mensaje claro:
    el proveedor solo hace texto->sonido ahí, no audio-a-audio."""
    from tests.test_tools import FakeDB, make_ctx, make_model, make_snapshot

    import app.tools.generation as generation_mod
    from app.tools.errors import XframeToolRetryableError
    from app.tools.generation import GenerateAudioTool

    monkeypatch.setattr(generation_mod, "db", FakeDB({}), raising=False)
    snap = make_snapshot(models=[make_model("eleven-sfx-v2", "audio")])
    tool = await GenerateAudioTool.create(make_ctx("production"), snap)
    assert tool is not None

    with pytest.raises(XframeToolRetryableError, match="only applies to kind='voice'"):
        await tool._arun_impl(
            kind="sfx",
            model_id="eleven-sfx-v2",
            prompt="lluvia sobre metal",
            reference_asset_id="77777777-7777-7777-7777-777777777777",
        )


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
