"""
Tests del montaje.

Se prueba el **grafo de filtros como cadena**, sin invocar ffmpeg. Es deliberado: lo
que falla en producción no es que ffmpeg esté roto, es que le pasamos un grafo mal
construido. Comprobar la cadena es rápido, no necesita el binario ni ficheros de vídeo,
y cubre exactamente la superficie donde aparecen los bugs.

Los `ClipProbe` se fabrican a mano con los formatos heterogéneos reales que devuelven
los proveedores: 4K a 30 fps, 720p a 24, y 1080p entregado como 1920x1088 por
alineación a macrobloques.
"""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import pytest

from app.assembly.ffmpeg import (
    AssemblyError,
    AssemblySpec,
    AudioTimelineClip,
    ClipsNotReadyError,
    IncompatibleClipsError,
    TargetFormat,
    TimelineClip,
    _build_command,
    _validate_timeline,
    _validate_transitions,
    resolve_target_format,
)
from app.assembly.probe import ClipProbe


@pytest.fixture(autouse=True)
def stable_ffmpeg_binary(monkeypatch):
    """Filtergraph tests must not depend on deployment credentials or PATH."""
    monkeypatch.setattr(
        "app.assembly.ffmpeg.get_settings",
        lambda: SimpleNamespace(ffmpeg_path="ffmpeg"),
    )


def make_probe(
    src: str,
    width: int,
    height: int,
    fps: float,
    duration_s: float,
    *,
    has_audio: bool = True,
) -> ClipProbe:
    return ClipProbe(
        src=src,
        width=width,
        height=height,
        fps=Fraction(fps).limit_denominator(1001),
        duration_s=duration_s,
        video_codec="h264",
        pix_fmt="yuv420p",
        has_audio=has_audio,
    )


@pytest.fixture
def heterogeneous_probes() -> list[ClipProbe]:
    return [
        make_probe("a.mp4", 3840, 2160, 30, 5.0),
        make_probe("b.mp4", 1280, 720, 24, 4.0, has_audio=False),
        make_probe("c.mp4", 1920, 1088, 30, 6.0),
    ]


@pytest.fixture
def clips() -> list[TimelineClip]:
    return [
        TimelineClip(asset_id="a1", src="a.mp4", shot_id="s1"),
        TimelineClip(
            asset_id="a2", src="b.mp4", shot_id="s2",
            transition_in="crossfade", transition_duration_s=1.0,
        ),
        TimelineClip(asset_id="a3", src="c.mp4", shot_id="s3", in_s=1.0, out_s=4.0),
    ]


# --------------------------------------------------------------------------- #
# Formato de destino                                                           #
# --------------------------------------------------------------------------- #


def test_target_never_upscales_and_picks_modal_fps(heterogeneous_probes):
    target, warnings = resolve_target_format(heterogeneous_probes)

    assert (target.width, target.height) == (1280, 720)
    assert target.fps == Fraction(30)
    assert target.rationale
    # Un aviso por clip reescalado y uno por el clip remuestreado de 24 a 30.
    assert len(warnings) == 3


def test_macroblock_padded_1080p_is_still_16_9(heterogeneous_probes):
    """
    1920x1088 es 16:9 con relleno de macrobloque, no un aspecto nuevo.

    Sin el ajuste por tolerancia, este montaje —que es el caso normal— se rechazaría
    por una diferencia de ocho píxeles que nadie puede ver.
    """
    target, _ = resolve_target_format(heterogeneous_probes)
    assert target.aspect == Fraction(16, 9)


def test_mixed_orientation_fails_with_actionable_message():
    probes = [
        make_probe("h.mp4", 1920, 1080, 30, 3.0),
        make_probe("v.mp4", 1080, 1920, 30, 3.0),
    ]
    with pytest.raises(IncompatibleClipsError) as exc:
        resolve_target_format(probes)

    message = str(exc.value)
    assert "aspect ratios" in message
    # El error debe enumerar las salidas: es lo que permite al agente autocorregirse.
    assert "allow_letterbox" in message
    assert "regenerate" in message


def test_mixed_orientation_allowed_explicitly():
    probes = [
        make_probe("h.mp4", 1920, 1080, 30, 3.0),
        make_probe("v.mp4", 1080, 1920, 30, 3.0),
    ]
    target, _ = resolve_target_format(probes, allow_letterbox=True)
    assert target.width % 2 == 0 and target.height % 2 == 0


