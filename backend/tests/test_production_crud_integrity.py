from __future__ import annotations

import pytest

from app.tools.errors import XframeToolRetryableError
from app.tools.production_crud import _validated_audio_scope

pytestmark = pytest.mark.asyncio


async def test_audio_scope_derives_scene_from_line_and_shot(monkeypatch):
    async def fake_owned(table: str, _project_id: str, row_id: str):
        if table == "script_lines":
            return {"id": row_id, "scene_id": "scene-a", "shot_id": "shot-a"}
        if table == "canvas_nodes":
            return {"id": row_id, "type": "shot"}
        if table == "script_scenes":
            return {"id": row_id}
        raise AssertionError(table)

    async def fake_fetchrow(_sql: str, *_args):
        return {"scene_id": "scene-a"}

    monkeypatch.setattr("app.tools.production_crud._owned", fake_owned)
    monkeypatch.setattr("app.tools.production_crud.db.fetchrow", fake_fetchrow)

    scene_id = await _validated_audio_scope(
        "project",
        scene_id=None,
        shot_id="shot-a",
        script_line_id="line-a",
    )

    assert scene_id == "scene-a"


async def test_audio_scope_rejects_line_from_another_scene(monkeypatch):
    async def fake_owned(table: str, _project_id: str, row_id: str):
        if table == "script_lines":
            return {"id": row_id, "scene_id": "scene-b", "shot_id": None}
        if table == "script_scenes":
            return {"id": row_id}
        raise AssertionError(table)

    monkeypatch.setattr("app.tools.production_crud._owned", fake_owned)

    with pytest.raises(XframeToolRetryableError, match="belongs to scene scene-b"):
        await _validated_audio_scope(
            "project",
            scene_id="scene-a",
            shot_id=None,
            script_line_id="line-b",
        )
