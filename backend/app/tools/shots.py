"""
Herramientas de shot list.

Un plano es una fila de `canvas_nodes` con `type='shot'`. Dos columnas cargan con casi
todo el peso conceptual:

- `position`: el **orden narrativo**, no la posición en el lienzo. Es la señal que le
  dice al modelo qué plano va antes de cuál y, por tanto, qué continuidad debe
  respetar. Equivale al orden por layout con el que PostHog serializa los insights de
  un dashboard: sin él, el modelo ve un conjunto y no una secuencia.
- `spec` (jsonb): la ficha técnica del plano — encuadre, duración, movimiento de
  cámara, elements presentes. Es lo que consume `generate_shot_batch`, así que un
  plano bien especificado en preproducción es una generación que no hay que repetir.

El movimiento de cámara y los elements van con `Literal` construido desde la BD, igual
que en las tools de generación: no tendría sentido impedir alucinar un movimiento al
generar y permitirlo al planificar, porque el plano alucinado llegaría igual al fan-out.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, Field

from app import db
from app.taxonomy.builder import (
    SnapshotTool,
    build_args,
    described,
    enumerate_for_prompt,
    literal_of,
)
from app.taxonomy.repo import TaxonomySnapshot, invalidate_cache
from app.tools.base import ToolContext
from app.tools.errors import UnknownEntityError, XframeToolRetryableError

FRAMINGS = (
    "extreme-wide", "wide", "full", "medium-wide", "medium", "medium-close",
    "close-up", "extreme-close-up", "over-the-shoulder", "pov", "insert",
)


async def _shot_or_raise(project_id: str, shot_id: str) -> dict[str, Any]:
    """Carga un plano o lanza el error que enumera los que sí existen."""
    row = await db.fetchrow(
        """
        select id, position, title, text, spec, shot_status
          from public.canvas_nodes
         where id = $1::uuid and project_id = $2::uuid and type = 'shot'
        """,
        shot_id,
        project_id,
    )
    if row is not None:
        return dict(row) | {"id": str(row["id"])}

    valid = await db.fetch(
        """
        select id, position, title from public.canvas_nodes
         where project_id = $1::uuid and type = 'shot' order by position nulls last
        """,
        project_id,
    )
    raise UnknownEntityError(
        "shot", shot_id, [f"{r['id']} (#{r['position']} {r['title']})" for r in valid]
    )


# --------------------------------------------------------------------------- #
# create_shot / update_shot                                                    #
# --------------------------------------------------------------------------- #


class _ShotToolBase(SnapshotTool):
    """Fábrica común: `create_shot` y `update_shot` comparten vocabulario cinematográfico
    y deben compartirlo *exactamente*, o el agente aprenderá dos dialectos distintos."""

    __abstract__ = True

    @staticmethod
    def _spec_fields(snap: TaxonomySnapshot, *, required_prompt: bool) -> dict[str, tuple[Any, Any]]:
        motions = snap.motion_ids()
        styles = snap.style_ids()
        elements = snap.element_names()

        fields: dict[str, tuple[Any, Any]] = {
            "title": described(
                str if required_prompt else (str | None),
                "Short slug for the shot, e.g. 'Marta enters the workshop'.",
                ... if required_prompt else None,
            ),
            "description": described(
                str if required_prompt else (str | None),
                "What happens in the shot, in prose. This becomes the base of the "
                "generation prompt, so describe action and staging, not intent.",
                ... if required_prompt else None,
            ),
            "framing": described(
                literal_of(FRAMINGS) | None,
                "Shot size. Pick deliberately: it is the main continuity signal between "
                "consecutive shots.",
                None,
            ),
            "duration_s": described(
                float | None,
                "Intended duration in seconds. Keep it within the limits of the models "
                "you plan to use; list_available_models shows them.",
                None,
            ),
        }
        if motions:
            fields["camera_motion"] = described(
                literal_of(motions) | None,
                "Camera movement, from the project's motion catalogue. Leave empty for a "
                "locked-off shot; do not invent a name.",
                None,
            )
        if styles:
            fields["styles"] = described(
                list[literal_of(styles)] | None,  # type: ignore[valid-type]
                "Visual style ids (palette, lighting, film stock, lens) that apply to "
                "this shot on top of the project style.",
                None,
            )
        if elements:
            fields["element_refs"] = described(
                list[literal_of(elements)] | None,  # type: ignore[valid-type]
                "Names of the characters, locations or objects appearing in this shot. "
                "Use the exact names offered here — this is what keeps a character "
                "looking like the same person across shots.",
                None,
            )
        return fields

    @staticmethod
    def _catalogue_note(snap: TaxonomySnapshot) -> str:
        parts: list[str] = []
        if snap.motions:
            parts.append("Camera motions available:\n" + enumerate_for_prompt(snap.motions, limit=40))
        if snap.elements:
            names = ", ".join(e.name for e in snap.elements)
            parts.append(f"Elements defined in this project: {names}.")
        else:
            parts.append(
                "No elements are defined in this project yet, so no shot can reference a "
                "character or location. Use define_element first if continuity matters."
            )
        return "\n\n" + "\n\n".join(parts) if parts else ""

    def _build_spec(self, kwargs: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
        """Normaliza la ficha técnica y resuelve los nombres de element a uuid, para que
        el fan-out no tenga que volver a resolver nada ni pueda resolverlo distinto."""
        spec = dict(base or {})
        for key in ("framing", "duration_s", "camera_motion", "styles"):
            if kwargs.get(key) is not None:
                spec[key] = kwargs[key]

        if kwargs.get("camera_motion") and self.snap.motion(kwargs["camera_motion"]) is None:
            raise UnknownEntityError("camera motion", kwargs["camera_motion"], self.snap.motion_ids())
        for style_id in kwargs.get("styles") or []:
            if self.snap.style(style_id) is None:
                raise UnknownEntityError("visual style", style_id, self.snap.style_ids())

        if kwargs.get("element_refs") is not None:
            refs = self.resolve_elements(kwargs["element_refs"])
            spec["elements"] = [{"id": r.element_id, "name": r.name, "role": r.role} for r in refs]
        return spec


class CreateShotTool(_ShotToolBase):
    """Alta de un plano al final de la secuencia."""

    name: str = "create_shot"
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    async def _arun_impl(self, **kwargs: Any) -> tuple[str, Any]:
        spec = self._build_spec(kwargs)
        async with db.transaction() as conn:
            position = await conn.fetchval(
                """
                select coalesce(max(position), -1) + 1 from public.canvas_nodes
                 where project_id = $1::uuid and type = 'shot'
                """,
                self.ctx.project_id,
            )
            row = await conn.fetchrow(
                """
                insert into public.canvas_nodes
                       (project_id, node_key, type, title, text, position, spec, shot_status)
                values ($1::uuid, $6, 'shot', $2, $3, $4, $5::jsonb, 'pending')
                returning id, node_key, position, title, text, spec, shot_status
                """,
                self.ctx.project_id,
                # `title` y `text` son NOT NULL en `canvas_nodes`. Tienen DEFAULT '',
                # pero un DEFAULT solo actúa cuando la columna se omite: pasar NULL
                # explícitamente lo viola igual. El modelo puede dejarse `description`
                # sin rellenar —es opcional en el esquema de la tool— y eso hundía la
                # creación de planos con un NotNullViolationError que el agente leía
                # como "bug interno, no reintentes".
                kwargs.get("title") or "",
                kwargs.get("description") or "",
                position,
                json.dumps(spec),
                # `node_key` es el identificador estable del nodo dentro del canvas: es a
                # lo que apuntan `canvas_edges.from_node` y `to_node`, que son `text` y no
                # claves ajenas al uuid. Es NOT NULL y sin default, así que hay que
                # generarlo aquí. No lo usaba ningún código —lo añadió el frontend por su
                # cuenta— y por eso no estaba en nuestro `schema.sql`: la creación de
                # planos fallaba contra la base de datos real mientras los tests, que
                # aplican ese fichero, pasaban en verde.
                f"shot-{uuid4().hex[:12]}",
            )
        ui = dict(row) | {"id": str(row["id"])}
        return (
            f"Shot #{row['position']} '{row['title']}' created (id={row['id']}). "
            f"Spec: {spec or 'none'}.",
            ui,
        )

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> CreateShotTool:
        tool = cls(
            args_schema=build_args("CreateShotArgs", **cls._spec_fields(snap, required_prompt=True)),
            description=(
                "Append a new shot to the end of the project's shot list, with its "
                "framing, duration, camera motion and the elements that appear in it.\n"
                "\n"
                "USE THIS while building or extending the shot list, one call per shot. "
                "Shots are cheap and free — a shot list is a plan, not a render.\n"
                "\n"
                "DO NOT use it to modify an existing shot (update_shot) or to reorder "
                "(reorder_shots). DO NOT invent a character, location or camera motion "
                "name: only the values offered in this tool's arguments exist, and "
                "anything else will be rejected."
                + cls._catalogue_note(snap)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


class UpdateShotTool(_ShotToolBase):
    """Modificación parcial de un plano."""

    name: str = "update_shot"
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    async def _arun_impl(self, shot_id: str, **kwargs: Any) -> tuple[str, Any]:
        current = await _shot_or_raise(self.ctx.project_id, shot_id)
        spec = self._build_spec(kwargs, base=current["spec"] or {})

        row = await db.fetchrow(
            """
            update public.canvas_nodes
               set title = coalesce($3, title),
                   text  = coalesce($4, text),
                   spec  = $5::jsonb
             where id = $1::uuid and project_id = $2::uuid
            returning id, position, title, text, spec, shot_status
            """,
            shot_id,
            self.ctx.project_id,
            kwargs.get("title"),
            kwargs.get("description"),
            json.dumps(spec),
        )
        ui = dict(row) | {"id": str(row["id"])}
        return f"Shot #{row['position']} '{row['title']}' updated. Spec: {spec}.", ui

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> UpdateShotTool:
        fields = cls._spec_fields(snap, required_prompt=False)
        fields["shot_id"] = described(
            str, "Exact id of the shot, as returned by read_project or create_shot."
        )
        tool = cls(
            args_schema=build_args("UpdateShotArgs", **fields),
            description=(
                "Change one existing shot: its title, description, framing, duration, "
                "camera motion or the elements in it. Omitted fields are left untouched.\n"
                "\n"
                "USE THIS when the user gives a note on a specific shot ('make the third "
                "one a close-up', 'Marta should be in this one too') and before "
                "regenerating a shot that came out wrong — fix the spec, then generate.\n"
                "\n"
                "DO NOT use it to change the order of shots (reorder_shots). DO NOT guess "
                "a shot id; read them first."
                + cls._catalogue_note(snap)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# reorder_shots / delete_shot                                                  #
# --------------------------------------------------------------------------- #


class ReorderShotsArgs(BaseModel):
    shot_ids: list[str] = Field(
        ...,
        description=(
            "Every shot id of the project, in the new narrative order. The list must be "
            "complete: a partial list would leave the rest of the sequence undefined."
        ),
    )


class ReorderShotsTool(SnapshotTool):
    """Reordenación narrativa."""

    name: str = "reorder_shots"
    args_schema: type[BaseModel] = ReorderShotsArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Set the narrative order of the whole shot list by listing every shot id in the "
        "order they should play.\n"
        "\n"
        "USE THIS when the user moves a shot, when you restructure the sequence, or when "
        "you insert a shot that belongs somewhere other than the end.\n"
        "\n"
        "DO NOT pass a partial list — every existing shot must appear exactly once, and "
        "the tool will reject anything else rather than guess. DO NOT use it to delete a "
        "shot by omitting it; that is delete_shot."
    )

    async def _arun_impl(self, shot_ids: list[str], **_: Any) -> tuple[str, Any]:
        rows = await db.fetch(
            "select id from public.canvas_nodes where project_id = $1::uuid and type = 'shot'",
            self.ctx.project_id,
        )
        existing = {str(r["id"]) for r in rows}
        given = list(dict.fromkeys(shot_ids))

        if set(given) != existing or len(given) != len(shot_ids):
            missing = sorted(existing - set(given))
            unknown = [s for s in shot_ids if s not in existing]
            raise XframeToolRetryableError(
                "reorder_shots needs every shot exactly once. "
                + (f"Missing: {', '.join(missing)}. " if missing else "")
                + (f"Not shots of this project: {', '.join(unknown)}. " if unknown else "")
                + ("Duplicated ids in your list. " if len(given) != len(shot_ids) else "")
                + f"The project has {len(existing)} shots; read_project lists them all."
            )

        async with db.transaction() as conn:
            for i, shot_id in enumerate(given):
                await conn.execute(
                    """
                    update public.canvas_nodes set position = $3
                     where id = $1::uuid and project_id = $2::uuid
                    """,
                    shot_id,
                    self.ctx.project_id,
                    i,
                )
        return f"Shot list reordered: {len(given)} shots.", {"order": given}


class DeleteShotArgs(BaseModel):
    shot_id: str = Field(..., description="Exact id of the shot to delete.")


class DeleteShotTool(SnapshotTool):
    """Borrado de un plano, con renumeración."""

    name: str = "delete_shot"
    args_schema: type[BaseModel] = DeleteShotArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Delete a shot from the shot list and renumber the rest so the narrative order "
        "stays contiguous. Assets already generated for that shot are kept.\n"
        "\n"
        "USE THIS only when the user explicitly asks to remove a shot.\n"
        "\n"
        "DO NOT delete a shot to 'clean up', to fix a mistake of your own, or as a step "
        "in a rewrite — update_shot changes it in place and preserves the work. Deleting "
        "is not undoable from your side."
    )

    async def _arun_impl(self, shot_id: str, **_: Any) -> tuple[str, Any]:
        shot = await _shot_or_raise(self.ctx.project_id, shot_id)
        async with db.transaction() as conn:
            await conn.execute(
                "delete from public.canvas_nodes where id = $1::uuid and project_id = $2::uuid",
                shot_id,
                self.ctx.project_id,
            )
            remaining = await conn.fetch(
                """
                select id from public.canvas_nodes
                 where project_id = $1::uuid and type = 'shot'
                 order by position nulls last
                """,
                self.ctx.project_id,
            )
            for i, row in enumerate(remaining):
                await conn.execute(
                    "update public.canvas_nodes set position = $2 where id = $1",
                    row["id"],
                    i,
                )
        invalidate_cache(f"project:{self.ctx.project_id}")
        return (
            f"Shot '{shot['title']}' deleted. {len(remaining)} shots remain, renumbered "
            f"from 0.",
            {"deleted": shot_id, "remaining": len(remaining)},
        )
