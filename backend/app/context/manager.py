"""
Gestor de contexto del proyecto.

Es el equivalente de `AssistantContextManager` (`ee/hogai/context/context.py`), y hace
tres cosas separadas a propósito:

1. **Cargar** el proyecto entero de BD → `XframeUIContext`. Async, con `asyncio.gather`
   tolerante a fallos: que se caiga la consulta de assets no puede tumbar el contexto.
2. **Serializar** ese objeto a XML, con los planos en ORDEN NARRATIVO y una escalera de
   degradación de tres peldaños cuando no cabe. Esto es una función **pura**: entra un
   `XframeUIContext`, sale texto. Se puede testear sin BD y sin LLM, y ese es medio
   motivo de que esté separada de la carga.
3. **Inyectar** el resultado como mensaje de contexto ANTES del mensaje humano.

Sobre el punto 3, que es el que más se malinterpreta: el contexto **no va en el system
prompt**. Va como mensaje en la conversación, delante del humano del turno. Dos
consecuencias, ambas buscadas:

- Entra en la caché de prompt como cualquier otro mensaje, en vez de invalidar el system
  prompt entero cada vez que el usuario cambia de pestaña.
- Sobrevive a la compactación como un mensaje más, y la ventana lo puede arrastrar.

Y la deduplicación por contenido exacto: si el usuario sigue mirando lo mismo turno tras
turno, el contexto se inyecta **una sola vez**. Es deliberadamente ingenua — comparar
contenidos, no ids ni hashes semánticos — porque el fallo que evita (repetir 40k tokens
en cada turno) es enorme y el fallo que introduce (reinyectar por un cambio de un byte)
es inocuo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage

from app import db
from app.context import prompts as P
from app.context.types import (
    AssetContext,
    BriefBlock,
    CameraSpec,
    ElementContext,
    GenSettings,
    Guidance,
    KnowledgeSource,
    OpenTab,
    ProjectSkill,
    ShotContext,
    XframeUIContext,
    narrative_sort_key,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Presupuesto                                                                  #
# --------------------------------------------------------------------------- #

APPROXIMATE_TOKEN_LENGTH = 4
"""Caracteres por token. Coincide con el que usa la compactación, a propósito."""

CONTEXT_TOKEN_BUDGET = 50_000
"""
Techo del contexto adjunto, en tokens.

La justificación es la misma que la de PostHog y merece escribirse entera: si el
contexto adjunto desborda la ventana de conversación (100k), la conversación **entera**
—incluido este contexto— se resume a unos pocos miles de tokens, y el agente pierde
justo el proyecto sobre el que se le acaba de preguntar. Más vale entregar una timeline
degradada que una timeline completa que provoca su propia destrucción.
"""

CONTEXT_CHAR_BUDGET = CONTEXT_TOKEN_BUDGET * APPROXIMATE_TOKEN_LENGTH

MAX_RECENT_ASSETS = 60
"""Ventana de assets recientes. El censo total viaja aparte en `assets_total`."""

MAX_PROMPT_CHARS = 1_200
"""Corte por prompt de plano en el peldaño completo. Un prompt más largo que esto casi
siempre es un pegote, no una intención."""

SPEC_PROMPT_CHARS = 160
"""Peldaño 2: el prompt se reduce a una línea reconocible, no desaparece."""


class ContextDetail(IntEnum):
    """
    Escalera de degradación. Menor es más detalle.

    El peldaño intermedio es el que hay que diseñar bien, porque es donde vive la mayor
    parte de las sesiones reales: un proyecto de 40 planos no cabe completo casi nunca,
    pero sus specs sin prompts largos sí, y con eso el agente todavía puede planificar,
    identificar el plano que le interesa y pedir su detalle con una tool.
    """

    FULL = 0
    """Spec completa: prompt íntegro, cámara, modelo, estado y asset."""

    SPECS = 1
    """Specs sin prompts largos: el modelo sigue viendo parámetros y continuidad."""

    TITLES = 2
    """Solo títulos y estados. El último recurso antes de truncar."""


@dataclass(slots=True)
class ContextReport:
    """
    Telemetría de la degradación.

    Sin esto no hay forma de enterarse de que a los usuarios con proyectos grandes se
    les está cayendo el contexto en silencio: el agente responde, solo que peor.
    """

    detail: ContextDetail = ContextDetail.FULL
    shots_total: int = 0
    shots_shown: int = 0
    assets_total: int = 0
    assets_shown: int = 0
    brief_truncated: bool = False
    chars: int = 0
    budget_chars: int = CONTEXT_CHAR_BUDGET
    sections_dropped: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """
        ¿Se perdió algo por presupuesto?

        `assets_shown < assets_total` **no** cuenta: la lista de assets es una ventana
        por diseño (`MAX_RECENT_ASSETS`) y en un proyecto con historia siempre lo será.
        Contarlo como degradación convertiría la telemetría en ruido constante y la haría
        inservible justo para lo que existe: detectar presupuestos mal calibrados.
        """
        return (
            self.detail is not ContextDetail.FULL
            or self.shots_shown < self.shots_total
            or self.brief_truncated
            or bool(self.sections_dropped)
        )

    def emit(self, *, project_id: str, user_id: str | None = None) -> None:
        """Registra el evento solo si hubo degradación. El caso feliz no es noticia."""
        if not self.degraded:
            return
        logger.info(
            "xframe context budget exceeded",
            extra={
                "event": "xframe_context_budget_exceeded",
                "project_id": project_id,
                "user_id": user_id,
                "detail": self.detail.name.lower(),
                "shots_shown": self.shots_shown,
                "shots_total": self.shots_total,
                "assets_shown": self.assets_shown,
                "assets_total": self.assets_total,
                "brief_truncated": self.brief_truncated,
                "sections_dropped": self.sections_dropped,
                "chars": self.chars,
                "budget_chars": self.budget_chars,
            },
        )


# --------------------------------------------------------------------------- #
# Mensajes de contexto                                                         #
# --------------------------------------------------------------------------- #

CONTEXT_MESSAGE_FLAG = "xframe_context"
"""
Marca de `additional_kwargs` que distingue un mensaje de contexto de uno humano.

PostHog tiene un tipo `ContextMessage` propio. Aquí no lo creamos porque el estado ya
está fijado y porque un `HumanMessage` marcado atraviesa el checkpointer msgpack sin
registrar nada: cualquier subclase nuestra tendría que sobrevivir a la (de)serialización
de LangGraph, y ese es un problema que no hace falta tener.
"""


def context_message(content: str, kind: str = "ui") -> HumanMessage:
    """Construye un mensaje de contexto, marcado para dedup y para la reinyección."""
    return HumanMessage(
        content=content,
        id=str(uuid4()),
        additional_kwargs={CONTEXT_MESSAGE_FLAG: kind},
    )


def is_context_message(message: BaseMessage) -> bool:
    return bool(getattr(message, "additional_kwargs", {}).get(CONTEXT_MESSAGE_FLAG))


def context_message_kind(message: BaseMessage) -> str | None:
    value = getattr(message, "additional_kwargs", {}).get(CONTEXT_MESSAGE_FLAG)
    return str(value) if value else None


# --------------------------------------------------------------------------- #
# Sanitización                                                                 #
# --------------------------------------------------------------------------- #


def _attr(value: Any) -> str:
    """
    Escapa un valor para meterlo en un atributo XML.

    No es cosmética: los títulos de plano y los nombres de asset son texto libre del
    usuario. Un nombre con comillas rompe el marcado y, peor, permite fabricar
    atributos o cerrar la etiqueta y escribir texto que parece del sistema.
    """
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _body(value: Any) -> str:
    """Escapa texto de cuerpo. Igual que `_attr` pero conservando comillas legibles."""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clip(text: str, limit: int) -> str:
    """Corte con marca. Nunca se corta sin decirlo."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _truncation(n: int, noun: str) -> str:
    return P.TRUNCATION_MARKER.format(n=n, noun=noun)


# --------------------------------------------------------------------------- #
# Serialización                                                                #
# --------------------------------------------------------------------------- #


