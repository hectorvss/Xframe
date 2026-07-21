"""
Vocabulario del contexto de UI.

Porta `MaxUIContext` de `ee/hogai/context/context.py`. La decisión de diseño que hay
que respetar es la misma que allí:

> El contexto **no es un puntero (id), es el objeto semiserializado**.

El frontend manda el shot entero con su spec, no `shot_id`. El backend lo *enriquece*
(igual que PostHog ejecuta la query del insight y adjunta los resultados): a cada plano
le pega su estado de render, su asset y lo que costó. Así el modelo puede razonar sobre
lo que el usuario está mirando sin gastar un turno entero en tool calls de lectura.

Nada de esto entra en el estado del grafo ni en el checkpoint: se reconstruye en cada
turno desde la BD y se inyecta como mensaje de contexto. El estado guarda `AssetRef`;
esto guarda la foto completa del proyecto, que es cara de serializar y barata de releer.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Pestaña abierta                                                              #
# --------------------------------------------------------------------------- #


class OpenTab(StrEnum):
    """
    Qué está mirando el usuario. Equivale a la ruta del frontend en PostHog, y sirve
    para lo mismo: determinar qué herramientas contextuales existen en este turno y
    qué parte del contexto merece detalle.

    Los valores coinciden con los de `setTab(...)` en `src/main.jsx`.
    """

    BRIEF = "brief"
    CANVAS = "canvas"
    ASSETS = "assets"
    ELEMENTS = "elements"
    PREVIEW = "preview"
    SCRIPT = "script"
    AUDIO = "audio"
    CHAT = "chat"


# --------------------------------------------------------------------------- #
# Piezas                                                                       #
# --------------------------------------------------------------------------- #


class BriefBlock(BaseModel):
    """
    Un bloque del briefing, tal cual está en `brief_blocks`.

    El brief es el documento fundacional del proyecto: de aquí sale el tratamiento y,
    más tarde, la biblia de estilo. Va entero al contexto salvo que no quepa, porque
    es barato comparado con la timeline y es lo que fija la intención del usuario.
    """

    id: str
    position: int
    type: str = "text"
    text: str = ""
    checked: bool = False
    src: str | None = None


class CameraSpec(BaseModel):
    """Bloque de cámara de un plano. Todo opcional: un plano se puede especificar a medias."""

    motion: str | None = None
    strength: float | None = None
    lens: str | None = None
    aperture: str | None = None


class AssetContext(BaseModel):
    """
    Un asset generado o subido.

    Lleva `prompt` y `model_id` a propósito: sin eso el agente no puede contestar a
    "hazme otro como ese pero de noche", que es la petición más frecuente que existe.
    """

    id: str
    name: str
    kind: str
    """`assets.type`: image | video | audio | cut."""

    status: Literal["generating", "ready", "failed"] = "ready"
    meta: str = ""
    role: str | None = None
    """Si tiene rol, este asset es además un Element."""

    shot_id: str | None = None
    model_id: str | None = None
    prompt: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    credits_spent: int = 0
    parent_id: str | None = None
    created_at: datetime | None = None


class ElementContext(BaseModel):
    """
    Personaje, localización u objeto. El sistema de continuidad del proyecto.

    `sheet` es la ficha destilada por el colector de memoria (`project_memory` con
    `kind='character_sheet'` y `element_id` apuntando a este asset). Es lo que hace que
    el mismo personaje se parezca a sí mismo entre planos, y por eso viaja aquí y se
    reinyecta tras compactar.

    Se referencia con `@nombre` porque es como ya funciona la UI: `EditorChat` inserta
    menciones `@` desde la lista de elements y el usuario las escribe a mano. Si el
    agente usara ids, el usuario y el agente hablarían idiomas distintos.
    """

    id: str
    name: str
    role: str
    meta: str = ""
    sheet: str | None = None
    thumb_url: str | None = None

    status: Literal["generating", "ready", "failed"] = "ready"
    """Estado del asset que respalda al element. Sin él no se puede saber si sirve."""

    @property
    def usable_as_reference(self) -> bool:
        """
        ¿Puede pasarse a un proveedor como referencia visual?

        Existe también en `taxonomy.repo.Element`, y **esa es la comprobación
        autoritativa**: allí se exige además que haya URL, y es la que consultan el
        builder y las tools antes de gastar créditos. Aquí se replica porque un
        `ElementContext` es lo que el contexto entrega al resto del sistema, y preguntarle
        si un element sirve es lo natural: sin la propiedad, quien lo intentaba se comía
        un `AttributeError` en tiempo de ejecución en vez de una respuesta.

        Un asset solo llega a `ready` después de que el worker haya subido el binario, así
        que el estado implica la existencia de la imagen.
        """
        return self.status == "ready"

    @property
    def mention(self) -> str:
        """`@nombre-del-element`, con espacios colapsados para que la mención sea un token."""
        return "@" + "-".join(self.name.split())


class ShotContext(BaseModel):
    """
    Un plano del canvas, con su spec COMPLETA y su estado de render.

    Es el equivalente exacto de `MaxInsightContext` + resultados ejecutados: PostHog
    adjunta la query *y* la tabla de resultados; nosotros adjuntamos la spec *y* el
    render. Un plano sin su estado de render es una invitación a que el agente
    regenere algo que ya existe, y eso se paga en créditos.
    """

    id: str
    position: int | None = None
    """
    Orden narrativo (`canvas_nodes.position`). No es cosmético: es la señal que le dice
    al modelo qué plano va antes de cuál y, por tanto, qué continuidad debe respetar.
    """

    type: str = "shot"
    title: str = ""
    text: str = ""
    """Descripción del plano tal cual la escribió el usuario en el canvas."""

    status: str = "pending"
    """`canvas_nodes.shot_status`: pending | generating | ready | failed | approved."""

    spec: dict[str, Any] = Field(default_factory=dict)
    """`canvas_nodes.spec`: prompt final, duración, semilla, overrides."""

    camera: CameraSpec = Field(default_factory=CameraSpec)
    element_names: list[str] = Field(default_factory=list)
    """Nombres de elements implicados. Se serializan como `@nombre`."""

    asset: AssetContext | None = None
    """El render asociado, si lo hay."""

    # Coordenadas del canvas. Solo se usan como desempate del orden narrativo cuando
    # `position` es NULL (un plano recién soltado en el lienzo todavía no lo tiene).
    x: float = 0.0
    y: float = 0.0

    @property
    def prompt(self) -> str:
        """El prompt efectivo del plano: el de la spec, y si no, la descripción del nodo."""
        value = self.spec.get("prompt") or self.text or ""
        return str(value)

    @property
    def duration_s(self) -> float | None:
        value = self.spec.get("duration_s") or self.spec.get("duration")
        return float(value) if value is not None else None

    @property
    def model_id(self) -> str | None:
        model = self.spec.get("model_id") or self.spec.get("model")
        if model:
            return str(model)
        return self.asset.model_id if self.asset else None


class GenSettings(BaseModel):
    """
    Ajustes de generación por defecto, de `profiles.settings`.

    El agente los necesita para no preguntar lo que ya está decidido. Son *defectos*,
    no restricciones: un plano puede sobrescribirlos en su spec.
    """

    model: str | None = None
    aspect: str | None = None
    resolution: str | None = None
    duration_s: float | None = None
    style: str | None = None
    camera: str | None = None
    mode: str | None = None
    genre: str | None = None
    sound: bool | None = None
    count: int | None = None

    camera_move: str | None = None
    """Movimiento de cámara elegido en el compositor (id del catálogo, p. ej. 'pan-left')."""

    speed_ramp: str | None = None
    """Rampa de velocidad del clip ('Lento → Rápido', 'Impacto'…). Es dirección de ritmo."""

    start_frame: str | None = None
    """Asset id de la imagen que debe ser el PRIMER frame del vídeo (i2v)."""

    end_frame: str | None = None
    """Asset id de la imagen que debe ser el ÚLTIMO frame (first-and-last-frame).
    start/end frame son la mecánica de las transiciones escena a escena: el último
    frame de una escena es el primero de la siguiente."""

    extra: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Guía del usuario: conocimiento y habilidades                                 #
# --------------------------------------------------------------------------- #


class KnowledgeSource(BaseModel):
    """Una fuente de conocimiento: nota, página web leída o archivo subido."""

    title: str = ""
    kind: str = "note"  # note | url | file
    url: str | None = None
    excerpt: str = ""
    """
    Resumen corto, NO el contenido entero. Una fuente puede tener 40.000 caracteres
    y meterlos en cada turno arruinaría el presupuesto de contexto. El extracto da el
    tema; si hiciera falta el texto completo, sería con una tool.
    """


class ProjectSkill(BaseModel):
    """Una habilidad activa: instrucción reutilizable que el usuario ha definido."""

    name: str = ""
    description: str = ""
    instructions: str = ""
    triggers: list[str] = Field(default_factory=list)


class Guidance(BaseModel):
    """
    Lo que el usuario define en Ajustes → Conocimiento y Habilidades.

    Es autoría del dueño de la cuenta, no material raspado: son sus INSTRUCCIONES
    permanentes. La biblia de estilo (memoria) las refina a partir de lo que aprueba;
    esto es lo que declara de entrada y se aplica desde el primer turno. Las fuentes
    web sí son contenido externo, y por eso se presentan como material de referencia,
    no como órdenes.
    """

    knowledge: str = ""
    """Instrucciones generales del espacio (y del proyecto, si las hay)."""

    sources: list[KnowledgeSource] = Field(default_factory=list)
    skills: list[ProjectSkill] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.knowledge.strip() or self.sources or self.skills)


# --------------------------------------------------------------------------- #
# El contexto completo                                                         #
# --------------------------------------------------------------------------- #


class XframeUIContext(BaseModel):
    """
    Memoria completa del proyecto para un turno.

    Requisito explícito del producto: el agente conoce **todo** el proyecto — todos los
    assets generados, el canvas, el briefing y los elements. Lo que no cabe en el
    presupuesto de tokens no se omite en silencio: se degrada por peldaños y se declara
    con un truncado autoconsciente ("…y 24 planos más"), de modo que el modelo sabe que
    hay más y puede pedirlo con una tool.
    """

    project_id: str
    project_title: str = ""
    open_tab: OpenTab = OpenTab.ASSETS

    brief: list[BriefBlock] = Field(default_factory=list)

    timeline: list[ShotContext] = Field(default_factory=list)
    """Planos en ORDEN NARRATIVO. Ver `narrative_sort_key`."""

    elements: list[ElementContext] = Field(default_factory=list)
    recent_assets: list[AssetContext] = Field(default_factory=list)
    selected_assets: list[AssetContext] = Field(default_factory=list)

    screenplay: list[dict[str, Any]] = Field(default_factory=list)
    """Editable scenes with ordered dialogue/action lines."""
    character_voices: list[dict[str, Any]] = Field(default_factory=list)
    audio_cues: list[dict[str, Any]] = Field(default_factory=list)
    transitions: list[dict[str, Any]] = Field(default_factory=list)

    gen_settings: GenSettings = Field(default_factory=GenSettings)
    credits: int = 0

    total_assets: int = 0
    """Total real en BD. `recent_assets` es una ventana; esto es el censo."""

    guidance: Guidance = Field(default_factory=Guidance)
    """Conocimiento y habilidades definidos por el usuario en Ajustes."""


def narrative_sort_key(shot: ShotContext) -> tuple[int, float, float, float]:
    """
    Orden narrativo del timeline.

    Primero `position` (el orden que el usuario ha fijado explícitamente), y para los
    planos que todavía no lo tienen, el orden de lectura del lienzo `(y, x)` — que es
    literalmente cómo PostHog ordena los insights de un dashboard por su layout.

    La tupla empieza con un 0/1 para que los planos sin `position` caigan al final en
    bloque en vez de intercalarse por azar.
    """
    if shot.position is not None:
        return (0, float(shot.position), 0.0, 0.0)
    return (1, 0.0, shot.y, shot.x)
