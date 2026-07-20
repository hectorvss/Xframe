"""
Tickets de un solo uso para el SSE de reenganche.

El problema, y por qué no vale con "manda el Bearer": el `EventSource` del navegador
**no admite cabeceras**. `/conversations/{id}/stream` es justo el endpoint que un
`EventSource` consume, así que no hay forma de que llegue un `Authorization` por ahí.

Se barajaron tres salidas:

1. **Cookie de sesión.** Funciona sin tocar el cliente, pero obliga a
   `withCredentials`, a cookies de terceros entre el dominio del front y el de la API, y
   a defenderse de CSRF en un GET que devuelve la transcripción entera. Mucha superficie
   para un solo endpoint.
2. **El access token en la query.** Es lo más corto de escribir y lo peor: el token va a
   los logs del proxy, al `Referer` y al historial, y dura lo que dure la sesión.
3. **Ticket de un solo uso** — lo que está implementado. El cliente pide un ticket con
   su Bearer normal (`POST /auth/stream-ticket`), y ese ticket, opaco y de 60 s, viaja
   por la query. Si se filtra a un log, ya está gastado y caducado.

El ticket se ata al `user_id` **y** a la conversación en el momento de emitirlo, y se
consume con `GETDEL` — atómico, así que dos reconexiones simultáneas no pueden gastar el
mismo ticket dos veces. Se guarda el hash del ticket, no el ticket: quien lea Redis no
obtiene credenciales utilizables.
"""

from __future__ import annotations

import hashlib
import secrets

from app.auth._redis import get_redis
from app.config import get_settings

_PREFIX = "xframe:sse-ticket:"


def _key(ticket: str) -> str:
    return _PREFIX + hashlib.sha256(ticket.encode()).hexdigest()


async def issue_stream_ticket(*, user_id: str, conversation_id: str) -> tuple[str, int]:
    """Emite un ticket para una conversación concreta. Devuelve `(ticket, ttl_s)`."""
    ttl = get_settings().sse_ticket_ttl_s
    ticket = secrets.token_urlsafe(32)
    await get_redis().set(_key(ticket), f"{user_id}:{conversation_id}", ex=ttl)
    return ticket, ttl


async def consume_stream_ticket(ticket: str, *, conversation_id: str) -> str | None:
    """
    Gasta el ticket y devuelve el `user_id` si es válido para esta conversación.

    Devuelve `None` en cualquier otro caso — inexistente, caducado, ya gastado o emitido
    para otra conversación. El ticket se consume igualmente: un ticket presentado contra
    la conversación equivocada es un intento de reutilización, y no merece un segundo uso.
    """
    if not ticket:
        return None
    stored = await get_redis().getdel(_key(ticket))
    if not stored:
        return None
    user_id, _, bound_conversation = str(stored).partition(":")
    if bound_conversation != conversation_id:
        return None
    return user_id or None
