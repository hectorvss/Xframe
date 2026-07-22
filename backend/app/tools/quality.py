"""Quality reports and immutable production completion gates."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, ClassVar, Literal

import httpx
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app import db
from app.config import get_settings
from app.llm import chat_model
from app.production.quality import inspect_media
from app.storage import get_signer
from app.taxonomy.builder import SnapshotTool
from app.tools.errors import XframeToolRetryableError

ALL_MODES: tuple[str, ...] = ("preproduction", "production", "edit")
CreativeCheckType = Literal[
    "identity", "continuity", "render", "prompt_adherence", "product_fidelity",
    "text_logo", "transition",
]


class CreativeCheck(BaseModel):
    check_type: CreativeCheckType
    passed: bool
    score: float = Field(ge=0, le=1)
    evidence: str
    issues: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class CreativeInspection(BaseModel):
    checks: list[CreativeCheck]


async def _image_data_url(url: str) -> str:
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.content
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("Image exceeds the 20 MB inspection limit.")
        mime = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
        return f"data:{mime};base64,{base64.b64encode(content).decode()}"


async def _video_frame_data_urls(url: str, duration_s: float) -> list[str]:
    times = sorted({0.0, max(0.0, duration_s / 2), max(0.0, duration_s - 0.08)})
    results: list[str] = []
    with tempfile.TemporaryDirectory(prefix="xframe-qa-") as folder:
        for index, timestamp in enumerate(times):
            output = Path(folder) / f"frame-{index}.jpg"
            process = await asyncio.create_subprocess_exec(
                get_settings().ffmpeg_path,
                "-hide_banner", "-nostdin", "-y", "-ss", f"{timestamp:.3f}", "-i", url,
                "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3",
                str(output), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0 or not output.exists():
                raise RuntimeError(stderr.decode(errors="replace")[-1000:])
            results.append(
                "data:image/jpeg;base64," + base64.b64encode(output.read_bytes()).decode()
            )
    return results


async def _inspect_audio_signal(url: str) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        get_settings().ffmpeg_path,
        "-hide_banner", "-nostdin", "-i", url,
        "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
        "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    text = stderr.decode(errors="replace")
    matches = re.findall(r"\{\s*\"input_i\"[\s\S]*?\}", text)
    if process.returncode != 0 or not matches:
        return {
            "passed": False,
            "score": 0.0,
            "metrics": {},
            "issues": [{"code": "audio_analysis_failed", "message": text[-500:]}],
        }
    raw = json.loads(matches[-1])
    integrated = float(raw.get("input_i", "-inf"))
    true_peak = float(raw.get("input_tp", "inf"))
    issues: list[dict[str, Any]] = []
    if integrated <= -55:
        issues.append({"code": "audio_effectively_silent", "integrated_lufs": integrated})
    if true_peak > 0.1:
        issues.append({"code": "audio_clipping_risk", "true_peak_dbtp": true_peak})
    score = max(0.0, 1.0 - 0.5 * len(issues))
    return {
        "passed": not issues,
        "score": score,
        "metrics": {
            "integrated_lufs": integrated,
            "true_peak_dbtp": true_peak,
            "loudness_range_lu": float(raw.get("input_lra", 0)),
            "threshold_lufs": float(raw.get("input_thresh", 0)),
        },
        "issues": issues,
    }


class InspectAssetArgs(BaseModel):
    asset_id: str


class InspectAssetTechnicalTool(SnapshotTool):
    name: str = "inspect_asset_technical"
    args_schema: type[BaseModel] = InspectAssetArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Probe the delivered media and persist an objective technical quality report "
        "covering streams, duration, resolution, codecs, sample rate and corruption. USE "
        "THIS after an audio/video/cut asset becomes ready and before approving it for a "
        "scene or final assembly. DO NOT infer properties from the generation request or "
        "mark a file passed when it cannot be opened and measured."
    )

    async def _arun_impl(self, asset_id: str, **_: Any) -> tuple[str, Any]:
        asset = await db.fetchrow(
            "select * from public.assets where id=$1::uuid and project_id=$2::uuid",
            asset_id, self.ctx.project_id,
        )
        if not asset or asset["status"] != "ready" or not asset["url"]:
            raise XframeToolRetryableError(f"Asset {asset_id} is not a ready stored output.")
        kind = str(asset["type"] or "")
        signed = await get_signer().sign(str(asset["url"]), ttl_s=300)
        try:
            report = await inspect_media(signed, kind)
        except Exception as exc:
            report = {"passed": False, "score": 0.0, "metrics": {},
                      "issues": [{"code": "probe_failed", "message": type(exc).__name__}]}
        row = await db.fetchrow(
            """insert into public.quality_reports
               (project_id,asset_id,check_type,status,score,passed,metrics,issues)
               values ($1::uuid,$2::uuid,'technical',$3,$4,$5,$6::jsonb,$7::jsonb)
               returning id""",
            self.ctx.project_id, asset_id, "passed" if report["passed"] else "failed",
            report["score"], report["passed"], report["metrics"], report["issues"],
        )
        return f"Technical inspection for asset {asset_id}: {'passed' if report['passed'] else 'failed'}.", {
            "report_id": str(row["id"]), "asset_id": asset_id, **report,
        }


class InspectAudioSignalTool(SnapshotTool):
    name: str = "inspect_audio_signal"
    args_schema: type[BaseModel] = InspectAssetArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Measure the actual stored audio signal and persist an automated audio quality "
        "report with integrated loudness, true peak, loudness range, silence and clipping "
        "evidence. USE THIS for generated voice, music, sound effects and final audio tracks "
        "after technical inspection and before manifest completion. DO NOT approve audio by "
        "reading its prompt, waveform placeholder or provider status."
    )

    async def _arun_impl(self, asset_id: str, **_: Any) -> tuple[str, Any]:
        asset = await db.fetchrow(
            "select id,type,url,status from public.assets where id=$1::uuid and project_id=$2::uuid",
            asset_id,
            self.ctx.project_id,
        )
        if not asset or asset["status"] != "ready" or not asset["url"]:
            raise XframeToolRetryableError(f"Asset {asset_id} is not a ready stored output.")
        kind = str(asset["type"] or "").lower()
        if kind not in {"audio", "music", "sound", "voice", "cut", "video", "vídeos"}:
            raise XframeToolRetryableError(
                f"Asset {asset_id} has no audio-capable media type ({asset['type']})."
            )
        signed = await get_signer().sign(str(asset["url"]), ttl_s=300)
        report = await _inspect_audio_signal(signed)
        row = await db.fetchrow(
            """insert into public.quality_reports
                 (project_id,asset_id,check_type,status,score,passed,metrics,issues,
                  review_source,reviewed_by,review_evidence)
               values ($1::uuid,$2::uuid,'audio',$3,$4,$5,$6::jsonb,$7::jsonb,
                       'automated',null,$8::jsonb) returning id""",
            self.ctx.project_id,
            asset_id,
            "passed" if report["passed"] else "failed",
            report["score"],
            report["passed"],
            report["metrics"],
            report["issues"],
            {"analyzer": "ffmpeg_loudnorm", "source": "actual_stored_media"},
        )
        status = "passed" if report["passed"] else "failed"
        return f"Audio signal inspection for asset {asset_id}: {status}.", {
            "report_id": str(row["id"]),
            "asset_id": asset_id,
            **report,
        }


class InspectAssetCreativeArgs(BaseModel):
    asset_id: str
    check_types: list[CreativeCheckType] | None = None


class InspectAssetCreativeTool(SnapshotTool):
    name: str = "inspect_asset_creative"
    args_schema: type[BaseModel] = InspectAssetCreativeArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Inspect actual output frames with the configured multimodal director model and "
        "persist evidence-backed creative QA for prompt adherence, render defects, identity, "
        "continuity, product, text/logo or transitions. USE THIS after technical "
        "inspection and before manifest completion. DO NOT review from prompts or metadata, "
        "claim spoken-script fidelity from silent frames, invent invisible evidence, or "
        "replace the user's final delivery approval."
    )

    async def _arun_impl(
        self, asset_id: str, check_types: list[str] | None = None, **_: Any
    ) -> tuple[str, Any]:
        asset = await db.fetchrow(
            """select id,name,type,url,status,shot_id,prompt,params
                 from public.assets where id=$1::uuid and project_id=$2::uuid""",
            asset_id,
            self.ctx.project_id,
        )
        if not asset or asset["status"] != "ready" or not asset["url"]:
            raise XframeToolRetryableError(f"Asset {asset_id} is not a ready stored output.")
        shot = None
        if asset["shot_id"]:
            shot = await db.fetchrow(
                """select id,title,text,spec from public.canvas_nodes
                    where id=$1::uuid and project_id=$2::uuid""",
                asset["shot_id"],
                self.ctx.project_id,
            )
        shot_spec = dict(shot["spec"] or {}) if shot else {}
        requested = list(dict.fromkeys(check_types or ["render", "prompt_adherence"]))
        if shot_spec.get("elements") and "identity" not in requested:
            requested.append("identity")
        reference_ids = [
            str(item.get("id"))
            for item in (shot_spec.get("elements") or [])
            if isinstance(item, dict) and item.get("id")
        ][:4]
        references = (
            await db.fetch(
                """select id,name,url from public.assets
                    where project_id=$1::uuid and id=any($2::uuid[]) and status='ready'""",
                self.ctx.project_id,
                reference_ids,
            )
            if reference_ids
            else []
        )
        transition = None
        if "transition" in requested:
            transition = await db.fetchrow(
                """select t.id,t.from_asset_id,t.to_asset_id,
                          fa.name as from_name,fa.url as from_url,fa.type as from_type,
                          ta.name as to_name,ta.url as to_url,ta.type as to_type
                     from public.timeline_transitions t
                     join public.assets fa on fa.id=t.from_asset_id
                     join public.assets ta on ta.id=t.to_asset_id
                    where t.project_id=$1::uuid and t.generated_asset_id=$2::uuid""",
                self.ctx.project_id,
                asset_id,
            )
            if not transition:
                raise XframeToolRetryableError(
                    "Transition QA requires an output linked to its exact boundary assets."
                )
        signed = await get_signer().sign(str(asset["url"]), ttl_s=600)
        kind = str(asset["type"] or "").lower()
        try:
            if "video" in kind or kind == "cut" or kind == "vídeos":
                technical = await inspect_media(signed, kind)
                duration = float(technical.get("metrics", {}).get("duration_s") or 1.0)
                output_images = await _video_frame_data_urls(signed, duration)
            else:
                output_images = [await _image_data_url(signed)]
        except Exception as exc:
            raise XframeToolRetryableError(
                f"Could not decode the actual media for creative inspection: {type(exc).__name__}."
            ) from exc

        prompt = {
            "asset": {"id": asset_id, "name": asset["name"], "type": asset["type"]},
            "shot": json.loads(json.dumps(dict(shot), default=str)) if shot else None,
            "generation_prompt": asset["prompt"],
            "checks": requested,
        }
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Act as a strict production QA director. Review the ACTUAL output frames "
                    "against this frozen intent. Fail uncertain or unsupported claims; identify "
                    "visible temporal inconsistency across frames. Return exactly one result for "
                    f"each requested check. Specification: {json.dumps(prompt, ensure_ascii=False)}"
                ),
            }
        ]
        for index, image_url in enumerate(output_images):
            content.extend(
                [
                    {"type": "text", "text": f"OUTPUT FRAME {index + 1}"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]
            )
        for reference in references:
            try:
                reference_url = await get_signer().sign(str(reference["url"]), ttl_s=600)
                content.extend(
                    [
                        {"type": "text", "text": f"CANONICAL REFERENCE: {reference['name']}"},
                        {"type": "image_url", "image_url": {"url": await _image_data_url(reference_url)}},
                    ]
                )
            except Exception:
                continue
        if transition:
            for side in ("from", "to"):
                boundary_url = await get_signer().sign(
                    str(transition[f"{side}_url"]), ttl_s=600
                )
                technical = await inspect_media(boundary_url, str(transition[f"{side}_type"]))
                duration = float(technical.get("metrics", {}).get("duration_s") or 0.1)
                frames = await _video_frame_data_urls(
                    boundary_url,
                    duration if side == "from" else 0.1,
                )
                boundary = frames[-1] if side == "from" else frames[0]
                content.extend(
                    [
                        {
                            "type": "text",
                            "text": (
                                "REQUIRED FROM BOUNDARY (last frame)"
                                if side == "from"
                                else "REQUIRED TO BOUNDARY (first frame)"
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": boundary}},
                    ]
                )
        try:
            inspector = chat_model("root", max_tokens=2600, streaming=False).with_structured_output(
                CreativeInspection
            )
            inspection = await inspector.ainvoke([HumanMessage(content=content)])
        except Exception as exc:
            raise XframeToolRetryableError(
                f"Creative inspection model failed: {type(exc).__name__}. No QA pass was recorded."
            ) from exc
        result_by_type = {item.check_type: item for item in inspection.checks}
        reports: list[dict[str, Any]] = []
        for check_type in requested:
            decision = result_by_type.get(check_type)
            if decision is None:
                decision = CreativeCheck(
                    check_type=check_type,
                    passed=False,
                    score=0,
                    evidence="The inspection model omitted this required check.",
                    issues=[{"code": "inspection_check_missing"}],
                )
            row = await db.fetchrow(
                """insert into public.quality_reports
                     (project_id,asset_id,check_type,status,score,passed,metrics,issues,
                      review_source,reviewed_by,review_evidence)
                   values ($1::uuid,$2::uuid,$3,$4,$5,$6,$7::jsonb,$8::jsonb,
                           'automated',null,$9::jsonb) returning id""",
                self.ctx.project_id,
                asset_id,
                check_type,
                "passed" if decision.passed else "failed",
                decision.score,
                decision.passed,
                decision.metrics,
                decision.issues,
                {"model": get_settings().model_root, "evidence": decision.evidence,
                 "frame_count": len(output_images), "reference_ids": reference_ids},
            )
            reports.append(
                {"report_id": str(row["id"]), "check_type": check_type,
                 "passed": decision.passed, "score": decision.score,
                 "evidence": decision.evidence, "issues": decision.issues}
            )
        passed = sum(1 for report in reports if report["passed"])
        return f"Creative inspection recorded: {passed}/{len(reports)} checks passed.", {
            "asset_id": asset_id,
            "reports": reports,
        }


class RecordQualityReviewArgs(BaseModel):
    asset_id: str
    check_type: Literal["lipsync", "identity", "continuity", "audio", "transition", "render",
                        "prompt_adherence", "script_fidelity", "product_fidelity",
                        "text_logo", "final_cut"]
    passed: bool
    score: float = Field(ge=0, le=1)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: str = Field(min_length=10, max_length=2000)


class RecordQualityReviewTool(SnapshotTool):
    name: str = "record_quality_review"
    args_schema: type[BaseModel] = RecordQualityReviewArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Persist a structured quality decision after an actual visual or listening review, "
        "including score, issues and measurable evidence. USE THIS to record identity, "
        "continuity, audio, transition, prompt, script, product, text/logo or final-cut "
        "review. DO NOT call it without inspecting the output, invent evidence, or turn "
        "uncertainty into a pass."
    )

    async def _arun_impl(self, asset_id: str, check_type: str, passed: bool,
                         score: float, issues: list[dict[str, Any]] | None = None,
                         metrics: dict[str, Any] | None = None, evidence: str = "", **_: Any) -> tuple[str, Any]:
        exists = await db.fetchval(
            "select exists(select 1 from public.assets where id=$1::uuid and project_id=$2::uuid)",
            asset_id, self.ctx.project_id,
        )
        if not exists:
            raise XframeToolRetryableError(f"Unknown asset {asset_id} in this project.")
        selected = any(
            str(ref.get("resource_id") or ref.get("id") or "") == asset_id
            for ref in self.ctx.resource_refs
        )
        mentioned = asset_id in self.ctx.user_message
        decision_words = (
            "apruebo", "aprobado", "he revisado", "falla", "rechazo", "se ve", "suena",
            "pass", "passed", "reviewed", "fail", "failed", "reject",
        )
        if not (selected or mentioned) or not any(word in self.ctx.user_message.lower() for word in decision_words):
            raise XframeToolRetryableError(
                "A human quality report requires the current user message to identify the "
                "asset (preferably with @) and explicitly state the observed pass/fail decision. "
                "Ask the user to inspect it; the agent cannot self-certify unseen media."
            )
        row = await db.fetchrow(
            """insert into public.quality_reports
               (project_id,asset_id,check_type,status,score,passed,metrics,issues,
                review_source,reviewed_by,review_evidence)
               values ($1::uuid,$2::uuid,$3,$4,$5,$6,$7::jsonb,$8::jsonb,
                       'human',$9::uuid,$10::jsonb) returning id""",
            self.ctx.project_id, asset_id, check_type, "passed" if passed else "failed",
            score, passed, metrics or {}, issues or [], self.ctx.user_id,
            {"message": self.ctx.user_message, "evidence": evidence,
             "resource_refs": self.ctx.resource_refs},
        )
        return f"Recorded {check_type} review for asset {asset_id}: {'passed' if passed else 'failed'}.", {
            "report_id": str(row["id"]), "asset_id": asset_id, "check_type": check_type,
            "passed": passed, "score": score, "issues": issues or [], "metrics": metrics or {},
        }


class CompleteManifestArgs(BaseModel):
    manifest_id: str


class CompleteProductionManifestTool(SnapshotTool):
    name: str = "complete_production_manifest"
    args_schema: type[BaseModel] = CompleteManifestArgs
    modes: ClassVar[tuple[str, ...]] = ("production", "edit")
    description: str = (
        "Close an executing production manifest only when every declared shot has a ready "
        "output and its latest required quality reports pass. USE THIS after generation "
        "and review to establish that a scene is safe for final assembly. DO NOT complete "
        "a manifest with missing renders, failed/needs-review reports or no quality evidence."
    )

    async def _arun_impl(self, manifest_id: str, **_: Any) -> tuple[str, Any]:
        manifest = await db.fetchrow(
            "select * from public.production_manifests where id=$1::uuid and project_id=$2::uuid",
            manifest_id, self.ctx.project_id,
        )
        if not manifest or manifest["status"] not in {"approved", "executing"}:
            raise XframeToolRetryableError(f"Manifest {manifest_id} is not approved/executing.")
        spec = dict(manifest["specification"] or {})
        shot_ids = [str(item["id"]) for item in spec.get("shots", [])]
        outputs = await db.fetch(
            """select distinct on (j.shot_id) a.id,a.shot_id,a.status,a.type,a.url,a.job_id,a.params
                 from public.generation_jobs j
                 join public.assets a on a.id=j.asset_id
                where j.project_id=$1::uuid and j.shot_id=any($2::text[])
                  and j.request #>> '{extra,manifest_id}' = $3
                order by j.shot_id,j.finished_at desc nulls last,j.created_at desc""",
            self.ctx.project_id, shot_ids, manifest_id,
        )
        by_shot = {str(row["shot_id"]): row for row in outputs}
        shot_specs = {str(item["id"]): item for item in spec.get("shots", [])}
        scripted_shots = {
            str(line.get("shot_id"))
            for line in spec.get("script_lines", [])
            if line.get("shot_id")
            and line.get("line_type") in {"dialogue", "voiceover", "caption"}
        }
        errors: list[dict[str, Any]] = []
        frozen_outputs: list[dict[str, Any]] = []
        for shot_id in shot_ids:
            asset = by_shot.get(shot_id)
            if not asset or asset["status"] != "ready":
                errors.append({"code": "missing_ready_output", "shot_id": shot_id})
                continue
            latest = await db.fetch(
                """select distinct on (check_type) id,check_type,passed,review_source
                     from public.quality_reports
                    where project_id=$1::uuid and asset_id=$2::uuid
                    order by check_type,created_at desc""",
                self.ctx.project_id, asset["id"],
            )
            reports = {row["check_type"]: row for row in latest}
            required = {"render", "prompt_adherence"}
            if str(asset["type"]).lower() in {"video", "cut", "vídeos"}:
                required.add("technical")
            frozen_shot = shot_specs.get(shot_id, {})
            shot_spec = dict(frozen_shot.get("spec") or {})
            elements = list(shot_spec.get("elements") or [])
            if elements:
                required.add("identity")
            if len(shot_ids) > 1:
                required.add("continuity")
            if any(
                isinstance(element, dict)
                and str(element.get("role") or "").lower() in {"product", "producto"}
                for element in elements
            ):
                required.add("product_fidelity")
            prompt_text = str(frozen_shot.get("text") or "").lower()
            if any(token in prompt_text for token in ("logo", "texto", "text", "rótulo", "caption")):
                required.add("text_logo")
            if shot_id in scripted_shots:
                required.add("script_fidelity")
            params = dict(asset.get("params") or {})
            if params.get("modality") == "lipsync" or params.get("extra", {}).get("operation_kind") == "lipsync":
                required.add("lipsync")
            for check in sorted(required):
                if not reports.get(check) or reports[check]["passed"] is not True:
                    errors.append({"code": "quality_gate_not_passed", "shot_id": shot_id,
                                   "asset_id": str(asset["id"]), "check_type": check})
                elif check == "script_fidelity" and reports[check]["review_source"] not in {
                    "human", "provider"
                }:
                    errors.append(
                        {
                            "code": "script_fidelity_requires_audible_evidence",
                            "shot_id": shot_id,
                            "asset_id": str(asset["id"]),
                            "review_source": reports[check]["review_source"],
                        }
                    )
            frozen_outputs.append(
                {
                    "shot_id": shot_id,
                    "asset_id": str(asset["id"]),
                    "job_id": str(asset["job_id"]),
                    "quality_report_ids": [str(row["id"]) for row in latest],
                }
            )
        audio_asset_ids = list(
            dict.fromkeys(
                str(cue["asset_id"])
                for cue in spec.get("audio_cues", [])
                if cue.get("asset_id")
            )
        )
        frozen_audio_reviews: dict[str, list[str]] = {}
        for audio_asset_id in audio_asset_ids:
            latest_audio = await db.fetch(
                """select distinct on (check_type) id,check_type,passed
                     from public.quality_reports
                    where project_id=$1::uuid and asset_id=$2::uuid
                      and check_type in ('technical','audio')
                    order by check_type,created_at desc""",
                self.ctx.project_id,
                audio_asset_id,
            )
            reports = {str(row["check_type"]): row for row in latest_audio}
            frozen_audio_reviews[audio_asset_id] = [str(row["id"]) for row in latest_audio]
            for check in ("technical", "audio"):
                if not reports.get(check) or reports[check]["passed"] is not True:
                    errors.append(
                        {"code": "audio_quality_gate_not_passed", "asset_id": audio_asset_id,
                         "check_type": check}
                    )
        if errors:
            raise XframeToolRetryableError(f"Manifest cannot complete. Resolve: {errors}")
        ordered_assets = [item["asset_id"] for item in frozen_outputs]
        transitions = await db.fetch(
            """select id,from_asset_id,to_asset_id,kind,duration_ms,generated_asset_id,
                      model_id,seed,parameters,signature,status
                 from public.timeline_transitions
                where project_id=$1::uuid and from_asset_id=any($2::uuid[])
                  and to_asset_id=any($2::uuid[])""",
            self.ctx.project_id,
            ordered_assets,
        )
        by_pair = {
            (str(row["from_asset_id"]), str(row["to_asset_id"])): dict(row)
            for row in transitions
        }
        frozen_transitions: list[dict[str, Any]] = []
        frozen_transition_reviews: dict[str, list[str]] = {}
        for index in range(1, len(ordered_assets)):
            pair = (ordered_assets[index - 1], ordered_assets[index])
            transition = by_pair.get(pair)
            if transition:
                if transition.get("kind") == "generated":
                    generated_id = transition.get("generated_asset_id")
                    if transition.get("status") != "ready" or not generated_id:
                        errors.append(
                            {"code": "generated_transition_not_ready", "from_asset_id": pair[0],
                             "to_asset_id": pair[1]}
                        )
                    else:
                        transition_reports = await db.fetch(
                            """select distinct on (check_type) id,check_type,passed
                                 from public.quality_reports
                                where project_id=$1::uuid and asset_id=$2::uuid
                                  and check_type in ('technical','transition')
                                order by check_type,created_at desc""",
                            self.ctx.project_id,
                            generated_id,
                        )
                        report_by_type = {
                            str(report["check_type"]): report for report in transition_reports
                        }
                        frozen_transition_reviews[str(generated_id)] = [
                            str(report["id"]) for report in transition_reports
                        ]
                        for check in ("technical", "transition"):
                            if not report_by_type.get(check) or report_by_type[check]["passed"] is not True:
                                errors.append(
                                    {"code": "transition_quality_gate_not_passed",
                                     "asset_id": str(generated_id), "check_type": check}
                                )
                frozen_transitions.append(
                    json.loads(json.dumps(transition, default=str))
                )
            else:
                frozen_transitions.append(
                    {"from_asset_id": pair[0], "to_asset_id": pair[1], "kind": "cut",
                     "duration_ms": 0, "status": "ready"}
                )
        if errors:
            raise XframeToolRetryableError(f"Manifest cannot complete. Resolve: {errors}")
        audio_plan = await db.fetchrow(
            """select id,version,content from public.artifacts
                where project_id=$1::uuid and kind='audio_plan'
                order by version desc limit 1""",
            self.ctx.project_id,
        )
        execution_snapshot = {
            "outputs": frozen_outputs,
            "audio_cues": spec.get("audio_cues", []),
            "audio_quality_report_ids": frozen_audio_reviews,
            "audio_plan": (
                json.loads(json.dumps(dict(audio_plan), default=str)) if audio_plan else None
            ),
            "transitions": frozen_transitions,
            "transition_quality_report_ids": frozen_transition_reviews,
        }
        execution_fingerprint = hashlib.sha256(
            json.dumps(execution_snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        await db.execute(
            """update public.production_manifests
                  set status='complete',execution_snapshot=$2::jsonb,
                      execution_fingerprint=$3,completed_at=now()
                where id=$1::uuid""",
            manifest_id,
            execution_snapshot,
            execution_fingerprint,
        )
        return f"Manifest {manifest_id} completed with {len(shot_ids)} quality-gated outputs.", {
            "manifest_id": manifest_id, "status": "complete", "shot_ids": shot_ids,
            "asset_ids": ordered_assets, "execution_fingerprint": execution_fingerprint,
        }


class ApproveFinalDeliveryArgs(BaseModel):
    asset_id: str


class ApproveFinalDeliveryTool(SnapshotTool):
    name: str = "approve_final_delivery"
    args_schema: type[BaseModel] = ApproveFinalDeliveryArgs
    modes: ClassVar[tuple[str, ...]] = ("production", "edit")
    description: str = (
        "Create the immutable delivery approval for a final cut after objective technical "
        "inspection and attributable human final-cut/audio review pass. USE THIS only when "
        "the current user explicitly approves that exact @cut for delivery. DO NOT treat a "
        "ready render, completed scene manifest, silence or the agent's own opinion as final approval."
    )

    async def _arun_impl(self, asset_id: str, **_: Any) -> tuple[str, Any]:
        asset = await db.fetchrow(
            "select id,type,status,params from public.assets where id=$1::uuid and project_id=$2::uuid",
            asset_id, self.ctx.project_id,
        )
        if not asset or str(asset["type"]).lower() != "cut" or asset["status"] != "ready":
            raise XframeToolRetryableError(f"Asset {asset_id} is not a ready final cut.")
        normalized = self.ctx.user_message.lower()
        explicit = any(term in normalized for term in (
            "apruebo la entrega", "apruebo el corte", "listo para entregar",
            "approve delivery", "approve the cut", "ready for delivery",
        ))
        selected = asset_id in self.ctx.user_message or any(
            str(ref.get("resource_id") or ref.get("id") or "") == asset_id
            for ref in self.ctx.resource_refs
        )
        if not explicit or not selected:
            raise XframeToolRetryableError(
                "Final delivery requires the current user to identify this cut with @/id "
                "and explicitly say it is approved for delivery."
            )
        params = dict(asset["params"] or {})
        manifest_id = params.get("manifest_id")
        if not manifest_id:
            raise XframeToolRetryableError("This cut has no completed manifest lineage.")
        manifest_ok = await db.fetchval(
            "select exists(select 1 from public.production_manifests where id=$1::uuid and project_id=$2::uuid and status='complete')",
            manifest_id, self.ctx.project_id,
        )
        if not manifest_ok:
            raise XframeToolRetryableError("The cut's production manifest is not complete.")
        latest = await db.fetch(
            """select distinct on (check_type) id,check_type,passed,metrics,review_source
                 from public.quality_reports where project_id=$1::uuid and asset_id=$2::uuid
                order by check_type,created_at desc""",
            self.ctx.project_id, asset_id,
        )
        reports = {str(row["check_type"]): row for row in latest}
        required = {"technical", "final_cut"}
        technical = reports.get("technical")
        if technical and dict(technical["metrics"] or {}).get("audio"):
            required.add("audio")
        failures = [name for name in sorted(required)
                    if not reports.get(name) or reports[name]["passed"] is not True]
        if failures:
            raise XframeToolRetryableError(
                "Final delivery quality gates are missing or failed: " + ", ".join(failures)
            )
        for human_check in {"final_cut", "audio"} & required:
            if reports[human_check]["review_source"] != "human":
                raise XframeToolRetryableError(
                    f"{human_check} must be an attributable human review, not agent self-certification."
                )
        report_ids = [str(reports[name]["id"]) for name in sorted(required)]
        row = await db.fetchrow(
            """insert into public.delivery_approvals
               (project_id,asset_id,manifest_id,approved_by,quality_report_ids,evidence)
               values ($1::uuid,$2::uuid,$3::uuid,$4::uuid,$5::uuid[],$6::jsonb)
               on conflict (project_id,asset_id) do update set
                 manifest_id=excluded.manifest_id,approved_by=excluded.approved_by,
                 quality_report_ids=excluded.quality_report_ids,evidence=excluded.evidence,
                 created_at=now() returning id,created_at""",
            self.ctx.project_id, asset_id, manifest_id, self.ctx.user_id, report_ids,
            {"message": self.ctx.user_message, "resource_refs": self.ctx.resource_refs},
        )
        return f"Final cut {asset_id} approved for delivery with {len(report_ids)} passed gates.", {
            "approval_id": str(row["id"]), "asset_id": asset_id,
            "manifest_id": str(manifest_id), "quality_report_ids": report_ids,
            "approved_at": str(row["created_at"]),
        }


QUALITY_TOOL_CLASSES: tuple[type[SnapshotTool], ...] = (
    InspectAssetTechnicalTool, InspectAudioSignalTool, InspectAssetCreativeTool,
    RecordQualityReviewTool, CompleteProductionManifestTool,
    ApproveFinalDeliveryTool,
)
