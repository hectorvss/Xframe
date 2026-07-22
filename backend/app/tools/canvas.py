"""Non-destructive canvas editing tools for the agent."""

from __future__ import annotations

from typing import Any, ClassVar, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app import db
from app.taxonomy.builder import SnapshotTool
from app.tools.errors import XframeToolRetryableError

ALL_MODES: tuple[str, ...] = ("preproduction", "production", "edit")

# Convención de coordenadas del lienzo, para que el agente maquete con sentido en vez
# de amontonar todo en (0,0). Coincide con el layout del frontend (src/main.jsx): un
# nodo ocupa ~250×120 px, así que ~300 px separan columnas y ~200 px separan filas.
# Guía sugerida: conceptos/referencias arriba-izquierda (x 40-320), y los planos
# fluyendo en fila hacia la derecha (x 400, 620, 840… en y ~480).
_XY_HINT = (
    "Canvas coordinate in pixels. Lay the canvas out so it reads: a node is ~250x120 px, "
    "so leave ~300px between columns and ~200px between rows. Put concepts and references "
    "top-left (x 40-320, y 80-360) and let shots flow left-to-right (x 400, 620, 840…, "
    "y ~480). Place a new node NEXT TO what it relates to and never stack two at the same "
    "spot."
)


class CreateCanvasNodeArgs(BaseModel):
    node_type: Literal["concept", "reference"] = "concept"
    title: str
    text: str = ""
    asset_id: str | None = None
    x: float = Field(0, description=_XY_HINT)
    y: float = Field(0, description=_XY_HINT)


class CreateCanvasNodeTool(SnapshotTool):
    name: str = "create_canvas_node"
    args_schema: type[BaseModel] = CreateCanvasNodeArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Create a persistent concept or visual-reference node on the project canvas, "
        "optionally linked to an existing project asset. USE THIS to organize research, "
        "creative reasoning and reference relationships outside the shot timeline. DO NOT "
        "use it for a production shot (use create_shot), invent an asset id, or overwrite "
        "existing nodes to rearrange the canvas."
    )

    async def _arun_impl(self, node_type: str, title: str, text: str = "",
                         asset_id: str | None = None, x: float = 0, y: float = 0,
                         **_: Any) -> tuple[str, Any]:
        media = None
        thumb = None
        if asset_id:
            asset = await db.fetchrow(
                "select name,url from public.assets where id=$1::uuid and project_id=$2::uuid",
                asset_id, self.ctx.project_id,
            )
            if not asset:
                raise XframeToolRetryableError(f"Unknown asset {asset_id} in this project.")
            media, thumb = asset["name"], asset["url"]
        row = await db.fetchrow(
            """insert into public.canvas_nodes
               (project_id,node_key,type,x,y,title,text,thumb,media,asset_id,spec,shot_status)
               values ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10::uuid,'{}'::jsonb,'pending')
               returning id,node_key,type,x,y,title,text,thumb,media,asset_id""",
            self.ctx.project_id, f"agent-{uuid4().hex}", node_type, x, y, title, text,
            thumb, media, asset_id,
        )
        payload = dict(row) | {"id": str(row["id"]),
                               "asset_id": str(row["asset_id"]) if row["asset_id"] else None}
        return f"Canvas {node_type} node {row['id']} created.", payload


class UpdateCanvasNodeArgs(BaseModel):
    node_id: str
    title: str | None = None
    text: str | None = None
    asset_id: str | None = None
    clear_asset: bool = False
    x: float | None = None
    y: float | None = None


class UpdateCanvasNodeTool(SnapshotTool):
    name: str = "update_canvas_node"
    args_schema: type[BaseModel] = UpdateCanvasNodeArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Edit one existing canvas node in place, including its copy, linked project asset "
        "or layout coordinates while preserving its stable id and graph edges. USE THIS for "
        "precise canvas changes requested in chat. DO NOT delete/recreate a node to edit it, "
        "attach an asset from another project, or clear media unless clear_asset is true."
    )

    async def _arun_impl(self, node_id: str, title: str | None = None,
                         text: str | None = None, asset_id: str | None = None,
                         clear_asset: bool = False, x: float | None = None,
                         y: float | None = None, **_: Any) -> tuple[str, Any]:
        asset = None
        if asset_id:
            asset = await db.fetchrow(
                "select id,name,url from public.assets where id=$1::uuid and project_id=$2::uuid",
                asset_id, self.ctx.project_id,
            )
            if not asset:
                raise XframeToolRetryableError(f"Unknown asset {asset_id} in this project.")
        row = await db.fetchrow(
            """update public.canvas_nodes set
                 title=coalesce($3,title), text=coalesce($4,text),
                 x=coalesce($5,x), y=coalesce($6,y),
                 asset_id=case when $7 then null when $8::uuid is not null then $8::uuid else asset_id end,
                 thumb=case when $7 then null when $8::uuid is not null then $9 else thumb end,
                 media=case when $7 then null when $8::uuid is not null then $10 else media end
               where id=$1::uuid and project_id=$2::uuid
               returning id,node_key,type,x,y,title,text,thumb,media,asset_id""",
            node_id, self.ctx.project_id, title, text, x, y, clear_asset, asset_id,
            asset["url"] if asset else None, asset["name"] if asset else None,
        )
        if not row:
            raise XframeToolRetryableError(f"Unknown canvas node {node_id} in this project.")
        return f"Canvas node {node_id} updated without changing its identity.", dict(row) | {"id": str(row["id"])}


