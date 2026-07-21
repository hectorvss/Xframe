"""
Construcción del toolset en runtime. Esta es la pieza central del sistema.

La tesis, heredada del taxonomy toolkit de PostHog y agravada en nuestro caso por la
volatilidad de los proveedores: **un `Literal[...]` hardcodeado es deuda con fecha de
caducidad conocida**. Veo 3.0 ya está apagado, Runway Gen-3/Gen-4 se apagan el 30 de
julio de 2026 y Sora 2 el 24 de septiembre. Si el enum vive en el código, apagar un
modelo es un despliegue; si vive en la BD, es un `UPDATE`.

Así que las tools no se instancian: se **construyen**. Para cada turno se lee la
taxonomía, se generan los `args_schema` con `pydantic.create_model` incrustando
`Literal[...]` poblados desde la BD, y se reescribe la `description` con lo que hay
disponible ahora mismo.

Cuatro consecuencias, y las cuatro son el motivo de que esto exista:

1. El modelo **no puede alucinar** un modelo apagado, un movimiento de cámara
   inventado ni un personaje inexistente: el enum acaba en el JSON Schema de la tool,
   no en una frase del prompt. Una restricción del esquema se cumple siempre; una
   instrucción del prompt se cumple casi siempre, y "casi" aquí se paga en créditos.
2. **La descripción nunca miente.** Se compone a partir del mismo snapshot que el
   esquema, así que no puede describir un modelo que el enum no admite.
3. **Los modos son estructurales.** En `preproduction` las tools de generación no se
   montan. No es que estén prohibidas: no existen. No hay prompt que las invoque.
4. **Un recurso restringido por plan es indistinguible de uno inexistente.** El
   usuario `free` nunca ve que Seedance 2.0 existe, así que el agente no se lo propone
   para luego fallar al ejecutarlo.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from app.taxonomy.repo import TaxonomySnapshot, load_snapshot
from app.tools.base import ToolContext, XframeTool

logger = logging.getLogger(__name__)


def _reference_path(url: str | None) -> str:
    """
    `assets.url` → ruta dentro del bucket, lista para firmarse más tarde.

    Aquí NO se firma, y ese es el punto. La taxonomía se cachea (`PROJECT_TTL_S`) y los
    `ElementRef` que salen de aquí acaban serializados en `generation_jobs.request`: una
    URL firmada puesta en este punto caducaría dentro de la caché y, peor, dentro de una
    fila de base de datos que se rehidrata en cada reintento. La firma es competencia del
    worker, inmediatamente antes del `submit`.

    Se normaliza en vez de copiar el valor tal cual para que la migración de los datos
    existentes no tenga que ser atómica: `object_path` acepta las URLs públicas que hoy
    hay en producción y las rutas que escribe el worker nuevo, y devuelve lo mismo para
    las dos. Lo que no reconoce —una URL externa que alguien pegó a mano— se deja intacto:
    romper esa referencia sería peor que dejarla pasar sin firmar.
    """
    from app.storage import StorageError, object_path

    if not url:
        return ""
    try:
        return object_path(url)
    except StorageError:
        return url


# --------------------------------------------------------------------------- #
# Base con snapshot                                                            #
# --------------------------------------------------------------------------- #


class SnapshotTool(XframeTool):
    """
    Tool que necesita ver la taxonomía en ejecución, no solo en su esquema.

    El esquema impide referenciar lo que no existe, pero sigue haciendo falta resolver
    (nombre de personaje → uuid, id de modelo → coste) y validar lo que el esquema no
    puede expresar, como que la duración pedida cabe en el rango del modelo elegido.
    """

    __abstract__ = True

    _snap: TaxonomySnapshot | None = None

    def bind_snapshot(self, snap: TaxonomySnapshot) -> SnapshotTool:
        self._snap = snap
        return self

    @property
    def snap(self) -> TaxonomySnapshot:
        if self._snap is None:
            raise RuntimeError(f"{self.name} used without a bound TaxonomySnapshot")
        return self._snap

    # -- resolución de entidades ------------------------------------------- #

    def resolve_elements(self, names: Sequence[str] | None) -> list[Any]:
        """
        Nombres de personajes/localizaciones → `ElementRef` listos para el proveedor.

        Doble red, y las dos hacen falta:

        - El `Literal` del esquema impide *escribir* un nombre inexistente en el 99 %
          de los casos.
        - Este método lo comprueba igualmente, porque el esquema puede quedarse atrás
          (el usuario borra un personaje a mitad de turno) y porque no todos los
          modelos respetan el enum al pie de la letra.

        El error enumera las opciones válidas: es lo que permite al modelo corregirse
        en el turno siguiente en vez de repetir el mismo nombre inventado.
        """
        from app.providers.base import ElementRef
        from app.tools.errors import UnknownEntityError, XframeToolRetryableError

        refs: list[ElementRef] = []
        valid = self.snap.element_names()
        for name in names or []:
            element = self.snap.element_by_name(name)
            if element is None:
                raise UnknownEntityError("element", name, valid)
            if not element.usable_as_reference:
                raise XframeToolRetryableError(
                    f"Element '{element.name}' exists but has no usable reference image "
                    f"(status={element.status}). Generate or upload its image first with "
                    f"define_element, or drop it from element_refs for this shot."
                )
            refs.append(
                ElementRef(
                    element_id=element.id,
                    name=element.name,
                    role=element.role,
                    image_url=_reference_path(element.url),
                )
            )
        return refs

    def require_model(self, model_id: str, modality: str) -> Any:
        """
        Id de modelo → `GenModel`, o error que enumera los válidos de esa modalidad.

        Distingue "no existe / no lo tienes" de "está apagado": si el modelo consta
        como retirado se lanza `ModelRetiredError` con alternativas, porque el agente
        (y sus datos de entrenamiento) van a seguir pidiendo Veo 3.0 durante meses.
        """
        from app.tools.errors import ModelRetiredError, UnknownEntityError

        model = self.snap.model(model_id)
        alternatives = self.snap.model_ids(modality)  # type: ignore[arg-type]
        if model is None:
            raise UnknownEntityError("model", model_id, alternatives)
        if model.modality != modality:
            raise UnknownEntityError(f"{modality} model", model_id, alternatives)
        if model.status == "retired":
            raise ModelRetiredError(model_id, alternatives)
        return model

    @classmethod
    async def create(
        cls, ctx: ToolContext, snap: TaxonomySnapshot
    ) -> SnapshotTool | None:
        """
        Factoría. Devolver `None` significa "esta tool no se monta en este contexto".

        Es el mecanismo con el que una tool se retira sola: `generate_video` devuelve
        `None` si este plan no tiene ni un modelo de vídeo activo. Mejor no ofrecerla
        que ofrecerla con un enum vacío, que es un esquema inválido, o con un enum de
        un solo valor falso, que es una mentira.
        """
        return cls().bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Utilidades de esquema                                                        #
# --------------------------------------------------------------------------- #


def literal_of(values: Sequence[str]) -> Any:
    """
    `Literal[...]` a partir de una lista en runtime.

    Devuelve `str` si la lista está vacía, porque `Literal[()]` es un tipo inválido.
    Ese caso no debería llegar aquí: quien construye la tool debe haber decidido antes
    no montarla. Degradar a `str` es la red de seguridad, no el camino previsto.
    """
    if not values:
        return str
    return Literal[tuple(values)]  # type: ignore[valid-type]


def enumerate_for_prompt(items: Sequence[Any], *, limit: int = 60) -> str:
    """
    Vuelca el catálogo en la descripción de la tool, una línea por entrada.

    Se trunca porque esta descripción viaja en **todos** los turnos de la conversación:
    un catálogo de 200 modelos convertiría el system prompt en el mayor coste fijo del
    sistema. Si se trunca, `list_available_models` es la vía para ver el resto.
    """
    lines = [it.summary_for_llm() for it in items[:limit]]
    if len(items) > limit:
        lines.append(f"…and {len(items) - limit} more — call list_available_models to see them.")
    return "\n".join(f"- {line}" for line in lines)


def build_args(model_name: str, /, **fields: tuple[Any, Any]) -> type[BaseModel]:
    """
    Azúcar sobre `create_model` para que los `create()` se lean como esquemas.

    El nombre es posicional-only porque `name` es un campo legítimo de varias tools
    (`define_element`, por ejemplo) y colisionaría con el parámetro.
    """
    return create_model(model_name, **fields)  # type: ignore[call-overload,no-any-return]


def described(type_: Any, description: str, default: Any = ...) -> tuple[Any, Any]:
    """Campo con descripción. La descripción del campo es tan leída como la de la tool."""
    return (type_, Field(default, description=description))


# --------------------------------------------------------------------------- #
# Registro de tools por modo                                                   #
# --------------------------------------------------------------------------- #


def _tool_classes() -> list[type[SnapshotTool]]:
    """
    Importación perezosa: los módulos de tools importan de aquí (`SnapshotTool`,
    `literal_of`), así que importarlos arriba sería un ciclo.
    """
    from app.tools import (
        brief,
        canvas,
        elements,
        generation,
        manifests,
        meta,
        production,
        production_crud,
        project,
        quality,
        shots,
    )

    return [
        # Lectura y planificación
        project.ReadProjectTool,
        project.SearchAssetsTool,
        project.ListAvailableModelsTool,
        project.EstimateCostTool,
        brief.WriteBriefTool,
        brief.UpdateBriefBlockTool,
        brief.AppendBriefBlockTool,
        brief.DeleteBriefBlockTool,
        *canvas.CANVAS_TOOL_CLASSES,
        shots.CreateShotTool,
        shots.UpdateShotTool,
        shots.ReorderShotsTool,
        shots.DeleteShotTool,
        elements.DefineElementTool,
        # Structured screenplay, cast, sound and edit intent
        *production.PRODUCTION_TOOL_CLASSES,
        *production_crud.PRODUCTION_CRUD_TOOL_CLASSES,
        *manifests.MANIFEST_TOOL_CLASSES,
        *quality.QUALITY_TOOL_CLASSES,
        # Generación
        generation.GenerateImageTool,
        generation.GenerateVideoTool,
        generation.GenerateShotBatchTool,
        generation.GenerateAudioTool,
        generation.ExecuteAssetOperationTool,
        generation.GenerateLipsyncTool,
        generation.GenerateTransitionTool,
        # `UpscaleAssetTool` retirada: no hay modelo de upscale en `gen_models` ni
        # adaptador que lo sirva. El porqué, en `app/tools/generation.py`.
        generation.AssembleVideoTool,
        # Meta
        meta.FinalizePlanTool,
        meta.CheckJobStatusTool,
        meta.SwitchModeTool,
    ]


async def build_tools_for_mode(
    ctx: ToolContext,
    *,
    snapshot: TaxonomySnapshot | None = None,
    include_meta: bool = True,
) -> list[XframeTool]:
    """
    Construye el toolset del modo actual.

    `include_meta=False` corta la recursión: `switch_mode` necesita saber qué tools
    existirían en los otros modos para describirlos con verdad, y para eso los
    construye de verdad. Sin esta bandera, construir `switch_mode` construiría
    `switch_mode` construyendo `switch_mode`.

    El snapshot se pasa una sola vez y se reutiliza: además de ahorrar consultas,
    garantiza que todas las tools del turno vean exactamente el mismo catálogo.
    """
    snap = snapshot or await load_snapshot(ctx.project_id, ctx.user_id)

    tools: list[XframeTool] = []
    for cls in _tool_classes():
        # Filtro por modo. Esto es la restricción estructural del punto 3: no se
        # instancia, luego no existe, luego no hay forma de invocarla.
        if ctx.mode not in cls.modes:
            continue
        if not include_meta and getattr(cls, "is_meta", False):
            continue
        try:
            tool = await cls.create(ctx, snap)
        except Exception:
            # Una tool que no se puede construir no debe tumbar el turno entero: se
            # cae ella sola y el agente sigue con las demás.
            logger.exception("tool_build_failed", extra={"tool": cls.__name__})
            continue
        if tool is not None:
            tools.append(tool)

    logger.info(
        "toolset_built",
        extra={
            "mode": ctx.mode,
            "plan": snap.plan,
            "tools": [t.name for t in tools],
            "models": len(snap.models),
            "elements": len(snap.elements),
        },
    )
    return tools


async def modes_with_tools(ctx: ToolContext, snap: TaxonomySnapshot) -> dict[str, list[str]]:
    """
    Qué tools existirían en cada modo, construyéndolas de verdad.

    Lo usa `switch_mode` para generar su propia descripción. Preguntárselo al builder
    en vez de mantener una tabla es lo que hace que el catálogo no pueda mentir: si
    mañana una tool cambia de modo, la descripción de `switch_mode` cambia con ella
    sin que nadie lo recuerde.
    """
    from app.agent.state import AgentMode

    out: dict[str, list[str]] = {}
    for mode in AgentMode:
        probe = ctx.model_copy(update={"mode": mode.value})
        built = await build_tools_for_mode(probe, snapshot=snap, include_meta=False)
        out[mode.value] = [t.name for t in built]
    return out