def test_odd_override_is_rejected(heterogeneous_probes):
    with pytest.raises(AssemblyError, match="even"):
        resolve_target_format(
            heterogeneous_probes, override=TargetFormat(1281, 721, Fraction(30))
        )


# --------------------------------------------------------------------------- #
# Grafo de filtros                                                             #
# --------------------------------------------------------------------------- #


def test_filter_graph_normalises_every_clip(clips, heterogeneous_probes):
    target, _ = resolve_target_format(heterogeneous_probes)
    spec = AssemblySpec(clips=clips, output_path="/tmp/out.mp4")
    args, _ = _build_command(spec, clips, heterogeneous_probes, target)
    graph = args[args.index("-filter_complex") + 1]

    for i in range(len(clips)):
        assert f"[{i}:v]" in graph
        assert f"[v{i}]" in graph
    # Cada clip pasa por escalado, relleno y corrección de SAR, sin excepción.
    assert graph.count("setsar=1") == len(clips)
    assert graph.count("scale=1280:720:force_original_aspect_ratio=decrease") == len(clips)


def test_crossfade_offset_and_total_duration(clips, heterogeneous_probes):
    """
    El encadenado solapa: la duración total es la suma menos el solape.

    5 + 4 - 1 (crossfade) + 3 (recortado de 1s a 4s) = 11 s.
    """
    target, _ = resolve_target_format(heterogeneous_probes)
    spec = AssemblySpec(clips=clips, output_path="/tmp/out.mp4")
    args, duration = _build_command(spec, clips, heterogeneous_probes, target)
    graph = args[args.index("-filter_complex") + 1]

    assert duration == pytest.approx(11.0)
    # El offset se mide desde el inicio de la cadena acumulada: 5 - 1 = 4.
    assert "xfade=transition=fade:duration=1.000:offset=4.000" in graph
    assert "concat=n=2:v=1:a=0" in graph


def test_silent_clip_gets_silence_not_a_skipped_stream(clips, heterogeneous_probes):
    """
    El clip sin audio debe recibir silencio de su duración exacta.

    Si `concat` se saltara el clip mudo, todo el audio posterior se adelantaría: el
    corte se vería sincronizado hasta ese plano y desincronizado a partir de ahí.
    """
    target, _ = resolve_target_format(heterogeneous_probes)
    spec = AssemblySpec(clips=clips, output_path="/tmp/out.mp4")
    args, _ = _build_command(spec, clips, heterogeneous_probes, target)
    graph = args[args.index("-filter_complex") + 1]

    assert "anullsrc" in graph
    assert "atrim=0:4.000" in graph  # exactamente la duración del clip mudo
    assert "[a1]" in graph


def test_subtitle_path_is_escaped_for_the_filter_graph(clips, heterogeneous_probes):
    """Una ruta Windows lleva `\\` y `:`, que son separadores dentro del grafo."""
    target, _ = resolve_target_format(heterogeneous_probes)
    spec = AssemblySpec(
        clips=clips, output_path="/tmp/out.mp4", subtitles_path=r"C:\subs\a.srt"
    )
    args, _ = _build_command(spec, clips, heterogeneous_probes, target)
    graph = args[args.index("-filter_complex") + 1]

    assert r"subtitles='C\:/subs/a.srt'" in graph
    assert args[args.index("-map") + 1] == "[vsub]"


def test_external_audio_track_replaces_clip_audio(clips, heterogeneous_probes):
    target, _ = resolve_target_format(heterogeneous_probes)
    spec = AssemblySpec(
        clips=clips, output_path="/tmp/out.mp4", audio_track="music.wav", audio_fade_out_s=2.0
    )
    args, _ = _build_command(spec, clips, heterogeneous_probes, target)
    graph = args[args.index("-filter_complex") + 1]

    assert "music.wav" in args
    assert "afade=t=out" in graph
    assert "acrossfade" not in graph  # el audio de los clips no se usa
    assert "[aout]" in graph


