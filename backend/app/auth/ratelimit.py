"""
Rate limit por usuario, sobre Redis.

`/chat` no tenía ninguno. Un turno arranca un grafo con Opus y puede encolar doce
generaciones: el coste por petición no es el de un endpoint CRUD, y la reserva de
créditos protege el saldo pero no el gasto en LLM ni la cola del worker.

Ventana fija y no *sliding window*: la ventana fija es un `INCR` con `EXPIRE` y se lee de
un vistazo. Su defecto conocido —hasta 2x el límite en el cambio de ventana— es
irrelevante aquí, donde el objetivo es frenar un bucle, no facturar con precisión.

Si Redis no está, **se deja pasar**. Es la decisión deliberada: caerse el limitador no
puede dejar el producto inservible, y el gasto real sigue teniendo su tope aguas abajo en
la reserva de créditos.
"""

from __future__ import annotations

import logging
import time

from app.auth._redis import get_redis
from app.config import get_settings

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Se ha superado el límite. Lleva los segundos que faltan para la siguiente ventana."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after_s = retry_after_s


async def check_rate_limit(
    user_id: str,
    *,
    bucket: str = "chat",
    limit: int | None = None,
    window_s: int | None = None,
) -> None:
    settings = get_settings()
    limit = limit if limit is not None else settings.chat_rate_limit
    window_s = window_s if window_s is not None else settings.chat_rate_limit_window_s
    if limit <= 0:
        return

    now = int(time.time())
    window = now // window_s
    key = f"xframe:rl:{bucket}:{user_id}:{window}"

    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            # Solo en la primera de la ventana: reponer el TTL en cada petición
            # convertiría un goteo constante en una clave inmortal.
            await redis.expire(key, window_s)
    except Exception as exc:
        logger.warning("ratelimit_unavailable", extra={"error": str(exc)})
        return

    if count > limit:
        raise RateLimitExceeded(retry_after_s=max(1, (window + 1) * window_s - now))
