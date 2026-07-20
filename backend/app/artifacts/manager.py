"""
Gestor de artefactos.

Dos responsabilidades y ninguna más:

1. **Persistir** contenido en la tabla `artifacts`, versionado por `(project_id, kind)`.
   Versionar en vez de sobrescribir es lo que permite que el usuario compare el plan que
   aprobó con el que el agente propone ahora.
2. **Enriquecer**: resolver las referencias (`ShotRefBlock`, `AssetRefBlock`) contra la
   BD justo antes de enviar el documento al frontend.

El manager no sabe qué es un guion ni un timeline. Sabe pedirle a un handler que
enriquezca un contenido, y los handlers se registran con un decorador. Añadir un tipo
de artefacto es escribir un handler y decorarlo; este fichero no se toca.

Sobre la degradación: enriquecer resuelve las referencias **en bloque** (una consulta
para todos los planos, otra para todos los assets) y cualquier referencia que no
aparezca en el resultado se convierte en `ErrorBlock`. Nunca lanza. La razón es que la
alternativa —propagar el fallo— hace que borrar un plano rompa la lectura del guion
entero, y el usuario pierde un documento por un borrado que creía inocuo.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from app import db
from app.artifacts.types import (
    CONTENT_BY_KIND,
    AssetBlock,
    AssetRefBlock,
    CutArtifactContent,
    EnrichedBlock,
    ErrorBlock,
    LoadingBlock,
    PlanArtifactContent,
    ScriptArtifactContent,
    ShotBlock,
    ShotRefBlock,
    StoredContent,
    TextBlock,
    TimelineArtifactContent,
)

logger = logging.getLogger(__name__)

T_Stored = TypeVar("T_Stored", bound=BaseModel)


# --------------------------------------------------------------------------- #
# Contexto y registro de handlers                                              #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class EnrichmentContext:
    """Lo que un handler necesita para resolver referencias. `project_id` es
    obligatorio: es el filtro que sustituye a RLS en la conexión de servicio."""

    project_id: str
    artifact_id: str | None = None


class ArtifactHandler(ABC, Generic[T_Stored]):
    """
    Handler de un tipo de artefacto.

    Declara con qué clase de contenido trabaja, a qué `kind` de la tabla corresponde, y
    cómo convertir el contenido guardado en contenido enriquecido.
    """

    content_class: type[T_Stored]
    db_kind: str

    @abstractmethod
    async def aenrich(self, content: T_Stored, context: EnrichmentContext) -> dict[str, Any]:
        """Contenido guardado → contenido listo para el frontend. No debe lanzar por una
        referencia rota: eso se degrada, no se propaga."""

    def validate(self, data: dict[str, Any]) -> T_Stored:
        return self.content_class.model_validate(data)

    def get_metadata(self, content: T_Stored) -> dict[str, Any]:
        """Metadatos de presentación (título, contadores). Los usa la lista de artefactos
        sin tener que cargar y enriquecer el documento entero."""
        return {"title": getattr(content, "title", ""), "blocks": len(getattr(content, "blocks", []))}


HANDLER_REGISTRY: dict[type, ArtifactHandler] = {}
_HANDLERS_BY_KIND: dict[str, ArtifactHandler] = {}

T_Handler = TypeVar("T_Handler", bound=type[ArtifactHandler])


def register_handler(handler_class: T_Handler) -> T_Handler:
    """
    Decorador de registro.

        @register_handler
        class ScriptHandler(ArtifactHandler[ScriptArtifactContent]):
            ...
    """
    instance = handler_class()  # type: ignore[call-arg]
    HANDLER_REGISTRY[instance.content_class] = instance
    _HANDLERS_BY_KIND[instance.db_kind] = instance
    return handler_class


def get_handler_for_content_class(content_class: type) -> ArtifactHandler:
    handler = HANDLER_REGISTRY.get(content_class)
    if handler is None:
        raise ValueError(f"No artifact handler registered for {content_class.__name__}")
    return handler


def get_handler_for_kind(kind: str) -> ArtifactHandler | None:
    return _HANDLERS_BY_KIND.get(kind)


# --------------------------------------------------------------------------- #
# Resolución de referencias                                                    #
# --------------------------------------------------------------------------- #


async def _resolve_blocks(
    blocks: Sequence[Any], context: EnrichmentContext
) -> list[EnrichedBlock]:
    """
    Resuelve todas las referencias de una lista de bloques.

    Dos consultas como mucho, sea cual sea el tamaño del documento: resolver bloque a
    bloque convertiría un guion de cuarenta planos en cuarenta y una consultas por cada
    lectura, y estos documentos se leen en cada render de la UI.
    """
    shot_ids = [b.shot_id for b in blocks if isinstance(b, ShotRefBlock)]
    asset_ids = [b.asset_id for b in blocks if isinstance(b, AssetRefBlock)]

    shots: dict[str, Any] = {}
    if shot_ids:
        rows = await db.fetch(
            """
            select n.id, n.position, n.title, n.text, n.spec, n.shot_status,
                   a.id as asset_id, a.url as asset_url
              from public.canvas_nodes n
              left join lateral (
                   select id, url from public.assets
                    where shot_id = n.id::text and status = 'ready'
                    order by created_at desc limit 1
              ) a on true
             where n.project_id = $1::uuid and n.id = any($2::uuid[])
            """,
            context.project_id,
            shot_ids,
        )
        shots = {str(r["id"]): r for r in rows}

    assets: dict[str, Any] = {}
    if asset_ids:
        rows = await db.fetch(
            """
            select id, name, type, url, status from public.assets
             where project_id = $1::uuid and id = any($2::uuid[])
            """,
            context.project_id,
            asset_ids,
        )
        assets = {str(r["id"]): r for r in rows}

    out: list[EnrichedBlock] = []
    for block in blocks:
        if isinstance(block, ShotRefBlock):
            row = shots.get(block.shot_id)
            if row is None:
                # Degradación. El documento sobrevive al borrado de un plano.
                out.append(
                    ErrorBlock(
                        message=(
                            "Este plano ya no existe en el proyecto. El resto del "
                            "documento sigue siendo válido."
                        ),
                        ref_kind="shot",
                        ref_id=block.shot_id,
                    )
                )
                continue
            out.append(
                ShotBlock(
                    shot_id=block.shot_id,
                    position=row["position"],
                    title=row["title"] or "",
                    description=row["text"] or "",
                    spec=dict(row["spec"] or {}),
                    shot_status=row["shot_status"],
                    asset_id=str(row["asset_id"]) if row["asset_id"] else None,
                    asset_url=row["asset_url"],
                    note=block.note,
                )
            )
        elif isinstance(block, AssetRefBlock):
            row = assets.get(block.asset_id)
            if row is None:
                out.append(
                    ErrorBlock(
                        message="Este recurso ya no está disponible.",
                        ref_kind="asset",
                        ref_id=block.asset_id,
                    )
                )
                continue
            out.append(
                AssetBlock(
                    asset_id=block.asset_id,
                    name=row["name"],
                    kind=row["type"],
                    url=row["url"],
                    status=row["status"],
                    caption=block.caption,
                )
            )
        elif isinstance(block, (TextBlock, LoadingBlock)):
            out.append(block)
        else:
            out.append(
                ErrorBlock(
                    message=f"Bloque de tipo desconocido: {getattr(block, 'type', '?')}.",
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Handlers                                                                     #
# --------------------------------------------------------------------------- #


class _BlockDocumentHandler(ArtifactHandler[T_Stored]):
    """Los cuatro tipos actuales son documentos de bloques y solo se diferencian en sus
    metadatos, así que comparten el enriquecido y no lo duplican cuatro veces."""

    extra_fields: tuple[str, ...] = ()

    async def aenrich(self, content: T_Stored, context: EnrichmentContext) -> dict[str, Any]:
        blocks = await _resolve_blocks(content.blocks, context)  # type: ignore[attr-defined]
        payload: dict[str, Any] = {
            "content_type": content.content_type,  # type: ignore[attr-defined]
            "title": content.title,  # type: ignore[attr-defined]
            "blocks": [b.model_dump(mode="json") for b in blocks],
            "broken_refs": sum(1 for b in blocks if isinstance(b, ErrorBlock)),
        }
        for name in self.extra_fields:
            payload[name] = getattr(content, name, None)
        return payload


@register_handler
class ScriptHandler(_BlockDocumentHandler[ScriptArtifactContent]):
    content_class = ScriptArtifactContent
    db_kind = "script"


@register_handler
class TimelineHandler(_BlockDocumentHandler[TimelineArtifactContent]):
    content_class = TimelineArtifactContent
    db_kind = "timeline"
    extra_fields = ("total_duration_s",)


@register_handler
class CutHandler(_BlockDocumentHandler[CutArtifactContent]):
    content_class = CutArtifactContent
    db_kind = "cut"
    extra_fields = ("cut_asset_id",)


@register_handler
class PlanHandler(_BlockDocumentHandler[PlanArtifactContent]):
    content_class = PlanArtifactContent
    db_kind = "plan"
    extra_fields = ("estimated_credits",)


# --------------------------------------------------------------------------- #
# Manager                                                                      #
# --------------------------------------------------------------------------- #


class ArtifactManager:
    """
    Fachada sobre la tabla `artifacts`. Un manager por proyecto.

    Todas las consultas llevan `project_id` porque el backend usa la conexión de
    servicio y salta RLS: aquí ese filtro no es una optimización, es el control de
    acceso.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    # -- escritura ---------------------------------------------------------- #

    async def acreate(self, content: StoredContent, name: str = "") -> dict[str, Any]:
        """
        Persiste una **versión nueva**, nunca sobrescribe.

        El agente reescribe el plan varias veces por conversación; que cada reescritura
        sea una versión es lo que permite responder "¿qué había cambiado respecto a lo
        que aprobé?" sin guardar diffs a mano.
        """
        handler = get_handler_for_content_class(type(content))
        async with db.transaction() as conn:
            version = await conn.fetchval(
                """
                select coalesce(max(version), 0) + 1 from public.artifacts
                 where project_id = $1::uuid and kind = $2
                """,
                self.project_id,
                handler.db_kind,
            )
            row = await conn.fetchrow(
                """
                insert into public.artifacts (project_id, kind, version, content, created_by)
                values ($1::uuid, $2, $3, $4::jsonb, 'agent')
                returning id, kind, version, created_at
                """,
                self.project_id,
                handler.db_kind,
                version,
                content.model_dump(mode="json"),
            )
        out = dict(row) | {"id": str(row["id"]), "name": name or handler.db_kind}
        logger.info("artifact_created", extra={"kind": handler.db_kind, "version": version})
        return out

    async def aupdate(self, artifact_id: str, content: StoredContent) -> dict[str, Any]:
        """Sustituye el contenido de una versión concreta. Es la excepción: se usa para
        corregir un artefacto recién creado en el mismo turno, no para editar historia."""
        row = await db.fetchrow(
            """
            update public.artifacts set content = $3::jsonb
             where id = $1::uuid and project_id = $2::uuid
            returning id, kind, version, created_at
            """,
            artifact_id,
            self.project_id,
            content.model_dump(mode="json"),
        )
        if row is None:
            raise ValueError(f"Artifact {artifact_id} not found in project {self.project_id}")
        return dict(row) | {"id": str(row["id"])}

    # -- lectura ------------------------------------------------------------ #

    async def alist(self, kind: str | None = None) -> list[dict[str, Any]]:
        """Índice de artefactos, sin enriquecer. Barato: no toca planos ni assets."""
        rows = await db.fetch(
            """
            select id, kind, version, created_by, created_at from public.artifacts
             where project_id = $1::uuid and ($2::text is null or kind = $2)
             order by kind, version desc
            """,
            self.project_id,
            kind,
        )
        return [dict(r) | {"id": str(r["id"])} for r in rows]

    async def alatest(self, kind: str) -> dict[str, Any] | None:
        """Última versión de un tipo, ya enriquecida. Es lo que quiere la UI el 95 % de
        las veces."""
        row = await db.fetchrow(
            """
            select id from public.artifacts
             where project_id = $1::uuid and kind = $2
             order by version desc limit 1
            """,
            self.project_id,
            kind,
        )
        return None if row is None else await self.aget(str(row["id"]))

    async def aget(self, artifact_id: str) -> dict[str, Any]:
        """
        Carga y enriquece un artefacto.

        Todo lo que puede fallar aquí degrada en vez de lanzar: un `kind` sin handler, un
        contenido que ya no valida contra su modelo (esquema evolucionado bajo datos
        viejos) o una referencia rota. Un documento guardado siempre se puede abrir; lo
        que no se pueda resolver se muestra como error dentro del documento.
        """
        row = await db.fetchrow(
            """
            select id, kind, version, content, created_by, created_at
              from public.artifacts where id = $1::uuid and project_id = $2::uuid
            """,
            artifact_id,
            self.project_id,
        )
        if row is None:
            raise ValueError(f"Artifact {artifact_id} not found in project {self.project_id}")

        envelope = {
            "id": str(row["id"]),
            "kind": row["kind"],
            "version": row["version"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }
        handler = get_handler_for_kind(row["kind"])
        if handler is None:
            return envelope | _degraded(
                f"No hay handler para artefactos de tipo '{row['kind']}'."
            )

        try:
            content = handler.validate(dict(row["content"] or {}))
        except ValidationError as e:
            logger.warning(
                "artifact_content_invalid",
                extra={"artifact": artifact_id, "kind": row["kind"], "err": str(e)[:300]},
            )
            return envelope | _degraded(
                "El contenido guardado de este artefacto no se puede interpretar con el "
                "esquema actual."
            )

        context = EnrichmentContext(project_id=self.project_id, artifact_id=artifact_id)
        payload = await handler.aenrich(content, context)
        return envelope | payload | {"metadata": handler.get_metadata(content)}


def _degraded(message: str) -> dict[str, Any]:
    """Documento mínimo que sigue siendo renderizable. Devolver esto en vez de lanzar es
    lo que garantiza que abrir un artefacto nunca sea un error de la aplicación."""
    return {
        "content_type": "error",
        "title": "",
        "blocks": [ErrorBlock(message=message).model_dump(mode="json")],
        "broken_refs": 1,
    }


CONTENT_CLASSES = CONTENT_BY_KIND