class DeleteCanvasNodeArgs(BaseModel):
    node_id: str


class DeleteCanvasNodeTool(SnapshotTool):
    name: str = "delete_canvas_node"
    args_schema: type[BaseModel] = DeleteCanvasNodeArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Delete one exact concept/reference canvas node and its graph edges. USE THIS only "
        "when the user explicitly asks to remove that node. DO NOT use it for production "
        "shots (use delete_shot), guess ids, or delete/recreate nodes as an editing method."
    )

    async def _arun_impl(self, node_id: str, **_: Any) -> tuple[str, Any]:
        row = await db.fetchrow(
            "select node_key,type from public.canvas_nodes where id=$1::uuid and project_id=$2::uuid",
            node_id, self.ctx.project_id,
        )
        if not row or row["type"] == "shot":
            raise XframeToolRetryableError(f"Unknown non-shot canvas node {node_id}.")
        async with db.transaction() as conn:
            await conn.execute(
                """delete from public.resource_bindings
                    where project_id=$1::uuid and scope_type='canvas' and scope_id=$2::uuid""",
                self.ctx.project_id,
                node_id,
            )
            await conn.execute(
                "delete from public.canvas_edges where project_id=$1::uuid and (from_node=$2 or to_node=$2)",
                self.ctx.project_id, row["node_key"],
            )
            await conn.execute("delete from public.canvas_nodes where id=$1::uuid", node_id)
        return f"Canvas node {node_id} deleted.", {"node_id": node_id, "deleted": True}


class ConnectCanvasNodesArgs(BaseModel):
    from_node_id: str
    to_node_id: str


class ConnectCanvasNodesTool(SnapshotTool):
    name: str = "connect_canvas_nodes"
    args_schema: type[BaseModel] = ConnectCanvasNodesArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Create a directed relationship between two existing canvas nodes while keeping "
        "their stable identities. USE THIS to express creative flow, dependency or sequence "
        "on the canvas. DO NOT connect resources from another project, create self-links or "
        "duplicate an edge that already exists."
    )

    async def _arun_impl(self, from_node_id: str, to_node_id: str, **_: Any) -> tuple[str, Any]:
        if from_node_id == to_node_id:
            raise XframeToolRetryableError("A canvas node cannot connect to itself.")
        rows = await db.fetch(
            "select id,node_key from public.canvas_nodes where project_id=$1::uuid and id=any($2::uuid[])",
            self.ctx.project_id, [from_node_id, to_node_id],
        )
        keys = {str(row["id"]): row["node_key"] for row in rows}
        if set(keys) != {from_node_id, to_node_id}:
            raise XframeToolRetryableError("Both canvas nodes must exist in this project.")
        row = await db.fetchrow(
            """insert into public.canvas_edges(project_id,from_node,to_node)
               values ($1::uuid,$2,$3) on conflict (project_id,from_node,to_node)
               do update set from_node=excluded.from_node returning id""",
            self.ctx.project_id, keys[from_node_id], keys[to_node_id],
        )
        return f"Connected canvas nodes {from_node_id} → {to_node_id}.", {
            "edge_id": str(row["id"]), "from_node_id": from_node_id, "to_node_id": to_node_id,
        }


class DisconnectCanvasNodesArgs(BaseModel):
    edge_id: str


class DisconnectCanvasNodesTool(SnapshotTool):
    name: str = "disconnect_canvas_nodes"
    args_schema: type[BaseModel] = DisconnectCanvasNodesArgs
    modes: ClassVar[tuple[str, ...]] = ALL_MODES
    description: str = (
        "Remove one exact canvas graph edge while preserving both connected nodes. USE THIS "
        "when the user removes or corrects a relationship on the canvas. DO NOT delete either "
        "node, guess an edge id, or remove unrelated relationships."
    )

    async def _arun_impl(self, edge_id: str, **_: Any) -> tuple[str, Any]:
        row = await db.fetchrow(
            """delete from public.canvas_edges
                where id=$1::uuid and project_id=$2::uuid returning from_node,to_node""",
            edge_id,
            self.ctx.project_id,
        )
        if not row:
            raise XframeToolRetryableError(f"Unknown canvas edge {edge_id} in this project.")
        return f"Canvas edge {edge_id} removed.", {
            "edge_id": edge_id,
            "from_node": row["from_node"],
            "to_node": row["to_node"],
            "deleted": True,
        }


CANVAS_TOOL_CLASSES: tuple[type[SnapshotTool], ...] = (
    CreateCanvasNodeTool, UpdateCanvasNodeTool, DeleteCanvasNodeTool,
    ConnectCanvasNodesTool, DisconnectCanvasNodesTool,
)
