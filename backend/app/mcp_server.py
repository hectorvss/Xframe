"""Servidor MCP remoto de Xframe.

La frontera MCP no reutiliza el JWT de otro producto ni acepta un ``user_id``
proporcionado por el cliente. Cada llamada lleva un token personal ``xfr_`` cuyo
hash, scopes y posible lista de proyectos se consultan en Postgres. Los JWT de
Supabase siguen funcionando para clientes controlados por el usuario.

No se anuncia OAuth mientras Xframe no tenga un Authorization Server que emita
tokens para este recurso: fingirlo haría que Claude/Cursor descubrieran una URL
de login que no puede completar el flujo. El transporte es Streamable HTTP y
los clientes que admitan cabeceras pueden conectarse hoy mismo.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import db
from app.auth.supabase import AuthError, verify_token
from app.storage import StorageError, get_signer

logger = logging.getLogger(__name__)

READ_SCOPES = {"projects:read", "assets:read", "context:read", "jobs:read"}
WRITE_SCOPES = {"projects:write", "assets:write"}
GENERATION_SCOPE = "generation:run"
ALL_SCOPES = READ_SCOPES | WRITE_SCOPES | {GENERATION_SCOPE}


@dataclass(frozen=True, slots=True)
class McpPrincipal:
    user_id: str
    scopes: frozenset[str]
    api_key_id: str | None = None
    project_ids: frozenset[str] = frozenset()

    def can(self, scope: str) -> bool:
        return scope in self.scopes


_principal: contextvars.ContextVar[McpPrincipal | None] = contextvars.ContextVar(
    "mcp_principal", default=None
)


def _current_principal() -> McpPrincipal:
    principal = _principal.get()
    if principal is None:
        raise RuntimeError("MCP tool invoked without an authenticated principal")
    return principal


async def _audit(
    principal: McpPrincipal,
    action: str,
    *,
    project_id: str | None = None,
    outcome: str = "ok",
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        await db.execute(
            """
            insert into public.agent_audit_events
              (owner_id, api_key_id, project_id, action, outcome, detail)
            values ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6::jsonb)
            """,
            principal.user_id,
            principal.api_key_id,
            project_id,
            action,
            outcome,
            json.dumps(detail or {}),
        )
    except Exception:
        # La auditoría no puede convertir una operación productiva correcta en
        # un 500 si aún no se aplicó la migración o el log tiene una incidencia.
        logger.exception("mcp_audit_failed", extra={"action": action})


async def _assert_scope(scope: str) -> McpPrincipal:
    principal = _current_principal()
    if not principal.can(scope):
        await _audit(principal, "scope_check", outcome="denied", detail={"required": scope})
        raise PermissionError(f"La credencial no tiene el permiso {scope}.")
    return principal


async def _assert_project(project_id: str, scope: str) -> McpPrincipal:
    principal = await _assert_scope(scope)
    if principal.project_ids and project_id not in principal.project_ids:
        await _audit(principal, "project_access", project_id=project_id, outcome="denied")
        raise PermissionError("La credencial no está autorizada para este proyecto.")

    row = await db.fetchrow(
        """
        select p.id
          from public.projects p
         where p.id = $1::uuid
           and (
             p.owner_id = $2::uuid
             or exists (
               select 1 from public.project_collaborators c
                where c.project_id = p.id and c.user_id = $2::uuid
                  and coalesce(c.status, 'accepted') = 'accepted'
             )
             or exists (
               select 1 from public.workspaces w
               join public.workspace_members m on m.workspace_id = w.id
                where w.owner_id = p.owner_id and m.user_id = $2::uuid
             )
           )
        """,
        project_id,
        principal.user_id,
    )
    if row is None:
        # No distinguimos inexistente de ajeno: los UUID no se convierten en un
        # oráculo de enumeración a través de una herramienta de terceros.
        raise LookupError("Proyecto no encontrado.")
    return principal


async def _signed_asset(row: Any) -> dict[str, Any]:
    asset = dict(row)
    if asset.get("url"):
        try:
            asset["url"] = await get_signer().sign(asset["url"])
        except StorageError:
            # Assets antiguos de demo pueden ser rutas estáticas; se devuelven
            # tal cual, igual que hace el editor.
            pass
    return asset


class McpBearerAuth:
    """Middleware ASGI sólo para el mount /mcp, sin afectar a webhooks/chat."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        raw = headers.get("authorization", "")
        scheme, _, token = raw.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            await self._reject(send, "Credenciales MCP ausentes.")
            return
        principal = await self._principal_for(token.strip(), scope)
        if principal is None:
            await self._reject(send, "Credenciales MCP inválidas.")
            return
        marker = _principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal.reset(marker)

    async def _principal_for(self, token: str, scope: Scope) -> McpPrincipal | None:
        # Clave de integración: se guarda sólo SHA-256, como las API keys ya
        # existentes de Xframe. Nunca se registra el token ni su hash.
        if token.startswith("xfr_"):
            digest = hashlib.sha256(token.encode()).hexdigest()
            row = await db.fetchrow(
                """
                select id, owner_id, scopes, project_ids, expires_at
                  from public.api_keys
                 where token_hash = $1 and revoked_at is null
                   and (expires_at is null or expires_at > now())
                """,
                digest,
            )
            if row is None:
                return None
            await db.execute(
                "update public.api_keys set last_used_at = now(), last_used_ip = $2::inet where id = $1::uuid",
                str(row["id"]),
                (scope.get("client") or ("", 0))[0] or None,
            )
            return McpPrincipal(
                user_id=str(row["owner_id"]),
                scopes=frozenset(row["scopes"] or []),
                api_key_id=str(row["id"]),
                project_ids=frozenset(str(value) for value in (row["project_ids"] or [])),
            )
        try:
            user = await verify_token(token)
        except AuthError:
            return None
        # Los JWT OAuth de Supabase conservan aud=authenticated, pero añaden el
        # client_id de la app que el usuario aprobó. Una sesión ordinaria no se
        # puede reutilizar como token MCP fuera de Xframe.
        if not user.claims.get("client_id"):
            return None
        return McpPrincipal(user_id=user.id, scopes=frozenset(ALL_SCOPES))

    @staticmethod
    async def _reject(send: Send, detail: str) -> None:
        from app.mcp_api import protected_resource_metadata_url

        response = JSONResponse(
            {"detail": detail},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="'
                    + protected_resource_metadata_url()
                    + '", scope="openid profile email"'
                )
            },
        )
        await send(
            {
                "type": "http.response.start",
                "status": response.status_code,
                "headers": response.raw_headers,
            }
        )
        await send({"type": "http.response.body", "body": response.body})