def _format_shot(shot: ShotContext, detail: ContextDetail) -> str:
    """
    Un plano. La forma la fija `docs/ARQUITECTURA-AGENTE.md` §5.

    En el peldaño `TITLES` cabe en una línea; en `FULL` lleva su spec entera más el
    asset, igual que PostHog adjunta la query *y* sus resultados. Nunca se omite el
    estado de render: el agente que no sabe qué está ya renderizado regenera, y eso
    cuesta créditos de verdad.
    """
    head_attrs = [
        f'id="{_attr(shot.id)}"',
        f'position="{shot.position if shot.position is not None else "-"}"',
        f'status="{_attr(shot.status)}"',
    ]
    if shot.title:
        head_attrs.append(f'title="{_attr(_clip(shot.title, 120))}"')
    duration = shot.duration_s
    if duration is not None:
        head_attrs.append(f'duration="{duration:g}s"')

    if detail is ContextDetail.TITLES:
        return f"<shot {' '.join(head_attrs)}/>"

    lines: list[str] = [f"<shot {' '.join(head_attrs)}>"]

    prompt = shot.prompt
    if prompt:
        limit = MAX_PROMPT_CHARS if detail is ContextDetail.FULL else SPEC_PROMPT_CHARS
        lines.append(f"  <prompt>{_body(_clip(prompt, limit))}</prompt>")

    if shot.element_names:
        mentions = " ".join("@" + "-".join(n.split()) for n in shot.element_names)
        lines.append(f"  <elements>{_body(mentions)}</elements>")

    cam = _format_camera(shot.camera)
    if cam:
        lines.append(f"  {cam}")

    if shot.model_id:
        lines.append(f"  <model>{_body(shot.model_id)}</model>")

    if detail is ContextDetail.FULL:
        for key, value in sorted(shot.spec.items()):
            if key in ("prompt", "duration_s", "duration", "model_id", "model", "camera"):
                continue
            if value in (None, "", [], {}):
                continue
            lines.append(f'  <param name="{_attr(key)}">{_body(_clip(str(value), 200))}</param>')

    if shot.asset is not None:
        a = shot.asset
        lines.append(
            f'  <asset id="{_attr(a.id)}" kind="{_attr(a.kind)}" status="{_attr(a.status)}"'
            f' cost_credits="{a.credits_spent}"/>'
        )

    lines.append("</shot>")
    return "\n".join(lines)


def _format_camera(camera: CameraSpec) -> str:
    parts = []
    if camera.motion:
        parts.append(f'motion="{_attr(camera.motion)}"')
    if camera.strength is not None:
        parts.append(f'strength="{camera.strength:g}"')
    if camera.lens:
        parts.append(f'lens="{_attr(camera.lens)}"')
    if camera.aperture:
        parts.append(f'aperture="{_attr(camera.aperture)}"')
    return f"<camera {' '.join(parts)}/>" if parts else ""


def _format_timeline(
    shots: Sequence[ShotContext], detail: ContextDetail, limit: int | None
) -> tuple[str, int]:
    """
    La timeline completa. Devuelve `(xml, planos_mostrados)`.

    Ordena por `narrative_sort_key` **aquí dentro** y no confía en que venga ordenada:
    el orden narrativo es la señal de continuidad más importante que recibe el modelo, y
    dejar que dependa de quién construyó la lista es pedir que un día se rompa en
    silencio.
    """
    ordered = sorted(shots, key=narrative_sort_key)
    total = len(ordered)
    shown = ordered if limit is None else ordered[:limit]

    body = [_format_shot(s, detail) for s in shown]
    if len(shown) < total:
        body.append(_truncation(total - len(shown), "planos"))

    return (
        P.TIMELINE_TEMPLATE.format(
            detail=detail.name.lower(),
            shown=len(shown),
            total=total,
            shots="\n".join(body),
        ),
        len(shown),
    )


def _format_brief(blocks: Sequence[BriefBlock], detail: ContextDetail) -> tuple[str, bool]:
    ordered = sorted(blocks, key=lambda b: b.position)
    limit = 4_000 if detail is ContextDetail.FULL else 1_200
    lines: list[str] = []
    used = 0
    truncated = False
    for block in ordered:
        if block.type == "image" and block.src:
            asset_attr = f' asset_id="{_attr(block.asset_id)}"' if block.asset_id else ""
            lines.append(f'<block type="image"{asset_attr} src="{_attr(block.src)}"/>')
            continue
        text = block.text.strip()
        if not text:
            continue
        if used + len(text) > limit:
            truncated = True
            break
        used += len(text)
        checked = ' checked="true"' if block.checked else ""
        lines.append(f'<block type="{_attr(block.type)}"{checked}>{_body(text)}</block>')
    if truncated:
        lines.append(_truncation(len(ordered) - len(lines), "bloques del brief"))
    if not lines:
        return "", False
    return P.BRIEF_TEMPLATE.format(blocks="\n".join(lines)), truncated


def _format_elements(elements: Sequence[ElementContext], detail: ContextDetail) -> str:
    """
    Los elements con su ficha y su rol.

    La ficha (`sheet`) va aquí incluso en el peldaño intermedio: es lo que sostiene la
    continuidad de personaje y es el dato cuya pérdida se paga en créditos, no en
    tokens. Solo se sacrifica en `TITLES`, y en ese punto ya estamos en emergencia.
    """
    if not elements:
        return ""
    lines: list[str] = []
    for el in sorted(elements, key=lambda e: (e.role, e.name)):
        head = f'<element mention="{_attr(el.mention)}" id="{_attr(el.id)}" role="{_attr(el.role)}"'
        if detail is ContextDetail.TITLES or (not el.sheet and not el.meta):
            lines.append(head + "/>")
            continue
        lines.append(head + ">")
        if el.meta:
            lines.append(f"  <meta>{_body(_clip(el.meta, 240))}</meta>")
        if el.sheet:
            limit = 900 if detail is ContextDetail.FULL else 320
            lines.append(f"  <sheet>{_body(_clip(el.sheet, limit))}</sheet>")
        lines.append("</element>")
    example = elements[0].mention if elements else "@personaje"
    return P.ELEMENTS_TEMPLATE.format(elements="\n".join(lines), example=_attr(example))


def _format_asset(asset: AssetContext, detail: ContextDetail) -> str:
    attrs = [
        f'id="{_attr(asset.id)}"',
        f'name="{_attr(_clip(asset.name, 80))}"',
        f'kind="{_attr(asset.kind)}"',
        f'status="{_attr(asset.status)}"',
    ]
    if asset.role:
        attrs.append(f'role="{_attr(asset.role)}"')
    if asset.shot_id:
        attrs.append(f'shot="{_attr(asset.shot_id)}"')
    if detail is ContextDetail.TITLES:
        return f"<asset {' '.join(attrs)}/>"
    if asset.model_id:
        attrs.append(f'model="{_attr(asset.model_id)}"')
    if asset.credits_spent:
        attrs.append(f'cost_credits="{asset.credits_spent}"')
    if detail is ContextDetail.FULL and asset.prompt:
        return (
            f"<asset {' '.join(attrs)}>\n"
            f"  <prompt>{_body(_clip(asset.prompt, 400))}</prompt>\n"
            f"</asset>"
        )
    return f"<asset {' '.join(attrs)}/>"


def _format_assets(
    assets: Sequence[AssetContext], total: int, detail: ContextDetail, limit: int | None
) -> tuple[str, int]:
    if not assets:
        return "", 0
    shown = assets if limit is None else assets[:limit]
    lines = [_format_asset(a, detail) for a in shown]
    if total > len(shown):
        lines.append(_truncation(total - len(shown), "assets"))
    return P.ASSETS_TEMPLATE.format(shown=len(shown), total=total, assets="\n".join(lines)), len(
        shown
    )


def _format_gen_settings(settings: GenSettings) -> str:
    pairs = {
        "model": settings.model,
        "mode": settings.mode,
        "genre": settings.genre,
        "aspect": settings.aspect,
        "resolution": settings.resolution,
        "duration_s": settings.duration_s,
        "count": settings.count,
        "sound": None if settings.sound is None else ("on" if settings.sound else "off"),
        "style": settings.style,
        "camera": settings.camera,
        "camera_move": settings.camera_move,
        "speed_ramp": settings.speed_ramp,
        "start_frame": settings.start_frame,
        "end_frame": settings.end_frame,
    }
    attrs = "".join(f' {k}="{_attr(v)}"' for k, v in pairs.items() if v not in (None, ""))
    return P.GEN_SETTINGS_TEMPLATE.format(attrs=attrs) if attrs else ""


