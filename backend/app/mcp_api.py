"""API de administración del servidor MCP."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import db
from app.auth import AuthUser, current_user
from app.config import get_settings
from app.mcp_server import ALL_SCOPES

router = APIRouter(prefix="/mcp", tags=["mcp"])


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=12)
    project_ids: list[str] = Field(default_factory=list, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def _mcp_url() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/mcp"


@router.get("/status")
async def status(user: AuthUser = Depends(current_user)) -> dict[str, object]:
    """Configuración pública y capacidades que consume Ajustes."""
    del user
    return {
        "status": "ready",
        "server_url": _mcp_url(),
        "transport": "streamable-http",
        "authentication": "personal-access-token",
        "scopes": sorted(ALL_SCOPES),
        "tools": [
            "list_projects", "get_project_context", "list_assets", "create_project",
            "update_project", "add_brief_block", "create_shot", "run_xframe_agent",
        ],
    }


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
    return {"ok": True}
