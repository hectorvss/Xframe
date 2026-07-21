"""Structured pre/post-production tools.

The expensive media calls remain in ``generation.py``.  These tools create the exact
documents those calls consume: screenplay, cast voices, multitrack cues, annotations
and deterministic transition records.  Planning therefore never spends credits.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import db
from app.artifacts.manager import ArtifactManager
from app.artifacts.types import (
    AudioPlanArtifactContent,
    ScreenplayArtifactContent,
    ShotRefBlock,
    TextBlock,
)
from app.production.audio import rank_music_candidates, validate_audio_plan
from app.production.transitions import transition_signature
from app.production.types import (
    AnnotationSpec,
    AudioCueSpec,
    AudioMixSpec,
    DialogueLineSpec,
    MusicBrief,
    MusicProfile,
    TrackKind,
    TransitionSpec,
)
from app.taxonomy.builder import SnapshotTool
from app.tools.errors import XframeToolRetryableError


class VoiceProfileArgs(BaseModel):
    character_name: str = Field(description="Existing character Element name.")
    profile_name: str
    provider: str
    provider_voice_id: str | None = None
    source: Literal["library", "designed", "cloned", "uploaded"] = "library"
    language: str = "es"
    accent: str | None = None
    description: str = ""
    performance_defaults: dict[str, Any] = Field(default_factory=dict)
    pronunciation_rules: list[dict[str, Any]] = Field(default_factory=list)
    consent_status: Literal["not_required", "pending", "verified", "rejected"] = (
        "not_required"
    )


class ReusableVoiceProfileArgs(BaseModel):
    profile_name: str
    provider: str
    provider_voice_id: str | None = None
    source: Literal["library", "designed", "cloned", "uploaded"] = "library"
    language: str = "es"
    accent: str | None = None
    description: str = ""
    performance_defaults: dict[str, Any] = Field(default_factory=dict)
    pronunciation_rules: list[dict[str, Any]] = Field(default_factory=list)
    consent_status: Literal["not_required", "pending", "verified", "rejected"] = (
        "not_required"
    )


class CreateVoiceProfileTool(SnapshotTool):
    name: str = "create_voice_profile"
    args_schema: type[BaseModel] = ReusableVoiceProfileArgs
    description: str = (
        "Create or update a reusable project voice in the Audio > Voices library. "
        "Use it when the user asks for a narrator, character or brand voice before "
        "assigning it to a screenplay character. A provider voice ID makes the profile "
        "ready for synthesis; without one it remains an explicit draft, never pretend it "
        "can already speak. Cloned or uploaded voices require verified consent."
    )

    async def _arun_impl(
        self,
        profile_name: str,
        provider: str,
        provider_voice_id: str | None = None,
        source: str = "library",
        language: str = "es",
        accent: str | None = None,
        description: str = "",
        performance_defaults: dict[str, Any] | None = None,
        pronunciation_rules: list[dict[str, Any]] | None = None,
        consent_status: str = "not_required",
        **_: Any,
    ) -> tuple[str, Any]:
        if source in {"cloned", "uploaded"} and consent_status != "verified":
            raise XframeToolRetryableError(
                "Cloned or uploaded voices require consent_status='verified' before they "
                "can be saved. Ask the user to provide or confirm consent evidence."
            )

        status = "ready" if provider_voice_id else "draft"
        row = await db.fetchrow(
            """
            insert into public.voice_profiles
              (project_id, name, provider, provider_voice_id, source, language,
               accent, description, settings, pronunciation_rules, consent_status, status)
            values ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12)
            on conflict (project_id, name) do update set
              provider=excluded.provider,
              provider_voice_id=excluded.provider_voice_id,
              source=excluded.source,
              language=excluded.language,
              accent=excluded.accent,
              description=excluded.description,
              settings=excluded.settings,
              pronunciation_rules=excluded.pronunciation_rules,
              consent_status=excluded.consent_status,
              status=excluded.status
            returning id, status
            """,
            self.ctx.project_id,
            profile_name,
            provider,
            provider_voice_id,
            source,
            language,
            accent,
            description,
            performance_defaults or {},
            pronunciation_rules or [],
            consent_status,
            status,
        )
        voice_id = str(row["id"])
        readiness = "ready to synthesize" if row["status"] == "ready" else "saved as a draft"
        return (
            f"Voice '{profile_name}' {readiness} in the project library.",
            {
                "kind": "voice_profile",
                "voice_profile_id": voice_id,
                "provider_voice_id": provider_voice_id,
                "status": row["status"],
            },
        )


class AssignCharacterVoiceTool(SnapshotTool):
    name: str = "assign_character_voice"
    args_schema: type[BaseModel] = VoiceProfileArgs
    description: str = (
        "Create or update a reusable voice identity and make it the default voice of an "
        "existing character Element. USE THIS after the character exists and the user has "
        "chosen or supplied its voice. DO NOT invent a voice identity or bypass consent; "
        "cloned/uploaded voices must carry verified consent. This spends no credits."
    )

    async def _arun_impl(
        self,
        character_name: str,
        profile_name: str,
        provider: str,
        provider_voice_id: str | None = None,
        source: str = "library",
        language: str = "es",
        accent: str | None = None,
        description: str = "",
        performance_defaults: dict[str, Any] | None = None,
        pronunciation_rules: list[dict[str, Any]] | None = None,
        consent_status: str = "not_required",
        **_: Any,
    ) -> tuple[str, Any]:
        element = self.snap.element_by_name(character_name)
        if element is None:
            raise XframeToolRetryableError(
                f"Character '{character_name}' does not exist. Define it as an Element first."
            )
        if source in {"cloned", "uploaded"} and consent_status != "verified":
            raise XframeToolRetryableError(
                "Cloned or uploaded voices require consent_status='verified' before they "
                "can be assigned. Ask the user to provide/confirm consent evidence."
            )

        async with db.transaction() as conn:
            row = await conn.fetchrow(
                """
                insert into public.voice_profiles
                  (project_id, name, provider, provider_voice_id, source, language,
                   accent, description, settings, pronunciation_rules, consent_status, status)
                values ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,'ready')
                on conflict (project_id, name) do update set
                  provider=excluded.provider,
                  provider_voice_id=excluded.provider_voice_id,
                  source=excluded.source,
                  language=excluded.language,
                  accent=excluded.accent,
                  description=excluded.description,
                  settings=excluded.settings,
                  pronunciation_rules=excluded.pronunciation_rules,
                  consent_status=excluded.consent_status,
                  status='ready'
                returning id
                """,
                self.ctx.project_id,
                profile_name,
                provider,
                provider_voice_id,
                source,
                language,
                accent,
                description,
                performance_defaults or {},
                pronunciation_rules or [],
                consent_status,
            )
            voice_id = str(row["id"])
            await conn.execute(
                """
                update public.character_voices set is_default=false
                 where project_id=$1::uuid and element_id=$2::uuid and is_default
                """,
                self.ctx.project_id,
                element.id,
            )
            await conn.execute(
                """
                insert into public.character_voices
                  (project_id, element_id, voice_profile_id, is_default, performance_defaults)
                values ($1::uuid,$2::uuid,$3::uuid,true,$4::jsonb)
                on conflict (element_id, voice_profile_id) do update set
                  is_default=true, performance_defaults=excluded.performance_defaults
                """,
                self.ctx.project_id,
                element.id,
                voice_id,
                performance_defaults or {},
            )
        return (
            f"Voice '{profile_name}' is now the default for @{character_name}.",
            {
                "kind": "voice_profile",
                "voice_profile_id": voice_id,
                "element_id": element.id,
                "character_name": character_name,
            },
        )


class ScreenplayLineInput(BaseModel):
    line_type: Literal["dialogue", "voiceover", "action", "caption"] = "dialogue"
    speaker_element_id: str | None = None
    voice_profile_id: str | None = None
    shot_id: str | None = None
    text: str = Field(min_length=1)
    language: str = "es"
    emotion: str = "neutral"
    direction: str = ""
    pace: float = Field(1.0, ge=0.5, le=2.0)
    intensity: float = Field(0.5, ge=0, le=1)
    pause_before_ms: int = Field(0, ge=0)
    pause_after_ms: int = Field(0, ge=0)
    target_duration_ms: int | None = Field(None, gt=0)
    pronunciation: dict[str, str] = Field(default_factory=dict)


class ScreenplaySceneInput(BaseModel):
    title: str
    setting: str = ""
    time_of_day: str = ""
    summary: str = ""
    dramatic_intent: str = ""
    target_duration_ms: int | None = Field(None, gt=0)
    lines: list[ScreenplayLineInput] = Field(default_factory=list)


class CreateScreenplayArgs(BaseModel):
    title: str
    language: str = "es"
    target_duration_s: float | None = Field(None, gt=0)
    scenes: list[ScreenplaySceneInput] = Field(min_length=1)
    replace_current: bool = True


class CreateScreenplayTool(SnapshotTool):
    name: str = "create_screenplay"
    args_schema: type[BaseModel] = CreateScreenplayArgs
    description: str = (
        "Create the structured screenplay that is authoritative for dialogue, voiceover, "
        "captions and shot-linked action. USE THIS when wording, speakers and scenes need "
        "to become an editable production document. DO NOT invent brand claims or present "
        "unapproved dialogue as approved. Produces a versioned screenplay artifact."
    )

    async def _arun_impl(
        self,
        title: str,
        scenes: list[dict[str, Any]] | list[ScreenplaySceneInput],
        language: str = "es",
        target_duration_s: float | None = None,
        replace_current: bool = True,
        **_: Any,
    ) -> tuple[str, Any]:
        parsed = [
            scene if isinstance(scene, ScreenplaySceneInput) else ScreenplaySceneInput.model_validate(scene)
            for scene in scenes
        ]
        snapshot: list[dict[str, Any]] = []
        scene_ids: list[str] = []
        cast_ids: set[str] = set()
        shot_ids: list[str] = []

        async with db.transaction() as conn:
            if replace_current:
                await conn.execute(
                    "delete from public.script_scenes where project_id=$1::uuid",
                    self.ctx.project_id,
                )
            for scene_position, scene in enumerate(parsed):
                scene_row = await conn.fetchrow(
                    """
                    insert into public.script_scenes
                      (project_id, position, title, setting, time_of_day, summary,
                       dramatic_intent, target_duration_ms)
                    values ($1::uuid,$2,$3,$4,$5,$6,$7,$8)
                    returning id
                    """,
                    self.ctx.project_id,
                    scene_position,
                    scene.title,
                    scene.setting,
                    scene.time_of_day,
                    scene.summary,
                    scene.dramatic_intent,
                    scene.target_duration_ms,
                )
                scene_id = str(scene_row["id"])
                scene_ids.append(scene_id)
                lines_snapshot: list[dict[str, Any]] = []
                for line_position, line in enumerate(scene.lines):
                    # Domain validation catches dialogue without a speaker before any
                    # row is written; the surrounding transaction keeps replacement atomic.
                    DialogueLineSpec(
                        scene_id=scene_id,
                        position=line_position,
                        line_type=line.line_type,
                        speaker_element_id=line.speaker_element_id,
                        voice_profile_id=line.voice_profile_id,
                        shot_id=line.shot_id,
                        text=line.text,
                        performance={
                            "language": line.language,
                            "emotion": line.emotion,
                            "direction": line.direction,
                            "pace": line.pace,
                            "intensity": line.intensity,
                            "pause_before_ms": line.pause_before_ms,
                            "pause_after_ms": line.pause_after_ms,
                            "pronunciation": line.pronunciation,
                        },
                        target_duration_ms=line.target_duration_ms,
                    )
                    row = await conn.fetchrow(
                        """
                        insert into public.script_lines
                          (project_id, scene_id, position, line_type, speaker_element_id,
                           voice_profile_id, shot_id, text, language, emotion, direction,
                           pronunciation, pace, intensity, pause_before_ms, pause_after_ms,
                           target_duration_ms)
                        values ($1::uuid,$2::uuid,$3,$4,$5::uuid,$6::uuid,$7::uuid,$8,$9,
                                $10,$11,$12::jsonb,$13,$14,$15,$16,$17)
                        returning id
                        """,
                        self.ctx.project_id,
                        scene_id,
                        line_position,
                        line.line_type,
                        line.speaker_element_id,
                        line.voice_profile_id,
                        line.shot_id,
                        line.text,
                        line.language,
                        line.emotion,
                        line.direction,
                        line.pronunciation,
                        line.pace,
                        line.intensity,
                        line.pause_before_ms,
                        line.pause_after_ms,
                        line.target_duration_ms,
                    )
                    line_data = line.model_dump(mode="json") | {"id": str(row["id"])}
                    lines_snapshot.append(line_data)
                    if line.speaker_element_id:
                        cast_ids.add(line.speaker_element_id)
                    if line.shot_id:
                        shot_ids.append(line.shot_id)
                snapshot.append(
                    scene.model_dump(mode="json", exclude={"lines"})
                    | {"id": scene_id, "position": scene_position, "lines": lines_snapshot}
                )

        blocks: list[Any] = [TextBlock(text=scene.title, heading=True) for scene in parsed]
        blocks.extend(ShotRefBlock(shot_id=shot_id) for shot_id in dict.fromkeys(shot_ids))
        artifact = await ArtifactManager(self.ctx.project_id).acreate(
            ScreenplayArtifactContent(
                title=title,
                language=language,
                target_duration_s=target_duration_s,
                scene_ids=scene_ids,
                cast_element_ids=sorted(cast_ids),
                scenes=snapshot,
                blocks=blocks,
            ),
            name=title,
        )
        line_count = sum(len(scene.lines) for scene in parsed)
        return (
            f"Screenplay '{title}' created with {len(parsed)} scenes and {line_count} lines. "
            f"Artifact {artifact['id']} is the immutable approval snapshot.",
            {
                "kind": "screenplay",
                "artifact_id": artifact["id"],
                "scene_ids": scene_ids,
                "scenes": snapshot,
                "line_count": line_count,
            },
        )


class CreateAudioPlanArgs(BaseModel):
    title: str = "Plan de audio"
    duration_ms: int = Field(gt=0)
    target_lufs: float = Field(-14.0, ge=-30, le=-5)
    true_peak_dbtp: float = Field(-1.0, ge=-6, le=0)
    cues: list[AudioCueSpec] = Field(default_factory=list)
    replace_current: bool = True


class CreateAudioPlanTool(SnapshotTool):
    name: str = "create_audio_plan"
    args_schema: type[BaseModel] = CreateAudioPlanArgs
    description: str = (
        "Create a deterministic multitrack sound plan from existing audio assets. Place "
        "dialogue, voiceover, music, effects, ambience and native sound with exact timing, "
        "gain, fades, looping and ducking. USE THIS after audio assets and cut duration are "
        "known. DO NOT use it to generate missing audio or silently clip invalid cues."
    )

    async def _arun_impl(
        self,
        duration_ms: int,
        cues: list[dict[str, Any]] | list[AudioCueSpec],
        title: str = "Plan de audio",
        target_lufs: float = -14.0,
        true_peak_dbtp: float = -1.0,
        replace_current: bool = True,
        **_: Any,
    ) -> tuple[str, Any]:
        parsed = [cue if isinstance(cue, AudioCueSpec) else AudioCueSpec.model_validate(cue) for cue in cues]
        spec = AudioMixSpec(
            duration_ms=duration_ms,
            target_lufs=target_lufs,
            true_peak_dbtp=true_peak_dbtp,
            cues=parsed,
        )
        errors = validate_audio_plan(spec)
        if errors:
            raise XframeToolRetryableError("Invalid audio plan:\n- " + "\n- ".join(errors))

        asset_ids = list(dict.fromkeys(cue.asset_id for cue in parsed))
        if asset_ids:
            rows = await db.fetch(
                """select id, type from public.assets
                    where project_id=$1::uuid and id=any($2::uuid[]) and status='ready'""",
                self.ctx.project_id,
                asset_ids,
            )
            valid = {str(row["id"]) for row in rows if "audio" in str(row["type"]).lower()}
            missing = [asset_id for asset_id in asset_ids if asset_id not in valid]
            if missing:
                raise XframeToolRetryableError(
                    "These cues do not reference ready audio assets in this project: "
                    + ", ".join(missing)
                )

        cue_ids: list[str] = []
        snapshots: list[dict[str, Any]] = []
        async with db.transaction() as conn:
            if replace_current:
                await conn.execute(
                    "delete from public.audio_cues where project_id=$1::uuid",
                    self.ctx.project_id,
                )
            for cue in parsed:
                row = await conn.fetchrow(
                    """
                    insert into public.audio_cues
                      (project_id, asset_id, shot_id, script_line_id, track_kind, start_ms,
                       end_ms, source_in_ms, source_out_ms, gain_db, fade_in_ms, fade_out_ms,
                       pan, loop, locked, approved, ducking_group, ducking_db, priority,
                       narrative_role, context_tags)
                    values ($1::uuid,$2::uuid,$3::uuid,$4::uuid,$5,$6,$7,$8,$9,$10,$11,
                            $12,$13,$14,$15,$16,$17,$18,$19,$20,$21::text[])
                    returning id
                    """,
                    self.ctx.project_id,
                    cue.asset_id,
                    cue.shot_id,
                    cue.script_line_id,
                    cue.track_kind.value,
                    cue.start_ms,
                    cue.end_ms,
                    cue.source_in_ms,
                    cue.source_out_ms,
                    cue.gain_db,
                    cue.fade_in_ms,
                    cue.fade_out_ms,
                    cue.pan,
                    cue.loop,
                    cue.locked,
                    cue.approved,
                    cue.ducking_group,
                    cue.ducking_db,
                    cue.priority,
                    cue.narrative_role,
                    cue.context_tags,
                )
                cue_id = str(row["id"])
                cue_ids.append(cue_id)
                snapshots.append(cue.model_dump(mode="json") | {"id": cue_id})

        artifact = await ArtifactManager(self.ctx.project_id).acreate(
            AudioPlanArtifactContent(
                title=title,
                cue_ids=cue_ids,
                cue_snapshot=snapshots,
                buses={kind.value: {"gain_db": 0.0} for kind in TrackKind},
                target_lufs=target_lufs,
                true_peak_dbtp=true_peak_dbtp,
                total_duration_s=duration_ms / 1000,
            ),
            name=title,
        )
        return (
            f"Audio plan '{title}' created with {len(cue_ids)} cues across "
            f"{len({cue.track_kind for cue in parsed})} buses.",
            {
                "kind": "audio_plan",
                "artifact_id": artifact["id"],
                "cue_ids": cue_ids,
                "cues": snapshots,
            },
        )


class ProfileAudioAssetArgs(BaseModel):
    asset_id: str
    bpm: float | None = Field(None, gt=0, le=400)
    musical_key: str | None = None
    mood: list[str] = Field(default_factory=list)
    instrumentation: list[str] = Field(default_factory=list)
    energy_curve: list[tuple[float, float]] = Field(default_factory=list)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    rights: dict[str, Any] = Field(default_factory=dict)


class ProfileAudioAssetTool(SnapshotTool):
    name: str = "profile_audio_asset"
    args_schema: type[BaseModel] = ProfileAudioAssetArgs
    description: str = (
        "Attach searchable musical metadata, energy curve, sections and licensing facts "
        "to an existing audio asset. USE THIS after upload/generation so future scenes can "
        "select it by context. DO NOT mark commercial rights unless their source is known."
    )

    async def _arun_impl(self, **kwargs: Any) -> tuple[str, Any]:
        profile = MusicProfile.model_validate(kwargs)
        exists = await db.fetchval(
            """select 1 from public.assets where id=$1::uuid and project_id=$2::uuid
                  and type='audio' and status='ready'""",
            profile.asset_id,
            self.ctx.project_id,
        )
        if not exists:
            raise XframeToolRetryableError(
                f"Audio asset {profile.asset_id} is not ready or does not belong to this project."
            )
        await db.execute(
            """
            insert into public.audio_asset_profiles
              (asset_id, project_id, bpm, musical_key, mood, instrumentation,
               energy_curve, sections, rights)
            values ($1::uuid,$2::uuid,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb)
            on conflict (asset_id) do update set
              bpm=excluded.bpm, musical_key=excluded.musical_key, mood=excluded.mood,
              instrumentation=excluded.instrumentation, energy_curve=excluded.energy_curve,
              sections=excluded.sections, rights=excluded.rights
            """,
            profile.asset_id,
            self.ctx.project_id,
            profile.bpm,
            profile.musical_key,
            profile.mood,
            profile.instrumentation,
            profile.energy_curve,
            profile.sections,
            profile.rights,
        )
        return (f"Audio asset {profile.asset_id} is now searchable by narrative context.", {"kind": "audio_profile", **profile.model_dump(mode="json")})


class SelectMusicArgs(BaseModel):
    moods: list[str] = Field(default_factory=list)
    intensity: float = Field(0.5, ge=0, le=1)
    bpm_min: float | None = Field(None, gt=0)
    bpm_max: float | None = Field(None, gt=0)
    instrumentation: list[str] = Field(default_factory=list)
    require_commercial_rights: bool = True
    limit: int = Field(5, ge=1, le=20)


class SelectMusicTool(SnapshotTool):
    name: str = "select_music_from_library"
    args_schema: type[BaseModel] = SelectMusicArgs
    description: str = (
        "Rank existing project music by mood, tempo, instrumentation, intensity and "
        "commercial rights with explicit reasons. USE THIS before generating new music; "
        "reuse a licensed contextual match when one exists. DO NOT return unlicensed "
        "tracks when commercial rights are required."
    )

    async def _arun_impl(self, limit: int = 5, **kwargs: Any) -> tuple[str, Any]:
        brief = MusicBrief.model_validate(kwargs)
        rows = await db.fetch(
            """
            select p.*, a.name
              from public.audio_asset_profiles p
              join public.assets a on a.id=p.asset_id
             where p.project_id=$1::uuid and a.status='ready'
            """,
            self.ctx.project_id,
        )
        profiles = [
            MusicProfile(
                asset_id=str(row["asset_id"]), bpm=row["bpm"], musical_key=row["musical_key"],
                mood=list(row["mood"] or []), instrumentation=list(row["instrumentation"] or []),
                energy_curve=list(row["energy_curve"] or []), sections=list(row["sections"] or []),
                rights=dict(row["rights"] or {}),
            )
            for row in rows
        ]
        names = {str(row["asset_id"]): row["name"] for row in rows}
        ranked = rank_music_candidates(brief, profiles)[:limit]
        payload = [
            {"asset_id": item.asset_id, "name": names[item.asset_id], "score": item.score, "reasons": list(item.reasons)}
            for item in ranked
        ]
        if not payload:
            return ("No licensed library track matches this scene. Generate a new piece from the brief.", {"kind": "music_selection", "candidates": []})
        return ("Ranked existing music by narrative fit:\n" + "\n".join(f"- {item['name']} ({item['score']:.0%}): {', '.join(item['reasons'])}" for item in payload), {"kind": "music_selection", "candidates": payload})


class AddAssetAnnotationArgs(AnnotationSpec):
    pass


class AddAssetAnnotationTool(SnapshotTool):
    name: str = "add_asset_annotation"
    args_schema: type[BaseModel] = AddAssetAnnotationArgs
    description: str = (
        "Attach a normalized region, drawing, text instruction or comment to an image or "
        "to an exact video frame. USE THIS when feedback targets a precise area/time. DO NOT "
        "burn feedback into the source pixels or use an annotation as an edit result."
    )

    async def _arun_impl(self, **kwargs: Any) -> tuple[str, Any]:
        annotation = AnnotationSpec.model_validate(kwargs)
        asset = await db.fetchrow(
            "select id, type from public.assets where id=$1::uuid and project_id=$2::uuid",
            annotation.asset_id,
            self.ctx.project_id,
        )
        if asset is None:
            raise XframeToolRetryableError("The annotated asset does not exist in this project.")
        row = await db.fetchrow(
            """
            insert into public.asset_annotations
              (project_id, asset_id, author_id, kind, body, time_ms, geometry, color)
            values ($1::uuid,$2::uuid,$3::uuid,$4,$5,$6,$7::jsonb,$8)
            returning id
            """,
            self.ctx.project_id,
            annotation.asset_id,
            self.ctx.user_id,
            annotation.kind,
            annotation.body,
            annotation.time_ms,
            annotation.geometry,
            annotation.color,
        )
        return (
            f"Annotation added to asset {annotation.asset_id}.",
            {"kind": "asset_annotation", "annotation_id": str(row["id"]), **annotation.model_dump()},
        )


class PlanTransitionArgs(TransitionSpec):
    pass


class PlanTransitionTool(SnapshotTool):
    name: str = "plan_transition"
    args_schema: type[BaseModel] = PlanTransitionArgs
    description: str = (
        "Create or reuse the deterministic record for a cut, crossfade or generated bridge "
        "between two exact assets. Generated bridges use both boundary assets and preserve "
        "their signature, duration and parameters. USE THIS before rendering a transition. "
        "DO NOT describe a vague bridge in chat or insert one without exact endpoints."
    )

    async def _arun_impl(self, **kwargs: Any) -> tuple[str, Any]:
        spec = TransitionSpec.model_validate(kwargs)
        rows = await db.fetch(
            "select id, type, status from public.assets where project_id=$1::uuid and id=any($2::uuid[])",
            self.ctx.project_id,
            [spec.from_asset_id, spec.to_asset_id],
        )
        if len(rows) != 2 or any(row["status"] != "ready" for row in rows):
            raise XframeToolRetryableError(
                "Both transition endpoints must be ready assets in the current project."
            )
        signature = transition_signature(spec)
        if spec.kind == "generated" and spec.seed is None:
            spec.seed = int(signature[:8], 16) & 0x7FFFFFFF
            signature = transition_signature(spec)
        existing = await db.fetchrow(
            """select id, status, generated_asset_id, operation_id
                 from public.timeline_transitions
                where project_id=$1::uuid and signature=$2""",
            self.ctx.project_id,
            signature,
        )
        if existing:
            row = existing
        else:
            async with db.transaction() as conn:
                operation_id = None
                if spec.kind == "generated":
                    operation_id = await conn.fetchval(
                        """
                        insert into public.asset_operations
                          (project_id, operation, model_id, prompt, params,
                           prompt_fingerprint)
                        values ($1::uuid,'transition',$2,$3,$4::jsonb,$5)
                        returning id
                        """,
                        self.ctx.project_id,
                        spec.model_id,
                        spec.prompt,
                        spec.model_dump(mode="json", exclude_none=True),
                        signature,
                    )
                    await conn.executemany(
                        """
                        insert into public.asset_operation_inputs
                          (operation_id, project_id, asset_id, role, position)
                        values ($1::uuid,$2::uuid,$3::uuid,$4,$5)
                        """,
                        [
                            (operation_id, self.ctx.project_id, spec.from_asset_id, "from", 0),
                            (operation_id, self.ctx.project_id, spec.to_asset_id, "to", 1),
                        ],
                    )
                row = await conn.fetchrow(
                    """
                    insert into public.timeline_transitions
                      (project_id, from_asset_id, to_asset_id, kind, duration_ms, model_id,
                       seed, parameters, signature, status, operation_id)
                    values ($1::uuid,$2::uuid,$3::uuid,$4,$5,$6,$7,$8::jsonb,$9,'planned',$10)
                    returning id, status, generated_asset_id, operation_id
                    """,
                    self.ctx.project_id,
                    spec.from_asset_id,
                    spec.to_asset_id,
                    spec.kind,
                    spec.duration_ms,
                    spec.model_id,
                    spec.seed,
                    spec.model_dump(mode="json", exclude_none=True),
                    signature,
                    operation_id,
                )
        return (
            f"Transition {row['id']} planned deterministically between the two assets.",
            {
                "kind": "transition",
                "transition_id": str(row["id"]),
                "signature": signature,
                "status": row["status"],
                "generated_asset_id": (
                    str(row["generated_asset_id"]) if row["generated_asset_id"] else None
                ),
                "operation_id": str(row["operation_id"]) if row["operation_id"] else None,
            },
        )


class AssetOperationArgs(BaseModel):
    operation: Literal["edit", "extend", "remix", "variation", "character", "upscale"]
    source_asset_ids: list[str] = Field(min_length=1)
    prompt: str = Field(min_length=1)
    model_id: str | None = None
    seed: int | None = None
    preserve: list[str] = Field(default_factory=list)
    annotation_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class PlanAssetOperationTool(SnapshotTool):
    name: str = "plan_asset_operation"
    args_schema: type[BaseModel] = AssetOperationArgs
    description: str = (
        "Create an auditable, non-destructive derived-asset operation for edit, extend, "
        "remix, controlled variation, reusable character extraction or upscale. USE THIS "
        "before generating from an existing asset so inputs, annotations, seed and what "
        "must be preserved remain attached to the output lineage. DO NOT overwrite source "
        "assets, and DO NOT claim an unsupported provider capability; planning spends no credits."
    )

    async def _arun_impl(
        self,
        operation: str,
        source_asset_ids: list[str],
        prompt: str,
        model_id: str | None = None,
        seed: int | None = None,
        preserve: list[str] | None = None,
        annotation_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        source_ids = list(dict.fromkeys(source_asset_ids))
        rows = await db.fetch(
            """select id, type, status from public.assets
                 where project_id=$1::uuid and id=any($2::uuid[])""",
            self.ctx.project_id,
            source_ids,
        )
        found = {str(row["id"]) for row in rows if row["status"] == "ready"}
        missing = [asset_id for asset_id in source_ids if asset_id not in found]
        if missing:
            raise XframeToolRetryableError(
                "Derived operations require ready source assets. Missing/not ready: "
                + ", ".join(missing)
            )
        annotation_ids = list(dict.fromkeys(annotation_ids or []))
        if annotation_ids:
            count = await db.fetchval(
                """select count(*) from public.asset_annotations
                     where project_id=$1::uuid and id=any($2::uuid[])
                       and asset_id=any($3::uuid[])""",
                self.ctx.project_id,
                annotation_ids,
                source_ids,
            )
            if int(count or 0) != len(annotation_ids):
                raise XframeToolRetryableError(
                    "One or more annotations do not belong to the selected source assets."
                )
        operation_params = {
            **(params or {}),
            "seed": seed,
            "preserve": sorted(set(preserve or [])),
            "annotation_ids": annotation_ids,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "operation": operation,
                    "sources": source_ids,
                    "prompt": prompt.strip(),
                    "model_id": model_id,
                    "params": operation_params,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        async with db.transaction() as conn:
            row = await conn.fetchrow(
                """
                insert into public.asset_operations
                  (project_id, operation, model_id, prompt, params, prompt_fingerprint)
                values ($1::uuid,$2,$3,$4,$5::jsonb,$6)
                returning id, status
                """,
                self.ctx.project_id,
                operation,
                model_id,
                prompt.strip(),
                operation_params,
                fingerprint,
            )
            operation_id = str(row["id"])
            await conn.executemany(
                """
                insert into public.asset_operation_inputs
                  (operation_id, project_id, asset_id, role, position)
                values ($1::uuid,$2::uuid,$3::uuid,'source',$4)
                """,
                [
                    (operation_id, self.ctx.project_id, asset_id, position)
                    for position, asset_id in enumerate(source_ids)
                ],
            )
        return (
            f"{operation.capitalize()} operation {operation_id} planned without modifying "
            "its source assets. Generate only with a model that declares the required capability.",
            {
                "kind": "asset_operation",
                "operation_id": operation_id,
                "operation": operation,
                "status": row["status"],
                "fingerprint": fingerprint,
                "source_asset_ids": source_ids,
            },
        )


PRODUCTION_TOOL_CLASSES: tuple[type[SnapshotTool], ...] = (
    CreateVoiceProfileTool,
    AssignCharacterVoiceTool,
    CreateScreenplayTool,
    CreateAudioPlanTool,
    ProfileAudioAssetTool,
    SelectMusicTool,
    AddAssetAnnotationTool,
    PlanAssetOperationTool,
    PlanTransitionTool,
)