def _format_production(ctx: XframeUIContext, detail: ContextDetail) -> str:
    if not (
        ctx.screenplay
        or ctx.asset_links
        or ctx.character_voices
        or ctx.audio_cues
        or ctx.audio_templates
        or ctx.annotations
        or ctx.transitions
        or ctx.resource_bindings
        or ctx.production_manifests
    ):
        return ""
    lines: list[str] = []
    if ctx.character_voices:
        lines.append("<cast_voices>")
        for voice in ctx.character_voices[:40]:
            lines.append(
                f'<voice character="{_attr(voice.get("character_name", ""))}" '
                f'element_id="{_attr(voice.get("element_id", ""))}" '
                f'profile_id="{_attr(voice.get("voice_profile_id", ""))}" '
                f'provider="{_attr(voice.get("provider", ""))}" '
                f'language="{_attr(voice.get("language", ""))}"/>'
            )
        lines.append("</cast_voices>")
    if ctx.screenplay:
        lines.append("<screenplay>")
        line_limit = 120 if detail is ContextDetail.FULL else 50
        used = 0
        for scene in ctx.screenplay[:30]:
            lines.append(
                f'<scene id="{_attr(scene.get("id", ""))}" position="{scene.get("position", 0)}" '
                f'timeline_start_ms="{scene.get("timeline_start_ms", 0)}" '
                f'target_duration_ms="{_attr(scene.get("target_duration_ms", ""))}" '
                f'shots="{_attr(",".join(scene.get("shot_ids", [])))}" '
                f'title="{_attr(scene.get("title", ""))}">'
            )
            for item in scene.get("lines", []):
                if used >= line_limit:
                    break
                used += 1
                attrs = (
                    f'id="{_attr(item.get("id", ""))}" type="{_attr(item.get("line_type", ""))}" '
                    f'speaker="{_attr(item.get("speaker_name", ""))}" '
                    f'shot="{_attr(item.get("shot_id", ""))}" '
                    f'emotion="{_attr(item.get("emotion", "neutral"))}" '
                    f'status="{_attr(item.get("status", "draft"))}"'
                )
                lines.append(f"<line {attrs}>{_body(_clip(str(item.get('text', '')), 800))}</line>")
            lines.append("</scene>")
        lines.append("</screenplay>")
    if ctx.asset_links:
        lines.append("<screenplay_asset_links>")
        for link in ctx.asset_links[:120]:
            lines.append(
                f'<asset_link id="{_attr(link.get("id", ""))}" '
                f'scene="{_attr(link.get("scene_id", ""))}" '
                f'line="{_attr(link.get("script_line_id", ""))}" '
                f'asset_id="{_attr(link.get("asset_id", ""))}" '
                f'asset_name="{_attr(link.get("asset_name", ""))}" '
                f'asset_type="{_attr(link.get("asset_type", ""))}" '
                f'asset_path="{_attr(link.get("asset_path", ""))}" '
                f'role="{_attr(link.get("role", "reference"))}" '
                f'range_ms="{_attr(link.get("start_offset_ms", ""))}-'
                f'{_attr(link.get("end_offset_ms", ""))}" '
                f'locked="{str(bool(link.get("locked", True))).lower()}">'
                f"{_body(_clip(str(link.get('instructions', '')), 500))}</asset_link>"
            )
        lines.append("</screenplay_asset_links>")
    if ctx.audio_cues:
        lines.append("<audio_cues>")
        for cue in ctx.audio_cues[:100]:
            lines.append(
                f'<cue id="{_attr(cue.get("id", ""))}" asset="{_attr(cue.get("asset_id", ""))}" '
                f'kind="{_attr(cue.get("track_kind", ""))}" '
                f'scene="{_attr(cue.get("scene_id", ""))}" '
                f'shot="{_attr(cue.get("shot_id", ""))}" '
                f'line="{_attr(cue.get("script_line_id", ""))}" '
                f'range_ms="{cue.get("start_ms", 0)}-{cue.get("end_ms", 0)}" '
                f'source_range_ms="{cue.get("source_in_ms", 0)}-'
                f'{_attr(cue.get("source_out_ms", ""))}" '
                f'gain_db="{cue.get("gain_db", 0)}" '
                f'fade_ms="{cue.get("fade_in_ms", 0)}-{cue.get("fade_out_ms", 0)}" '
                f'pan="{cue.get("pan", 0)}" loop="{str(bool(cue.get("loop", False))).lower()}" '
                f'locked="{str(bool(cue.get("locked", False))).lower()}" '
                f'approved="{str(bool(cue.get("approved", False))).lower()}" '
                f'ducking_group="{_attr(cue.get("ducking_group", ""))}" '
                f'ducking_db="{_attr(cue.get("ducking_db", ""))}" '
                f'role="{_attr(cue.get("narrative_role", ""))}"/>'
            )
        lines.append("</audio_cues>")
    if ctx.audio_templates:
        lines.append("<sound_templates>")
        for template in ctx.audio_templates[:60]:
            lines.append(
                f'<sound_template id="{_attr(template.get("id", ""))}" '
                f'name="{_attr(template.get("name", ""))}" '
                f'asset_id="{_attr(template.get("asset_id", ""))}" '
                f'kind="{_attr(template.get("kind", ""))}" '
                f'duration_ms="{_attr(template.get("duration_ms", ""))}" '
                f'loop="{str(bool(template.get("loop", False))).lower()}" '
                f'intensity="{_attr(template.get("intensity", 0.5))}">'
                f"{_body(_clip(str(template.get('prompt', '')), 700))}</sound_template>"
            )
        lines.append("</sound_templates>")
    if ctx.annotations:
        lines.append("<asset_annotations>")
        for annotation in ctx.annotations[:120]:
            lines.append(
                f'<annotation id="{_attr(annotation.get("id", ""))}" '
                f'asset_id="{_attr(annotation.get("asset_id", ""))}" '
                f'kind="{_attr(annotation.get("kind", ""))}" '
                f'time_ms="{_attr(annotation.get("time_ms", ""))}" '
                f'status="{_attr(annotation.get("status", "open"))}" '
                f'geometry="{_attr(json.dumps(annotation.get("geometry") or {}, separators=(",", ":")))}">'
                f'{_body(_clip(str(annotation.get("body", "")), 500))}</annotation>'
            )
        lines.append("</asset_annotations>")
    if ctx.transitions:
        lines.append("<transitions>")
        for transition in ctx.transitions[:80]:
            lines.append(
                f'<transition id="{_attr(transition.get("id", ""))}" '
                f'from="{_attr(transition.get("from_asset_id", ""))}" '
                f'to="{_attr(transition.get("to_asset_id", ""))}" '
                f'kind="{_attr(transition.get("kind", ""))}" '
                f'duration_ms="{transition.get("duration_ms", 0)}" '
                f'status="{_attr(transition.get("status", ""))}"/>'
            )
        lines.append("</transitions>")
    if ctx.resource_bindings:
        lines.append("<resource_bindings>")
        for binding in ctx.resource_bindings[:160]:
            lines.append(
                f'<binding id="{_attr(binding.get("id", ""))}" '
                f'resource_type="{_attr(binding.get("resource_type", ""))}" '
                f'resource_id="{_attr(binding.get("resource_id", ""))}" '
                f'scope_type="{_attr(binding.get("scope_type", ""))}" '
                f'scope_id="{_attr(binding.get("scope_id", ""))}" '
                f'role="{_attr(binding.get("role", "reference"))}" '
                f'range_ms="{_attr(binding.get("start_ms", ""))}-'
                f'{_attr(binding.get("end_ms", ""))}" '
                f'locked="{str(bool(binding.get("locked", True))).lower()}">'
                f'{_body(_clip(str(binding.get("instructions", "")), 500))}</binding>'
            )
        lines.append("</resource_bindings>")
    if ctx.production_manifests:
        lines.append("<production_manifests>")
        for manifest in ctx.production_manifests[:30]:
            validation = manifest.get("validation") or {}
            lines.append(
                f'<manifest id="{_attr(manifest.get("id", ""))}" '
                f'scene_id="{_attr(manifest.get("scene_id", ""))}" '
                f'version="{manifest.get("version", 0)}" '
                f'status="{_attr(manifest.get("status", ""))}" '
                f'valid="{str(bool(validation.get("valid"))).lower()}" '
                f'fingerprint="{_attr(manifest.get("fingerprint", ""))}" '
                f'execution_fingerprint="{_attr(manifest.get("execution_fingerprint", ""))}" '
                f'completed_at="{_attr(manifest.get("completed_at", ""))}"/>'
            )
        lines.append("</production_manifests>")
    return P.PRODUCTION_TEMPLATE.format(body="\n".join(lines))


