"""
Montaje final con ffmpeg.

Entrada: el timeline en orden narrativo con los assets `ready`.
Salida: un asset de tipo `cut`, que es un artefacto más — versionado y regenerable.

Por qué ffmpeg y no un motor de composición: los clips **ya vienen renderizados**. El
trabajo que queda es concatenar, encadenar transiciones, pegar audio y quemar
subtítulos. Un motor de composición añadiría un runtime que mantener a cambio de nada.

Lo que sí es difícil, y ocupa la mayor parte de este fichero, es la **normalización**.
Los clips llegan de proveedores distintos y llegan heterogéneos: 720p / 1080p / 4K,
24 / 25 / 30 fps, píxeles no cuadrados, con y sin pista de audio. Concatenar streams
que no comparten formato produce, según el filtro, un error críptico de ffmpeg o —peor—
un fichero que se genera sin quejarse y se ve mal. Por eso aquí:

1. Se sondea cada clip con ffprobe (`probe.py`): nunca se asume el formato.
2. Se decide un formato de destino explícito y se justifica (`resolve_target_format`).
3. Se escala, se rellena y se remuestrea **cada** clip a ese destino antes de pegarlo.
4. Lo que no se puede resolver sin inventar imagen, falla con un mensaje que dice qué
   clip, qué formato tenía y qué hacer.

Ese punto 4 es deliberado. El fallo caro no es el montaje que revienta, es el montaje
que sale torcido y nadie mira hasta que el cliente lo ve.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import uuid
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Literal, Sequence

import structlog

from app.assembly.probe import ClipProbe, probe_clips
from app.config import get_settings
from app.tools.errors import XframeToolFatalError, XframeToolRetryableError

logger = structlog.get_logger(__name__)

Transition = Literal["cut", "crossfade"]

#: Un montaje largo en 4K es minutos de CPU. Por encima de esto no está trabajando,
#: está atascado (una URL que no cierra, un filtro que espera un stream que no llega).
DEFAULT_ASSEMBLY_TIMEOUT_S = 1800.0

#: Duración por defecto de un encadenado. Por debajo de ~0.3 s no se lee como
#: transición sino como un fallo de reproducción.
DEFAULT_CROSSFADE_S = 0.5

#: yuv420p exige dimensiones pares; si no, libx264 falla al final del render, después
#: de haber gastado todo el tiempo de codificación.
_DIMENSION_ALIGNMENT = 2

#: Resoluciones de destino admitidas al normalizar hacia abajo.
_STANDARD_HEIGHTS = (480, 720, 1080, 1440, 2160)

#: Aspectos de entrega habituales. Un clip que cae cerca de uno de estos **es** ese
#: aspecto: 1920x1088 es 16:9 con relleno de macrobloque, no un formato nuevo.
_STANDARD_ASPECTS = (
    Fraction(21, 9), Fraction(16, 9), Fraction(4, 3), Fraction(5, 4),
    Fraction(1, 1), Fraction(4, 5), Fraction(3, 4), Fraction(9, 16),
)

#: Tolerancia relativa al comparar aspectos. El 2% cubre el relleno a múltiplos de 16
#: (1088 frente a 1080 es un 0.7%) sin llegar a confundir 16:9 con 4:3 (33%).
_ASPECT_TOLERANCE = 0.02


# --------------------------------------------------------------------------- #
# Errores                                                                      #
# --------------------------------------------------------------------------- #


class AssemblyError(XframeToolFatalError):
    """
    El montaje no se puede realizar tal y como está pedido. Fatal: reintentar el mismo
    montaje con el mismo timeline vuelve a fallar. Lo que cambia el resultado es
    cambiar el timeline o regenerar un plano.
    """


class ClipsNotReadyError(AssemblyError):
    """
    Se ha pedido montar con planos que todavía no tienen asset utilizable.

    Se nombran los planos concretos porque el agente puede actuar sobre eso: esperar al
    job, regenerar, o quitarlos del corte. "El montaje falló" no es accionable.
    """

    def __init__(self, shot_ids: Sequence[str]):
        self.shot_ids = list(shot_ids)
        super().__init__(
            f"Cannot assemble: {len(self.shot_ids)} shot(s) are not ready — "
            f"{', '.join(self.shot_ids)}. Wait for their generation jobs to finish, "
            f"regenerate them, or exclude them from the cut before assembling again."
        )


class IncompatibleClipsError(XframeToolRetryableError):
    """
    Los clips no se pueden normalizar a un formato común sin degradar el resultado.

    Retryable y no fatal: se resuelve ajustando la entrada —fijando un `TargetFormat`
    explícito, o permitiendo barras negras—, y el mensaje enumera esas salidas para que
    el modelo pueda decidir en el siguiente turno en vez de quedarse bloqueado.
    """


class FFmpegFailedError(AssemblyError):
    """
    ffmpeg terminó con error. Lleva el final del stderr, que es donde ffmpeg pone el
    diagnóstico real, y el comando completo, para poder reproducirlo a mano.
    """

    def __init__(self, returncode: int, stderr_tail: str, command: str):
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        self.command = command
        super().__init__(
            f"ffmpeg exited with code {returncode}. Last output:\n{stderr_tail}\n\n"
            f"Command was:\n{command}"
        )


# --------------------------------------------------------------------------- #
# Modelo del corte                                                             #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class TimelineClip:
    """
    Un plano del timeline, en orden narrativo.

    `transition_in` describe cómo entra este plano desde el anterior; el primer plano
    del corte ignora su transición porque no hay nada de donde encadenar. Se modela así,
    y no como transición "de salida", porque es como lo piensa un montador: la
    transición pertenece al corte que abre el plano.
    """

    asset_id: str
    src: str
    """Ruta local o URL legible por ffmpeg. Si es firmada, su TTL debe cubrir el render."""

    shot_id: str | None = None
    status: Literal["generating", "ready", "failed"] = "ready"

    #: Recorte dentro del clip. `None` = usar el clip entero.
    in_s: float | None = None
    out_s: float | None = None

    transition_in: Transition = "cut"
    transition_duration_s: float = DEFAULT_CROSSFADE_S

    @property
    def label(self) -> str:
        return self.shot_id or self.asset_id


@dataclass(slots=True, frozen=True)
class TargetFormat:
    """Formato al que se normaliza todo. Explícito para que sea auditable y fijable."""

    width: int
    height: int
    fps: Fraction

    #: Por qué se eligió. Va al artefacto y a los logs: cuando dentro de dos meses
    #: alguien pregunte por qué el corte salió a 24 fps, la respuesta está guardada.
    rationale: str = ""

    @property
    def aspect(self) -> Fraction:
        return Fraction(self.width, self.height)

    def __str__(self) -> str:
        return f"{self.width}x{self.height}@{float(self.fps):.4g}fps"


@dataclass(slots=True)
class AssemblySpec:
    """Todo lo que define un corte. Serializable: es lo que se guarda en el artefacto."""

    clips: list[TimelineClip]
    output_path: str

    #: Pista de audio única para todo el corte (música, locución, mezcla ya hecha).
    #: Si se da, sustituye al audio de los clips: mezclar ambos sin control de niveles
    #: produce una locución tapada por la música, y esa decisión no es nuestra.
    audio_track: str | None = None
    audio_fade_out_s: float = 0.0

    #: Ruta a un .srt/.ass. Se queman en la imagen, porque un `cut` es un entregable
    #: plano: no todos los reproductores de destino leen subtítulos incrustados.
    subtitles_path: str | None = None
    subtitles_style: str | None = None

    #: Formato de destino. `None` = decidirlo a partir de los clips reales.
    target: TargetFormat | None = None

    #: Permitir barras negras al mezclar aspects distintos. Por defecto no: es un fallo
    #: de planificación (planos verticales y horizontales en el mismo corte) y se debe
    #: ver como tal, no enterrarlo bajo pillarbox silencioso.
    allow_letterbox: bool = False

    include_clip_audio: bool = True
    crf: int = 18
    preset: str = "medium"

    #: Versión del artefacto `cut`. El corte es regenerable, así que se versiona igual
    #: que el guion y el timeline.
    version: int = 1

    def ready_clips(self) -> list[TimelineClip]:
        return [c for c in self.clips if c.status == "ready"]


@dataclass(slots=True)
class AssemblyResult:
    """Resultado del montaje. Es lo que se convierte en asset `cut` + artefacto."""

    output_path: str
    duration_s: float
    target: TargetFormat
    version: int

    clip_asset_ids: list[str] = field(default_factory=list)
    probes: list[ClipProbe] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    command: str = ""
    elapsed_s: float = 0.0

    def to_artifact_content(self) -> dict:
        """
        Contenido del artefacto `cut` para `artifacts.content`.

        **Referencias, nunca copias** — la regla de la sección 14 de la arquitectura.
        Se guardan los `asset_id` de los planos, así que regenerar un plano queda
        reflejado en todo lo que lo referencia sin propagar nada a mano.
        """
        return {
            "kind": "cut",
            "version": self.version,
            "duration_s": round(self.duration_s, 3),
            "format": {
                "width": self.target.width,
                "height": self.target.height,
                "fps": float(self.target.fps),
                "rationale": self.target.rationale,
            },
            "shots": [{"kind": "asset_ref", "asset_id": aid} for aid in self.clip_asset_ids],
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- #
# Normalización                                                                #
# --------------------------------------------------------------------------- #


def resolve_target_format(
    probes: Sequence[ClipProbe],
    *,
    override: TargetFormat | None = None,
    allow_letterbox: bool = False,
) -> tuple[TargetFormat, list[str]]:
    """
    Decide el formato común de destino a partir de lo que son los clips **de verdad**.

    Dos criterios, y los dos tienen la misma raíz: *no inventar información*.

    - **Resolución: la menor del lote, nunca mayor.** Escalar 720p a 4K no añade
      detalle, solo lo emborrona y multiplica el tiempo de codificación. Un corte
      mezclado se ve mejor a la resolución de su peor clip que con un plano
      escandalosamente blando entre planos nítidos.
    - **Frame rate: el más frecuente del lote.** Cualquier destino obliga a remuestrear
      los clips que no coincidan, así que se elige el que menos clips toca. Frente a
      "el mínimo", esto evita convertir un corte mayoritariamente a 30 fps en uno a
      24 fps por culpa de un solo plano.

    Devuelve el formato y la lista de avisos (clips que habrá que remuestrear). Los
    avisos se propagan hasta el artefacto: no bloquean, pero quedan escritos.
    """
    if not probes:
        raise AssemblyError("Cannot resolve a target format: no clips were provided.")

    warnings: list[str] = []

    # Se comparan aspectos **ajustados**, no exactos. Sin esto, un 1080p entregado como
    # 1920x1088 —que es lo que devuelven la mitad de los proveedores— se leería como un
    # formato distinto y bloquearía un montaje perfectamente válido.
    aspects = {_snap_aspect(p.aspect) for p in probes}
    if len(aspects) > 1 and not allow_letterbox and override is None:
        detail = ", ".join(f"{p.label} [{_snap_aspect(p.aspect)}]" for p in probes)
        raise IncompatibleClipsError(
            f"The timeline mixes {len(aspects)} different aspect ratios, which cannot be "
            f"combined without adding black bars to some shots: {detail}. "
            f"Either regenerate the odd shots at the aspect ratio of the rest, set an "
            f"explicit target format, or pass allow_letterbox=True if the black bars are "
            f"intentional."
        )

    if override is not None:
        target = _validated_override(override)
        warnings.extend(_resample_warnings(probes, target))
        return target, warnings

    # --- resolución: la del clip más pequeño, con el aspecto mayoritario ---
    #
    # La altura sale del clip más pequeño (nunca escalar hacia arriba) pero el aspecto
    # sale de la mayoría, no de ese clip: si el más pequeño es justo el que llegó con
    # relleno de macrobloque, tomar su aspecto literal produciría un destino torcido
    # como 1905 de ancho y metería a todos los demás por el escalador sin motivo.
    smallest = min(probes, key=lambda p: p.pixels)
    aspect = _modal_aspect(probes)
    height = _even(_snap_height(smallest.height))
    width = _even(int(round(height * float(aspect))))

    # --- fps: la moda; a igualdad de frecuencia, el menor (menos frames inventados) ---
    counts: dict[Fraction, int] = {}
    for p in probes:
        counts[p.fps] = counts.get(p.fps, 0) + 1
    fps = min(counts, key=lambda f: (-counts[f], f))

    resolutions = {f"{p.width}x{p.height}" for p in probes}
    rates = {f"{p.fps_float:.4g}" for p in probes}
    rationale = (
        f"clips arrived as {sorted(resolutions)} at {sorted(rates)} fps; "
        f"normalised down to the smallest resolution (never upscale) and to the most "
        f"common frame rate (fewest clips resampled)"
    )

    target = TargetFormat(width=width, height=height, fps=fps, rationale=rationale)
    warnings.extend(_resample_warnings(probes, target))

    logger.info(
        "target format resolved",
        target=str(target),
        source_resolutions=sorted(resolutions),
        source_fps=sorted(rates),
        warnings=len(warnings),
    )
    return target, warnings


def _validated_override(override: TargetFormat) -> TargetFormat:
    if override.width <= 0 or override.height <= 0:
        raise AssemblyError(f"Invalid target format {override}: dimensions must be positive.")
    if override.fps <= 0:
        raise AssemblyError(f"Invalid target format {override}: frame rate must be positive.")
    if override.width % _DIMENSION_ALIGNMENT or override.height % _DIMENSION_ALIGNMENT:
        raise AssemblyError(
            f"Invalid target format {override}: width and height must both be even, because "
            f"the yuv420p pixel format used for H.264 output cannot represent odd dimensions. "
            f"Use {_even(override.width)}x{_even(override.height)} instead."
        )
    return override


def _resample_warnings(probes: Sequence[ClipProbe], target: TargetFormat) -> list[str]:
    """Un aviso por clip que no encaja de fábrica. Informativos, no bloqueantes."""
    warnings: list[str] = []
    for p in probes:
        if (p.width, p.height) != (target.width, target.height):
            warnings.append(
                f"{p.src}: rescaled from {p.width}x{p.height} to {target.width}x{target.height}"
            )
        if p.fps != target.fps:
            warnings.append(
                f"{p.src}: frame rate converted from {p.fps_float:.4g} to {float(target.fps):.4g} "
                f"(some frames will be duplicated or dropped)"
            )
        if p.sar != 1:
            warnings.append(f"{p.src}: non-square pixels (SAR {p.sar}) corrected to square")
    return warnings


def _snap_aspect(aspect: Fraction, *, tolerance: float = _ASPECT_TOLERANCE) -> Fraction:
    """
    Ajusta un aspecto medido al estándar más cercano si cae dentro de la tolerancia.

    Es lo que convierte "1920x1088" en "16:9" en vez de en "30:17". Sin este ajuste, el
    montaje rechazaría material correcto por una diferencia de ocho píxeles que ningún
    espectador puede ver.
    """
    value = float(aspect)
    for standard in _STANDARD_ASPECTS:
        if abs(value - float(standard)) / float(standard) <= tolerance:
            return standard
    return aspect


def _modal_aspect(probes: Sequence[ClipProbe]) -> Fraction:
    """Aspecto mayoritario del lote; a igualdad, el del clip más pequeño."""
    counts: dict[Fraction, int] = {}
    for p in probes:
        snapped = _snap_aspect(p.aspect)
        counts[snapped] = counts.get(snapped, 0) + 1
    smallest_aspect = _snap_aspect(min(probes, key=lambda p: p.pixels).aspect)
    return max(counts, key=lambda a: (counts[a], a == smallest_aspect))


def _snap_height(height: int) -> int:
    """
    Ajusta a la altura estándar inmediatamente inferior o igual.

    Los proveedores devuelven cosas como 1088 o 1082 porque los códecs alinean a
    macrobloques. Sin este ajuste, un corte de clips "1080p" acabaría a 1082 de alto y
    todo pasaría por el escalador sin necesidad.
    """
    candidates = [h for h in _STANDARD_HEIGHTS if h <= height]
    return candidates[-1] if candidates else _even(height)


def _even(value: int) -> int:
    return value - (value % _DIMENSION_ALIGNMENT)


# --------------------------------------------------------------------------- #
# Montaje                                                                      #
# --------------------------------------------------------------------------- #


async def assemble_cut(
    spec: AssemblySpec,
    *,
    timeout_s: float = DEFAULT_ASSEMBLY_TIMEOUT_S,
) -> AssemblyResult:
    """
    Monta el corte y devuelve el resultado.

    Orden de operaciones, y ninguno es opcional:

    1. Validar el timeline (planos listos, transiciones que caben en su clip).
    2. Sondear los clips reales.
    3. Resolver el formato de destino.
    4. Construir el grafo de filtros y ejecutarlo.
    5. Comprobar que el fichero de salida existe y no está vacío.

    El paso 5 parece paranoia y no lo es: ffmpeg puede devolver 0 y dejar un fichero de
    0 bytes cuando el grafo de filtros no produjo ningún frame.
    """
    clips = _validate_timeline(spec)
    probes = await probe_clips([c.src for c in clips])

    target, warnings = resolve_target_format(
        probes, override=spec.target, allow_letterbox=spec.allow_letterbox
    )
    _validate_transitions(clips, probes)

    args, expected_duration = _build_command(spec, clips, probes, target)
    command = _shell_repr(args)

    Path(spec.output_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "assembly starting",
        clips=len(clips),
        target=str(target),
        expected_duration_s=round(expected_duration, 2),
        version=spec.version,
    )

    elapsed = await _run_ffmpeg(args, timeout_s=timeout_s, command=command)
    _verify_output(spec.output_path, command)

    result = AssemblyResult(
        output_path=spec.output_path,
        duration_s=expected_duration,
        target=target,
        version=spec.version,
        clip_asset_ids=[c.asset_id for c in clips],
        probes=list(probes),
        warnings=warnings,
        command=command,
        elapsed_s=elapsed,
    )

    logger.info(
        "assembly finished",
        output=spec.output_path,
        duration_s=round(result.duration_s, 2),
        elapsed_s=round(elapsed, 1),
        warnings=len(warnings),
    )
    return result


def _validate_timeline(spec: AssemblySpec) -> list[TimelineClip]:
    """Todo lo que se puede rechazar sin tocar disco se rechaza aquí."""
    if not spec.clips:
        raise AssemblyError(
            "Cannot assemble an empty timeline. Add at least one shot with a ready asset."
        )

    not_ready = [c.label for c in spec.clips if c.status != "ready"]
    if not_ready:
        raise ClipsNotReadyError(not_ready)

    clips = spec.ready_clips()

    for clip in clips:
        if clip.in_s is not None and clip.in_s < 0:
            raise AssemblyError(f"Shot '{clip.label}' has a negative in point ({clip.in_s}s).")
        if clip.in_s is not None and clip.out_s is not None and clip.out_s <= clip.in_s:
            raise AssemblyError(
                f"Shot '{clip.label}' has out point {clip.out_s}s at or before its in point "
                f"{clip.in_s}s. The out point must be strictly greater."
            )
    return clips


def _validate_transitions(clips: Sequence[TimelineClip], probes: Sequence[ClipProbe]) -> None:
    """
    Un encadenado consume tiempo de los dos planos que une. Si dura más que alguno de
    ellos, ffmpeg produce un corte con frames congelados o directamente falla con un
    error sobre timestamps que no dice nada. Mejor rechazarlo aquí y explicarlo.
    """
    for i, clip in enumerate(clips):
        if i == 0 or clip.transition_in != "crossfade":
            continue

        d = clip.transition_duration_s
        if d <= 0:
            raise AssemblyError(
                f"Shot '{clip.label}' asks for a crossfade of {d}s. "
                f"Use a positive duration, or set the transition to 'cut'."
            )

        prev_dur = _effective_duration(clips[i - 1], probes[i - 1])
        this_dur = _effective_duration(clip, probes[i])
        shortest = min(prev_dur, this_dur)
        if d >= shortest:
            raise AssemblyError(
                f"Shot '{clip.label}' asks for a {d}s crossfade, but the shortest of the two "
                f"shots it joins lasts only {shortest:.2f}s. A crossfade must be shorter than "
                f"both shots. Shorten the transition to under {shortest / 2:.2f}s, lengthen the "
                f"shots, or use a hard cut."
            )


def _effective_duration(clip: TimelineClip, probe: ClipProbe) -> float:
    """Duración real del clip tras aplicar el recorte del timeline."""
    start = clip.in_s or 0.0
    end = clip.out_s if clip.out_s is not None else probe.duration_s

    if start >= probe.duration_s:
        raise AssemblyError(
            f"Shot '{clip.label}' starts at {start:.2f}s but its clip only lasts "
            f"{probe.duration_s:.2f}s. The provider delivered a shorter clip than the timeline "
            f"assumes — adjust the in point or regenerate the shot."
        )
    if end > probe.duration_s + 1e-3:
        raise AssemblyError(
            f"Shot '{clip.label}' ends at {end:.2f}s but its clip only lasts "
            f"{probe.duration_s:.2f}s. Providers routinely deliver slightly shorter clips than "
            f"requested — adjust the out point to at most {probe.duration_s:.2f}s."
        )
    return max(0.0, min(end, probe.duration_s) - start)


# --------------------------------------------------------------------------- #
# Grafo de filtros                                                             #
# --------------------------------------------------------------------------- #


def _build_command(
    spec: AssemblySpec,
    clips: Sequence[TimelineClip],
    probes: Sequence[ClipProbe],
    target: TargetFormat,
) -> tuple[list[str], float]:
    """
    Construye la invocación completa de ffmpeg y la duración esperada del corte.

    Se usa `filter_complex` y no el demuxer `concat` porque el demuxer exige que todos
    los ficheros compartan códec, resolución y base de tiempos — exactamente lo que
    nuestros clips no comparten. El grafo de filtros normaliza y pega en un solo paso.
    """
    settings = get_settings()
    args: list[str] = [settings.ffmpeg_path, "-hide_banner", "-nostdin", "-y"]

    for clip in clips:
        args += ["-i", clip.src]

    audio_input_index: int | None = None
    if spec.audio_track:
        audio_input_index = len(clips)
        args += ["-i", spec.audio_track]

    filters: list[str] = [
        _normalise_clip_filter(i, clip, probe, target)
        for i, (clip, probe) in enumerate(zip(clips, probes, strict=True))
    ]

    chain_steps, (final_video, duration) = _walk_chain(clips, probes)
    filters.extend(chain_steps)

    # Subtítulos al final del grafo: se queman sobre la imagen ya montada y normalizada,
    # así el tamaño de letra es consistente aunque los clips vinieran a resoluciones
    # distintas. Quemarlos antes de escalar produce texto de cuerpos diferentes.
    if spec.subtitles_path:
        filters.append(f"[{final_video}]{_subtitles_filter(spec)}[vsub]")
        final_video = "vsub"

    audio_label: str | None = None
    if spec.audio_track and audio_input_index is not None:
        audio_filter = f"[{audio_input_index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
        if spec.audio_fade_out_s > 0:
            fade_start = max(0.0, duration - spec.audio_fade_out_s)
            audio_filter += f",afade=t=out:st={fade_start:.3f}:d={spec.audio_fade_out_s:.3f}"
        # `apad` + recorte a la duración del vídeo: una pista musical más corta que el
        # corte dejaría silencio sin declarar, y una más larga alargaría el fichero.
        audio_filter += f",apad,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS"
        filters.append(f"{audio_filter}[aout]")
        audio_label = "aout"
    elif spec.include_clip_audio and any(p.has_audio for p in probes):
        audio_label = _chain_audio(filters, clips, probes, target)

    args += ["-filter_complex", ";".join(filters)]
    args += ["-map", f"[{final_video}]"]
    if audio_label:
        args += ["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    else:
        args += ["-an"]

    args += [
        "-c:v", "libx264",
        "-preset", spec.preset,
        "-crf", str(spec.crf),
        # yuv420p y no algo mejor: es el único pix_fmt que reproducen todos los
        # navegadores y todas las apps sociales. Un corte que no se ve en el móvil del
        # cliente no está terminado.
        "-pix_fmt", "yuv420p",
        "-r", f"{target.fps.numerator}/{target.fps.denominator}",
        "-movflags", "+faststart",
        spec.output_path,
    ]
    return args, duration


def _normalise_clip_filter(
    index: int, clip: TimelineClip, probe: ClipProbe, target: TargetFormat
) -> str:
    """
    Lleva un clip cualquiera al formato de destino. El orden de los filtros importa:

    1. `trim` + `setpts`: recorta y reinicia los timestamps a cero. Sin `setpts`, el
       clip conserva su tiempo original y aparece más tarde de lo que debe.
    2. `fps`: remuestrea antes de escalar, porque escalar frames que se van a descartar
       es tiempo de CPU tirado.
    3. `scale` con `force_original_aspect_ratio=decrease` + `pad`: encaja dentro del
       destino sin deformar. Nunca recorta contenido: preferimos barras negras a
       quedarnos sin la cara del personaje.
    4. `setsar=1`: descarta la relación de píxel de origen. Si se omite, un clip con
       píxeles no cuadrados sale estirado y el resto no.
    """
    steps: list[str] = []

    if clip.in_s is not None or clip.out_s is not None:
        start = clip.in_s or 0.0
        end = clip.out_s if clip.out_s is not None else probe.duration_s
        steps.append(f"trim=start={start:.3f}:end={end:.3f}")
    steps.append("setpts=PTS-STARTPTS")

    steps.append(f"fps={target.fps.numerator}/{target.fps.denominator}")
    steps.append(
        f"scale={target.width}:{target.height}:force_original_aspect_ratio=decrease:flags=bicubic"
    )
    steps.append(f"pad={target.width}:{target.height}:(ow-iw)/2:(oh-ih)/2:color=black")
    steps.append("setsar=1")
    steps.append("format=yuv420p")

    return f"[{index}:v]{','.join(steps)}[v{index}]"


def _walk_chain(
    clips: Sequence[TimelineClip], probes: Sequence[ClipProbe]
) -> tuple[list[str], tuple[str, float]]:
    """
    Recorre el timeline acumulando el corte de izquierda a derecha.

    Se construye por pares y no con un único `concat=n=N` porque un corte real mezcla
    cortes secos y encadenados, y `xfade` solo opera sobre dos entradas. Tratar ambos
    casos con la misma acumulación evita tener dos rutas de código que se desincronizan
    (que es como se cuelan los desfases de audio).
    """
    steps: list[str] = []
    acc_label = "v0"
    acc_duration = _effective_duration(clips[0], probes[0])

    for i in range(1, len(clips)):
        clip = clips[i]
        clip_duration = _effective_duration(clip, probes[i])
        out_label = f"vx{i}"

        if clip.transition_in == "crossfade":
            d = clip.transition_duration_s
            # `offset` se mide desde el inicio de la cadena acumulada, no del clip.
            offset = acc_duration - d
            steps.append(
                f"[{acc_label}][v{i}]xfade=transition=fade:duration={d:.3f}:"
                f"offset={offset:.3f}[{out_label}]"
            )
            acc_duration = acc_duration + clip_duration - d
        else:
            steps.append(f"[{acc_label}][v{i}]concat=n=2:v=1:a=0[{out_label}]")
            acc_duration = acc_duration + clip_duration

        acc_label = out_label

    return steps, (acc_label, acc_duration)


def _chain_audio(
    filters: list[str],
    clips: Sequence[TimelineClip],
    probes: Sequence[ClipProbe],
    target: TargetFormat,
) -> str:
    """
    Monta el audio de los propios clips siguiendo las mismas transiciones que el vídeo.

    Los clips que llegan mudos se rellenan con silencio de su duración exacta. Sin eso,
    `concat` de audio salta el clip mudo y **todo el audio posterior se adelanta**: el
    corte se ve sincronizado hasta el primer plano sin pista y desincronizado a partir
    de ahí. Es el fallo más difícil de diagnosticar de todo el montaje.
    """
    for i, (clip, probe) in enumerate(zip(clips, probes, strict=True)):
        duration = _effective_duration(clip, probe)
        if probe.has_audio:
            steps = []
            if clip.in_s is not None or clip.out_s is not None:
                start = clip.in_s or 0.0
                end = clip.out_s if clip.out_s is not None else probe.duration_s
                steps.append(f"atrim=start={start:.3f}:end={end:.3f}")
            steps += [
                "asetpts=PTS-STARTPTS",
                "aresample=48000",
                "aformat=sample_fmts=fltp:channel_layouts=stereo",
                # Rellenar y recortar a la duración exacta del vídeo: las pistas de
                # audio de los proveedores suelen desviarse unos milisegundos.
                f"apad,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS",
            ]
            filters.append(f"[{i}:a]{','.join(steps)}[a{i}]")
        else:
            filters.append(
                f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[a{i}]"
            )

    acc = "a0"
    for i in range(1, len(clips)):
        clip = clips[i]
        out = f"ax{i}"
        if clip.transition_in == "crossfade":
            filters.append(
                f"[{acc}][a{i}]acrossfade=d={clip.transition_duration_s:.3f}:c1=tri:c2=tri[{out}]"
            )
        else:
            filters.append(f"[{acc}][a{i}]concat=n=2:v=0:a=1[{out}]")
        acc = out

    del target  # el audio no depende del formato de vídeo; se acepta por simetría
    return acc


def _subtitles_filter(spec: AssemblySpec) -> str:
    """
    Filtro `subtitles`, con el escapado que exige ffmpeg.

    El escapado no es opcional ni cosmético: la ruta viaja dentro de la cadena de
    `filter_complex`, donde `:`, `\\` y `'` son separadores. En Windows, cualquier ruta
    absoluta (`C:\\Users\\…`) contiene los tres, así que sin esto los subtítulos fallan
    exactamente en las máquinas de desarrollo del equipo.
    """
    path = str(spec.subtitles_path)
    escaped = path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    parts = [f"subtitles='{escaped}'"]
    if spec.subtitles_style:
        style = spec.subtitles_style.replace("'", r"\'")
        parts.append(f"force_style='{style}'")
    return ":".join(parts)


# --------------------------------------------------------------------------- #
# Ejecución                                                                    #
# --------------------------------------------------------------------------- #


async def _run_ffmpeg(args: list[str], *, timeout_s: float, command: str) -> float:
    """
    Ejecuta ffmpeg como subproceso async, con timeout y captura de stderr.

    Detalles que importan:

    - `-nostdin` (puesto al construir el comando): sin él, ffmpeg puede quedarse
      esperando entrada del terminal y colgar el worker indefinidamente.
    - stderr se captura entero pero solo se propaga la cola: ffmpeg escribe una línea
      de progreso por segundo, y meter eso en un mensaje de herramienta reventaría el
      contexto del agente. El diagnóstico está siempre en las últimas líneas.
    - Al vencer el timeout se mata el proceso y se espera: sin el `wait`, queda un
      zombi que sigue ocupando CPU mientras el worker atiende el siguiente job.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AssemblyError(
            f"ffmpeg binary not found ({exc}). Set FFMPEG_PATH or install ffmpeg in the image."
        ) from exc

    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise AssemblyError(
            f"ffmpeg timed out after {timeout_s:.0f}s and was killed. The cut is probably too "
            f"long or too large for a single pass, or one of the source URLs stopped responding. "
            f"Command was:\n{command}"
        ) from None

    elapsed = loop.time() - started
    text = stderr.decode("utf-8", "replace")

    if proc.returncode != 0:
        raise FFmpegFailedError(proc.returncode or -1, _tail(text), command)

    return elapsed