def test_multitrack_audio_places_cues_and_mixes_native_sound(clips, heterogeneous_probes):
    target, _ = resolve_target_format(heterogeneous_probes)
    spec = AssemblySpec(
        clips=clips,
        output_path="/tmp/out.mp4",
        audio_cues=[
            AudioTimelineClip(
                asset_id="dialogue",
                src="dialogue.wav",
                track_kind="dialogue",
                start_s=1.25,
                end_s=4.25,
                gain_db=-2,
                fade_in_s=0.1,
                fade_out_s=0.2,
            ),
            AudioTimelineClip(
                asset_id="music",
                src="music.wav",
                track_kind="music",
                start_s=0,
                end_s=11,
                gain_db=-14,
                loop=True,
                ducking_group="dialogue",
                ducking_db=-12,
            ),
        ],
    )
    args, duration = _build_command(spec, clips, heterogeneous_probes, target)
    graph = args[args.index("-filter_complex") + 1]

    assert duration == pytest.approx(11.0)
    assert "dialogue.wav" in args and "music.wav" in args
    assert "adelay=1250|1250" in graph
    assert "volume=-14dB" in graph
    assert "sidechaincompress" in graph
    assert "amix=inputs=3" in graph  # native cut + dialogue + score
    assert "loudnorm=I=-14:TP=-1" in graph
    assert "-stream_loop" in args


def test_multitrack_audio_rejects_cue_past_cut(clips, heterogeneous_probes):
    target, _ = resolve_target_format(heterogeneous_probes)
    spec = AssemblySpec(
        clips=clips,
        output_path="/tmp/out.mp4",
        audio_cues=[
            AudioTimelineClip(
                asset_id="late",
                src="late.wav",
                track_kind="sfx",
                start_s=10,
                end_s=12,
            )
        ],
    )
    with pytest.raises(AssemblyError, match="invalid range"):
        _build_command(spec, clips, heterogeneous_probes, target)


def test_single_clip_timeline_needs_no_chaining(heterogeneous_probes):
    solo = [TimelineClip(asset_id="a1", src="a.mp4", shot_id="s1")]
    target, _ = resolve_target_format(heterogeneous_probes[:1])
    args, duration = _build_command(
        AssemblySpec(clips=solo, output_path="/tmp/out.mp4"), solo, heterogeneous_probes[:1], target
    )

    assert duration == pytest.approx(5.0)
    assert args[args.index("-map") + 1] == "[v0]"


def test_output_is_web_playable(clips, heterogeneous_probes):
    target, _ = resolve_target_format(heterogeneous_probes)
    args, _ = _build_command(
        AssemblySpec(clips=clips, output_path="/tmp/out.mp4"), clips, heterogeneous_probes, target
    )

    assert "yuv420p" in args          # sin esto no se ve en Safari ni en redes sociales
    assert "+faststart" in args       # sin esto no arranca hasta descargar entero
    assert args[-1] == "/tmp/out.mp4"


# --------------------------------------------------------------------------- #
# Validación                                                                   #
# --------------------------------------------------------------------------- #


def test_not_ready_shots_are_named_in_the_error():
    spec = AssemblySpec(
        clips=[
            TimelineClip("a1", "a.mp4", shot_id="s1"),
            TimelineClip("a2", "b.mp4", shot_id="s2", status="generating"),
            TimelineClip("a3", "c.mp4", shot_id="s3", status="failed"),
        ],
        output_path="/tmp/out.mp4",
    )
    with pytest.raises(ClipsNotReadyError) as exc:
        _validate_timeline(spec)

    # El agente necesita saber cuáles, no cuántos.
    assert exc.value.shot_ids == ["s2", "s3"]


def test_empty_timeline_is_rejected():
    with pytest.raises(AssemblyError, match="empty timeline"):
        _validate_timeline(AssemblySpec(clips=[], output_path="/tmp/out.mp4"))


def test_crossfade_longer_than_its_shots_is_rejected(heterogeneous_probes):
    clips = [
        TimelineClip("a1", "a.mp4", shot_id="s1"),
        TimelineClip(
            "a2", "b.mp4", shot_id="s2", transition_in="crossfade", transition_duration_s=9.0
        ),
    ]
    with pytest.raises(AssemblyError) as exc:
        _validate_transitions(clips, heterogeneous_probes[:2])

    message = str(exc.value)
    assert "4.00s" in message   # la duración del plano más corto
    assert "hard cut" in message  # y la salida alternativa


def test_out_point_beyond_the_delivered_clip_is_rejected(heterogeneous_probes):
    """
    Los proveedores entregan clips algo más cortos de lo pedido, y el timeline suele
    asumir la duración solicitada. Es un desajuste rutinario y debe decirlo claramente.
    """
    clips = [TimelineClip("a1", "a.mp4", shot_id="s1", out_s=99.0)]
    with pytest.raises(AssemblyError, match="only lasts"):
        _build_command(
            AssemblySpec(clips=clips, output_path="/tmp/o.mp4"),
            clips,
            heterogeneous_probes[:1],
            TargetFormat(1280, 720, Fraction(30)),
        )