def serialize_context(
    ctx: XframeUIContext,
    *,
    budget_chars: int = CONTEXT_CHAR_BUDGET,
) -> tuple[str, ContextReport]:
    """
    `XframeUIContext` → XML dentro de `<attached_context>`, dentro del presupuesto.

    Función pura: sin BD, sin LLM, sin reloj. Es la que se testea.

    Estrategia de la escalera: se intenta el peldaño completo; si no cabe, se baja de
    peldaño **globalmente** (no por sección) y se reintenta; y solo si tampoco cabe en
    el peldaño más pobre se recortan planos y assets por la cola, con marcador. El
    presupuesto es global y no por sección por la misma razón que en PostHog es global
    y no por dashboard: dos secciones que caben por separado pueden no caber juntas.

    Lo que nunca se degrada por debajo de su mínimo: la cabecera del proyecto (créditos
    y pestaña) y la selección actual. Son diminutas y son lo que da sentido al turno.
    """
    report = ContextReport(
        shots_total=len(ctx.timeline),
        assets_total=ctx.total_assets or len(ctx.recent_assets),
        budget_chars=budget_chars,
    )

    for detail in (ContextDetail.FULL, ContextDetail.SPECS, ContextDetail.TITLES):
        text, shots_shown, assets_shown, brief_truncated = _render(ctx, detail, None, None)
        if len(text) <= budget_chars or detail is ContextDetail.TITLES:
            report.detail = detail
            report.shots_shown = shots_shown
            report.assets_shown = assets_shown
            report.brief_truncated = brief_truncated
            report.chars = len(text)
            if len(text) <= budget_chars:
                return text, report
            break

    # Ni el peldaño más pobre cabe: se recortan elementos por la cola, con marcador.
    # Se sacrifican assets antes que planos, porque la timeline es el hilo narrativo y
    # los assets se pueden volver a listar con una tool sin perder el sentido del todo.
    detail = ContextDetail.TITLES
    report.detail = detail
    for assets_limit, shots_limit in _shrink_plan(len(ctx.recent_assets), len(ctx.timeline)):
        text, shots_shown, assets_shown, brief_truncated = _render(
            ctx, detail, shots_limit, assets_limit
        )
        report.shots_shown = shots_shown
        report.assets_shown = assets_shown
        report.brief_truncated = brief_truncated
        report.chars = len(text)
        if len(text) <= budget_chars:
            if assets_limit == 0:
                report.sections_dropped.append("assets")
            return text, report

    # El último recurso no puede ser un corte por caracteres: deja XML inválido y puede
    # amputar precisamente los dos referentes que nunca se degradan (el total de planos
    # y la selección actual). Se entrega una cápsula estructuralmente válida, aunque no
    # quepa ningún plano concreto, para que el agente sepa qué falta y pueda leerlo con
    # una tool.
    text, shots_shown = _render_minimal_context(ctx, budget_chars)
    report.shots_shown = shots_shown
    report.assets_shown = 0
    report.brief_truncated = bool(ctx.brief)
    report.sections_dropped.extend(["brief", "assets", "timeline_detail", "hard_truncated"])
    report.chars = len(text)

    # Un presupuesto menor que esta cápsula no es utilizable: no sacrificamos un XML
    # válido ni la selección para simular que se respetó. El presupuesto normal es
    # 200.000 caracteres; este camino solo existe para defensas y tests de estrés.
    return text, report