def _verify_output(path: str, command: str) -> None:
    """
    ffmpeg puede salir con código 0 y dejar un fichero vacío cuando el grafo de filtros
    no produjo ningún frame. Un `cut` de 0 bytes que se sube a storage y se marca
    `ready` es peor que un fallo, porque nadie se entera hasta que alguien le da al play.
    """
    if not os.path.exists(path):
        raise AssemblyError(
            f"ffmpeg reported success but produced no file at '{path}'. Command was:\n{command}"
        )
    if os.path.getsize(path) == 0:
        raise AssemblyError(
            f"ffmpeg reported success but produced an empty file at '{path}'. The filter graph "
            f"emitted no frames. Command was:\n{command}"
        )


def _shell_repr(args: Sequence[str]) -> str:
    """Comando reproducible a mano. Es la primera pregunta al depurar un montaje."""
    return " ".join(shlex.quote(a) for a in args)


def _tail(text: str, *, max_chars: int = 2000) -> str:
    text = text.strip()
    return text if len(text) <= max_chars else "…" + text[-max_chars:]


def default_output_path(project_id: str, version: int, *, workdir: str = "/tmp/xframe") -> str:
    """
    Ruta de trabajo para un corte. El sufijo aleatorio evita que dos regeneraciones
    concurrentes de la misma versión se pisen el fichero temporal.
    """
    return str(Path(workdir) / project_id / f"cut_v{version}_{uuid.uuid4().hex[:8]}.mp4")
