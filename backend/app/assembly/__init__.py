"""
Montaje final.

Los clips ya vienen renderizados de los proveedores, así que el montaje es
concatenación + transiciones + audio + subtítulos. No hace falta un motor de
composición: hace falta un normalizador fiable.

Dos módulos:

- `probe`:  qué es cada clip **de verdad** (ffprobe), no lo que dijo el proveedor.
- `ffmpeg`: cómo se pegan entre sí una vez normalizados.

El resultado es un asset de tipo `cut`, que es un artefacto más: versionado,
referenciable y regenerable desde el timeline.
"""

from app.assembly.ffmpeg import (
    AssemblyError,
    AssemblyResult,
    AssemblySpec,
    AudioTimelineClip,
    TargetFormat,
    TimelineClip,
    Transition,
    assemble_cut,
    resolve_target_format,
)
from app.assembly.probe import ClipProbe, ProbeError, probe_clip, probe_clips

__all__ = [
    "AssemblyError",
    "AssemblyResult",
    "AssemblySpec",
    "AudioTimelineClip",
    "ClipProbe",
    "ProbeError",
    "TargetFormat",
    "TimelineClip",
    "Transition",
    "assemble_cut",
    "probe_clip",
    "probe_clips",
    "resolve_target_format",
]
