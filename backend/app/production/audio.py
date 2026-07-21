"""Deterministic audio planning primitives."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from app.production.types import AudioMixSpec, MusicBrief, MusicProfile


def validate_audio_plan(spec: AudioMixSpec) -> list[str]:
    """Return actionable errors without mutating or silently clipping the plan."""

    errors: list[str] = []
    for index, cue in enumerate(spec.cues):
        label = cue.id or f"cue-{index + 1}"
        if cue.end_ms > spec.duration_ms:
            errors.append(
                f"{label} ends at {cue.end_ms}ms, after the cut ends at {spec.duration_ms}ms"
            )
        source_length = (
            cue.source_out_ms - cue.source_in_ms if cue.source_out_ms is not None else None
        )
        timeline_length = cue.end_ms - cue.start_ms
        if source_length is not None and source_length < timeline_length and not cue.loop:
            errors.append(
                f"{label} needs {timeline_length}ms but its source range is only "
                f"{source_length}ms and looping is disabled"
            )

    # Two dialogue cues may overlap only if the author explicitly keeps both unlocked;
    # flagging rather than forbidding supports natural interruptions while making them
    # visible before a costly render.
    dialogue = sorted(
        (c for c in spec.cues if c.track_kind.value in {"dialogue", "voiceover"}),
        key=lambda cue: cue.start_ms,
    )
    for left, right in pairwise(dialogue):
        if right.start_ms < left.end_ms and (left.locked or right.locked):
            errors.append(
                f"approved dialogue cues overlap between {right.start_ms}ms and "
                f"{min(left.end_ms, right.end_ms)}ms"
            )
    return errors


@dataclass(frozen=True, slots=True)
class RankedMusic:
    asset_id: str
    score: float
    reasons: tuple[str, ...]


def rank_music_candidates(brief: MusicBrief, profiles: list[MusicProfile]) -> list[RankedMusic]:
    """Explainable library matching; the LLM chooses among ranked, licensed options."""

    wanted_moods = {value.casefold() for value in brief.moods}
    wanted_instruments = {value.casefold() for value in brief.instrumentation}
    ranked: list[RankedMusic] = []

    for profile in profiles:
        if brief.require_commercial_rights and not profile.rights.get("commercial", False):
            continue
        score = 0.0
        reasons: list[str] = []
        moods = {value.casefold() for value in profile.mood}
        instruments = {value.casefold() for value in profile.instrumentation}
        if wanted_moods:
            overlap = len(wanted_moods & moods) / len(wanted_moods)
            score += overlap * 0.45
            if overlap:
                reasons.append(f"mood match {overlap:.0%}")
        if wanted_instruments:
            overlap = len(wanted_instruments & instruments) / len(wanted_instruments)
            score += overlap * 0.2
            if overlap:
                reasons.append(f"instrument match {overlap:.0%}")
        if profile.bpm is not None:
            bpm_ok = (brief.bpm_min is None or profile.bpm >= brief.bpm_min) and (
                brief.bpm_max is None or profile.bpm <= brief.bpm_max
            )
            if bpm_ok:
                score += 0.15
                reasons.append(f"tempo {profile.bpm:g} BPM")
        if profile.energy_curve:
            average = sum(point[1] for point in profile.energy_curve) / len(profile.energy_curve)
            energy_fit = max(0.0, 1.0 - abs(average - brief.intensity))
            score += energy_fit * 0.2
            reasons.append(f"energy fit {energy_fit:.0%}")
        ranked.append(RankedMusic(profile.asset_id, round(score, 6), tuple(reasons)))

    return sorted(ranked, key=lambda item: (-item.score, item.asset_id))
