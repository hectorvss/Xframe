from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.runner import ConversationRunner
from app.context.manager import XframeContextManager, serialize_context
from app.context.types import XframeUIContext


@pytest.mark.asyncio
async def test_production_loader_does_not_swap_bindings_and_annotations(monkeypatch):
    binding = {
        "id": "11111111-1111-4111-8111-111111111111",
        "resource_type": "asset",
        "resource_id": "22222222-2222-4222-8222-222222222222",
        "scope_type": "scene",
        "scope_id": "33333333-3333-4333-8333-333333333333",
        "role": "product",
        "start_ms": 1200,
        "end_ms": 3800,
        "instructions": "Keep the exact product",
        "locked": True,
        "priority": 10,
        "metadata": {},
    }
    annotation = {
        "id": "44444444-4444-4444-8444-444444444444",
        "asset_id": "22222222-2222-4222-8222-222222222222",
        "kind": "region",
        "body": "Replace only this label",
        "time_ms": None,
        "geometry": {"type": "rect", "x": 0.2, "y": 0.3, "width": 0.4, "height": 0.2},
        "color": "#2563eb",
        "status": "open",
        "created_at": None,
    }

    async def fake_fetch(sql: str, *_args):
        if "from public.resource_bindings" in sql:
            return [binding]
        if "from public.asset_annotations" in sql:
            return [annotation]
        return []

    monkeypatch.setattr("app.context.manager.db.fetch", fake_fetch)
    production = await XframeContextManager("project", "user")._load_production()

    assert production["resource_bindings"][0]["resource_type"] == "asset"
    assert production["resource_bindings"][0]["scope_type"] == "scene"
    assert production["annotations"][0]["kind"] == "region"
    assert production["annotations"][0]["asset_id"] == annotation["asset_id"]


def test_annotations_are_serialized_even_without_other_production_sections():
    ctx = XframeUIContext(
        project_id="project",
        annotations=[
            {
                "id": "annotation-1",
                "asset_id": "asset-1",
                "kind": "region",
                "body": "Only this area",
                "geometry": {"type": "rect", "x": 0.1},
                "status": "open",
            }
        ],
    )

    text, _ = serialize_context(ctx)

    assert "<asset_annotations>" in text
    assert 'id="annotation-1"' in text
    assert "Only this area" in text


def test_audio_cue_serialization_preserves_full_scope_and_mix_controls():
    ctx = XframeUIContext(
        project_id="project",
        audio_cues=[
            {
                "id": "cue-1",
                "asset_id": "audio-1",
                "scene_id": "scene-1",
                "shot_id": "shot-1",
                "script_line_id": "line-1",
                "track_kind": "music",
                "start_ms": 1200,
                "end_ms": 4800,
                "source_in_ms": 300,
                "source_out_ms": 3900,
                "gain_db": -6,
                "fade_in_ms": 250,
                "fade_out_ms": 500,
                "pan": -0.25,
                "loop": True,
                "locked": True,
                "approved": True,
                "ducking_group": "dialogue",
                "ducking_db": -10,
                "narrative_role": "build tension",
            }
        ],
    )

    text, _ = serialize_context(ctx)

    assert 'scene="scene-1"' in text
    assert 'shot="shot-1"' in text
    assert 'line="line-1"' in text
    assert 'source_range_ms="300-3900"' in text
    assert 'fade_ms="250-500"' in text
    assert 'ducking_db="-10"' in text
    assert 'approved="true"' in text


@pytest.mark.asyncio
async def test_empty_ui_reference_lists_clear_previous_turn_context():
    class FakeGraph:
        async def aget_state(self, _config):
            return SimpleNamespace(next=(), values={"mode": "production"})

    runner = ConversationRunner.__new__(ConversationRunner)
    runner._graph = FakeGraph()
    state = await runner._resolve_input(
        config={"configurable": {"thread_id": "conversation"}},
        conversation_id="conversation",
        project_id="project",
        user_id="user",
        message="Continue without references",
        ui_context={"selected_asset_ids": [], "resource_refs": []},
        resume_payload=None,
    )

    assert state.selected_asset_ids == []
    assert state.resource_refs == []


@pytest.mark.asyncio
async def test_explicit_operation_and_quality_report_refs_are_project_validated(monkeypatch):
    operation_id = "11111111-1111-4111-8111-111111111111"
    report_id = "22222222-2222-4222-8222-222222222222"

    async def fake_fetch(sql: str, _project_id: str, ids: list[str]):
        if "public.asset_operations" in sql and operation_id in ids:
            return [{"id": operation_id, "label": "remix"}]
        if "public.quality_reports" in sql and report_id in ids:
            return [{"id": report_id, "label": "continuity"}]
        return []

    monkeypatch.setattr("app.context.manager.db.fetch", fake_fetch)
    refs = await XframeContextManager("project", "user")._resolve_resource_refs(
        [
            {"type": "operation", "id": operation_id, "mention": "operation-remix"},
            {"type": "report", "id": report_id, "mention": "report-continuity"},
            {
                "type": "report",
                "id": "33333333-3333-4333-8333-333333333333",
                "mention": "foreign-report",
            },
        ]
    )

    assert [(item["type"], item["id"]) for item in refs] == [
        ("operation", operation_id),
        ("report", report_id),
    ]
