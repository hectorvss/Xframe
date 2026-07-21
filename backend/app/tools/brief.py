"""
Herramientas del brief.

El brief es el tratamiento del proyecto y se guarda como bloques tipo Notion en
`brief_blocks` (`position` + `type` + `text`). Que sean bloques y no un campo de texto
tiene una consecuencia directa sobre el agente: puede corregir **un** párrafo sin
reescribir el documento, y el usuario ve un diff pequeño en vez de un muro nuevo.

Por eso hay dos tools y no una. `write_brief` sustituye el documento (uso legítimo:
está vacío o el usuario pidió empezar de cero) y `update_brief_block` toca un bloque.
Si solo existiera la primera, el agente reescribiría el brief entero en cada matiz y
pisaría lo que el usuario hubiera editado a mano.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from app import db
from app.taxonomy.builder import SnapshotTool
from app.tools.errors import UnknownEntityError

BlockType = Literal["heading", "text", "bullet", "todo", "quote", "image"]

BLOCK_TYPE_TO_UI = {"heading": "h1"}
"""
Traducción al vocabulario del editor de brief del frontend (h1/h2/text/bullet/…).

El agente escribía `type='heading'` tal cual a `brief_blocks` y el editor no conoce ese
tipo: `blockMeta[block.type]` era `undefined` y la pestaña Project brief moría entera con
una pantalla en blanco. El Literal se queda con 'heading' —es el nombre natural que el
modelo elige y cambiárselo es pelearse contra el prompt—, pero lo que se PERSISTE es el
tipo que el editor sabe pintar.
"""


class BriefBlockIn(BaseModel):
    """Un bloque del brief. `position` la asigna la tool: dejársela al modelo produce
    huecos y duplicados que luego hay que reparar."""

    type: BlockType = Field("text", description="Block type, as in a Notion document.")
    text: str = Field("", description="Block content. Plain text, no markdown syntax.")
    checked: bool = Field(False, description="Only meaningful for 'todo' blocks.")
    src: str | None = Field(None, description="Image URL. Only for 'image' blocks.")
    asset_id: str | None = Field(
        None, description="Existing project asset id for an image block; preferred over a raw URL."
    )


class WriteBriefArgs(BaseModel):
    blocks: list[BriefBlockIn] = Field(
        ...,
        description=(
            "The full brief, in reading order. This REPLACES every existing block, so "
            "include everything you want to keep."
        ),
    )


class WriteBriefTool(SnapshotTool):
    """Reescritura completa del brief."""

    name: str = "write_brief"
    args_schema: type[BaseModel] = WriteBriefArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Replace the entire project brief with a new list of blocks (headings, "
        "paragraphs, bullets, todos). The brief is the creative treatment: premise, "
        "tone, visual references, structure.\n"
        "\n"
        "USE THIS when the brief is empty, or when the user explicitly asks to rewrite "
        "or restructure it from scratch.\n"
        "\n"
        "DO NOT use it to change one paragraph, fix a typo or add a line — that is "
        "update_brief_block, and this tool would silently destroy any edit the user made "
        "by hand. DO NOT call it without reading the current brief first (read_project), "
        "or you will delete content you never saw."
    )

    async def _arun_impl(self, blocks: list[Any], **_: Any) -> tuple[str, Any]:
        parsed = [b if isinstance(b, BriefBlockIn) else BriefBlockIn.model_validate(b) for b in blocks]

        async with db.transaction() as conn:
            await conn.execute(
                "delete from public.brief_blocks where project_id = $1", self.ctx.project_id
            )
            rows = []
            for i, block in enumerate(parsed):
                src = block.src
                if block.asset_id:
                    asset = await conn.fetchrow(
                        "select url from public.assets where id=$1::uuid and project_id=$2::uuid",
                        block.asset_id, self.ctx.project_id,
                    )
                    if not asset:
                        raise UnknownEntityError("asset", block.asset_id, [])
                    src = asset["url"]
                row = await conn.fetchrow(
                    """
                    insert into public.brief_blocks
                           (project_id, position, type, text, checked, src, asset_id)
                    values ($1, $2, $3, $4, $5, $6, $7::uuid)
                    returning id, position, type, text, checked, src, asset_id
                    """,
                    self.ctx.project_id,
                    i,
                    BLOCK_TYPE_TO_UI.get(block.type, block.type),
                    block.text,
                    block.checked,
                    src,
                    block.asset_id,
                )
                rows.append(dict(row) | {"id": str(row["id"])})

        headings = [b.text for b in parsed if b.type == "heading"] or ["(no headings)"]
        return (
            f"Brief rewritten: {len(parsed)} blocks. Sections: {', '.join(headings)}.",
            {"blocks": rows},
        )


class UpdateBriefBlockArgs(BaseModel):
    block_id: str = Field(
        ...,
        description=(
            "Exact id of the block, as returned by read_project. Never guess it: block "
            "ids are UUIDs and an invented one will simply not exist."
        ),
    )
    text: str | None = Field(None, description="New content. Omit to leave it unchanged.")
    type: BlockType | None = Field(None, description="New block type. Omit to keep it.")
    checked: bool | None = Field(None, description="New checked state for 'todo' blocks.")


class UpdateBriefBlockTool(SnapshotTool):
    """Edición quirúrgica de un bloque."""

    name: str = "update_brief_block"
    args_schema: type[BaseModel] = UpdateBriefBlockArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Update one block of the brief in place: its text, its type or its checked "
        "state. Everything else in the document is left untouched.\n"
        "\n"
        "USE THIS for every incremental change to the brief — rewording a paragraph, "
        "ticking a todo, promoting a line to a heading. It is the default; write_brief "
        "is the exception.\n"
        "\n"
        "DO NOT invent block ids: read the brief with read_project and use the ids it "
        "returned. DO NOT use it to append a new block; a brief that needs new structure "
        "should be rewritten with write_brief."
    )

    async def _arun_impl(
        self,
        block_id: str,
        text: str | None = None,
        type: str | None = None,
        checked: bool | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        row = await db.fetchrow(
            """
            update public.brief_blocks
               set text    = coalesce($3, text),
                   type    = coalesce($4, type),
                   checked = coalesce($5, checked)
             where id = $1::uuid and project_id = $2::uuid
            returning id, position, type, text, checked, src
            """,
            block_id,
            self.ctx.project_id,
            text,
            BLOCK_TYPE_TO_UI.get(type, type) if type else None,
            checked,
        )
        if row is None:
            valid = await db.fetch(
                """
                select id, left(text, 48) as preview from public.brief_blocks
                 where project_id = $1 order by position
                """,
                self.ctx.project_id,
            )
            raise UnknownEntityError(
                "brief block",
                block_id,
                [f"{r['id']} ({r['preview']})" for r in valid],
            )

        ui = dict(row) | {"id": str(row["id"])}
        return f"Block {row['position']} updated: {row['text'][:120]}", ui


class AppendBriefBlockArgs(BaseModel):
    block: BriefBlockIn
    after_block_id: str | None = Field(
        None, description="Insert after this exact block id; omit to append at the end."
    )


class AppendBriefBlockTool(SnapshotTool):
    name: str = "append_brief_block"
    args_schema: type[BaseModel] = AppendBriefBlockArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")
    description: str = (
        "Insert one new block into the project brief without rewriting existing content. "
        "USE THIS to add a section, paragraph, requirement, todo or project-asset image at "
        "an exact location. DO NOT use write_brief for an incremental addition, invent an "
        "after_block_id, or persist a temporary/signed browser URL as an image reference."
    )

    async def _arun_impl(self, block: Any, after_block_id: str | None = None,
                         **_: Any) -> tuple[str, Any]:
        parsed = block if isinstance(block, BriefBlockIn) else BriefBlockIn.model_validate(block)
        rows = await db.fetch(
            "select id,position from public.brief_blocks where project_id=$1::uuid order by position",
            self.ctx.project_id,
        )
        position = len(rows)
        if after_block_id:
            target = next((row for row in rows if str(row["id"]) == after_block_id), None)
            if not target:
                raise UnknownEntityError("brief block", after_block_id, [str(row["id"]) for row in rows])
            position = int(target["position"]) + 1
        src = parsed.src
        if parsed.asset_id:
            asset = await db.fetchrow(
                "select url from public.assets where id=$1::uuid and project_id=$2::uuid",
                parsed.asset_id, self.ctx.project_id,
            )
            if not asset:
                raise UnknownEntityError("asset", parsed.asset_id, [])
            src = asset["url"]
        async with db.transaction() as conn:
            await conn.execute(
                "update public.brief_blocks set position=position+1 where project_id=$1::uuid and position >= $2",
                self.ctx.project_id, position,
            )
            row = await conn.fetchrow(
                """insert into public.brief_blocks
                   (project_id,position,type,text,checked,src,asset_id)
                   values ($1::uuid,$2,$3,$4,$5,$6,$7::uuid)
                   returning id,position,type,text,checked,src,asset_id""",
                self.ctx.project_id, position, BLOCK_TYPE_TO_UI.get(parsed.type, parsed.type),
                parsed.text, parsed.checked, src, parsed.asset_id,
            )
        return f"Brief block inserted at position {position}.", dict(row) | {"id": str(row["id"])}


class DeleteBriefBlockArgs(BaseModel):
    block_id: str


class DeleteBriefBlockTool(SnapshotTool):
    name: str = "delete_brief_block"
    args_schema: type[BaseModel] = DeleteBriefBlockArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")
    description: str = (
        "Delete exactly one identified block from the project brief and compact positions. "
        "USE THIS when the user explicitly removes a requirement or obsolete section. DO "
        "NOT delete a block merely to rewrite it, guess its id, or replace the whole brief."
    )

    async def _arun_impl(self, block_id: str, **_: Any) -> tuple[str, Any]:
        row = await db.fetchrow(
            "delete from public.brief_blocks where id=$1::uuid and project_id=$2::uuid returning position",
            block_id, self.ctx.project_id,
        )
        if not row:
            raise UnknownEntityError("brief block", block_id, [])
        await db.execute(
            "update public.brief_blocks set position=position-1 where project_id=$1::uuid and position > $2",
            self.ctx.project_id, row["position"],
        )
        return f"Brief block {block_id} deleted.", {"block_id": block_id, "deleted": True}
