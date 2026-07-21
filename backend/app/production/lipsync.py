"""Quality gate for lip-sync outputs.

The actual metrics may come from SyncNet, face embeddings and temporal detectors.  The
policy lives here so all providers are judged by the same delivery standard.
"""

from __future__ import annotations

from app.production.types import LipSyncMetrics, QualityDecision


def evaluate_lipsync(metrics: LipSyncMetrics) -> QualityDecision:
    weights = {
        "av_sync": 0.35,
        "identity": 0.25,
        "temporal_stability": 0.15,
        "mouth_quality": 0.15,
        "speaker_accuracy": 0.10,
    }
    score = sum(getattr(metrics, name) * weight for name, weight in weights.items())
    issues: list[str] = []
    retry: str | None = None

    if metrics.av_sync < 0.88 or metrics.max_offset_ms > 80:
        issues.append("audio and mouth movement are not tightly synchronized")
        retry = "retry_with_tighter_audio_segment"
    if metrics.identity < 0.90:
        issues.append("facial identity drifted from the source character")
        retry = retry or "retry_with_identity_preservation"
    if metrics.temporal_stability < 0.86:
        issues.append("face flicker or temporal instability was detected")
        retry = retry or "retry_with_premium_model"
    if metrics.mouth_quality < 0.86:
        issues.append("mouth or teeth artifacts were detected")
        retry = retry or "retry_with_premium_model"
    if metrics.speaker_accuracy < 0.98:
        issues.append("speech was assigned to the wrong visible speaker")
        retry = "request_face_mapping"

    passed = score >= 0.89 and not issues
    return QualityDecision(
        passed=passed,
        score=round(score, 6),
        issues=issues,
        retry_strategy=None if passed else retry,
    )
