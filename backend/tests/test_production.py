from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.artifacts.manager import get_handler_for_kind
from app.artifacts.types import AudioPlanArtifactContent, ScreenplayArtifactContent
from app.production.audio import rank_music_candidates, validate_audio_plan
from app.production.lipsync import evaluate_lipsync
from app.production.transitions import transition_signature
from app.production.types import (
    AnnotationSpec,
    AudioCueSpec,
    AudioMixSpec,
    DialogueLineSpec,
    LipSyncMetrics,
    LipSyncSegmentSpec,
    MusicBrief,
    MusicProfile,
    TrackKind,
    TransitionSpec,
)


def test_new_artifact_kinds_are_registered() -> None:
    screenplay = get_handler_for_kind("screenplay")
    audio = get_handler_for_kind("audio_plan")
    assert screenplay is not None and screenplay.content_class is ScreenplayArtifactContent
    assert audio is not None and audio.content_class is AudioPlanArtifactContent


def test_dialogue_requires_a_speaker_but_voiceover_does_not() -> None:
    with pytest.raises(ValidationError, match="speaker_element_id"):
        DialogueLineSpec(scene_id="scene", position=0, text="Hola")

    line = DialogueLineSpec(
        scene_id="scene", position=0, line_type="voiceover", text="Hola"
    )
    assert line.speaker_element_id is None


def test_audio_cue_rejects_impossible_fades() -> None:
    with pytest.raises(ValidationError, match="fades"):
        AudioCueSpec(
            asset_id="music",
            track_kind=TrackKind.MUSIC,
            start_ms=0,
            end_ms=1000,
            fade_in_ms=700,
            fade_out_ms=700,
        )


def test_audio_plan_reports_out_of_bounds_and_short_source() -> None:
    spec = AudioMixSpec(
        duration_ms=5000,
        cues=[
            AudioCueSpec(
                id="score",
                asset_id="music",
                track_kind=TrackKind.MUSIC,
                start_ms=1000,
                end_ms=6000,
                source_in_ms=0,
                source_out_ms=2000,
            )
        ],
    )
    errors = validate_audio_plan(spec)
    assert any("after the cut" in error for error in errors)
    assert any("looping is disabled" in error for error in errors)


def test_music_ranking_filters_rights_and_is_explainable() -> None:
    brief = MusicBrief(moods=["tense"], intensity=0.8, bpm_min=100, bpm_max=130)
    profiles = [
        MusicProfile(
            asset_id="licensed",
            bpm=120,
            mood=["tense", "cinematic"],
            energy_curve=[(0.0, 0.7), (1.0, 0.9)],
            rights={"commercial": True},
        ),
        MusicProfile(
            asset_id="personal-only",
            bpm=120,
            mood=["tense"],
            rights={"commercial": False},
        ),
    ]
    ranked = rank_music_candidates(brief, profiles)
    assert [item.asset_id for item in ranked] == ["licensed"]
    assert ranked[0].score >= 0.8
    assert ranked[0].reasons


def test_lipsync_gate_accepts_delivery_quality() -> None:
    result = evaluate_lipsync(
        LipSyncMetrics(
            av_sync=0.96,
            identity=0.97,
            temporal_stability=0.94,
            mouth_quality=0.93,
            speaker_accuracy=1.0,
            max_offset_ms=32,
        )
    )
    assert result.passed
    assert result.retry_strategy is None


def test_lipsync_gate_routes_wrong_speaker_to_manual_mapping() -> None:
    result = evaluate_lipsync(
        LipSyncMetrics(
            av_sync=0.95,
            identity=0.96,
            temporal_stability=0.95,
            mouth_quality=0.95,
            speaker_accuracy=0.5,
            max_offset_ms=20,
        )
    )
    assert not result.passed
    assert result.retry_strategy == "request_face_mapping"


def test_lipsync_segment_requires_face_or_speaker_mapping() -> None:
    with pytest.raises(ValidationError, match="speaker or an explicit face track"):
        LipSyncSegmentSpec(audio_asset_id="audio", start_ms=0, end_ms=1000)


def test_transition_signature_is_stable_and_sensitive_to_inputs() -> None:
    a = TransitionSpec(
        from_asset_id="a",
        to_asset_id="b",
        model_id="model",
        preserve_element_ids=["z", "a"],
        parameters={"strength": 0.5},
    )
    b = a.model_copy(update={"preserve_element_ids": ["a", "z"]})
    c = a.model_copy(update={"duration_ms": 2000})
    assert transition_signature(a) == transition_signature(b)
    assert transition_signature(a) != transition_signature(c)


def test_annotation_geometry_is_normalized() -> None:
    AnnotationSpec(asset_id="a", kind="region", geometry={"x": 0.2, "width": 0.5})
    with pytest.raises(ValidationError, match="normalized"):
        AnnotationSpec(asset_id="a", kind="region", geometry={"x": 20})
