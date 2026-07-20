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


class BriefBlockIn(BaseModel):
    """Un bloque del brief. `position` la asigna la tool: dejársela al modelo produce
    huecos y duplicados que luego hay que reparar."""

    type: BlockType = Field("text", description="Block type, as in a Notion document.")
    text: str = Field("", description="Block content. Plain text, no markdown syntax.")
    checked: bool = Field(False, description="Only meaningful for 'todo' blocks.")
    src: str | None = Field(None, description="Image URL. Only for 'image' blocks.")


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
                row = await conn.fetchrow(
                    """
                    insert into public.brief_blocks
                           (project_id, position, type, text, checked, src)
                    values ($1, $2, $3, $4, $5, $6)
                    returning id, position, type, text, checked, src
                    """,
                    self.ctx.project_id,
                    i,
                    block.type,
                    block.text,
                    block.checked,
                    block.src,
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
        type: str | None = None,  # noqa: A002 — el nombre lo fija el esquema del bloque
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
            type,
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
