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
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Iterable, Sequence
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
    OpenTab,
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


def _format_timeline(shots: Sequence[ShotContext], detail: ContextDetail, limit: int | None) -> tuple[str, int]:
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
            lines.append(f'<block type="image" src="{_attr(block.src)}"/>')
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
    return P.ASSETS_TEMPLATE.format(shown=len(shown), total=total, assets="\n".join(lines)), len(shown)


def _format_gen_settings(settings: GenSettings) -> str:
    pairs = {
        "model": settings.model,
        "aspect": settings.aspect,
        "resolution": settings.resolution,
        "duration_s": settings.duration_s,
        "style": settings.style,
        "camera": settings.camera,
    }
    attrs = "".join(f' {k}="{_attr(v)}"' for k, v in pairs.items() if v not in (None, ""))
    return P.GEN_SETTINGS_TEMPLATE.format(attrs=attrs) if attrs else ""


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

    report.sections_dropped.append("hard_truncated")
    marker = "\n" + _truncation(0, "secciones")
    return text[: max(0, budget_chars - len(marker))] + marker, report


def _shrink_plan(n_assets: int, n_shots: int) -> Iterable[tuple[int, int]]:
    """Plan de recorte: primero los assets, después los planos. Nunca por debajo de 5 planos."""
    for assets_limit in (min(n_assets, 20), 8, 0):
        yield assets_limit, n_shots
    shots_limit = n_shots
    while shots_limit > 5:
        shots_limit = max(5, shots_limit // 2)
        yield 0, shots_limit


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

    brief_xml, brief_truncated = _format_brief(ctx.brief, detail)
    if brief_xml:
        sections.append(brief_xml)

    shots_shown = 0
    if ctx.timeline:
        timeline_xml, shots_shown = _format_timeline(ctx.timeline, detail, shots_limit)
        sections.append(timeline_xml)

    if elements_xml := _format_elements(ctx.elements, detail):
        sections.append(elements_xml)

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
            return_exceptions=True,
        )
        project, brief, shots, assets_bundle, sheets, profile = [
            self._or_default(r, default) for r, default in zip(results, ({}, [], [], ([], 0), {}, {}))
        ]

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
            elements=elements,
            recent_assets=assets,
            selected_assets=selected,
            gen_settings=self._build_gen_settings(project, profile),
            credits=int(profile.get("credits", 0) or 0),
            total_assets=total_assets,
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

    async def _load_profile(self) -> dict[str, Any]:
        row = await db.fetchrow(
            "select credits, settings from public.profiles where id = $1::uuid", self._user_id
        )
        return dict(row) if row else {}

    async def _load_brief(self) -> list[BriefBlock]:
        rows = await db.fetch(
            """
            select id, position, type, text, checked, src
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
            select id, type, x, y, title, text, position, spec, shot_status
              from public.canvas_nodes
             where project_id = $1::uuid
             order by position nulls last, y, x
            """,
            self._project_id,
        )
        shots: list[ShotContext] = []
        for r in rows:
            spec = dict(r["spec"] or {})
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
                    camera=CameraSpec(**camera_raw) if isinstance(camera_raw, dict) else CameraSpec(),
                    x=float(r["x"] or 0),
                    y=float(r["y"] or 0),
                )
            )
        return shots

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
    def _attach_assets_to_shots(shots: Sequence[ShotContext], assets: Sequence[AssetContext]) -> None:
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
    def _attach_element_names(shots: Sequence[ShotContext], elements: Sequence[ElementContext]) -> None:
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
                        names.append(by_name[item.lower()].name if item.lower() in by_name else item)
                    elif isinstance(item, dict) and item.get("name"):
                        names.append(str(item["name"]))
                shot.element_names = names
                continue
            haystack = f"{shot.title} {shot.text} {shot.prompt}".lower()
            shot.element_names = [e.name for name, e in by_name.items() if name and name in haystack]

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
        known = {"model", "aspect", "resolution", "duration_s", "style", "camera"}
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

        if include_memory:
            from app.memory.store import ProjectMemoryStore

            if memory_text := await ProjectMemoryStore(self._project_id).format_for_prompt():
                candidates.append(context_message(memory_text, kind="memory"))

        return deduplicate_context_messages(existing_messages, candidates)


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
