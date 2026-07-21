"""
Tipos de artefacto.

Un artefacto es un documento persistido, versionado y con id estable que (a) el usuario
ve renderizado, (b) el agente puede referenciar en turnos posteriores y (c) puede
componerse dentro de otro artefacto. La diferencia entre "el agente te describe un
guion" y "el agente crea un guion que existe".

La distinción central, copiada de PostHog, es **lo que se guarda ≠ lo que se envía**:

- `Stored*Block` es lo que va a la columna `artifacts.content`. Contiene **referencias**
  (`ShotRefBlock`, `AssetRefBlock`), no copias.
- `Enriched*Block` es lo que llega al frontend, con la referencia ya resuelta.

Por qué importa aquí más que en un producto de analítica: un plano se regenera muchas
veces. Si el guion, el timeline y el plan guardaran una copia del plano, regenerarlo
dejaría tres documentos desincronizados y el usuario vería el corte viejo en dos de
ellos. Con referencias, regenerar un plano actualiza todo lo que lo referencia sin
tocar ningún documento.

Corolario incómodo que hay que modelar desde el principio: una referencia puede
romperse (el usuario borra el plano). La resolución degrada ese bloque a `ErrorBlock` y
sigue: **un documento no se pierde porque una de sus referencias haya desaparecido**.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeVar, Union

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Bloques comunes                                                              #
# --------------------------------------------------------------------------- #


class TextBlock(BaseModel):
    """Prosa. Idéntico guardado y enriquecido: no referencia nada."""

    type: Literal["text"] = "text"
    text: str
    heading: bool = False


class ErrorBlock(BaseModel):
    """
    Referencia rota. Es un tipo de bloque de primera clase, no una excepción.

    Modelarlo así es lo que permite que un guion con veinte planos y uno borrado siga
    siendo un guion de veinte bloques, uno de ellos marcado. La alternativa —fallar la
    lectura— convierte un borrado accidental en pérdida del documento entero.
    """

    type: Literal["error"] = "error"
    message: str
    ref_kind: str | None = None
    ref_id: str | None = None


class LoadingBlock(BaseModel):
    """Referencia a algo que todavía se está generando. Placeholder explícito para que
    la UI no tenga que distinguir "vacío" de "en curso"."""

    type: Literal["loading"] = "loading"
    label: str = "Generando…"
    ref_id: str | None = None


# --------------------------------------------------------------------------- #
# Referencias (lo que se guarda)                                               #
# --------------------------------------------------------------------------- #


class ShotRefBlock(BaseModel):
    """
    Referencia a un plano. **El bloque clave de todo el sistema.**

    Guarda solo el `shot_id`. Al resolverse trae el título, la ficha técnica y el asset
    vigente del plano, así que un plano regenerado se ve actualizado en el guion, en el
    timeline y en el plan a la vez, sin escribir en ninguno de los tres.
    """

    type: Literal["shot_ref"] = "shot_ref"
    shot_id: str
    note: str | None = None
    """Anotación propia del documento (una acotación del guion, por ejemplo). Es lo
    único que este bloque puede decir del plano por su cuenta."""


class AssetRefBlock(BaseModel):
    """Referencia a un asset concreto, cuando importa esta versión y no la vigente
    (una comparativa de dos tomas, por ejemplo)."""

    type: Literal["asset_ref"] = "asset_ref"
    asset_id: str
    caption: str | None = None


# --------------------------------------------------------------------------- #
# Bloques resueltos (lo que se envía)                                          #
# --------------------------------------------------------------------------- #


class ShotBlock(BaseModel):
    """`ShotRefBlock` resuelto."""

    type: Literal["shot"] = "shot"
    shot_id: str
    position: int | None = None
    title: str = ""
    description: str = ""
    spec: dict[str, Any] = Field(default_factory=dict)
    shot_status: str = "pending"
    asset_id: str | None = None
    asset_url: str | None = None
    note: str | None = None


class AssetBlock(BaseModel):
    """`AssetRefBlock` resuelto."""

    type: Literal["asset"] = "asset"
    asset_id: str
    name: str = ""
    kind: str = "image"
    url: str | None = None
    status: str = "ready"
    caption: str | None = None


StoredBlock = Annotated[
    TextBlock | ShotRefBlock | AssetRefBlock | LoadingBlock, Field(discriminator="type")
]
EnrichedBlock = Annotated[
    TextBlock | ShotBlock | AssetBlock | LoadingBlock | ErrorBlock,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
# Contenidos de artefacto                                                      #
# --------------------------------------------------------------------------- #


class _BaseContent(BaseModel):
    title: str = ""
    blocks: list[StoredBlock] = Field(default_factory=list)


class ScriptArtifactContent(_BaseContent):
    """Guion: prosa con planos intercalados por referencia."""

    content_type: Literal["script"] = "script"


class ScreenplayArtifactContent(_BaseContent):
    """Structured screenplay snapshot.

    Scenes and lines remain normalized in their own tables so the UI can edit and
    collaborate at line granularity.  The artifact stores stable references and is the
    immutable version the user approved before voice/video generation.
    """

    content_type: Literal["screenplay"] = "screenplay"
    scene_ids: list[str] = Field(default_factory=list)
    cast_element_ids: list[str] = Field(default_factory=list)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    language: str = "es"
    target_duration_s: float | None = None


class TimelineArtifactContent(_BaseContent):
    """Timeline: la secuencia de planos con sus duraciones."""

    content_type: Literal["timeline"] = "timeline"
    total_duration_s: float | None = None


class AudioPlanArtifactContent(_BaseContent):
    """Versioned snapshot of the multitrack sound direction for a cut."""

    content_type: Literal["audio_plan"] = "audio_plan"
    cue_ids: list[str] = Field(default_factory=list)
    cue_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    buses: dict[str, Any] = Field(default_factory=dict)
    target_lufs: float = -14.0
    true_peak_dbtp: float = -1.0
    total_duration_s: float | None = None


class CutArtifactContent(_BaseContent):
    """Montaje: el corte entregado y los planos que lo componen."""

    content_type: Literal["cut"] = "cut"
    cut_asset_id: str | None = None


class PlanArtifactContent(_BaseContent):
    """Plan de producción: lo que se va a rodar y lo que cuesta. Es el documento que el
    usuario aprueba antes de que se gaste un crédito, así que su coste estimado forma
    parte del contenido y no de un mensaje suelto que se pierde en el historial."""

    content_type: Literal["plan"] = "plan"
    estimated_credits: int = 0


StoredContent = Union[
    ScriptArtifactContent,
    ScreenplayArtifactContent,
    TimelineArtifactContent,
    AudioPlanArtifactContent,
    CutArtifactContent,
    PlanArtifactContent,
]

CONTENT_BY_KIND: dict[str, type[BaseModel]] = {
    "script": ScriptArtifactContent,
    "screenplay": ScreenplayArtifactContent,
    "timeline": TimelineArtifactContent,
    "audio_plan": AudioPlanArtifactContent,
    "cut": CutArtifactContent,
    "plan": PlanArtifactContent,
}
"""
`artifacts.kind` (columna, con CHECK) → clase de contenido. La tabla es la fuente de
verdad del conjunto de tipos válidos; este diccionario solo lo traduce a Python.
"""

T_Stored = TypeVar("T_Stored", bound=BaseModel)