mcp = FastMCP(
    "Xframe",
    instructions=(
        "Trabaja sólo sobre los proyectos que el usuario haya autorizado. "
        "Lee el contexto antes de generar, informa de que los renders se encolan "
        "y nunca inventes URLs o estados de assets."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
async def list_projects(limit: int = 50) -> list[dict[str, Any]]:
    """Lista los proyectos que la credencial puede consultar."""
    principal = await _assert_scope("projects:read")
    limit = max(1, min(limit, 100))
    rows = await db.fetch(
        """
        select p.id, p.title, p.prompt, p.cover_url, p.settings, p.updated_at, p.created_at
          from public.projects p
         where p.owner_id = $1::uuid
         order by p.updated_at desc
         limit $2
        """,
        principal.user_id,
        limit,
    )
    if principal.project_ids:
        rows = [row for row in rows if str(row["id"]) in principal.project_ids]
    return [dict(row) for row in rows]


@mcp.tool()
async def get_project_context(project_id: str) -> dict[str, Any]:
    """Devuelve brief, planos, assets, memoria y artefactos recientes de un proyecto."""
    principal = await _assert_project(project_id, "context:read")
    project, brief, shots, assets, memory, artifacts = await __import__("asyncio").gather(
        db.fetchrow(
            "select id, title, prompt, settings, cover_url, created_at, updated_at from public.projects where id = $1::uuid",
            project_id,
        ),
        db.fetch("select id, position, type, text, checked, src from public.brief_blocks where project_id = $1::uuid order by position", project_id),
        db.fetch("select id, node_key, title, text, position, spec, shot_status from public.canvas_nodes where project_id = $1::uuid and type = 'shot' order by position nulls last", project_id),
        db.fetch("select id, name, type, role, status, prompt, params, url, created_at from public.assets where project_id = $1::uuid order by created_at desc limit 100", project_id),
        db.fetch("select kind, element_id, content, updated_at from public.project_memory where project_id = $1::uuid order by updated_at desc", project_id),
        db.fetch("select id, kind, version, content, created_at from public.artifacts where project_id = $1::uuid order by created_at desc limit 20", project_id),
    )
    await _audit(principal, "get_project_context", project_id=project_id)
    return {
        "project": dict(project) if project else None,
        "brief": [dict(row) for row in brief],
        "shots": [dict(row) for row in shots],
        "assets": [await _signed_asset(row) for row in assets],
        "memory": [dict(row) for row in memory],
        "artifacts": [dict(row) for row in artifacts],
    }


@mcp.tool()
async def list_assets(project_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Lista assets con URLs firmadas de corta duración."""
    principal = await _assert_project(project_id, "assets:read")
    limit = max(1, min(limit, 200))
    rows = await db.fetch(
        """
        select id, name, type, role, status, prompt, params, url, created_at
          from public.assets
         where project_id = $1::uuid and ($2::text is null or status = $2)
         order by created_at desc limit $3
        """,
        project_id,
        status,
        limit,
    )
    await _audit(principal, "list_assets", project_id=project_id)
    return [await _signed_asset(row) for row in rows]


@mcp.tool()
async def create_project(title: str, prompt: str = "") -> dict[str, Any]:
    """Crea un proyecto vacío para la persona propietaria de la credencial."""
    principal = await _assert_scope("projects:write")
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError("El título debe tener entre 1 y 200 caracteres.")
    row = await db.fetchrow(
        """
        insert into public.projects (owner_id, title, prompt)
        values ($1::uuid, $2, $3)
        returning id, title, prompt, settings, created_at, updated_at
        """,
        principal.user_id,
        title,
        prompt[:10_000],
    )
    await _audit(principal, "create_project", project_id=str(row["id"]))
    return dict(row)


@mcp.tool()
async def update_project(project_id: str, title: str | None = None, prompt: str | None = None) -> dict[str, Any]:
    """Actualiza el título o el prompt maestro de un proyecto autorizado."""
    principal = await _assert_project(project_id, "projects:write")
    if title is None and prompt is None:
        raise ValueError("Indica al menos title o prompt.")
    if title is not None and (not title.strip() or len(title) > 200):
        raise ValueError("El título debe tener entre 1 y 200 caracteres.")
    row = await db.fetchrow(
        """
        update public.projects
           set title = coalesce($2, title), prompt = coalesce($3, prompt), updated_at = now()
         where id = $1::uuid
         returning id, title, prompt, settings, updated_at
        """,
        project_id,
        title.strip() if title is not None else None,
        prompt[:10_000] if prompt is not None else None,
    )
    await _audit(principal, "update_project", project_id=project_id)
    return dict(row)


@mcp.tool()
async def add_brief_block(project_id: str, text: str, block_type: str = "text") -> dict[str, Any]:
    """Añade una nota al brief manteniendo todos los bloques que ya existen."""
    principal = await _assert_project(project_id, "projects:write")
    if not text.strip() or len(text) > 20_000:
        raise ValueError("El bloque debe tener entre 1 y 20.000 caracteres.")
    row = await db.fetchrow(
        """
        insert into public.brief_blocks (project_id, position, type, text)
        values ($1::uuid, (select coalesce(max(position), -1) + 1 from public.brief_blocks where project_id = $1::uuid), $2, $3)
        returning id, position, type, text, checked, src
        """,
        project_id,
        block_type[:100],
        text.strip(),
    )
    await _audit(principal, "add_brief_block", project_id=project_id)
    return dict(row)


@mcp.tool()
async def create_shot(project_id: str, title: str, description: str, position: int | None = None) -> dict[str, Any]:
    """Crea un plano editable en el timeline del proyecto."""
    principal = await _assert_project(project_id, "projects:write")
    if not title.strip() or not description.strip():
        raise ValueError("El plano necesita título y descripción.")
    position = position if position is not None else int(
        await db.fetchval("select coalesce(max(position), 0) + 1 from public.canvas_nodes where project_id = $1::uuid and type = 'shot'", project_id)
    )
    row = await db.fetchrow(
        """
        insert into public.canvas_nodes (project_id, node_key, type, title, text, position, spec)
        values ($1::uuid, $2, 'shot', $3, $4, $5, '{}'::jsonb)
        returning id, node_key, title, text, position, spec, shot_status
        """,
        project_id,
        f"mcp-shot-{uuid4()}",
        title.strip()[:300],
        description.strip()[:10_000],
        position,
    )
    await _audit(principal, "create_shot", project_id=project_id, detail={"shot": str(row["id"])})
    return dict(row)


@mcp.tool()
async def run_xframe_agent(project_id: str, instruction: str, mode: str = "production") -> dict[str, Any]:
    """Ejecuta el agente nativo de Xframe: puede planificar, generar y montar usando las herramientas del SaaS."""
    principal = await _assert_project(project_id, GENERATION_SCOPE)
    if not instruction.strip() or len(instruction) > 20_000:
        raise ValueError("La instrucción debe tener entre 1 y 20.000 caracteres.")
    if mode not in {"preproduction", "production", "edit"}:
        raise ValueError("mode debe ser preproduction, production o edit.")

    # Import tardío: evita el ciclo app.main -> mcp_server -> app.main al montar.
    from app.main import get_runner

    runner = get_runner()
    conversation_id = str(uuid4())
    events: list[dict[str, Any]] = []
    async for event in runner.run(
        conversation_id=conversation_id,
        project_id=project_id,
        user_id=principal.user_id,
        message=instruction.strip(),
        ui_context={"open_tab": "assets", "mcp": True, "requested_mode": mode},
    ):
        kind = event.get("type")
        if kind in {"message_delta", "tool_result", "asset_ready", "job_status", "error"}:
            events.append(event)
    await _audit(principal, "run_xframe_agent", project_id=project_id, detail={"conversation": conversation_id})
    return {"conversation_id": conversation_id, "events": events}


def asgi_app() -> ASGIApp:
    """Aplicación que se monta como ``/mcp`` en FastAPI."""
    return McpBearerAuth(mcp.streamable_http_app())