def _shrink_plan(n_assets: int, n_shots: int) -> Iterable[tuple[int, int]]:
    """Plan de recorte: primero los assets, después los planos. Nunca por debajo de 5 planos."""
    for assets_limit in (min(n_assets, 20), 8, 0):
        yield assets_limit, n_shots
    shots_limit = n_shots
    while shots_limit > 5:
        shots_limit = max(5, shots_limit // 2)
        yield 0, shots_limit


def _render_minimal_context(ctx: XframeUIContext, budget_chars: int) -> tuple[str, int]:
    """Cápsula válida: conserva identidad, selección y tantos títulos como quepan."""
    project = P.PROJECT_TEMPLATE.format(
        project_id=_attr(ctx.project_id),
        title=_attr(_clip(ctx.project_title, 120)),
        open_tab=_attr(ctx.open_tab.value),
        credits=ctx.credits,
        total_assets=ctx.total_assets or len(ctx.recent_assets),
    )
    selection = ""
    if ctx.selected_assets:
        selection = P.SELECTION_TEMPLATE.format(
            assets="\n".join(
                _format_asset(asset, ContextDetail.FULL) for asset in ctx.selected_assets
            )
        )

    def wrap(timeline: str) -> str:
        sections = [project]
        if timeline:
            sections.append(timeline)
        if selection:
            sections.append(selection)
        sections.append(_truncation(0, "secciones"))
        return P.CONTEXT_WRAPPER.format(sections="\n".join(sections))

    if not ctx.timeline:
        return wrap(""), 0

    total = len(ctx.timeline)
    titles: list[str] = []
    best = wrap(
        P.TIMELINE_TEMPLATE.format(
            detail=ContextDetail.TITLES.name.lower(),
            shown=0,
            total=total,
            shots=_truncation(total, "planos"),
        )
    )
    for shot in ctx.timeline:
        candidate_titles = [*titles, _format_shot(shot, ContextDetail.TITLES)]
        body = candidate_titles.copy()
        if len(candidate_titles) < total:
            body.append(_truncation(total - len(candidate_titles), "planos"))
        candidate = wrap(
            P.TIMELINE_TEMPLATE.format(
                detail=ContextDetail.TITLES.name.lower(),
                shown=len(candidate_titles),
                total=total,
                shots="\n".join(body),
            )
        )
        if len(candidate) > budget_chars:
            break
        titles = candidate_titles
        best = candidate

    return best, len(titles)


# Topes de la guía del usuario. Son directrices, no un volcado: se acotan aquí para que
# ni un texto de conocimiento largo ni veinte fuentes puedan desbordar el presupuesto.
_GUIDANCE_KNOWLEDGE_CHARS = 4_000
_GUIDANCE_SKILL_INSTR_CHARS = 600
_GUIDANCE_SOURCE_EXCERPT_CHARS = 400
_GUIDANCE_MAX_SOURCES = 12


def _format_guidance(guidance: Guidance) -> str:
    """Conocimiento + habilidades + fuentes del usuario → XML acotado, o cadena vacía."""
    if guidance.is_empty:
        return ""

    parts: list[str] = []

    if text := guidance.knowledge.strip():
        parts.append(
            P.KNOWLEDGE_TEMPLATE.format(text=_body(_clip(text, _GUIDANCE_KNOWLEDGE_CHARS)))
        )

    if guidance.skills:
        rendered = "\n".join(_format_skill(skill) for skill in guidance.skills if skill.name)
        if rendered:
            parts.append(P.SKILLS_TEMPLATE.format(skills=rendered))

    if guidance.sources:
        rendered = "\n".join(
            _format_source(source) for source in guidance.sources[:_GUIDANCE_MAX_SOURCES]
        )
        if rendered:
            parts.append(P.SOURCES_TEMPLATE.format(sources=rendered))

    if not parts:
        return ""
    return P.GUIDANCE_TEMPLATE.format(sections="\n".join(parts))


def _format_skill(skill: ProjectSkill) -> str:
    triggers = ", ".join(skill.triggers) if skill.triggers else ""
    attrs = f' triggers="{_attr(triggers)}"' if triggers else ""
    desc = f"{skill.description.strip()}\n" if skill.description.strip() else ""
    instr = _body(_clip(skill.instructions.strip(), _GUIDANCE_SKILL_INSTR_CHARS))
    return f'<skill name="{_attr(skill.name)}"{attrs}>\n{desc}{instr}\n</skill>'


def _format_source(source: KnowledgeSource) -> str:
    url = f' url="{_attr(source.url)}"' if source.url else ""
    excerpt = _body(_clip(source.excerpt.strip(), _GUIDANCE_SOURCE_EXCERPT_CHARS))
    return (
        f'<source kind="{_attr(source.kind)}" title="{_attr(source.title)}"{url}>\n'
        f"{excerpt}\n</source>"
    )


def _render(
    ctx: XframeUIContext,
    detail: ContextDetail,
    shots_limit: int | None,
    assets_limit: int | None,
) -> tuple[str, int, int, bool]:
    """Una pasada de renderizado a un peldaño y unos límites dados."""
    sections: list[str] = [
        P.PROJECT_TEMPLATE.format(
            project_id=_attr(ctx.project_id),
            title=_attr(_clip(ctx.project_title, 120)),
            open_tab=_attr(ctx.open_tab.value),
            credits=ctx.credits,
            total_assets=ctx.total_assets or len(ctx.recent_assets),
        )
    ]

    if gen := _format_gen_settings(ctx.gen_settings):
        sections.append(gen)

    # La guía del usuario va alta, junto a los ajustes: son directrices permanentes que
    # enmarcan todo el turno, como la memoria. No entra en la escalera de recorte —está
    # acotada en origen— porque perder las instrucciones del usuario por presupuesto es
    # peor que perder el asset número cuarenta.
    if guidance_xml := _format_guidance(ctx.guidance):
        sections.append(guidance_xml)

    brief_xml, brief_truncated = _format_brief(ctx.brief, detail)
    if brief_xml:
        sections.append(brief_xml)

    shots_shown = 0
    if ctx.timeline:
        timeline_xml, shots_shown = _format_timeline(ctx.timeline, detail, shots_limit)
        sections.append(timeline_xml)

    if elements_xml := _format_elements(ctx.elements, detail):
        sections.append(elements_xml)

    if production_xml := _format_production(ctx, detail):
        sections.append(production_xml)

    assets_xml, assets_shown = _format_assets(
        ctx.recent_assets, ctx.total_assets or len(ctx.recent_assets), detail, assets_limit
    )
    if assets_xml:
        sections.append(assets_xml)

    # La selección se serializa siempre completa: es diminuta y es el referente de
    # "esto", "este plano", "el de aquí". Perderla convierte la petición en un acertijo.
    if ctx.selected_assets:
        sections.append(
            P.SELECTION_TEMPLATE.format(
                assets="\n".join(_format_asset(a, ContextDetail.FULL) for a in ctx.selected_assets)
            )
        )

    text = P.CONTEXT_WRAPPER.format(sections="\n".join(sections))
    return text, shots_shown, assets_shown, brief_truncated


# --------------------------------------------------------------------------- #
# Carga desde BD                                                               #
# --------------------------------------------------------------------------- #


def _coerce_tab(value: OpenTab | str) -> OpenTab:
    """
    Pestaña abierta, tolerante a basura.

    El valor viene del frontend en cada turno. Con `OpenTab(value)` a secas, una pestaña
    que el cliente renombre —o un cliente viejo tras un despliegue— lanza `ValueError`
    dentro del nodo raíz y **tumba el turno entero** por un dato puramente decorativo:
    `open_tab` solo decide a qué parte del contexto se le da más detalle. Degradar a
    `ASSETS` y registrar el valor raro es la respuesta proporcionada.
    """
    if isinstance(value, OpenTab):
        return value
    try:
        return OpenTab(value)
    except ValueError:
        logger.info("xframe_unknown_open_tab", extra={"open_tab": str(value)[:40]})
        return OpenTab.ASSETS


def _flatten_setting(key: str, value: Any) -> Any:
    """
    Normaliza un ajuste de generación a lo que `GenSettings` declara.

    El frontend guarda `style` y `camera` como diccionarios anidados —así los escribe
    `defaultGenSettings` en `src/lib/db.js`: `{"Paleta de color": "Auto", "Iluminación":
    "Auto"}`— pero el modelo los declara como cadenas. El backend se escribió asumiendo
    una forma que el frontend nunca produjo, y el resultado era un `ValidationError` de
    pydantic que reventaba el nodo raíz **en cada turno**, antes de llamar al modelo.

    Se aplana a `"clave: valor · clave: valor"` en vez de serializar a JSON porque el
    destinatario es un LLM leyendo un bloque de contexto, no un parser.
    """
    if key == "duration_s":
        try:
            return float(str(value).rstrip("s")) if value is not None else None
        except (TypeError, ValueError):
            return None
    if key == "count":
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    if key == "sound":
        # Se conserva como bool: el frontend lo guarda como booleano JSON.
        return bool(value) if value is not None else None
    if key in ("start_frame", "end_frame") and isinstance(value, dict):
        # El frontend guarda {id, url, name} para poder pintar la miniatura; al modelo
        # le basta el id — la URL firmada caduca y se re-resuelve con read_project.
        return str(value.get("id")) if value.get("id") else None
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in value.items() if v not in (None, "", "Auto")]
        return " · ".join(parts) if parts else None
    if isinstance(value, (list, tuple)):
        return " · ".join(str(v) for v in value) or None
    return str(value) if value is not None else None


