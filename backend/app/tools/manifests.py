"""Scene-level production manifests and structural approval gates."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app import db
from app.taxonomy.builder import SnapshotTool
from app.tools.errors import XframeToolRetryableError

ALL_MODES: tuple[str, ...] = ("preproduction", "production", "edit")


class BuildManifestArgs(BaseModel):
    scene_id: str
    shot_ids: list[str] | None = Field(
        None,
        description=(
            "Optional safety assertion. The scene_shots relation is authoritative; when "
            "provided this list must match its exact order."
        ),
    )
    title: str | None = None
    objective: str = ""
    visual_language: str = ""
    continuity_rules: list[str] = Field(default_factory=list)
    delivery: dict[str, Any] = Field(default_factory=dict)


class BuildProductionManifestTool(SnapshotTool):
    name: str = "build_production_manifest"
    args_schema: type[BaseModel] = BuildManifestArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Snapshot one scene into an executable production manifest containing exact script, "
        "ordered shots, locked resources, voices, audio placements, visual language and "
        "delivery rules, then run structural validation. USE THIS before any multi-shot "
        "scene is rendered or rebuilt. DO NOT approve or generate from a manifest whose "
        "validation reports unresolved errors, missing references or unready voices."
    )

    async def _arun_impl(
        self, scene_id: str, shot_ids: list[str] | None = None, title: str | None = None,
        objective: str = "", visual_language: str = "",
        continuity_rules: list[str] | None = None,
        delivery: dict[str, Any] | None = None, **_: Any,
    ) -> tuple[str, Any]:
        scene = await db.fetchrow(
            "select * from public.script_scenes where id=$1::uuid and project_id=$2::uuid",
            scene_id, self.ctx.project_id,
        )
        if not scene:
            raise XframeToolRetryableError(f"Unknown scene {scene_id} in this project.")
        canonical_rows = await db.fetch(
            """select shot_id from public.scene_shots
                where project_id=$1::uuid and scene_id=$2::uuid order by position""",
            self.ctx.project_id,
            scene_id,
        )
        canonical_shot_ids = [str(row["shot_id"]) for row in canonical_rows]
        if not canonical_shot_ids:
            raise XframeToolRetryableError(
                "This scene has no canonical shots. Assign its canvas shots to the scene "
                "before building a production manifest."
            )
        if shot_ids is not None and list(dict.fromkeys(shot_ids)) != canonical_shot_ids:
            raise XframeToolRetryableError(
                "shot_ids does not match the scene's canonical shot order. Update the "
                "scene assignment instead of overriding it in the manifest."
            )
        shot_ids = canonical_shot_ids
        lines = await db.fetch(
            """select l.*, a.name as speaker_name, vp.name as voice_name,
                      vp.provider_voice_id, vp.status as voice_status
                 from public.script_lines l
            left join public.assets a on a.id=l.speaker_element_id
            left join public.voice_profiles vp on vp.id=l.voice_profile_id
                where l.scene_id=$1::uuid order by l.position""",
            scene_id,
        )
        shots = await db.fetch(
            """select n.id,ss.position,n.title,n.text,n.spec,n.shot_status
                 from public.scene_shots ss
                 join public.canvas_nodes n on n.id=ss.shot_id
                where ss.project_id=$1::uuid and ss.scene_id=$2::uuid and n.type='shot'
                order by ss.position""",
            self.ctx.project_id, scene_id,
        )
        found = {str(row["id"]) for row in shots}
        missing_shots = [shot_id for shot_id in shot_ids if shot_id not in found]
        bindings = await db.fetch(
            """select * from public.resource_bindings where project_id=$1::uuid and (
                 (scope_type='scene' and scope_id=$2::uuid) or
                 (scope_type='line' and scope_id=any($3::uuid[])) or
                 (scope_type='shot' and scope_id=any($4::uuid[])) or
                 scope_type='timeline' or
                 scope_type='project') order by priority desc,created_at""",
            self.ctx.project_id, scene_id, [str(row["id"]) for row in lines], shot_ids,
        )
        legacy_links = await db.fetch(
            """select sal.*,a.name as asset_name,a.type as asset_type,a.status as asset_status
                 from public.script_asset_links sal join public.assets a on a.id=sal.asset_id
                where sal.project_id=$1::uuid and sal.scene_id=$2::uuid""",
            self.ctx.project_id, scene_id,
        )
        cues = await db.fetch(
            """select c.*,a.name as asset_name,a.status as asset_status
                 from public.audio_cues c join public.assets a on a.id=c.asset_id
                where c.project_id=$1::uuid and (
                  c.scene_id=$4::uuid or c.script_line_id=any($2::uuid[]) or c.shot_id=any($3::uuid[]))
                order by c.start_ms""",
            self.ctx.project_id, [str(row["id"]) for row in lines], shot_ids, scene_id,
        )

        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if missing_shots:
            errors.append({"code": "missing_shots", "ids": missing_shots})
        if not lines:
            warnings.append({"code": "scene_has_no_script_lines"})
        # Polymorphic bindings intentionally have no loose FK. Resolve them here so an
        # approved snapshot can never contain a deleted or unready locked resource.
        binding_tables = {
            "asset": ("assets", "status"), "element": ("assets", "status"),
            "voice": ("voice_profiles", "status"),
            "sound_template": ("audio_templates", None),
            "transition": ("timeline_transitions", "status"),
        }
        for binding in bindings:
            if not binding["locked"]:
                continue
            table, status_column = binding_tables[str(binding["resource_type"])]
            select = f"id,{status_column}" if status_column else "id"
            resource = await db.fetchrow(
                f"select {select} from public.{table} where id=$1::uuid and project_id=$2::uuid",
                binding["resource_id"], self.ctx.project_id,
            )
            if not resource:
                errors.append({"code": "bound_resource_missing", "binding_id": str(binding["id"])})
            elif status_column and str(resource[status_column]) not in {"ready", "approved"}:
                errors.append({"code": "bound_resource_not_ready", "binding_id": str(binding["id"]),
                               "status": str(resource[status_column])})
        for line in lines:
            line_id = str(line["id"])
            if line["line_type"] == "dialogue" and not line["speaker_element_id"]:
                errors.append({"code": "dialogue_without_speaker", "line_id": line_id})
            if line["line_type"] in {"dialogue", "voiceover"}:
                if not line["provider_voice_id"] or line["voice_status"] != "ready":
                    errors.append({"code": "speech_without_ready_voice", "line_id": line_id})
            if line["status"] == "failed":
                errors.append({"code": "failed_script_line", "line_id": line_id})
        for shot in shots:
            spec = dict(shot["spec"] or {})
            if not str(shot["text"] or "").strip():
                errors.append({"code": "shot_without_prompt", "shot_id": str(shot["id"])})
            if not spec.get("duration_s"):
                errors.append({"code": "shot_without_duration", "shot_id": str(shot["id"])})
            for element in spec.get("elements") or []:
                if isinstance(element, dict) and not element.get("id"):
                    errors.append({"code": "unresolved_shot_element", "shot_id": str(shot["id"])})
        for link in legacy_links:
            if link["asset_status"] != "ready":
                errors.append({"code": "linked_asset_not_ready", "asset_id": str(link["asset_id"])})
        for cue in cues:
            if cue["asset_status"] != "ready":
                errors.append({"code": "audio_asset_not_ready", "cue_id": str(cue["id"])})
            if cue["end_ms"] <= cue["start_ms"]:
                errors.append({"code": "invalid_audio_range", "cue_id": str(cue["id"])})
            if not cue["approved"]:
                errors.append({"code": "audio_cue_not_approved", "cue_id": str(cue["id"])})

        def clean(rows: Any) -> list[dict[str, Any]]:
            return [json.loads(json.dumps(dict(row), default=str)) for row in rows]

        specification = {
            "scene": json.loads(json.dumps(dict(scene), default=str)),
            "script_lines": clean(lines),
            "shots": clean(shots),
            "resource_bindings": clean(bindings),
            "legacy_asset_links": clean(legacy_links),
            "audio_cues": clean(cues),
            "director": {
                "objective": objective,
                "visual_language": visual_language,
                "continuity_rules": continuity_rules or [],
                "delivery": delivery or {},
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(specification, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        validation = {"valid": not errors, "errors": errors, "warnings": warnings}
        version = int(await db.fetchval(
            """select coalesce(max(version),0)+1 from public.production_manifests
                where project_id=$1::uuid and scene_id=$2::uuid""",
            self.ctx.project_id, scene_id,
        ))
        row = await db.fetchrow(
            """insert into public.production_manifests
               (project_id,scene_id,version,title,status,specification,validation,fingerprint)
               values ($1::uuid,$2::uuid,$3,$4,$5,$6::jsonb,$7::jsonb,$8) returning id,status""",
            self.ctx.project_id, scene_id, version,
            title or f"{scene['title']} v{version}",
            "validated" if not errors else "invalid",
            specification, validation, fingerprint,
        )
        return (
            f"Production manifest {row['id']} v{version}: "
            f"{len(errors)} errors, {len(warnings)} warnings.",
            {"manifest_id": str(row["id"]), "version": version,
             "status": row["status"], "validation": validation,
             "fingerprint": fingerprint, "shot_ids": shot_ids},
        )


class ManifestIdArgs(BaseModel):
    manifest_id: str


class ApproveProductionManifestTool(SnapshotTool):
    name: str = "approve_production_manifest"
    args_schema: type[BaseModel] = ManifestIdArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Lock a validated production manifest as the authoritative specification for its "
        "scene and supersede the previous approved version. USE THIS only after the user "
        "approves the visible manifest and validation has no errors. DO NOT approve an "
        "invalid manifest, infer approval from silence, or mutate its snapshot afterwards."
    )

    async def _arun_impl(self, manifest_id: str, **_: Any) -> tuple[str, Any]:
        normalized = re.sub(r"\s+", " ", self.ctx.user_message.lower()).strip()
        approval_terms = (
            "apruebo", "aprobar", "aprueba", "aprobado", "doy el visto bueno",
            "confirmo", "adelante con el manifiesto", "approve", "approved",
            "confirm manifest", "go ahead with the manifest",
        )
        if not any(term in normalized for term in approval_terms):
            raise XframeToolRetryableError(
                "Manifest approval requires explicit approval in the user's current "
                "message. Show the manifest and ask the user to approve it; do not infer "
                "consent from an earlier turn, silence, or a request to inspect it."
            )
        row = await db.fetchrow(
            """select * from public.production_manifests
                where id=$1::uuid and project_id=$2::uuid""",
            manifest_id, self.ctx.project_id,
        )
        if not row:
            raise XframeToolRetryableError(f"Unknown manifest {manifest_id}.")
        validation = dict(row["validation"] or {})
        if row["status"] != "validated" or not validation.get("valid"):
            raise XframeToolRetryableError(
                f"Manifest {manifest_id} is {row['status']} and cannot be approved. "
                f"Resolve: {validation.get('errors', [])}"
            )
        async with db.transaction() as conn:
            await conn.execute(
                """update public.production_manifests set status='validated',approved_at=null
                    where project_id=$1::uuid and scene_id=$2::uuid and status='approved'""",
                self.ctx.project_id, row["scene_id"],
            )
            await conn.execute(
                """update public.production_manifests
                      set status='approved', approved_at=now(), approved_by=$2::uuid,
                          approval_evidence=$3::jsonb
                    where id=$1::uuid""",
                manifest_id, self.ctx.user_id,
                {"message": self.ctx.user_message, "resource_refs": self.ctx.resource_refs},
            )
        return f"Manifest {manifest_id} approved and locked for production.", {
            "manifest_id": manifest_id, "status": "approved", "fingerprint": row["fingerprint"]
        }


MANIFEST_TOOL_CLASSES: tuple[type[SnapshotTool], ...] = (
    BuildProductionManifestTool,
    ApproveProductionManifestTool,
)
