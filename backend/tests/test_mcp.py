"""Regresiones de la frontera OAuth/MCP."""

from __future__ import annotations

import os

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
