"""
Inspección de clips con ffprobe.

Por qué existe este módulo en vez de fiarnos de la petición que mandamos al proveedor:
**lo que pedimos y lo que llega no coinciden**. Casos reales y frecuentes:

- Se pide 5 s y llegan 5.12 s, porque el modelo genera en múltiplos de frames y redondea.
- Se pide 1080p y llega 1088 de alto (los códecs alinean a macrobloques de 16).
- Se pide 24 fps y el contenedor declara 24000/1001 (23.976), que no es lo mismo.
- Un clip vertical llega con matriz de rotación en vez de girado: 1920x1080 en el
  stream, 1080x1920 en pantalla.
- Un proveedor entrega el vídeo sin pista de audio y otro con una pista muda.

Cada una de esas discrepancias, sin detectar, se convierte en un desajuste de
sincronía o en un salto visible en el montaje. Y se detecta gratis: ffprobe cuesta
milisegundos y el render cuesta minutos, así que **siempre se sondea antes de montar**.

Ninguna de estas funciones decide nada: solo informan. Las decisiones de
normalización viven en `ffmpeg.resolve_target_format`.
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import structlog

from app.config import get_settings
from app.tools.errors import XframeToolFatalError

logger = structlog.get_logger(__name__)

#: Sondear un fichero es leer cabeceras. Si tarda más que esto no es un fichero lento,
#: es una URL que no responde o un contenedor corrupto.
PROBE_TIMEOUT_S = 30.0


class ProbeError(XframeToolFatalError):
    """
    El clip no se puede leer. Fatal a propósito: reintentar el sondeo de un fichero
    corrupto da el mismo resultado. Lo que hay que hacer es regenerar el plano, y para
    eso el agente necesita saber **qué** clip falló, no solo que "el montaje falló".
    """

    def __init__(self, src: str, reason: str):
        self.src = src
        super().__init__(
            f"Could not probe clip '{src}': {reason}. "
            f"This clip cannot be used in an assembly. Check whether its asset finished "
            f"rendering, and regenerate that shot if the file is truncated or corrupt."
        )


@dataclass(slots=True, frozen=True)
class ClipProbe:
    """
    Lo que ffprobe dice que es un clip. Todo medido, nada declarado.

    `width`/`height` son ya las dimensiones **en pantalla**: si el contenedor traía
    matriz de rotación, se aplica aquí. Quien consuma esto no debe volver a pensar en
    rotación, porque olvidarlo una sola vez produce un montaje con clips tumbados.
    """

    src: str

    width: int
    height: int
    fps: Fraction
    duration_s: float

    video_codec: str
    pix_fmt: str
    has_audio: bool
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None

    rotation: int = 0
    #: Sample aspect ratio. Distinto de 1 significa píxeles no cuadrados: hay que
    #: corregirlo al normalizar o el clip sale estirado.
    sar: Fraction = Fraction(1, 1)

    @property
    def fps_float(self) -> float:
        return float(self.fps)

    @property
    def aspect(self) -> Fraction:
        """Relación de aspecto en pantalla, ya con la SAR aplicada."""
        return Fraction(self.width, self.height) * self.sar

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def label(self) -> str:
        """Descripción corta para mensajes de error dirigidos al agente."""
        return f"{self.width}x{self.height}@{self.fps_float:.3g}fps ({self.duration_s:.2f}s)"


async def probe_clip(src: str, *, timeout_s: float = PROBE_TIMEOUT_S) -> ClipProbe:
    """
    Sondea un clip (ruta local o URL) y devuelve sus propiedades reales.

    Se piden streams y formato en una sola invocación: ffprobe abre el fichero una vez,
    y sobre una URL remota eso es la diferencia entre una petición HTTP y dos.
    """
    raw = await _run_ffprobe(src, timeout_s=timeout_s)

    streams: list[dict[str, Any]] = raw.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        raise ProbeError(src, "the file contains no video stream")

    rotation = _rotation_of(video)
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ProbeError(src, "the video stream declares no usable dimensions")

    # Rotación de 90/270 grados: lo que se ve está girado respecto a lo almacenado.
    if rotation % 180 == 90:
        width, height = height, width

    fps = _parse_fps(video, src)
    duration_s = _parse_duration(video, raw.get("format") or {}, src)

    probe = ClipProbe(
        src=src,
        width=width,
        height=height,
        fps=fps,
        duration_s=duration_s,
        video_codec=str(video.get("codec_name") or "unknown"),
        pix_fmt=str(video.get("pix_fmt") or "unknown"),
        has_audio=audio is not None,
        audio_codec=str(audio.get("codec_name")) if audio else None,
        audio_sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        audio_channels=int(audio["channels"]) if audio and audio.get("channels") else None,
        rotation=rotation,
        sar=_parse_ratio(video.get("sample_aspect_ratio"), default=Fraction(1, 1)),
    )

    logger.debug(
        "clip probed",
        src=src,
        resolution=f"{probe.width}x{probe.height}",
        fps=probe.fps_float,
        duration_s=probe.duration_s,
        has_audio=probe.has_audio,
    )
    return probe


async def probe_clips(
    srcs: list[str], *, timeout_s: float = PROBE_TIMEOUT_S, concurrency: int = 8
) -> list[ClipProbe]:
    """
    Sondea varios clips en paralelo, preservando el orden de entrada.

    Con límite de concurrencia porque un timeline de 40 planos abriría 40 conexiones a
    la vez contra el storage, y el que se queja entonces es el storage.

    Si falla alguno se lanza **un solo** error que los nombra todos: al agente le sirve
    mucho más "estos tres clips están rotos" que descubrirlos de uno en uno.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(src: str) -> ClipProbe | ProbeError:
        async with sem:
            try:
                return await probe_clip(src, timeout_s=timeout_s)
            except ProbeError as exc:  # se recolectan, no se propagan de inmediato
                return exc

    results = await asyncio.gather(*(_one(s) for s in srcs))

    failures = [r for r in results if isinstance(r, ProbeError)]
    if failures:
        detail = "; ".join(f"{f.src}: {f}" for f in failures)
        raise ProbeError(
            failures[0].src,
            f"{len(failures)} of {len(srcs)} clips could not be read — {detail}",
        )

    return [r for r in results if isinstance(r, ClipProbe)]


