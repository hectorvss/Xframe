"""Incremental screenplay editing and universal resource bindings."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from app import db
from app.taxonomy.builder import SnapshotTool
from app.tools.errors import XframeToolRetryableError

ALL_MODES: tuple[str, ...] = ("preproduction", "production", "edit")


async def _owned(table: str, project_id: str, row_id: str) -> dict[str, Any]:
    row = await db.fetchrow(
        f"select * from public.{table} where id=$1::uuid and project_id=$2::uuid",
        row_id,
        project_id,
    )
    if not row:
        raise XframeToolRetryableError(f"Unknown {table} id {row_id} in this project.")
    return dict(row)


async def _validated_audio_scope(
    project_id: str,
    *,
    scene_id: str | None,
    shot_id: str | None,
    script_line_id: str | None,
) -> str | None:
    """Return the canonical scene and reject contradictory audio context links."""
    effective_scene = scene_id
    if script_line_id:
        line = await _owned("script_lines", project_id, script_line_id)
        line_scene = str(line["scene_id"])
        if effective_scene and str(effective_scene) != line_scene:
            raise XframeToolRetryableError(
                f"Script line {script_line_id} belongs to scene {line_scene}, not {effective_scene}."
            )
        effective_scene = effective_scene or line_scene
        if shot_id and line.get("shot_id") and str(line["shot_id"]) != str(shot_id):
            raise XframeToolRetryableError(
                f"Script line {script_line_id} is bound to shot {line['shot_id']}, not {shot_id}."
            )
    if shot_id:
        shot = await _owned("canvas_nodes", project_id, shot_id)
        if shot.get("type") != "shot":
            raise XframeToolRetryableError(f"Canvas node {shot_id} is not a production shot.")
        membership = await db.fetchrow(
            """select scene_id from public.scene_shots
                where project_id=$1::uuid and shot_id=$2::uuid""",
            project_id,
            shot_id,
        )
        if not membership:
            raise XframeToolRetryableError(
                f"Shot {shot_id} must be assigned to a screenplay scene before audio can target it."
            )
        shot_scene = str(membership["scene_id"])
        if effective_scene and str(effective_scene) != shot_scene:
            raise XframeToolRetryableError(
                f"Shot {shot_id} belongs to scene {shot_scene}, not {effective_scene}."
            )
        effective_scene = effective_scene or shot_scene
    if effective_scene:
        await _owned("script_scenes", project_id, str(effective_scene))
    return str(effective_scene) if effective_scene else None


async def _validate_script_line_refs(
    project_id: str,
    *,
    scene_id: str,
    speaker_element_id: str | None,
    voice_profile_id: str | None,
    shot_id: str | None,
) -> None:
    if speaker_element_id:
        speaker = await _owned("assets", project_id, speaker_element_id)
        if not speaker.get("role"):
            raise XframeToolRetryableError(
                f"Asset {speaker_element_id} is not a reusable character Element."
            )
    if voice_profile_id:
        await _owned("voice_profiles", project_id, voice_profile_id)
    if shot_id:
        shot = await _owned("canvas_nodes", project_id, shot_id)
        if shot.get("type") != "shot":
            raise XframeToolRetryableError(f"Canvas node {shot_id} is not a production shot.")
        membership = await db.fetchrow(
            """select scene_id from public.scene_shots
                where project_id=$1::uuid and shot_id=$2::uuid""",
            project_id,
            shot_id,
        )
        if not membership:
            raise XframeToolRetryableError(
                f"Shot {shot_id} must be assigned to scene {scene_id} before a line can target it."
            )
        if str(membership["scene_id"]) != str(scene_id):
            raise XframeToolRetryableError(
                f"Shot {shot_id} belongs to scene {membership['scene_id']}, not {scene_id}."
            )


class CreateSceneArgs(BaseModel):
    title: str = "Nueva escena"
    setting: str = ""
    time_of_day: str = ""
    summary: str = ""
    dramatic_intent: str = ""
    timeline_start_ms: int | None = Field(
        None,
        ge=0,
        description="Absolute project offset. Omit to append after the latest timed scene.",
    )
    target_duration_ms: int | None = Field(None, gt=0)
    position: int | None = Field(None, ge=0)


class CreateScriptSceneTool(SnapshotTool):
    name: str = "create_script_scene"
    args_schema: type[BaseModel] = CreateSceneArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Create one editable screenplay scene without replacing the rest of the script. "
        "USE THIS when the user adds a scene or when a structured script is being built "
        "incrementally. DO NOT use create_screenplay merely to append one scene."
    )

    async def _arun_impl(self, position: int | None = None, **values: Any) -> tuple[str, Any]:
        async with db.transaction() as conn:
            if values["timeline_start_ms"] is None:
                values["timeline_start_ms"] = int(
                    await conn.fetchval(
                        """select coalesce(max(timeline_start_ms +
                                   coalesce(target_duration_ms,0)),0)
                             from public.script_scenes where project_id=$1::uuid""",
                        self.ctx.project_id,
                    )
                )
            if position is None:
                position = int(await conn.fetchval(
                    "select coalesce(max(position),-1)+1 from public.script_scenes where project_id=$1::uuid",
                    self.ctx.project_id,
                ))
            else:
                await conn.execute(
                    "update public.script_scenes set position=position+1 where project_id=$1::uuid and position >= $2",
                    self.ctx.project_id,
                    position,
                )
            row = await conn.fetchrow(
                """insert into public.script_scenes
                   (project_id,position,title,setting,time_of_day,summary,dramatic_intent,
                    timeline_start_ms,target_duration_ms)
                   values ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9) returning *""",
                self.ctx.project_id, position, values["title"], values["setting"],
                values["time_of_day"], values["summary"], values["dramatic_intent"],
                values["timeline_start_ms"], values["target_duration_ms"],
            )
        result = dict(row) | {"id": str(row["id"])}
        return f"Scene {position + 1} created with id {row['id']}.", result


class UpdateSceneArgs(BaseModel):
    scene_id: str
    title: str | None = None
    setting: str | None = None
    time_of_day: str | None = None
    summary: str | None = None
    dramatic_intent: str | None = None
    timeline_start_ms: int | None = Field(None, ge=0)
    target_duration_ms: int | None = Field(None, gt=0)
    clear_target_duration: bool = False
    status: Literal["draft", "approved", "locked"] | None = None


class UpdateScriptSceneTool(SnapshotTool):
    name: str = "update_script_scene"
    args_schema: type[BaseModel] = UpdateSceneArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Patch one screenplay scene while preserving all other scenes and lines. USE THIS "
        "for a note scoped to an existing scene. DO NOT recreate the whole screenplay or "
        "guess a scene id; use the id in project context."
    )

    async def _arun_impl(self, scene_id: str, **values: Any) -> tuple[str, Any]:
        current = await _owned("script_scenes", self.ctx.project_id, scene_id)
        clear_target_duration = bool(values.pop("clear_target_duration", False))
        patch = {key: value for key, value in values.items() if value is not None}
        if clear_target_duration:
            patch["target_duration_ms"] = None
        if not patch:
            raise XframeToolRetryableError("No scene fields were supplied to update.")
        merged = current | patch
        row = await db.fetchrow(
            """update public.script_scenes set title=$3,setting=$4,time_of_day=$5,
               summary=$6,dramatic_intent=$7,timeline_start_ms=$8,
               target_duration_ms=$9,status=$10,updated_at=now()
               where id=$1::uuid and project_id=$2::uuid returning *""",
            scene_id, self.ctx.project_id, merged["title"], merged["setting"],
            merged["time_of_day"], merged["summary"], merged["dramatic_intent"],
            merged["timeline_start_ms"], merged["target_duration_ms"], merged["status"],
        )
        return f"Scene {scene_id} updated.", dict(row) | {"id": str(row["id"])}


class DeleteIdArgs(BaseModel):
    id: str


class DeleteScriptSceneTool(SnapshotTool):
    name: str = "delete_script_scene"
    args_schema: type[BaseModel] = DeleteIdArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Delete one screenplay scene and its lines. USE THIS only when the user explicitly "
        "removes a scene and understands that its ordered lines and scene-scoped links "
        "will also disappear. DO NOT use it to hide, shorten or rewrite a scene; update it "
        "instead, and never infer deletion from a general request to improve pacing."
    )

    async def _arun_impl(self, id: str, **_: Any) -> tuple[str, Any]:
        row = await _owned("script_scenes", self.ctx.project_id, id)
        line_ids = await db.fetch(
            "select id from public.script_lines where project_id=$1::uuid and scene_id=$2::uuid",
            self.ctx.project_id,
            id,
        )
        async with db.transaction() as conn:
            await conn.execute(
                """delete from public.resource_bindings
                    where project_id=$1::uuid and (
                      (scope_type='scene' and scope_id=$2::uuid) or
                      (scope_type='line' and scope_id=any($3::uuid[])))""",
                self.ctx.project_id,
                id,
                [str(item["id"]) for item in line_ids],
            )
            await conn.execute("delete from public.script_scenes where id=$1::uuid", id)
        return f"Scene '{row['title']}' deleted.", {"scene_id": id, "deleted": True}


class ScriptLineArgs(BaseModel):
    scene_id: str
    line_type: Literal["dialogue", "voiceover", "action", "caption"] = "dialogue"
    speaker_element_id: str | None = None
    voice_profile_id: str | None = None
    shot_id: str | None = None
    text: str = Field(min_length=1)
    language: str = "es"
    emotion: str = "neutral"
    direction: str = ""
    pace: float = Field(1, ge=0.5, le=2)
    intensity: float = Field(0.5, ge=0, le=1)
    pause_before_ms: int = Field(0, ge=0)
    pause_after_ms: int = Field(0, ge=0)
    target_duration_ms: int | None = Field(None, gt=0)
    position: int | None = Field(None, ge=0)


class CreateScriptLineTool(SnapshotTool):
    name: str = "create_script_line"
    args_schema: type[BaseModel] = ScriptLineArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Add one exact dialogue, voiceover, action or caption line to a scene. USE THIS "
        "when wording must remain editable and addressable by id. DO NOT paraphrase approved "
        "copy or generate speech directly from unstructured text."
    )

    async def _arun_impl(self, scene_id: str, position: int | None = None, **v: Any) -> tuple[str, Any]:
        await _owned("script_scenes", self.ctx.project_id, scene_id)
        await _validate_script_line_refs(
            self.ctx.project_id,
            scene_id=scene_id,
            speaker_element_id=v.get("speaker_element_id"),
            voice_profile_id=v.get("voice_profile_id"),
            shot_id=v.get("shot_id"),
        )
        async with db.transaction() as conn:
            if position is None:
                position = int(await conn.fetchval(
                    "select coalesce(max(position),-1)+1 from public.script_lines where scene_id=$1::uuid", scene_id
                ))
            else:
                await conn.execute(
                    "update public.script_lines set position=position+1 where scene_id=$1::uuid and position >= $2",
                    scene_id, position,
                )
            row = await conn.fetchrow(
                """insert into public.script_lines
                   (project_id,scene_id,position,line_type,speaker_element_id,voice_profile_id,
                    shot_id,text,language,emotion,direction,pace,intensity,pause_before_ms,
                    pause_after_ms,target_duration_ms)
                   values ($1::uuid,$2::uuid,$3,$4,$5::uuid,$6::uuid,$7::uuid,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                   returning *""",
                self.ctx.project_id, scene_id, position, v["line_type"], v["speaker_element_id"],
                v["voice_profile_id"], v["shot_id"], v["text"], v["language"], v["emotion"],
                v["direction"], v["pace"], v["intensity"], v["pause_before_ms"],
                v["pause_after_ms"], v["target_duration_ms"],
            )
        return f"Script line {row['id']} created.", dict(row) | {"id": str(row["id"])}


class UpdateLineArgs(BaseModel):
    line_id: str
    line_type: Literal["dialogue", "voiceover", "action", "caption"] | None = None
    speaker_element_id: str | None = None
    clear_speaker: bool = False
    voice_profile_id: str | None = None
    clear_voice: bool = False
    shot_id: str | None = None
    clear_shot: bool = False
    text: str | None = Field(None, min_length=1)
    language: str | None = None
    emotion: str | None = None
    direction: str | None = None
    pace: float | None = Field(None, ge=0.5, le=2)
    intensity: float | None = Field(None, ge=0, le=1)
    pause_before_ms: int | None = Field(None, ge=0)
    pause_after_ms: int | None = Field(None, ge=0)
    target_duration_ms: int | None = Field(None, gt=0)
    clear_target_duration: bool = False
    status: Literal["draft", "ready", "generating", "review", "approved", "failed"] | None = None


class UpdateScriptLineTool(SnapshotTool):
    name: str = "update_script_line"
    args_schema: type[BaseModel] = UpdateLineArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Patch one screenplay line, including wording, speaker, voice, shot, performance "
        "and approval status. USE THIS for precise line notes. DO NOT replace the complete "
        "screenplay or alter approved wording unless the user asks."
    )

    async def _arun_impl(self, line_id: str, **values: Any) -> tuple[str, Any]:
        current = await _owned("script_lines", self.ctx.project_id, line_id)
        clear_speaker = bool(values.pop("clear_speaker", False))
        clear_voice = bool(values.pop("clear_voice", False))
        clear_shot = bool(values.pop("clear_shot", False))
        clear_target_duration = bool(values.pop("clear_target_duration", False))
        patch = {key: value for key, value in values.items() if value is not None}
        if clear_speaker:
            patch["speaker_element_id"] = None
        if clear_voice:
            patch["voice_profile_id"] = None
        if clear_shot:
            patch["shot_id"] = None
        if clear_target_duration:
            patch["target_duration_ms"] = None
        if not patch:
            raise XframeToolRetryableError("No line fields were supplied to update.")
        merged = current | patch
        await _validate_script_line_refs(
            self.ctx.project_id,
            scene_id=str(current["scene_id"]),
            speaker_element_id=merged.get("speaker_element_id"),
            voice_profile_id=merged.get("voice_profile_id"),
            shot_id=merged.get("shot_id"),
        )
        columns = (
            "line_type", "speaker_element_id", "voice_profile_id", "shot_id", "text",
            "language", "emotion", "direction", "pace", "intensity", "pause_before_ms",
            "pause_after_ms", "target_duration_ms", "status",
        )
        assignments = ",".join(f"{name}=${index + 3}" for index, name in enumerate(columns))
        row = await db.fetchrow(
            f"update public.script_lines set {assignments},updated_at=now() where id=$1::uuid and project_id=$2::uuid returning *",
            line_id, self.ctx.project_id, *(merged[name] for name in columns),
        )
        return f"Script line {line_id} updated.", dict(row) | {"id": str(row["id"])}


class DeleteScriptLineTool(SnapshotTool):
    name: str = "delete_script_line"
    args_schema: type[BaseModel] = DeleteIdArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Delete one screenplay line. USE THIS only for a line the user explicitly removes. "
        "The operation also removes line-scoped references, so preserve its id when the "
        "intent is a revision. DO NOT delete a line to change its wording, speaker, voice, "
        "approval state or timing; update it instead."
    )

    async def _arun_impl(self, id: str, **_: Any) -> tuple[str, Any]:
        await _owned("script_lines", self.ctx.project_id, id)
        async with db.transaction() as conn:
            await conn.execute(
                """delete from public.resource_bindings where project_id=$1::uuid
                    and scope_type='line' and scope_id=$2::uuid""",
                self.ctx.project_id,
                id,
            )
            await conn.execute("delete from public.script_lines where id=$1::uuid", id)
        return f"Script line {id} deleted.", {"line_id": id, "deleted": True}


class AssignShotToSceneArgs(BaseModel):
    scene_id: str
    shot_id: str
    position: int | None = Field(None, ge=0)


async def _renumber_scene_shots(conn: Any, project_id: str, scene_id: str) -> list[str]:
    rows = await conn.fetch(
        """select shot_id from public.scene_shots
            where project_id=$1::uuid and scene_id=$2::uuid
            order by position,created_at,shot_id""",
        project_id,
        scene_id,
    )
    shot_ids = [str(row["shot_id"]) for row in rows]
    if shot_ids:
        await conn.execute(
            """update public.scene_shots set position=position+100000
                where project_id=$1::uuid and scene_id=$2::uuid""",
            project_id,
            scene_id,
        )
        for index, shot_id in enumerate(shot_ids):
            await conn.execute(
                """update public.scene_shots set position=$4
                    where project_id=$1::uuid and scene_id=$2::uuid and shot_id=$3::uuid""",
                project_id,
                scene_id,
                shot_id,
                index,
            )
    return shot_ids


class AssignShotToSceneTool(SnapshotTool):
    name: str = "assign_shot_to_scene"
    args_schema: type[BaseModel] = AssignShotToSceneArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Assign one exact production shot to one screenplay scene at an explicit order. "
        "This is the canonical scene-to-shot relation used by manifests and assembly. "
        "USE THIS whenever a shot is created for, moved to, or reordered inside a scene. "
        "DO NOT rely only on prose, line links or a caller-provided manifest shot list."
    )

    async def _arun_impl(
        self, scene_id: str, shot_id: str, position: int | None = None, **_: Any
    ) -> tuple[str, Any]:
        await _owned("script_scenes", self.ctx.project_id, scene_id)
        shot = await _owned("canvas_nodes", self.ctx.project_id, shot_id)
        if shot.get("type") != "shot":
            raise XframeToolRetryableError(f"Canvas node {shot_id} is not a production shot.")
        async with db.transaction() as conn:
            previous = await conn.fetchrow(
                """select scene_id from public.scene_shots
                    where project_id=$1::uuid and shot_id=$2::uuid""",
                self.ctx.project_id,
                shot_id,
            )
            conflicting_lines = await conn.fetch(
                """select id,scene_id from public.script_lines
                    where project_id=$1::uuid and shot_id=$2::uuid and scene_id<>$3::uuid""",
                self.ctx.project_id,
                shot_id,
                scene_id,
            )
            if conflicting_lines:
                ids = ", ".join(str(row["id"]) for row in conflicting_lines)
                raise XframeToolRetryableError(
                    f"Shot {shot_id} is still used by screenplay lines in another scene: {ids}. "
                    "Move or unlink those lines before moving the shot."
                )
            await conn.execute(
                "delete from public.scene_shots where project_id=$1::uuid and shot_id=$2::uuid",
                self.ctx.project_id,
                shot_id,
            )
            if previous and str(previous["scene_id"]) != scene_id:
                await _renumber_scene_shots(conn, self.ctx.project_id, str(previous["scene_id"]))
            next_position = int(
                await conn.fetchval(
                    """select coalesce(max(position),-1)+1 from public.scene_shots
                        where project_id=$1::uuid and scene_id=$2::uuid""",
                    self.ctx.project_id,
                    scene_id,
                )
            )
            await conn.execute(
                """insert into public.scene_shots(project_id,scene_id,shot_id,position)
                    values ($1::uuid,$2::uuid,$3::uuid,$4)""",
                self.ctx.project_id,
                scene_id,
                shot_id,
                next_position,
            )
            ordered = await _renumber_scene_shots(conn, self.ctx.project_id, scene_id)
            ordered.remove(shot_id)
            target = len(ordered) if position is None else min(position, len(ordered))
            ordered.insert(target, shot_id)
            await conn.execute(
                """update public.scene_shots set position=position+100000
                    where project_id=$1::uuid and scene_id=$2::uuid""",
                self.ctx.project_id,
                scene_id,
            )
            for index, ordered_id in enumerate(ordered):
                await conn.execute(
                    """update public.scene_shots set position=$4
                        where project_id=$1::uuid and scene_id=$2::uuid and shot_id=$3::uuid""",
                    self.ctx.project_id,
                    scene_id,
                    ordered_id,
                    index,
                )
        return f"Shot {shot_id} assigned to scene {scene_id} at position {target}.", {
            "scene_id": scene_id,
            "shot_id": shot_id,
            "position": target,
            "order": ordered,
        }


class RemoveShotFromSceneArgs(BaseModel):
    shot_id: str


class RemoveShotFromSceneTool(SnapshotTool):
    name: str = "remove_shot_from_scene"
    args_schema: type[BaseModel] = RemoveShotFromSceneArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Remove a shot's canonical scene membership without deleting the shot or its assets. "
        "USE THIS when the user deliberately moves a shot back to an unassigned pool. "
        "DO NOT use it to delete a shot, move it to another scene, or bypass manifest order."
    )

    async def _arun_impl(self, shot_id: str, **_: Any) -> tuple[str, Any]:
        async with db.transaction() as conn:
            linked_lines = await conn.fetch(
                """select id from public.script_lines
                    where project_id=$1::uuid and shot_id=$2::uuid""",
                self.ctx.project_id,
                shot_id,
            )
            if linked_lines:
                ids = ", ".join(str(row["id"]) for row in linked_lines)
                raise XframeToolRetryableError(
                    f"Shot {shot_id} is still used by screenplay lines: {ids}. "
                    "Unlink those lines before removing its scene membership."
                )
            row = await conn.fetchrow(
                """delete from public.scene_shots
                    where project_id=$1::uuid and shot_id=$2::uuid returning scene_id""",
                self.ctx.project_id,
                shot_id,
            )
            if not row:
                raise XframeToolRetryableError(f"Shot {shot_id} has no scene membership.")
            await _renumber_scene_shots(conn, self.ctx.project_id, str(row["scene_id"]))
        return f"Shot {shot_id} is now unassigned.", {"shot_id": shot_id, "removed": True}


ResourceType = Literal["asset", "element", "voice", "sound_template", "transition"]
ScopeType = Literal["project", "scene", "line", "shot", "timeline", "canvas"]


class BindResourceArgs(BaseModel):
    resource_type: ResourceType
    resource_id: str
    scope_type: ScopeType
    scope_id: str | None = None
    role: str = "reference"
    start_ms: int | None = Field(None, ge=0)
    end_ms: int | None = Field(None, gt=0)
    instructions: str = ""
    locked: bool = True
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self) -> BindResourceArgs:
        if self.scope_type not in {"project", "timeline"} and not self.scope_id:
            raise ValueError("scope_id is required outside project/timeline scope")
        if self.scope_type == "timeline" and self.start_ms is None:
            raise ValueError("timeline bindings require start_ms")
        if self.end_ms is not None and self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be after start_ms")
        return self


RESOURCE_TABLES = {
    "asset": "assets", "element": "assets", "voice": "voice_profiles",
    "sound_template": "audio_templates", "transition": "timeline_transitions",
}
SCOPE_TABLES = {
    "scene": "script_scenes", "line": "script_lines", "shot": "canvas_nodes",
    "canvas": "canvas_nodes",
}


class BindResourceTool(SnapshotTool):
    name: str = "bind_resource"
    args_schema: type[BaseModel] = BindResourceArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Bind an exact resource id to a project, scene, line, shot, canvas node or timeline "
        "range with role, instructions and a lock. USE THIS whenever the user says which @ "
        "resource must appear where or when. DO NOT encode a mandatory resource only in prose."
    )

    async def _arun_impl(self, resource_type: str, resource_id: str, scope_type: str,
                         scope_id: str | None = None, **v: Any) -> tuple[str, Any]:
        resource = await _owned(RESOURCE_TABLES[resource_type], self.ctx.project_id, resource_id)
        if resource_type == "element" and not resource.get("role"):
            raise XframeToolRetryableError("The selected asset is not an Element yet.")
        if scope_type in SCOPE_TABLES:
            await _owned(SCOPE_TABLES[scope_type], self.ctx.project_id, str(scope_id))
        row = await db.fetchrow(
            """insert into public.resource_bindings
               (project_id,resource_type,resource_id,scope_type,scope_id,role,start_ms,end_ms,
                instructions,locked,priority,metadata)
               values ($1::uuid,$2,$3::uuid,$4,$5::uuid,$6,$7,$8,$9,$10,$11,$12::jsonb)
               on conflict (project_id,resource_type,resource_id,scope_type,
                 (coalesce(scope_id,'00000000-0000-0000-0000-000000000000'::uuid)),role,
                 (coalesce(start_ms,-1)),(coalesce(end_ms,-1)))
               do update set instructions=excluded.instructions,locked=excluded.locked,
                 priority=excluded.priority,metadata=excluded.metadata,updated_at=now()
               returning *""",
            self.ctx.project_id, resource_type, resource_id, scope_type, scope_id,
            v["role"], v["start_ms"], v["end_ms"], v["instructions"], v["locked"],
            v["priority"], v["metadata"],
        )
        result = dict(row) | {"id": str(row["id"]), "resource_label": resource.get("name")}
        return f"Resource {resource_id} bound to {scope_type} {scope_id or self.ctx.project_id}.", result


class RemoveResourceBindingTool(SnapshotTool):
    name: str = "remove_resource_binding"
    args_schema: type[BaseModel] = DeleteIdArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Remove one explicit resource binding by id. USE THIS when the user says a resource "
        "must no longer apply to that scope. DO NOT delete the underlying asset or remove "
        "other bindings that still use it; a resource may intentionally be reused in many "
        "scenes and time ranges, each with independent instructions and locks."
    )

    async def _arun_impl(self, id: str, **_: Any) -> tuple[str, Any]:
        await _owned("resource_bindings", self.ctx.project_id, id)
        await db.execute("delete from public.resource_bindings where id=$1::uuid", id)
        return f"Resource binding {id} removed.", {"binding_id": id, "deleted": True}


class UpdateVoiceProfileArgs(BaseModel):
    voice_profile_id: str
    name: str | None = Field(None, min_length=1)
    provider: str | None = None
    provider_voice_id: str | None = None
    clear_provider_voice_id: bool = False
    source: Literal["library", "designed", "cloned", "uploaded"] | None = None
    language: str | None = None
    accent: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    pronunciation_rules: list[dict[str, Any]] | None = None
    consent_status: Literal["not_required", "pending", "verified", "rejected"] | None = None
    status: Literal["draft", "ready", "disabled"] | None = None


class UpdateVoiceProfileTool(SnapshotTool):
    name: str = "update_voice_profile"
    args_schema: type[BaseModel] = UpdateVoiceProfileArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Patch one reusable voice profile by id, including provider identity, performance "
        "settings and pronunciation. USE THIS for exact Audio > Voices edits requested in "
        "chat. DO NOT invent provider ids, mark a voice ready without one, or weaken consent."
    )

    async def _arun_impl(self, voice_profile_id: str, **values: Any) -> tuple[str, Any]:
        current = await _owned("voice_profiles", self.ctx.project_id, voice_profile_id)
        clear_provider = bool(values.pop("clear_provider_voice_id", False))
        patch = {key: value for key, value in values.items() if value is not None}
        if clear_provider:
            patch["provider_voice_id"] = None
            patch["status"] = "draft"
        merged = current | patch
        if merged.get("source") in {"cloned", "uploaded"} and merged.get("consent_status") != "verified":
            raise XframeToolRetryableError("Cloned or uploaded voices require verified consent.")
        if merged.get("status") == "ready" and not merged.get("provider_voice_id"):
            raise XframeToolRetryableError("A ready voice requires a real provider_voice_id.")
        columns = (
            "name", "provider", "provider_voice_id", "source", "language", "accent",
            "description", "settings", "pronunciation_rules", "consent_status", "status",
        )
        assignments = ",".join(f"{name}=${index + 3}" for index, name in enumerate(columns))
        row = await db.fetchrow(
            f"update public.voice_profiles set {assignments},updated_at=now() "
            "where id=$1::uuid and project_id=$2::uuid returning *",
            voice_profile_id,
            self.ctx.project_id,
            *(merged[name] for name in columns),
        )
        return f"Voice profile {voice_profile_id} updated.", dict(row) | {"id": str(row["id"])}


class DeleteVoiceProfileArgs(BaseModel):
    voice_profile_id: str


class DeleteVoiceProfileTool(SnapshotTool):
    name: str = "delete_voice_profile"
    args_schema: type[BaseModel] = DeleteVoiceProfileArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Delete one exact reusable voice profile and clear its assignments while preserving "
        "already generated audio. USE THIS only when the user explicitly removes that voice. "
        "DO NOT delete a voice merely to change its settings or provider id."
    )

    async def _arun_impl(self, voice_profile_id: str, **_: Any) -> tuple[str, Any]:
        await _owned("voice_profiles", self.ctx.project_id, voice_profile_id)
        async with db.transaction() as conn:
            await conn.execute(
                "update public.script_lines set voice_profile_id=null where project_id=$1::uuid and voice_profile_id=$2::uuid",
                self.ctx.project_id,
                voice_profile_id,
            )
            await conn.execute(
                "delete from public.character_voices where project_id=$1::uuid and voice_profile_id=$2::uuid",
                self.ctx.project_id,
                voice_profile_id,
            )
            await conn.execute(
                "delete from public.resource_bindings where project_id=$1::uuid and resource_type='voice' and resource_id=$2::uuid",
                self.ctx.project_id,
                voice_profile_id,
            )
            await conn.execute("delete from public.voice_profiles where id=$1::uuid", voice_profile_id)
        return f"Voice profile {voice_profile_id} deleted.", {"voice_profile_id": voice_profile_id, "deleted": True}


class SetCharacterVoiceArgs(BaseModel):
    character_element_id: str
    voice_profile_id: str | None = None


class SetCharacterVoiceTool(SnapshotTool):
    name: str = "set_character_voice"
    args_schema: type[BaseModel] = SetCharacterVoiceArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Assign an existing reusable voice profile to an existing character Element, or clear "
        "the assignment with null. USE THIS when the user selects exact @ character and voice "
        "resources. DO NOT create a replacement profile or infer a voice the user did not choose."
    )

    async def _arun_impl(
        self, character_element_id: str, voice_profile_id: str | None = None, **_: Any
    ) -> tuple[str, Any]:
        element = await _owned("assets", self.ctx.project_id, character_element_id)
        if not element.get("role"):
            raise XframeToolRetryableError("The selected asset is not a reusable Element.")
        if voice_profile_id:
            voice = await _owned("voice_profiles", self.ctx.project_id, voice_profile_id)
            if voice.get("status") != "ready":
                raise XframeToolRetryableError("Only a ready voice can be assigned to a character.")
        async with db.transaction() as conn:
            await conn.execute(
                "delete from public.character_voices where project_id=$1::uuid and element_id=$2::uuid",
                self.ctx.project_id,
                character_element_id,
            )
            if voice_profile_id:
                await conn.execute(
                    """insert into public.character_voices
                         (project_id,element_id,voice_profile_id,is_default,performance_defaults)
                       values ($1::uuid,$2::uuid,$3::uuid,true,'{}'::jsonb)""",
                    self.ctx.project_id,
                    character_element_id,
                    voice_profile_id,
                )
        return "Character voice assignment updated.", {
            "character_element_id": character_element_id,
            "voice_profile_id": voice_profile_id,
        }


class PlaceAudioAssetArgs(BaseModel):
    asset_id: str
    track_kind: Literal["dialogue", "voiceover", "music", "sfx", "ambience", "native"]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    scene_id: str | None = None
    shot_id: str | None = None
    script_line_id: str | None = None
    source_in_ms: int = Field(0, ge=0)
    source_out_ms: int | None = Field(None, gt=0)
    gain_db: float = Field(0, ge=-60, le=24)
    fade_in_ms: int = Field(0, ge=0)
    fade_out_ms: int = Field(0, ge=0)
    pan: float = Field(0, ge=-1, le=1)
    loop: bool = False
    locked: bool = False
    approved: bool = False
    ducking_group: str | None = None
    ducking_db: float | None = Field(None, ge=-60, le=0)
    narrative_role: str = ""
    context_tags: list[str] = Field(default_factory=list)
    time_basis: Literal["project", "scene"] = "project"

    @model_validator(mode="after")
    def valid_range(self) -> PlaceAudioAssetArgs:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be after start_ms")
        if self.source_out_ms is not None and self.source_out_ms <= self.source_in_ms:
            raise ValueError("source_out_ms must be after source_in_ms")
        return self


class PlaceAudioAssetTool(SnapshotTool):
    name: str = "place_audio_asset"
    args_schema: type[BaseModel] = PlaceAudioAssetArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Place a ready audio or audiovisual asset on the deterministic multitrack timeline "
        "with exact in/out, gain, fades, pan, looping, ducking, scene, shot and script-line links. "
        "USE THIS whenever the user specifies where an existing sound must play. DO NOT "
        "regenerate a sound that already exists or place an unready/foreign asset."
    )

    async def _arun_impl(self, asset_id: str, **v: Any) -> tuple[str, Any]:
        asset = await _owned("assets", self.ctx.project_id, asset_id)
        if asset.get("status") != "ready":
            raise XframeToolRetryableError("Only ready media can be placed on the audio timeline.")
        v["scene_id"] = await _validated_audio_scope(
            self.ctx.project_id,
            scene_id=v.get("scene_id"),
            shot_id=v.get("shot_id"),
            script_line_id=v.get("script_line_id"),
        )
        time_basis = v.pop("time_basis", "project")
        if time_basis == "scene":
            if not v.get("scene_id"):
                raise XframeToolRetryableError(
                    "Scene-relative audio placement requires scene_id."
                )
            scene = await _owned("script_scenes", self.ctx.project_id, v["scene_id"])
            offset = int(scene.get("timeline_start_ms") or 0)
            v["start_ms"] += offset
            v["end_ms"] += offset
        columns = (
            "track_kind", "start_ms", "end_ms", "scene_id", "shot_id", "script_line_id",
            "source_in_ms", "source_out_ms", "gain_db", "fade_in_ms", "fade_out_ms",
            "pan", "loop", "locked", "approved", "ducking_group", "ducking_db",
            "narrative_role", "context_tags",
        )
        row = await db.fetchrow(
            """insert into public.audio_cues
               (project_id,asset_id,track_kind,start_ms,end_ms,scene_id,shot_id,script_line_id,
                source_in_ms,source_out_ms,gain_db,fade_in_ms,fade_out_ms,pan,loop,locked,
                approved,ducking_group,ducking_db,narrative_role,context_tags)
               values ($1::uuid,$2::uuid,$3,$4,$5,$6::uuid,$7::uuid,$8::uuid,$9,$10,$11,$12,$13,
                       $14,$15,$16,$17,$18,$19,$20,$21::text[]) returning *""",
            self.ctx.project_id, asset_id, *(v[name] for name in columns),
        )
        return (
            f"Audio asset {asset_id} placed at {v['start_ms']}-{v['end_ms']}ms.",
            dict(row) | {"id": str(row["id"]), "asset_id": asset_id},
        )


class UpdateAudioCueArgs(BaseModel):
    cue_id: str
    track_kind: Literal["dialogue", "voiceover", "music", "sfx", "ambience", "native"] | None = None
    start_ms: int | None = Field(None, ge=0)
    end_ms: int | None = Field(None, gt=0)
    source_in_ms: int | None = Field(None, ge=0)
    source_out_ms: int | None = Field(None, gt=0)
    clear_source_out: bool = False
    scene_id: str | None = None
    clear_scene_link: bool = False
    shot_id: str | None = None
    clear_shot_link: bool = False
    script_line_id: str | None = None
    clear_script_line_link: bool = False
    gain_db: float | None = Field(None, ge=-60, le=24)
    fade_in_ms: int | None = Field(None, ge=0)
    fade_out_ms: int | None = Field(None, ge=0)
    pan: float | None = Field(None, ge=-1, le=1)
    loop: bool | None = None
    locked: bool | None = None
    approved: bool | None = None
    ducking_group: str | None = None
    clear_ducking: bool = False
    ducking_db: float | None = Field(None, ge=-60, le=0)
    narrative_role: str | None = None
    context_tags: list[str] | None = None
    priority: int | None = None


class UpdateAudioCueTool(SnapshotTool):
    name: str = "update_audio_cue"
    args_schema: type[BaseModel] = UpdateAudioCueArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Patch one existing audio cue without rebuilding the complete mix: timing, trim, "
        "gain, fades, pan, loop, ducking, lock, approval or narrative role. USE THIS for "
        "a precise mix note targeting a cue id. DO NOT recreate or move unrelated cues, "
        "and do not silently allow an end before its start."
    )

    async def _arun_impl(self, cue_id: str, **values: Any) -> tuple[str, Any]:
        current = await _owned("audio_cues", self.ctx.project_id, cue_id)
        clear_scene = bool(values.pop("clear_scene_link", False))
        clear_shot = bool(values.pop("clear_shot_link", False))
        clear_line = bool(values.pop("clear_script_line_link", False))
        clear_source_out = bool(values.pop("clear_source_out", False))
        clear_ducking = bool(values.pop("clear_ducking", False))
        patch = {key: value for key, value in values.items() if value is not None}
        if clear_scene:
            patch["scene_id"] = None
        if clear_shot:
            patch["shot_id"] = None
        if clear_line:
            patch["script_line_id"] = None
        if clear_source_out:
            patch["source_out_ms"] = None
        if clear_ducking:
            patch["ducking_group"] = None
            patch["ducking_db"] = None
        if not patch:
            raise XframeToolRetryableError("No cue fields were supplied to update.")
        merged = current | patch
        if merged["end_ms"] <= merged["start_ms"]:
            raise XframeToolRetryableError("Audio cue end_ms must be after start_ms.")
        if merged.get("source_out_ms") is not None and merged["source_out_ms"] <= merged["source_in_ms"]:
            raise XframeToolRetryableError("Audio cue source_out_ms must follow source_in_ms.")
        merged["scene_id"] = await _validated_audio_scope(
            self.ctx.project_id,
            scene_id=merged.get("scene_id"),
            shot_id=merged.get("shot_id"),
            script_line_id=merged.get("script_line_id"),
        )
        columns = (
            "track_kind", "start_ms", "end_ms", "source_in_ms", "source_out_ms", "scene_id",
            "shot_id", "script_line_id", "gain_db",
            "fade_in_ms", "fade_out_ms", "pan", "loop", "locked", "approved",
            "ducking_group", "ducking_db", "narrative_role", "context_tags", "priority",
        )
        assignments = ",".join(f"{name}=${index + 3}" for index, name in enumerate(columns))
        row = await db.fetchrow(
            f"update public.audio_cues set {assignments},updated_at=now() where id=$1::uuid and project_id=$2::uuid returning *",
            cue_id, self.ctx.project_id, *(merged[name] for name in columns),
        )
        return f"Audio cue {cue_id} updated.", dict(row) | {"id": str(row["id"])}


class DeleteAudioCueTool(SnapshotTool):
    name: str = "delete_audio_cue"
    args_schema: type[BaseModel] = DeleteIdArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Remove one audio cue from the mix while preserving its reusable source asset. "
        "USE THIS when the user removes that exact occurrence from the timeline. DO NOT "
        "delete the asset, its sound template or other placements, and do not use deletion "
        "when a timing or gain update would express the requested change."
    )

    async def _arun_impl(self, id: str, **_: Any) -> tuple[str, Any]:
        await _owned("audio_cues", self.ctx.project_id, id)
        await db.execute("delete from public.audio_cues where id=$1::uuid", id)
        return f"Audio cue {id} removed; its source asset remains reusable.", {"cue_id": id, "deleted": True}


class AudioTemplateArgs(BaseModel):
    name: str
    kind: Literal["music", "sfx", "ambience"]
    prompt: str = ""
    asset_id: str | None = None
    duration_ms: int | None = Field(None, gt=0)
    loop: bool = False
    intensity: float = Field(0.5, ge=0, le=1)
    composition_plan: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_source(self) -> AudioTemplateArgs:
        if not self.asset_id and not self.prompt.strip():
            raise ValueError("A sound template needs an approved asset or a generation brief")
        return self


class CreateAudioTemplateTool(SnapshotTool):
    name: str = "create_audio_template"
    args_schema: type[BaseModel] = AudioTemplateArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Create or update a reusable project sound template backed by an approved media "
        "asset or by a precise generation brief. USE THIS when a sound, music bed or "
        "ambience should be reusable by drag-and-drop and by the agent. DO NOT label an "
        "unapproved or missing asset as reusable, and never replace the underlying file."
    )

    async def _arun_impl(self, asset_id: str | None = None, **v: Any) -> tuple[str, Any]:
        if asset_id:
            asset = await _owned("assets", self.ctx.project_id, asset_id)
            if asset.get("status") != "ready":
                raise XframeToolRetryableError("A template source asset must be ready.")
        row = await db.fetchrow(
            """insert into public.audio_templates
               (project_id,name,kind,prompt,asset_id,duration_ms,loop,intensity,composition_plan,tags)
               values ($1::uuid,$2,$3,$4,$5::uuid,$6,$7,$8,$9::jsonb,$10::text[])
               on conflict (project_id,name) do update set kind=excluded.kind,prompt=excluded.prompt,
                 asset_id=excluded.asset_id,duration_ms=excluded.duration_ms,loop=excluded.loop,
                 intensity=excluded.intensity,composition_plan=excluded.composition_plan,
                 tags=excluded.tags,updated_at=now() returning *""",
            self.ctx.project_id, v["name"], v["kind"], v["prompt"], asset_id,
            v["duration_ms"], v["loop"], v["intensity"], v["composition_plan"], v["tags"],
        )
        return f"Sound template '{v['name']}' saved.", dict(row) | {"id": str(row["id"])}


class UpdateAudioTemplateArgs(BaseModel):
    template_id: str
    name: str | None = Field(None, min_length=1)
    kind: Literal["music", "sfx", "ambience"] | None = None
    prompt: str | None = None
    asset_id: str | None = None
    clear_asset: bool = False
    duration_ms: int | None = Field(None, gt=0)
    loop: bool | None = None
    intensity: float | None = Field(None, ge=0, le=1)
    composition_plan: dict[str, Any] | None = None
    tags: list[str] | None = None


class UpdateAudioTemplateTool(SnapshotTool):
    name: str = "update_audio_template"
    args_schema: type[BaseModel] = UpdateAudioTemplateArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Patch one reusable sound template by id while retaining its stable identity. USE "
        "THIS to rename it, revise its brief or swap its approved source. DO NOT mutate the "
        "source media or leave the template without either an asset or a generation brief."
    )

    async def _arun_impl(self, template_id: str, **values: Any) -> tuple[str, Any]:
        current = await _owned("audio_templates", self.ctx.project_id, template_id)
        clear_asset = bool(values.pop("clear_asset", False))
        patch = {key: value for key, value in values.items() if value is not None}
        if clear_asset:
            patch["asset_id"] = None
        if patch.get("asset_id"):
            asset = await _owned("assets", self.ctx.project_id, patch["asset_id"])
            if asset.get("status") != "ready":
                raise XframeToolRetryableError("A template source asset must be ready.")
        merged = current | patch
        if not merged.get("asset_id") and not str(merged.get("prompt") or "").strip():
            raise XframeToolRetryableError("A sound template needs an asset or a generation brief.")
        columns = (
            "name", "kind", "prompt", "asset_id", "duration_ms", "loop", "intensity",
            "composition_plan", "tags",
        )
        assignments = ",".join(f"{name}=${index + 3}" for index, name in enumerate(columns))
        row = await db.fetchrow(
            f"update public.audio_templates set {assignments},updated_at=now() "
            "where id=$1::uuid and project_id=$2::uuid returning *",
            template_id,
            self.ctx.project_id,
            *(merged[name] for name in columns),
        )
        return f"Sound template {template_id} updated.", dict(row) | {"id": str(row["id"])}


class DeleteAudioTemplateArgs(BaseModel):
    template_id: str


class DeleteAudioTemplateTool(SnapshotTool):
    name: str = "delete_audio_template"
    args_schema: type[BaseModel] = DeleteAudioTemplateArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Delete one reusable sound template while preserving its source asset and timeline "
        "placements. USE THIS only when the user explicitly removes that preset. DO NOT "
        "delete the underlying audio or unrelated templates."
    )

    async def _arun_impl(self, template_id: str, **_: Any) -> tuple[str, Any]:
        await _owned("audio_templates", self.ctx.project_id, template_id)
        async with db.transaction() as conn:
            await conn.execute(
                "delete from public.resource_bindings where project_id=$1::uuid and resource_type='sound_template' and resource_id=$2::uuid",
                self.ctx.project_id,
                template_id,
            )
            await conn.execute("delete from public.audio_templates where id=$1::uuid", template_id)
        return f"Sound template {template_id} deleted.", {"template_id": template_id, "deleted": True}


PRODUCTION_CRUD_TOOL_CLASSES: tuple[type[SnapshotTool], ...] = (
    CreateScriptSceneTool, UpdateScriptSceneTool, DeleteScriptSceneTool,
    CreateScriptLineTool, UpdateScriptLineTool, DeleteScriptLineTool,
    AssignShotToSceneTool, RemoveShotFromSceneTool,
    BindResourceTool, RemoveResourceBindingTool,
    UpdateVoiceProfileTool, DeleteVoiceProfileTool, SetCharacterVoiceTool,
    PlaceAudioAssetTool, UpdateAudioCueTool, DeleteAudioCueTool, CreateAudioTemplateTool,
    UpdateAudioTemplateTool, DeleteAudioTemplateTool,
)
