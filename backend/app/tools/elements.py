"""
Herramienta de elements.

Un **element** es un asset con `role`: personaje, localización u objeto. Es la unidad de
continuidad del proyecto, y por eso esta tool existe aparte en vez de ser un campo más
de `create_shot`.

El porqué es económico, no estético. Sin ficha de personaje, cada plano genera una
persona ligeramente distinta, el usuario lo ve al montar y hay que regenerar la mitad
del corto. La continuidad no se pide por prompt: se ancla a una imagen de referencia y
a una descripción canónica que viaja con cada generación que menciona ese element.

Definir un element es idempotente por nombre a propósito. El agente va a llamar a esta
tool varias veces sobre el mismo personaje según lo va concretando, y cada llamada debe
afinar la ficha, no crear un personaje gemelo que rompa justo lo que venía a arreglar.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app import db
from app.taxonomy.builder import SnapshotTool, build_args, described, literal_of
from app.taxonomy.repo import TaxonomySnapshot, invalidate_cache
from app.tools.base import ToolContext

ROLES = ("Personaje", "Localización", "Objeto")
"""
Roles canónicos. El esquema los deja abiertos (`role` es texto libre en la BD y el
usuario puede escribir el suyo), pero el enum guía al agente hacia los tres que la UI
sabe agrupar. Sugerir sin imponer.
"""


class DefineElementTool(SnapshotTool):
    """Crea o actualiza la ficha de un element."""

    name: str = "define_element"
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    async def _arun_impl(
        self,
        name: str,
        role: str,
        description: str,
        reference_asset_id: str | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        name = name.strip()
        existing = self.snap.element_by_name(name)

        reference_url: str | None = None
        if reference_asset_id:
            row = await db.fetchrow(
                "select url, status, type from public.assets where id = $1::uuid and project_id = $2::uuid",
                reference_asset_id,
                self.ctx.project_id,
            )
            asset_type = str(row["type"] if row else "").lower()
            if row is None or not any(token in asset_type for token in ("image", "imagen", "imágen")):
                from app.tools.errors import UnknownEntityError

                valid = await db.fetch(
                    """
                    select id, name from public.assets
                     where project_id = $1::uuid and status = 'ready'
                       and (lower(type) like '%image%' or lower(type) like '%imagen%')
                     order by created_at desc limit 40
                    """,
                    self.ctx.project_id,
                )
                raise UnknownEntityError(
                    "image asset", reference_asset_id, [f"{r['id']} ({r['name']})" for r in valid]
                )
            reference_url = row["url"]

        if existing is not None:
            row = await db.fetchrow(
                """
                update public.assets
                   set role = $3,
                       meta = $4,
                       url  = coalesce($5, url),
                       -- Adjuntar la referencia CIERRA el estado. Sin esta línea, el
                       -- element nacía en 'generating' (creación sin URL, más abajo) y
                       -- se quedaba ahí para siempre aunque el agente le adjuntara la
                       -- imagen después: la UI mostraba una tarjeta "Generando…" eterna
                       -- para un element perfectamente terminado. También rescata a un
                       -- element barrido a 'failed' al que por fin le llega su imagen.
                       status = case
                                    when coalesce($5, url) is not null then 'ready'
                                    else status
                                end
                 where id = $1::uuid and project_id = $2::uuid
                returning id, name, role, meta, url, status
                """,
                existing.id,
                self.ctx.project_id,
                role,
                description,
                reference_url,
            )
            verb = "updated"
        else:
            row = await db.fetchrow(
                """
                insert into public.assets (project_id, name, type, meta, role, url, status)
                values ($1::uuid, $2, 'image', $3, $4, $5::text,
                        case when $5::text is null then 'generating' else 'ready' end)
                returning id, name, role, meta, url, status
                """,
                self.ctx.project_id,
                name,
                description,
                role,
                reference_url,
            )
            verb = "created"

        # Sin esto, la siguiente tool del mismo turno construiría su Literal sin este
        # element y el agente no podría usar lo que acaba de definir.
        invalidate_cache(f"project:{self.ctx.project_id}")

        ui = dict(row) | {"id": str(row["id"])}
        hint = (
            ""
            if row["url"]
            else " It has no reference image yet, so it cannot be used in element_refs "
            "until you generate one with generate_image and attach it here."
        )
        return (
            f"Element '{row['name']}' ({row['role']}) {verb}.{hint}",
            ui,
        )

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> DefineElementTool:
        known = snap.element_names()
        roster = (
            "Elements already defined: " + ", ".join(known) + ". Reuse the exact name to "
            "refine one of them instead of creating a near-duplicate."
            if known
            else "No elements are defined yet in this project."
        )
        tool = cls(
            args_schema=build_args(
                "DefineElementArgs",
                name=described(
                    str,
                    "Canonical name of the element, exactly as it will be referred to in "
                    "shots ('Marta', 'El taller'). Reusing an existing name updates that "
                    "element; a new name creates a new one.",
                ),
                role=described(
                    literal_of(ROLES),
                    "What kind of element this is. It drives how the reference is used "
                    "at generation time.",
                ),
                description=described(
                    str,
                    "Canonical description: physical appearance, wardrobe, age, "
                    "distinguishing features for a character; architecture, light and "
                    "materials for a location. This text travels with every generation "
                    "that references the element, so write what must stay constant, not "
                    "what happens in a particular shot.",
                ),
                reference_asset_id=described(
                    str | None,
                    "Id of an existing image asset to use as the visual reference. Omit "
                    "if you have not generated one yet.",
                    None,
                ),
            ),
            description=(
                "Create or update the sheet of a project element — a character, a "
                "location or an object — with its canonical description and, optionally, "
                "a reference image.\n"
                "\n"
                "USE THIS the first time the user names anything that will appear in more "
                "than one shot, and again whenever its look is refined. Elements are what "
                "keep a character recognisable across shots; without them the same person "
                "will be generated differently in every shot and the work has to be "
                "redone.\n"
                "\n"
                "DO NOT create an element for something that appears once and never "
                "again — put it in the shot description instead. DO NOT invent a name the "
                "user never used, and DO NOT create a second element for someone who "
                "already exists under a slightly different spelling: reuse the exact "
                "existing name to update them.\n"
                "\n" + roster
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]
