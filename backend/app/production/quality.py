"""Deterministic media inspection used by production quality gates."""

from __future__ import annotations

from typing import Any

from app.assembly.probe import _run_ffprobe


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def inspect_media(url: str, kind: str) -> dict[str, Any]:
    """Inspect an internal signed media URL without trusting provider metadata."""
    raw = await _run_ffprobe(url, timeout_s=30)
    streams = list(raw.get("streams") or [])
    fmt = dict(raw.get("format") or {})
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    duration = _float(fmt.get("duration")) or _float((video or audio or {}).get("duration"))
    issues: list[dict[str, Any]] = []
    normalized = kind.lower()
    is_image = normalized in {"image", "images", "imagen", "imágenes"}
    if normalized in {"video", "cut", "vídeos"} and not video:
        issues.append({"code": "missing_video_stream", "message": "No video stream found."})
    if is_image and not video:
        issues.append({"code": "unreadable_image", "message": "No decodable image stream found."})
    if normalized in {"audio"} and not audio:
        issues.append({"code": "missing_audio_stream", "message": "No audio stream found."})
    if not is_image and (duration is None or duration <= 0):
        issues.append({"code": "invalid_duration", "message": "Media duration is unavailable or zero."})
    metrics = {
        "duration_s": duration,
        "format": fmt.get("format_name"),
        "size_bytes": int(fmt.get("size") or 0),
        "video": ({"width": int(video.get("width") or 0),
                   "height": int(video.get("height") or 0),
                   "codec": video.get("codec_name"), "pixel_format": video.get("pix_fmt"),
                   "fps": video.get("avg_frame_rate") or video.get("r_frame_rate")} if video else None),
        "audio": ({"codec": audio.get("codec_name"),
                   "sample_rate": int(audio.get("sample_rate") or 0),
                   "channels": int(audio.get("channels") or 0)} if audio else None),
    }
    return {"passed": not issues, "score": 1.0 if not issues else 0.0,
            "metrics": metrics, "issues": issues}