class XframeContextManager:
    """
    Carga, serializa e inyecta el contexto del proyecto.

    Se instancia por turno. No cachea nada entre turnos a propósito: el proyecto cambia
    debajo (los jobs terminan de forma asíncrona) y un contexto cacheado le contaría al
    agente un render que ya no existe o le ocultaría uno que acaba de salir.
    """

    def __init__(self, project_id: str, user_id: str) -> None:
        self._project_id = project_id
        self._user_id = user_id

    # -- carga ------------------------------------------------------------- #

    async def load(
        self,
        *,
        open_tab: OpenTab | str = OpenTab.ASSETS,
        selected_asset_ids: Sequence[str] | None = None,
    ) -> XframeUIContext:
        """
        Memoria completa del proyecto desde BD.

        Todas las consultas van en paralelo con `return_exceptions=True`: una sección
        que falla se queda vacía y el resto del contexto llega igual. El contrato es que
        el agente responda con menos contexto, nunca que el turno se caiga porque una
        consulta secundaria dio error.
        """
        results = await asyncio.gather(
            self._load_project(),
            self._load_brief(),
            self._load_shots(),
            self._load_assets(),
            self._load_sheets(),
            self._load_profile(),
            self._load_guidance(),
            self._load_production(),
            self._load_canvas_graph(),
            return_exceptions=True,
        )
        (
            project,
            brief,
            shots,
            assets_bundle,
            sheets,
            profile,
            guidance,
            production,
            canvas_graph,
        ) = [
            self._or_default(r, default)
            for r, default in zip(
                results,
                ({}, [], [], ([], 0), {}, {}, Guidance(), {}, ([], [])),
                strict=True,
            )
        ]
        canvas_nodes, canvas_links = canvas_graph

        assets, total_assets = assets_bundle
        elements = self._build_elements(assets, sheets)
        by_id = {a.id: a for a in assets}
        self._attach_assets_to_shots(shots, assets)
        self._attach_element_names(shots, elements)

        selected = [by_id[i] for i in (selected_asset_ids or []) if i in by_id]

        return XframeUIContext(
            project_id=self._project_id,
            project_title=project.get("title", ""),
            open_tab=_coerce_tab(open_tab),
            brief=brief,
            timeline=sorted(shots, key=narrative_sort_key),
            canvas_nodes=canvas_nodes,
            canvas_links=canvas_links,
            elements=elements,
            recent_assets=assets,
            selected_assets=selected,
            screenplay=production.get("screenplay", []),
            asset_links=production.get("asset_links", []),
            character_voices=production.get("character_voices", []),
            audio_cues=production.get("audio_cues", []),
            audio_templates=production.get("audio_templates", []),
            annotations=production.get("annotations", []),
            transitions=production.get("transitions", []),
            resource_bindings=production.get("resource_bindings", []),
            production_manifests=production.get("production_manifests", []),
            gen_settings=self._build_gen_settings(project, profile),
            credits=int(profile.get("credits", 0) or 0),
            total_assets=total_assets,
            guidance=guidance,
        )

    @staticmethod
    def _or_default(result: Any, default: Any) -> Any:
        if isinstance(result, BaseException):
            logger.warning("context_section_failed", exc_info=result)
            return default
        return result

    async def _load_project(self) -> dict[str, Any]:
        row = await db.fetchrow(
            "select id, title, prompt, settings from public.projects where id = $1::uuid",
            self._project_id,
        )
        return dict(row) if row else {}

    async def _load_production(self) -> dict[str, Any]:
        (
            scene_rows,
            line_rows,
            scene_shot_rows,
            voice_rows,
            cue_rows,
            transition_rows,
            asset_link_rows,
            audio_template_rows,
            resource_binding_rows,
            annotation_rows,
            production_manifest_rows,
        ) = await asyncio.gather(
            db.fetch(
                """select id, position, title, setting, time_of_day, summary,
                          dramatic_intent, timeline_start_ms, target_duration_ms, status
                     from public.script_scenes where project_id=$1::uuid
                    order by position""",
                self._project_id,
            ),
            db.fetch(
                """select l.id, l.scene_id, l.position, l.line_type, l.speaker_element_id,
                          speaker.name as speaker_name, l.voice_profile_id, l.shot_id, l.text,
                          l.language, l.emotion, l.direction, l.pace, l.intensity,
                          l.pause_before_ms, l.pause_after_ms, l.target_duration_ms,
                          l.audio_asset_id, l.status
                     from public.script_lines l
                     left join public.assets speaker on speaker.id=l.speaker_element_id
                    where l.project_id=$1::uuid order by l.scene_id, l.position""",
                self._project_id,
            ),
            db.fetch(
                """select scene_id, shot_id, position
                     from public.scene_shots where project_id=$1::uuid
                    order by scene_id, position""",
                self._project_id,
            ),
            db.fetch(
                """select cv.element_id, element.name as character_name,
                          cv.voice_profile_id, vp.name as voice_name, vp.provider,
                          vp.provider_voice_id, vp.language, vp.accent, vp.description,
                          vp.settings, vp.pronunciation_rules, vp.consent_status
                     from public.character_voices cv
                     join public.assets element on element.id=cv.element_id
                     join public.voice_profiles vp on vp.id=cv.voice_profile_id
                    where cv.project_id=$1::uuid and cv.is_default""",
                self._project_id,
            ),
            db.fetch(
                """select id, asset_id, scene_id, shot_id, script_line_id, track_kind, start_ms,
                          end_ms, source_in_ms, source_out_ms, gain_db, fade_in_ms,
                          fade_out_ms, pan, loop, locked, approved, ducking_group,
                          ducking_db, priority, narrative_role, context_tags
                     from public.audio_cues where project_id=$1::uuid
                    order by start_ms, priority desc""",
                self._project_id,
            ),
            db.fetch(
                """select id, from_asset_id, to_asset_id, kind, duration_ms,
                          generated_asset_id, model_id, seed, parameters, signature, status
                     from public.timeline_transitions where project_id=$1::uuid
                    order by created_at""",
                self._project_id,
            ),
            db.fetch(
                """select sal.id, sal.scene_id, sal.script_line_id, sal.asset_id,
                          a.name as asset_name, a.type as asset_type, a.url as asset_path,
                          sal.role, sal.instructions, sal.start_offset_ms,
                          sal.end_offset_ms, sal.locked
                     from public.script_asset_links sal
                     join public.assets a on a.id=sal.asset_id
                    where sal.project_id=$1::uuid
                    order by sal.scene_id, sal.script_line_id nulls first, sal.created_at""",
                self._project_id,
            ),
            db.fetch(
                """select id, name, asset_id, kind, prompt, duration_ms, loop, intensity,
                          composition_plan, tags
                     from public.audio_templates where project_id=$1::uuid
                    order by updated_at desc""",
                self._project_id,
            ),
            db.fetch(
                """select id, resource_type, resource_id, scope_type, scope_id, role,
                          start_ms, end_ms, instructions, locked, priority, metadata
                     from public.resource_bindings where project_id=$1::uuid
                    order by priority desc, created_at""",
                self._project_id,
            ),
            db.fetch(
                """select id,asset_id,kind,body,time_ms,geometry,color,status,created_at
                     from public.asset_annotations where project_id=$1::uuid
                    order by created_at desc limit 200""",
                self._project_id,
            ),
            db.fetch(
                """select id, scene_id, version, title, status, validation, fingerprint,
                          execution_fingerprint,approved_at,completed_at,updated_at
                     from public.production_manifests
                     where project_id=$1::uuid order by scene_id,version desc""",
                self._project_id,
            ),
        )
        lines_by_scene: dict[str, list[dict[str, Any]]] = {}
        for row in line_rows:
            data = dict(row)
            for key in (
                "id",
                "scene_id",
                "speaker_element_id",
                "voice_profile_id",
                "shot_id",
                "audio_asset_id",
            ):
                if data.get(key) is not None:
                    data[key] = str(data[key])
            lines_by_scene.setdefault(data["scene_id"], []).append(data)
        screenplay: list[dict[str, Any]] = []
        shots_by_scene: dict[str, list[str]] = {}
        for row in scene_shot_rows:
            shots_by_scene.setdefault(str(row["scene_id"]), []).append(str(row["shot_id"]))
        for row in scene_rows:
            data = dict(row)
            data["id"] = str(data["id"])
            data["lines"] = lines_by_scene.get(data["id"], [])
            data["shot_ids"] = shots_by_scene.get(data["id"], [])
            screenplay.append(data)

        def stringify(rows: Any, uuid_fields: tuple[str, ...]) -> list[dict[str, Any]]:
            output: list[dict[str, Any]] = []
            for row in rows:
                data = dict(row)
                for key in uuid_fields:
                    if data.get(key) is not None:
                        data[key] = str(data[key])
                output.append(data)
            return output

        return {
            "screenplay": screenplay,
            "asset_links": stringify(
                asset_link_rows, ("id", "scene_id", "script_line_id", "asset_id")
            ),
            "character_voices": stringify(voice_rows, ("element_id", "voice_profile_id")),
            "audio_cues": stringify(
                cue_rows, ("id", "asset_id", "scene_id", "shot_id", "script_line_id")
            ),
            "audio_templates": stringify(audio_template_rows, ("id",)),
            "annotations": stringify(annotation_rows, ("id", "asset_id")),
            "transitions": stringify(
                transition_rows,
                ("id", "from_asset_id", "to_asset_id", "generated_asset_id"),
            ),
            "resource_bindings": stringify(
                resource_binding_rows, ("id", "resource_id", "scope_id")
            ),
            "production_manifests": stringify(
                production_manifest_rows, ("id", "scene_id")
            ),
        }

    async def _load_profile(self) -> dict[str, Any]:
        row = await db.fetchrow(
            "select credits, settings from public.profiles where id = $1::uuid", self._user_id
        )
        return dict(row) if row else {}

    async def _load_guidance(self) -> Guidance:
        """
        Conocimiento y habilidades que el usuario define en Ajustes.

        Están en el ámbito del espacio de trabajo, no del proyecto, y el espacio es el
        que posee este usuario. Se cargan las tres tablas a la vez; cada una que falle
        deja su parte vacía. Se recorta agresivamente al serializar: son instrucciones,
        no un volcado —una fuente web puede tener 40.000 caracteres y aquí solo entra su
        extracto—.
        """
        knowledge_rows, source_rows, skill_rows = await asyncio.gather(
            db.fetch(
                """
                select content, project_id
                  from public.knowledge
                 where workspace_id in (
                         select id from public.workspaces where owner_id = $1::uuid
                       )
                   and (project_id is null or project_id = $2::uuid)
                   and content <> ''
                 order by (project_id = $2::uuid) desc
                """,
                self._user_id,
                self._project_id,
            ),
            db.fetch(
                """
                select title, kind, url, excerpt
                  from public.knowledge_sources
                 where workspace_id in (
                         select id from public.workspaces where owner_id = $1::uuid
                       )
                   and enabled and status = 'ready'
                 order by created_at desc
                 limit 20
                """,
                self._user_id,
            ),
            db.fetch(
                """
                select name, description, instructions, triggers
                  from public.skills
                 where workspace_id in (
                         select id from public.workspaces where owner_id = $1::uuid
                       )
                   and enabled
                 order by is_builtin, name
                """,
                self._user_id,
            ),
            return_exceptions=True,
        )

        knowledge = "\n\n".join(
            (r["content"] or "").strip()
            for r in (self._or_default(knowledge_rows, []) or [])
            if (r["content"] or "").strip()
        )

        sources = [
            KnowledgeSource(
                title=(r["title"] or "").strip() or "Sin título",
                kind=r["kind"] or "note",
                url=r["url"],
                excerpt=(r["excerpt"] or "").strip(),
            )
            for r in (self._or_default(source_rows, []) or [])
        ]

        skills = [
            ProjectSkill(
                name=(r["name"] or "").strip(),
                description=(r["description"] or "").strip(),
                instructions=(r["instructions"] or "").strip(),
                triggers=list(r["triggers"] or []),
            )
            for r in (self._or_default(skill_rows, []) or [])
        ]

        return Guidance(knowledge=knowledge, sources=sources, skills=skills)

    async def _load_brief(self) -> list[BriefBlock]:
        rows = await db.fetch(
            """
            select id, position, type, text, checked, src, asset_id
              from public.brief_blocks
             where project_id = $1::uuid
             order by position
            """,
            self._project_id,
        )
        return [
            BriefBlock(
                id=str(r["id"]),
                position=r["position"],
                type=r["type"],
                text=r["text"] or "",
                checked=bool(r["checked"]),
                src=r["src"],
                asset_id=str(r["asset_id"]) if r["asset_id"] else None,
            )
            for r in rows
        ]

    async def _load_shots(self) -> list[ShotContext]:
        """
        Los nodos del canvas, ordenados por `position` con `(y, x)` de desempate.

        El ORDER BY ya sale ordenado de la BD, pero la serialización vuelve a ordenar:
        el orden narrativo es demasiado importante para depender de un solo sitio.
        """
        rows = await db.fetch(
            """
            select id, type, x, y, title, text, position, spec, shot_status, asset_id
              from public.canvas_nodes
             where project_id = $1::uuid and type = 'shot'
             order by position nulls last, y, x
            """,
            self._project_id,
        )
        shots: list[ShotContext] = []
        for r in rows:
            spec = dict(r["spec"] or {})
            if r["asset_id"] and "asset_id" not in spec:
                spec["asset_id"] = str(r["asset_id"])
            camera_raw = spec.get("camera") or {}
            shots.append(
                ShotContext(
                    id=str(r["id"]),
                    position=r["position"],
                    type=r["type"],
                    title=r["title"] or "",
                    text=r["text"] or "",
                    status=r["shot_status"] or "pending",
                    spec=spec,
                    camera=CameraSpec(**camera_raw)
                    if isinstance(camera_raw, dict)
                    else CameraSpec(),
                    x=float(r["x"] or 0),
                    y=float(r["y"] or 0),
                )
            )
        return shots

    async def _load_canvas_graph(self) -> tuple[list[CanvasNode], list[CanvasLink]]:
        """
        El lienzo COMO GRAFO: los nodos libres (concepto/referencia) y las aristas.

        Los planos ya viajan por `_load_shots`; aquí se cargan los nodos que NO son
        planos y TODAS las aristas, resolviendo cada extremo a una etiqueta legible.
        Sin esto el agente veía una lista de planos y era ciego a la estructura que el
        usuario dibujó alrededor — conceptos, referencias y qué alimenta a qué. Peor: el
        agente podía CREAR nodos y conexiones que luego no podía releer.

        Las aristas de `canvas_edges` referencian por `node_key` (texto), no por uuid, así
        que se construye un mapa `node_key → (etiqueta, tipo)` sobre TODOS los nodos —
        planos incluidos— para poder decir "Concepto: isla → Plano 03" en vez de un par
        de identificadores opacos. Una arista con un extremo colgando (nodo borrado) se
        descarta en silencio: es ruido, no información.
        """
        node_rows, edge_rows = await asyncio.gather(
            db.fetch(
                """
                select node_key, type, title, text, asset_id
                  from public.canvas_nodes
                 where project_id = $1::uuid
                """,
                self._project_id,
            ),
            db.fetch(
                "select from_node, to_node from public.canvas_edges where project_id = $1::uuid",
                self._project_id,
            ),
        )

        # Nombres de asset para los nodos que cuelgan una referencia visual.
        asset_ids = [r["asset_id"] for r in node_rows if r["asset_id"]]
        asset_names: dict[str, str] = {}
        if asset_ids:
            arows = await db.fetch(
                "select id, name from public.assets where id = any($1::uuid[])", asset_ids
            )
            asset_names = {str(r["id"]): r["name"] for r in arows}

        # Mapa node_key → etiqueta legible, sobre TODOS los nodos (para resolver aristas).
        def _label(r: Any) -> str:
            title = (r["title"] or "").strip()
            if title:
                return title
            kind = r["type"] or "nodo"
            body = (r["text"] or "").strip()
            return f"{kind}: {body[:40]}" if body else kind

        label_by_key = {r["node_key"]: _label(r) for r in node_rows}
        kind_by_key = {r["node_key"]: (r["type"] or "concept") for r in node_rows}

        nodes = [
            CanvasNode(
                key=r["node_key"],
                kind=r["type"] or "concept",
                title=r["title"] or "",
                text=r["text"] or "",
                asset_name=asset_names.get(str(r["asset_id"])) if r["asset_id"] else None,
            )
            for r in node_rows
            if (r["type"] or "concept") != "shot"
        ]

        links: list[CanvasLink] = []
        for e in edge_rows:
            fk, tk = e["from_node"], e["to_node"]
            if fk not in label_by_key or tk not in label_by_key:
                continue  # arista huérfana: un extremo ya no existe
            links.append(
                CanvasLink(
                    from_label=label_by_key[fk],
                    to_label=label_by_key[tk],
                    from_kind=kind_by_key.get(fk, "concept"),
                    to_kind=kind_by_key.get(tk, "concept"),
                )
            )
        return nodes, links

    async def _load_assets(self) -> tuple[list[AssetContext], int]:
        """
        Todos los assets del proyecto — con ventana.

        El requisito es memoria completa, y por eso el censo (`total`) se cuenta aparte
        y viaja siempre: aunque solo se serialicen los N más recientes, el agente sabe
        cuántos hay. Los elements se cargan enteros al margen de la ventana, porque son
        el sistema de continuidad y no pueden caerse por antigüedad.
        """
        rows, total = await asyncio.gather(
            db.fetch(
                """
                select id, name, type, meta, status, role, shot_id, model_id, prompt,
                       params, credits_spent, parent_id, created_at
                  from public.assets
                 where project_id = $1::uuid
                 -- Los elements primero y fuera de la ventana por antigüedad: son el
                 -- sistema de continuidad y no pueden caerse de la lista por viejos.
                 order by (role is null), created_at desc
                 limit $2
                """,
                self._project_id,
                MAX_RECENT_ASSETS,
            ),
            db.fetchval(
                "select count(*) from public.assets where project_id = $1::uuid", self._project_id
            ),
        )
        assets = [
            AssetContext(
                id=str(r["id"]),
                name=r["name"],
                kind=r["type"],
                meta=r["meta"] or "",
                status=r["status"],
                role=r["role"],
                shot_id=r["shot_id"],
                model_id=r["model_id"],
                prompt=r["prompt"],
                params=dict(r["params"] or {}),
                credits_spent=int(r["credits_spent"] or 0),
                parent_id=str(r["parent_id"]) if r["parent_id"] else None,
                created_at=r["created_at"],
            )
            for r in rows
        ]
        return assets, int(total or 0)

    async def _load_sheets(self) -> dict[str, str]:
        """Fichas de personaje indexadas por `element_id`."""
        rows = await db.fetch(
            """
            select element_id, content
              from public.project_memory
             where project_id = $1::uuid
               and kind = 'character_sheet'
               and element_id is not null
            """,
            self._project_id,
        )
        return {str(r["element_id"]): r["content"] for r in rows}

    # -- ensamblado -------------------------------------------------------- #

    @staticmethod
    def _build_elements(
        assets: Sequence[AssetContext], sheets: dict[str, str]
    ) -> list[ElementContext]:
        return [
            ElementContext(
                id=a.id,
                name=a.name,
                role=a.role or "",
                meta=a.meta,
                sheet=sheets.get(a.id),
                status=a.status,
            )
            for a in assets
            if a.role
        ]

    @staticmethod
    def _attach_assets_to_shots(
        shots: Sequence[ShotContext], assets: Sequence[AssetContext]
    ) -> None:
        """
        Pega a cada plano su render. Gana el más reciente que esté `ready`; si no hay
        ninguno listo, el más reciente sea cual sea su estado — porque "generando" y
        "fallido" son información que el agente necesita tanto como "listo".
        """
        by_shot: dict[str, list[AssetContext]] = {}
        for a in assets:
            if a.shot_id:
                by_shot.setdefault(a.shot_id, []).append(a)
        for shot in shots:
            candidates = by_shot.get(shot.id)
            if not candidates:
                continue
            ready = [c for c in candidates if c.status == "ready"]
            shot.asset = (ready or candidates)[0]

    @staticmethod
    def _attach_element_names(
        shots: Sequence[ShotContext], elements: Sequence[ElementContext]
    ) -> None:
        """
        Deduce qué elements aparecen en cada plano.

        Prioriza lo explícito (`spec.elements`, que es lo que escriben las tools) y solo
        cae a buscar el nombre en el prompt cuando no hay nada explícito, porque el
        usuario escribe `@Marco` a mano en el canvas y esa mención tiene que contar.
        """
        by_name = {e.name.lower(): e for e in elements}
        for shot in shots:
            explicit = shot.spec.get("elements")
            if isinstance(explicit, list) and explicit:
                names: list[str] = []
                for item in explicit:
                    if isinstance(item, str):
                        names.append(
                            by_name[item.lower()].name if item.lower() in by_name else item
                        )
                    elif isinstance(item, dict) and item.get("name"):
                        names.append(str(item["name"]))
                shot.element_names = names
                continue
            haystack = f"{shot.title} {shot.text} {shot.prompt}".lower()
            shot.element_names = [
                e.name for name, e in by_name.items() if name and name in haystack
            ]

    @staticmethod
    def _build_gen_settings(project: dict[str, Any], profile: dict[str, Any]) -> GenSettings:
        """
        Ajustes efectivos: los del perfil como base, los del proyecto por encima.

        El proyecto gana porque un ajuste que el usuario tocó estando dentro del
        proyecto es una decisión sobre *ese* proyecto, no sobre su cuenta.
        """
        merged: dict[str, Any] = {}
        for source in (profile.get("settings") or {}, project.get("settings") or {}):
            if isinstance(source, dict):
                merged.update(source.get("gen") if isinstance(source.get("gen"), dict) else source)

        # El frontend guarda `res` y `dur`; `GenSettings` los llama `resolution` y
        # `duration_s`. Sin esta normalización caían a `extra` y el modelo nunca veía la
        # resolución ni la duración que el usuario había elegido.
        aliases = {"res": "resolution", "dur": "duration_s"}
        for old, new in aliases.items():
            if old in merged and new not in merged:
                merged[new] = merged.pop(old)

        known = {
            "model",
            "aspect",
            "resolution",
            "duration_s",
            "style",
            "camera",
            "mode",
            "genre",
            "sound",
            "count",
            "camera_move",
            "speed_ramp",
            "start_frame",
            "end_frame",
        }
        return GenSettings(
            **{k: _flatten_setting(k, v) for k, v in merged.items() if k in known},
            extra={k: v for k, v in merged.items() if k not in known},
        )

    # -- inyección --------------------------------------------------------- #

    async def get_context_messages(
        self,
        existing_messages: Sequence[BaseMessage],
        *,
        open_tab: OpenTab | str = OpenTab.ASSETS,
        selected_asset_ids: Sequence[str] | None = None,
        resource_refs: Sequence[dict[str, Any]] | None = None,
        include_memory: bool = True,
    ) -> list[HumanMessage]:
        """
        Mensajes de contexto de este turno, ya deduplicados contra el historial.

        Devuelve lista vacía si no hay nada nuevo que contar. Ese es el caso frecuente y
        el que hace que la caché de prompt sirva de algo.
        """
        ctx = await self.load(open_tab=open_tab, selected_asset_ids=selected_asset_ids)
        text, report = serialize_context(ctx)
        report.emit(project_id=self._project_id, user_id=self._user_id)

        candidates = [context_message(text, kind="ui")]

        if explicit := await self._resolve_resource_refs(resource_refs or []):
            candidates.append(
                context_message(
                    "<explicit_resources>\n"
                    + json.dumps(explicit, ensure_ascii=False, separators=(",", ":"))
                    + "\n</explicit_resources>",
                    kind="resources",
                )
            )

        if include_memory:
            from app.memory.store import ProjectMemoryStore

            if memory_text := await ProjectMemoryStore(self._project_id).format_for_prompt():
                candidates.append(context_message(memory_text, kind="memory"))

        return deduplicate_context_messages(existing_messages, candidates)

    async def _resolve_resource_refs(
        self, refs: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Valida cada referencia @ contra el proyecto antes de mostrársela al LLM."""
        tables = {
            "asset": ("assets", "name"),
            "element": ("assets", "name"),
            "scene": ("script_scenes", "title"),
            "line": ("script_lines", "text"),
            "shot": ("canvas_nodes", "title"),
            "canvas": ("canvas_nodes", "title"),
            "voice": ("voice_profiles", "name"),
            "cue": ("audio_cues", "track_kind"),
            "sound_template": ("audio_templates", "name"),
            "transition": ("timeline_transitions", "signature"),
            "manifest": ("production_manifests", "title"),
            "annotation": ("asset_annotations", "body"),
            "operation": ("asset_operations", "operation"),
            "report": ("quality_reports", "check_type"),
            "brief": ("brief_blocks", "text"),
        }
        grouped: dict[str, list[dict[str, Any]]] = {}
        for ref in refs[:100]:
            kind = str(ref.get("type", ""))
            if kind in tables and ref.get("id"):
                grouped.setdefault(kind, []).append(dict(ref))

        output: list[dict[str, Any]] = []
        for kind, items in grouped.items():
            table, label_column = tables[kind]
            ids = list(dict.fromkeys(str(item["id"]) for item in items))
            rows = await db.fetch(
                f"select id, {label_column} as label from public.{table} "
                "where project_id=$1::uuid and id=any($2::uuid[])",
                self._project_id,
                ids,
            )
            valid = {str(row["id"]): str(row["label"] or "") for row in rows}
            for item in items:
                item_id = str(item["id"])
                if item_id not in valid:
                    continue
                output.append(
                    {
                        "type": kind,
                        "id": item_id,
                        "label": valid[item_id],
                        "mention": item.get("mention"),
                        "scope": item.get("scope") or {},
                    }
                )
        return output


def deduplicate_context_messages(
    existing: Sequence[BaseMessage], candidates: Sequence[HumanMessage]
) -> list[HumanMessage]:
    """
    Dedup ingenua por contenido exacto, igual que `_deduplicate_context_messages`.

    Si el usuario sigue mirando lo mismo, el contexto entra una vez. Si cambia una coma
    del brief, entra otra vez entero — y eso es correcto: el proyecto cambió, y comparar
    ids o hashes semánticos costaría más de lo que ahorra.
    """
    seen = {m.content for m in existing if is_context_message(m)}
    out: list[HumanMessage] = []
    for msg in candidates:
        if msg.content in seen:
            continue
        seen.add(msg.content)
        out.append(msg)
    return out


def inject_context_messages(
    messages: Sequence[BaseMessage], context_messages: Sequence[BaseMessage]
) -> list[BaseMessage]:
    """
    Inserta el contexto **antes** del último mensaje humano real.

    Antes y no después: así el modelo lee el proyecto y luego la petición, que es el
    orden en que un humano lo entendería. Y antes y no en el system prompt: así entra en
    la caché como un mensaje más y la compactación lo puede arrastrar en su ventana.
    """
    if not context_messages:
        return list(messages)

    msgs = list(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], HumanMessage) and not is_context_message(msgs[i]):
            return [*msgs[:i], *context_messages, *msgs[i:]]
    return [*msgs, *context_messages]
