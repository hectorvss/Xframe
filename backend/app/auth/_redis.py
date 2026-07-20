"""
Cliente de Redis compartido por los tickets y el rate limit.

Aparte del de `stream.bus` a propósito: aquel transporta progreso y se traga sus fallos
porque perder un evento es tolerable. Éste sostiene decisiones de seguridad y de gasto,
y sus fallos no se pueden tragar en silencio.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import get_settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def set_redis(client: aioredis.Redis | None) -> None:
    """Inyección para los tests."""
    global _client
    _client = client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
