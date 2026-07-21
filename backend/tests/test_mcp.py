"""Regresiones de la frontera OAuth/MCP."""

from __future__ import annotations

import os

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("SUPABASE_URL", "https://proyecto.supabase.co")

from app import mcp_server
from app.auth import AuthUser

ALICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_oauth_token_without_explicit_mcp_grant_is_rejected(monkeypatch) -> None:
    async def token(_token: str) -> AuthUser:
        return AuthUser(id=ALICE, email=None, claims={"client_id": "dynamic-client"})

    async def no_grant(*_args):
        return None

    monkeypatch.setattr(mcp_server, "verify_token", token)
    monkeypatch.setattr(mcp_server.db, "fetchrow", no_grant)

    principal = await mcp_server.McpBearerAuth(object())._principal_for("jwt", {})

    assert principal is None


@pytest.mark.asyncio
async def test_oauth_token_uses_the_saved_client_grant(monkeypatch) -> None:
    async def token(_token: str) -> AuthUser:
        return AuthUser(id=ALICE, email=None, claims={"client_id": "dynamic-client"})

    async def grant(*_args):
        return {"scopes": ["projects:read"], "project_ids": [PROJECT]}

    monkeypatch.setattr(mcp_server, "verify_token", token)
    monkeypatch.setattr(mcp_server.db, "fetchrow", grant)

    principal = await mcp_server.McpBearerAuth(object())._principal_for("jwt", {})

    assert principal is not None
    assert principal.scopes == frozenset({"projects:read"})
    assert principal.project_ids == frozenset({PROJECT})


@pytest.mark.asyncio
async def test_streamable_http_initialize_runs_inside_mcp_lifespan(monkeypatch) -> None:
    """El primer initialize no puede fallar por un task group sin arrancar."""
    principal = mcp_server.McpPrincipal(
        user_id=ALICE,
        scopes=frozenset(mcp_server.ALL_SCOPES),
    )

    async def authenticated(*_args):
        return principal

    monkeypatch.setattr(mcp_server.McpBearerAuth, "_principal_for", authenticated)
    app = mcp_server.asgi_app()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "xframe-regression", "version": "1.0"},
        },
    }

    async with mcp_server.session_manager_lifespan():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost:8000",
        ) as client:
            response = await client.post(
                "/",
                json=request,
                headers={
                    "Authorization": "Bearer test-token",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-06-18",
                },
            )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "Xframe"