# --------------------------------------------------------------------------- #
# Interno                                                                      #
# --------------------------------------------------------------------------- #


def _ffprobe_path() -> str:
    """
    ffprobe se instala junto a ffmpeg, así que se deriva de `FFMPEG_PATH` en lugar de
    añadir otra variable de entorno que alguien olvidará poner.
    """
    ffmpeg = get_settings().ffmpeg_path
    candidate = ffmpeg[: -len("ffmpeg")] + "ffprobe" if ffmpeg.endswith("ffmpeg") else "ffprobe"
    return candidate if shutil.which(candidate) else "ffprobe"


async def _run_ffprobe(src: str, *, timeout_s: float) -> dict[str, Any]:
    """Ejecuta ffprobe y devuelve su JSON. Todo fallo se traduce a `ProbeError`."""
    args = [
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        src,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            _ffprobe_path(),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ProbeError(src, f"ffprobe binary not found ({exc})") from exc

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ProbeError(src, f"ffprobe timed out after {timeout_s:.0f}s") from None

    if proc.returncode != 0:
        raise ProbeError(src, _tail(stderr.decode("utf-8", "replace")))

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(src, f"ffprobe returned unparseable output ({exc})") from exc


def _rotation_of(video: dict[str, Any]) -> int:
    """
    Lee la rotación de donde toque: el tag `rotate` (contenedores viejos) o la
    displaymatrix de `side_data_list` (lo que usa ffmpeg moderno).
    """
    tags = video.get("tags") or {}
    if "rotate" in tags:
        try:
            return int(float(tags["rotate"])) % 360
        except (TypeError, ValueError):
            pass

    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            try:
                # La displaymatrix da la rotación con signo invertido respecto a `rotate`.
                return int(round(-float(side["rotation"]))) % 360
            except (TypeError, ValueError):
                continue
    return 0


def _parse_fps(video: dict[str, Any], src: str) -> Fraction:
    """
    Se prefiere `avg_frame_rate` sobre `r_frame_rate`: el segundo es la base de tiempos
    del contenedor y en material de VFR puede ser 1000/1, que no describe nada.
    """
    for key in ("avg_frame_rate", "r_frame_rate"):
        fps = _parse_ratio(video.get(key), default=None)
        if fps is not None and fps > 0:
            return fps
    raise ProbeError(src, "the video stream declares no usable frame rate")


def _parse_duration(video: dict[str, Any], fmt: dict[str, Any], src: str) -> float:
    """
    Duración del stream de vídeo antes que la del contenedor: si hay una pista de audio
    más larga, la del contenedor miente sobre cuánta imagen hay realmente.
    """
    for candidate in (video.get("duration"), fmt.get("duration")):
        try:
            value = float(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            return value

    # Último recurso: nº de frames / fps. Pasa con algunos WebM sin duración en cabecera.
    try:
        frames = int(video["nb_frames"])
        fps = _parse_fps(video, src)
        if frames > 0 and fps > 0:
            return frames / float(fps)
    except (KeyError, TypeError, ValueError, ProbeError):
        pass

    raise ProbeError(src, "the file declares no usable duration")


def _parse_ratio(value: Any, *, default: Fraction | None) -> Fraction | None:
    """Parsea "30000/1001" o "1:1". Un denominador 0 significa "desconocido"."""
    if not value or not isinstance(value, str):
        return default
    text = value.replace(":", "/")
    try:
        ratio = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return default
    return ratio if ratio > 0 else default


def _tail(text: str, *, max_chars: int = 600) -> str:
    """El diagnóstico útil de ffmpeg/ffprobe está siempre al final del stderr."""
    text = text.strip()
    return text if len(text) <= max_chars else "…" + text[-max_chars:]
