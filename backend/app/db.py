"""
Acceso a Postgres con asyncpg.

Sin ORM a propósito: el esquema ya está escrito en SQL y con RLS, y las consultas del
agente son pocas y muy específicas. Un ORM aquí solo añadiría una capa que traducir.

El backend usa la conexión de servicio (salta RLS), así que **todo repositorio filtra
por `project_id` explícitamente**. Es la contrapartida de no apoyarse en RLS.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            get_settings().database_url,
            min_size=2,
            max_size=16,
            init=_init_conn,
        )
    return _pool


async def _init_conn(conn: asyncpg.Connection) -> None:
    """jsonb ↔ dict sin tener que serializar en cada llamada."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call init_pool() on startup")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    async with pool().acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    async with pool().acquire() as conn, conn.transaction():
        yield conn


async def fetch(q: str, *args: Any) -> list[asyncpg.Record]:
    async with acquire() as conn:
        return await conn.fetch(q, *args)


async def fetchrow(q: str, *args: Any) -> asyncpg.Record | None:
    async with acquire() as conn:
        return await conn.fetchrow(q, *args)


async def fetchval(q: str, *args: Any) -> Any:
    async with acquire() as conn:
        return await conn.fetchval(q, *args)


async def execute(q: str, *args: Any) -> str:
    async with acquire() as conn:
        return await conn.execute(q, *args)
