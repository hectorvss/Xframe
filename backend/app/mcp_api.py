"""API de administración del servidor MCP."""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import db
from app.auth import AuthUser, current_user
from app.config import get_settings
from app.mcp_server import ALL_SCOPES, OAUTH_ACCESS_LEVELS

router = APIRouter(prefix="/mcp", tags=["mcp"])
oauth_router = APIRouter(tags=["oauth"])


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=12)
    project_ids: list[str] = Field(default_factory=list, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class OAuthGrantCreate(BaseModel):
    client_id: str = Field(min_length=1, max_length=300)
    access_level: Literal["readonly", "editor", "full"]
    project_ids: list[str] = Field(default_factory=list, max_length=100)


def _mcp_url() -> str:
    # La ruta canonica del mount lleva barra final; asi los clientes no tienen
    # que preservar Authorization a traves de una redireccion 307.
    return f"{get_settings().public_base_url.rstrip('/')}/mcp/"


def oauth_issuer_url() -> str:
    return f"{get_settings().supabase_url.rstrip('/')}/auth/v1"


def protected_resource_metadata_url() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/.well-known/oauth-protected-resource/mcp"


@oauth_router.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource_metadata() -> dict[str, object]:
    """RFC 9728: descubrimiento del Authorization Server por clientes MCP."""
    return {
        "resource": _mcp_url(),
        "authorization_servers": [oauth_issuer_url()],
        "scopes_supported": ["openid", "profile", "email"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{get_settings().public_base_url.rstrip('/')}/settings/mcp-server",
    }


async def _probe_oauth_server() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(
                f"{get_settings().supabase_url.rstrip('/')}/.well-known/oauth-authorization-server/auth/v1"
            )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


# Caché del sondeo al Authorization Server. Preguntar a Supabase en cada 401 del MCP o
# en cada carga de Ajustes metería 3 s de latencia y una dependencia de red en el camino
# de auth. El estado sólo cambia al reconfigurar el proyecto, así que unos minutos de TTL
# sobran. Es el mismo criterio que el gate de proveedores: un instante, no un sondeo por
# petición.
_oauth_probe_cache: tuple[float, bool] | None = None
_OAUTH_PROBE_TTL_S = 300.0


async def oauth_server_enabled() -> bool:
    """¿Hay de verdad un Authorization Server emitiendo tokens para este recurso?

    De esto depende que anunciemos OAuth o no. Anunciarlo sin AS manda a Claude/Cursor a
    un descubrimiento que no pueden completar; no anunciarlo cuando sí lo hay les niega el
    flujo automático. La respuesta tiene que salir de sondear el AS, no de una constante.
    """
    global _oauth_probe_cache
    now = time.monotonic()
    if _oauth_probe_cache is not None and now - _oauth_probe_cache[0] < _OAUTH_PROBE_TTL_S:
        return _oauth_probe_cache[1]
    enabled = await _probe_oauth_server()
    _oauth_probe_cache = (now, enabled)
    return enabled


@router.get("/status")
async def status(user: AuthUser = Depends(current_user)) -> dict[str, object]:
    """Configuración pública y capacidades que consume Ajustes."""
    del user
    oauth_enabled = await oauth_server_enabled()
    return {
        "status": "ready",
        "server_url": _mcp_url(),
        "transport": "streamable-http",
        # La verdad, no la aspiración: el token personal xfr_ funciona siempre; OAuth 2.1
        # sólo cuando hay un Authorization Server detrás que lo respalde.
        "authentication": "oauth-2.1" if oauth_enabled else "bearer-token",
        "oauth": {
            "enabled": oauth_enabled,
            "issuer": oauth_issuer_url(),
            "protected_resource_metadata": protected_resource_metadata_url(),
            "authorization_path": "/oauth/consent",
        },
        "scopes": sorted(ALL_SCOPES),
        "tools": [
            "list_projects", "get_project_context", "list_assets", "create_project",
            "update_project", "add_brief_block", "create_shot", "run_xframe_agent",
        ],
    }


async def _available_projects(user_id: str) -> list[dict[str, object]]:
    rows = await db.fetch(
        """
        select p.id, p.title, p.updated_at
          from public.projects p
         where p.owner_id = $1::uuid
            or exists (
              select 1 from public.project_collaborators c
               where c.project_id = p.id and c.user_id = $1::uuid
                 and coalesce(c.status, 'accepted') = 'accepted'
            )
            or exists (
              select 1 from public.workspaces w
              join public.workspace_members m on m.workspace_id = w.id
               where w.owner_id = p.owner_id and m.user_id = $1::uuid
            )
         order by p.updated_at desc
         limit 100
        """,
        user_id,
    )
    return [dict(row) for row in rows]


@router.get("/oauth-grants/projects")
async def oauth_grant_projects(user: AuthUser = Depends(current_user)) -> list[dict[str, object]]:
    """Proyectos que el usuario puede delegar a un cliente OAuth."""
    return await _available_projects(user.id)


@router.get("/oauth-grants")
async def list_oauth_grants(user: AuthUser = Depends(current_user)) -> list[dict[str, object]]:
    rows = await db.fetch(
        """
        select client_id, scopes, project_ids, created_at, updated_at
          from public.oauth_mcp_grants
         where owner_id = $1::uuid and revoked_at is null
         order by updated_at desc
        """,
        user.id,
    )
    return [dict(row) for row in rows]


@router.post("/oauth-grants", status_code=201)
async def create_oauth_grant(
    body: OAuthGrantCreate, request: Request, user: AuthUser = Depends(current_user)
) -> dict[str, object]:
    """Guarda la delegaciÃ³n elegida antes de que Supabase emita el token OAuth."""
    accessible_ids = {str(project["id"]) for project in await _available_projects(user.id)}
    requested_ids = set(body.project_ids)
    if not requested_ids.issubset(accessible_ids):
        raise HTTPException(404, "Uno o mÃ¡s proyectos no estÃ¡n disponibles.")

    scopes = sorted(OAUTH_ACCESS_LEVELS[body.access_level])
    row = await db.fetchrow(
        """
        insert into public.oauth_mcp_grants (owner_id, client_id, scopes, project_ids, revoked_at)
        values ($1::uuid, $2, $3::text[], $4::uuid[], null)
        on conflict (owner_id, client_id) do update
          set scopes = excluded.scopes,
              project_ids = excluded.project_ids,
              revoked_at = null,
              updated_at = now()
        returning client_id, scopes, project_ids, created_at, updated_at
        """,
        user.id,
        body.client_id.strip(),
        scopes,
        sorted(requested_ids),
    )
    try:
        await db.execute(
            """
            insert into public.agent_audit_events (owner_id, action, outcome, detail)
            values ($1::uuid, 'grant_oauth_mcp', 'ok', jsonb_build_object('client_id', $2, 'ip', $3))
            """,
            user.id,
            body.client_id.strip(),
            request.client.host if request.client else None,
        )
    except Exception:
        pass
    return dict(row)


@router.delete("/oauth-grants/{client_id}")
async def revoke_oauth_grant(client_id: str, user: AuthUser = Depends(current_user)) -> dict[str, bool]:
    result = await db.execute(
        """
        update public.oauth_mcp_grants set revoked_at = now(), updated_at = now()
         where owner_id = $1::uuid and client_id = $2 and revoked_at is null
        """,
        user.id,
        client_id,
    )
    if result.endswith("0"):
        raise HTTPException(404, "ConcesiÃ³n OAuth no encontrada.")
    return {"ok": True}


@router.get("/credentials")
async def list_credentials(user: AuthUser = Depends(current_user)) -> list[dict[str, object]]:
    rows = await db.fetch(
        """
        select id, name, prefix, scopes, project_ids, last_used_at, created_at, expires_at, revoked_at
          from public.api_keys where owner_id = $1::uuid order by created_at desc
        """,
        user.id,
    )
    return [dict(row) for row in rows]


@router.post("/credentials", status_code=201)
async def create_credential(
    body: CredentialCreate, request: Request, user: AuthUser = Depends(current_user)
) -> dict[str, object]:
    scopes = set(body.scopes)
    invalid = scopes - ALL_SCOPES
    if invalid:
        raise HTTPException(422, f"Scopes no reconocidas: {', '.join(sorted(invalid))}")
    if body.project_ids:
        owned = await db.fetch(
            "select id from public.projects where owner_id = $1::uuid and id = any($2::uuid[])",
            user.id, body.project_ids,
        )
        if len(owned) != len(set(body.project_ids)):
            raise HTTPException(404, "Uno o más proyectos no están disponibles.")

    token = f"xfr_{secrets.token_urlsafe(32)}"
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days)
        if body.expires_in_days else None
    )
    row = await db.fetchrow(
        """
        insert into public.api_keys (owner_id, name, prefix, token_hash, scopes, project_ids, expires_at)
        values ($1::uuid, $2, $3, $4, $5::text[], $6::uuid[], $7)
        returning id, name, prefix, scopes, project_ids, created_at, expires_at
        """,
        user.id, body.name.strip(), token[:16], hashlib.sha256(token.encode()).hexdigest(),
        sorted(scopes), body.project_ids, expires_at,
    )
    try:
        await db.execute(
            """
            insert into public.agent_audit_events (owner_id, api_key_id, action, outcome, detail)
            values ($1::uuid, $2::uuid, 'create_credential', 'ok', jsonb_build_object('ip', $3))
            """,
            user.id, str(row["id"]), request.client.host if request.client else None,
        )
    except Exception:
        pass  # la credencial es válida incluso durante el despliegue de la migración
    return {"credential": dict(row), "token": token}


@router.post("/credentials/{credential_id}/revoke")
async def revoke_credential(credential_id: str, user: AuthUser = Depends(current_user)) -> dict[str, bool]:
    result = await db.execute(
        "update public.api_keys set revoked_at = now() where id = $1::uuid and owner_id = $2::uuid and revoked_at is null",
        credential_id, user.id,
    )
    if result.endswith("0"):
        raise HTTPException(404, "Credencial no encontrada.")
    try:
        await db.execute(
            """
            insert into public.agent_audit_events (owner_id, api_key_id, action, outcome)
            values ($1::uuid, $2::uuid, 'revoke_credential', 'ok')
            """,
            user.id,
            credential_id,
        )
    except Exception:
        pass
    return {"ok": True}
