"""
Frontera de autenticación y de tenant.

Tres piezas, separadas porque fallan por motivos distintos:

- `supabase`  — quién eres. Verifica el JWT de Supabase contra el JWKS del proyecto.
- `ownership` — qué es tuyo. Contrasta `project_id` y `conversation_id` contra `owner_id`.
- `tickets`   — cómo se autentica un `EventSource`, que no puede mandar cabeceras.

Y `ratelimit`, que no es seguridad de acceso sino de gasto: sin él, un usuario
autenticado puede vaciar el monedero a base de turnos.
"""

from app.auth.ownership import (
    assert_conversation_available,
    assert_conversation_owner,
    assert_project_owner,
)
from app.auth.ratelimit import RateLimitExceeded, check_rate_limit
from app.auth.supabase import AuthError, AuthUser, bearer_token, current_user, verify_token
from app.auth.tickets import consume_stream_ticket, issue_stream_ticket

__all__ = [
    "AuthError",
    "AuthUser",
    "RateLimitExceeded",
    "assert_conversation_available",
    "assert_conversation_owner",
    "assert_project_owner",
    "bearer_token",
    "check_rate_limit",
    "consume_stream_ticket",
    "current_user",
    "issue_stream_ticket",
    "verify_token",
]
