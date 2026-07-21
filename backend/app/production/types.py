"""Typed contracts shared by the agent, API, worker and editor UI.

These models deliberately contain no provider-specific payload.  A voice, music cue,
lip-sync segment or transition remains editable when its current provider is retired.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AudioMode(StrEnum):
    SILENT = "silent"
    NATIVE = "native"
    SCRIPTED = "scripted"
    EXISTING = "existing"


class TrackKind(StrEnum):
    DIALOGUE = "dialogue"
    VOICEOVER = "voiceover"
    MUSIC = "music"
    SFX = "sfx"
    AMBIENCE = "ambience"
    NATIVE = "native"


class AssetOperationKind(StrEnum):
    EDIT = "edit"
    EXTEND = "extend"
    REMIX = "remix"
    VARIATION = "variation"
    CHARACTER = "character"
    LIPSYNC = "lipsync"
    TRANSITION = "transition"
    UPSCALE = "upscale"
    VOICE = "voice"
    MUSIC = "music"
    SFX = "sfx"
    MIX = "mix"


class VoicePerformance(BaseModel):
    language: str = "es"
    emotion: str = "neutral"
    direction: str = ""
    pace: float = Field(1.0, ge=0.5, le=2.0)
    intensity: float = Field(0.5, ge=0.0, le=1.0)
    pause_before_ms: int = Field(0, ge=0)
    pause_after_ms: int = Field(0, ge=0)
    pronunciation: dict[str, str] = Field(default_factory=dict)


class DialogueLineSpec(BaseModel):
    id: str | None = None
    scene_id: str
    position: int = Field(ge=0)
    line_type: str = "dialogue"
    speaker_element_id: str | None = None
    voice_profile_id: str | None = None
    shot_id: str | None = None
    text: str = Field(min_length=1, max_length=10_000)
    performance: VoicePerformance = Field(default_factory=VoicePerformance)
    target_duration_ms: int | None = Field(None, gt=0)

    @model_validator(mode="after")
    def speaker_required_for_dialogue(self) -> DialogueLineSpec:
        if self.line_type == "dialogue" and not self.speaker_element_id:
            raise ValueError("dialogue lines require speaker_element_id")
        return self


class AudioCueSpec(BaseModel):
    id: str | None = None
    asset_id: str
    track_kind: TrackKind
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    source_in_ms: int = Field(0, ge=0)
    source_out_ms: int | None = Field(None, gt=0)
    gain_db: float = Field(0.0, ge=-96.0, le=24.0)
    fade_in_ms: int = Field(0, ge=0)
    fade_out_ms: int = Field(0, ge=0)
    pan: float = Field(0.0, ge=-1.0, le=1.0)
    loop: bool = False
    locked: bool = False
    approved: bool = False
    ducking_group: str | None = None
    ducking_db: float | None = Field(None, ge=-48.0, le=0.0)
    priority: int = 0
    narrative_role: str = ""
    context_tags: list[str] = Field(default_factory=list)
    shot_id: str | None = None
    script_line_id: str | None = None

    @model_validator(mode="after")
    def valid_range(self) -> AudioCueSpec:
        if self.end_ms <= self.start_ms:
            raise ValueError("audio cue end_ms must be after start_ms")
        if self.source_out_ms is not None and self.source_out_ms <= self.source_in_ms:
            raise ValueError("audio cue source_out_ms must be after source_in_ms")
        if self.fade_in_ms + self.fade_out_ms > self.end_ms - self.start_ms:
            raise ValueError("audio cue fades cannot exceed cue duration")
        return self


class AudioMixSpec(BaseModel):
    duration_ms: int = Field(gt=0)
    target_lufs: float = Field(-14.0, ge=-30.0, le=-5.0)
    true_peak_dbtp: float = Field(-1.0, ge=-6.0, le=0.0)
    cues: list[AudioCueSpec] = Field(default_factory=list)
    bus_gains_db: dict[TrackKind, float] = Field(default_factory=dict)


class MusicProfile(BaseModel):
    asset_id: str
    bpm: float | None = Field(None, gt=0, le=400)
    musical_key: str | None = None
    mood: list[str] = Field(default_factory=list)
    instrumentation: list[str] = Field(default_factory=list)
    energy_curve: list[tuple[float, float]] = Field(default_factory=list)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    rights: dict[str, Any] = Field(default_factory=dict)


class MusicBrief(BaseModel):
    moods: list[str] = Field(default_factory=list)
    intensity: float = Field(0.5, ge=0.0, le=1.0)
    bpm_min: float | None = Field(None, gt=0)
    bpm_max: float | None = Field(None, gt=0)
    instrumentation: list[str] = Field(default_factory=list)
    require_commercial_rights: bool = True


class LipSyncSegmentSpec(BaseModel):
    speaker_element_id: str | None = None
    face_track_id: str | None = None
    audio_asset_id: str
    script_line_id: str | None = None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    source_in_ms: int = Field(0, ge=0)
    source_out_ms: int | None = Field(None, gt=0)

    @model_validator(mode="after")
    def valid_segment(self) -> LipSyncSegmentSpec:
        if self.end_ms <= self.start_ms:
            raise ValueError("lip-sync segment end_ms must be after start_ms")
        if not self.speaker_element_id and not self.face_track_id:
            raise ValueError("lip-sync segment requires a speaker or an explicit face track")
        return self


class LipSyncMetrics(BaseModel):
    av_sync: float = Field(ge=0.0, le=1.0)
    identity: float = Field(ge=0.0, le=1.0)
    temporal_stability: float = Field(ge=0.0, le=1.0)
    mouth_quality: float = Field(ge=0.0, le=1.0)
    speaker_accuracy: float = Field(1.0, ge=0.0, le=1.0)
    max_offset_ms: float = Field(ge=0.0)


class QualityDecision(BaseModel):
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    retry_strategy: str | None = None


class AnnotationSpec(BaseModel):
    asset_id: str
    kind: str
    body: str = ""
    time_ms: int | None = Field(None, ge=0)
    geometry: dict[str, Any] = Field(default_factory=dict)
    color: str = "#2563eb"

    @model_validator(mode="after")
    def normalized_geometry(self) -> AnnotationSpec:
        for key in ("x", "y", "width", "height"):
            value = self.geometry.get(key)
            if value is not None and not 0 <= float(value) <= 1:
                raise ValueError(f"annotation geometry.{key} must be normalized to 0..1")
        return self


class TransitionSpec(BaseModel):
    from_asset_id: str
    to_asset_id: str
    kind: Literal["cut", "crossfade", "generated"] = "generated"
    duration_ms: int = Field(1000, ge=0, le=10_000)
    model_id: str | None = None
    seed: int | None = None
    preserve_element_ids: list[str] = Field(default_factory=list)
    motion_direction: str | None = None
    prompt: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def different_sources(self) -> TransitionSpec:
        if self.from_asset_id == self.to_asset_id:
            raise ValueError("a transition requires two different assets")
        if self.kind == "cut" and self.duration_ms != 0:
            raise ValueError("a cut must have duration_ms=0")
        if self.kind != "cut" and self.duration_ms == 0:
            raise ValueError("crossfade/generated transitions require positive duration_ms")
        return self
