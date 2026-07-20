"""
API HTTP.

El chat va por SSE. El detalle que condiciona el diseño: **el grafo no bloquea mientras se
renderiza**. Las herramientas de generación encolan y devuelven una referencia en estado
`generating`; el worker es el dueño del job y publica `asset_ready` en el bus cuando
termina. El frontend pinta un placeholder mientras tanto.

Si el usuario cierra el navegador, el worker sigue. Al volver, se reengancha al stream con
`last_event_id` y ve lo que se perdió.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import (
    AuthError,
    AuthUser,
    RateLimitExceeded,
    assert_conversation_available,
    assert_conversation_owner,
    assert_project_owner,
    bearer_token,
    check_rate_limit,
    consume_stream_ticket,
    current_user,
    issue_stream_ticket,
    verify_token,
)
from app.auth._redis import close_redis
from app.config import get_settings
from app.db import close_pool, init_pool
from app.jobs.webhooks import router as webhooks_router
from app.runtime import configure_event_loop
from app.stream.bus import EventBus

if TYPE_CHECKING:
    from app.agent.runner import ConversationRunner

# Antes de que nadie cree un bucle. Ver app/runtime.py.
configure_event_loop()

logger = logging.getLogger(__name__)

_runner: ConversationRunner | None = None
_bus: EventBus | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    El grafo se importa aquí dentro, no arriba.

    No es un detalle de estilo: `app.agent.runner` arrastra langgraph y el checkpointer
    de Postgres, y con el import en la cabecera este módulo —donde vive la frontera de
    autenticación— no se puede ni importar sin ese árbol entero instalado. La frontera de
    seguridad tiene que ser testeable sin levantar el agente.
    """
    from app.agent.runner import ConversationRunner, make_checkpointer
    from app.jobs import resume

    global _runner, _bus
    await init_pool()
    # El cliente de Redis se crea en el constructor: no hay `connect()` que llamar.
    # La versión anterior lo invocaba y el proceso no llegaba a levantar.
    _bus = EventBus()
    checkpointer = await make_checkpointer()
    async with checkpointer as cp:
        await cp.setup()
        _runner = ConversationRunner(cp, _bus)
        # El módulo de reanudación construye su propio runner cuando corre dentro del
        # worker, que es un proceso sin grafo. Aquí ya hay uno con su checkpointer
        # abierto: prestárselo evita abrir un segundo contra la misma base para hacer
        # exactamente lo mismo.
        resume.set_runner(_runner)
        yield
    resume.set_runner(None)
    await _bus.close()
    await close_redis()
    await close_pool()


app = FastAPI(title="Xframe Agent", lifespan=lifespan)


# Webhooks de proveedor. Va montado aquí y no dentro del `lifespan` porque es una ruta
# como cualquier otra; lo que sí conviene tener claro es que **no lleva `current_user`**:
# quien llama es el proveedor desde su infraestructura, y lo que autentica la petición es
# la firma del cuerpo (ver `app/jobs/webhooks.py`). Hasta ahora ese módulo existía y no lo
# montaba nadie, así que todo dependía del polling.
app.include_router(webhooks_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    conversation_id: str
    project_id: str
    message: str | None = None
    ui_context: dict[str, Any] | None = None
    resume: dict[str, Any] | None = None


def _sse(event: dict[str, Any], event_id: str | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}data: {json.dumps(event, ensure_ascii=False)}\n\n"


GENERIC_ERROR = "No se ha podido completar la petición. Inténtalo de nuevo."
"""
Lo único que ve el cliente cuando algo revienta.

Antes se serializaba `str(e)` de cualquier excepción. Con asyncpg eso incluye fragmentos
de la consulta, nombres de tabla y de columna, y a veces el valor que provocó el
conflicto — un mapa del esquema servido a quien sepa provocar un error. El detalle va al
log, con `exc_info`, donde tiene sentido y donde no lo lee un atacante.
"""


def _sanitize(event: dict[str, Any]) -> dict[str, Any]:
    """
    Filtro de salida de los eventos del grafo.

    Está aquí, en la frontera HTTP, y no solo en el runner, porque es el único punto por
    el que pasa **todo** lo que sale hacia el cliente. Cualquier productor de eventos que
    se añada mañana queda cubierto sin acordarse de nada.
    """
    if event.get("type") != "error":
        return event
    logger.warning("agent_error_sanitized", extra={"detail": str(event.get("message"))[:2_000]})
    return {"type": "error", "message": GENERIC_ERROR}


@app.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user: AuthUser = Depends(current_user),
) -> StreamingResponse:
    if _runner is None:
        raise HTTPException(503, "agent not ready")

    # El orden importa. Primero el límite de peticiones (barato, no toca la BD), después
    # la propiedad del proyecto (una consulta) y solo entonces se arranca el grafo, que
    # es lo que cuesta dinero.
    try:
        await check_rate_limit(user.id)
    except RateLimitExceeded as exc:
        raise HTTPException(
            429,
            "Demasiadas peticiones. Espera unos segundos.",
            headers={"Retry-After": str(exc.retry_after_s)},
        ) from exc

    await assert_project_owner(req.project_id, user.id)
    await assert_conversation_available(req.conversation_id, req.project_id, user.id)

    # Sembrar el stream antes de arrancar: si el cliente se reengancha por SSE contra una
    # clave de Redis que aún no existe, pierde los primeros eventos del turno.
    if _bus is not None:
        await _bus.seed(req.conversation_id)

    # El usuario ha hablado, así que la cadena de reanudaciones automáticas vuelve a
    # empezar. El tope de `app/jobs/resume.py` acota lo que el sistema hace **solo**; sin
    # este reinicio, una sesión larga agotaría las tres reanudaciones y a partir de ahí el
    # agente dejaría de enterarse de sus propios renders para siempre.
    if req.message:
        from app.jobs.resume import note_user_turn

        await note_user_turn(req.conversation_id)

    async def stream() -> AsyncIterator[str]:
        async for event in _runner.run(
            conversation_id=req.conversation_id,
            project_id=req.project_id,
            user_id=user.id,
            message=req.message,
            ui_context=req.ui_context,
            resume_payload=req.resume,
        ):
            if await request.is_disconnected():
                # No abortamos nada: los jobs en curso son del worker y deben seguir.
                logger.info("client_disconnected", extra={"conv": req.conversation_id})
                break
            yield _sse(_sanitize(event))
        yield _sse({"type": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class StreamTicket(BaseModel):
    ticket: str
    expires_in: int


@app.post("/auth/stream-ticket")
async def stream_ticket(
    conversation_id: str = Query(...),
    user: AuthUser = Depends(current_user),
) -> StreamTicket:
    """
    Ticket de un solo uso para abrir el SSE de reenganche.

    Existe porque el `EventSource` del navegador no manda cabeceras y por tanto no puede
    presentar el Bearer. El razonamiento completo y las alternativas descartadas están
    en `app/auth/tickets.py`.
    """
    await assert_conversation_owner(conversation_id, user.id)
    ticket, ttl = await issue_stream_ticket(user_id=user.id, conversation_id=conversation_id)
    return StreamTicket(ticket=ticket, expires_in=ttl)


@app.get("/conversations/{conversation_id}/stream")
async def reattach(
    conversation_id: str,
    request: Request,
    ticket: str | None = Query(default=None),
) -> StreamingResponse:
    """
    Reengancharse a una conversación en curso. `Last-Event-ID` permite recuperar lo que
    se perdió mientras el cliente estuvo desconectado — por eso el bus es un Redis Stream
    y no un pub/sub.

    Ese mismo `Last-Event-ID` es lo que hacía que la falta de autenticación aquí fuera
    grave y no menor: con `0-0` no se escuchaba lo que pasara a partir de ahora, se
    **reproducía la transcripción entera** de la conversación de otro.

    Dos formas de autenticarse, en este orden: el Bearer normal (para un cliente que
    controle sus cabeceras, como el móvil o un `fetch` con streams) o un ticket de un
    solo uso por query, para el `EventSource` del navegador.
    """
    # La autenticación va antes que la comprobación de disponibilidad del bus: un 503
    # contestado a quien no se ha identificado ya es información sobre el estado interno,
    # y sobre todo hace que el orden de las comprobaciones dependa del despliegue.
    user_id: str | None = None
    if token := bearer_token(request):
        try:
            user_id = (await verify_token(token)).id
        except AuthError as exc:
            logger.info("auth_rejected", extra={"reason": str(exc)})
            raise HTTPException(401, "credenciales inválidas") from exc
    elif ticket:
        user_id = await consume_stream_ticket(ticket, conversation_id=conversation_id)

    if not user_id:
        raise HTTPException(401, "credenciales inválidas")

    await assert_conversation_owner(conversation_id, user_id)

    if _bus is None:
        raise HTTPException(503, "bus not ready")

    last_id = request.headers.get("last-event-id") or "0-0"

    async def stream() -> AsyncIterator[str]:
        # StreamEvent ya sabe serializarse al protocolo SSE, con su `id:` para que el
        # navegador reanude solo. No lo reimplementamos aquí.
        async for event in _bus.subscribe(conversation_id, last_event_id=last_id):
            if await request.is_disconnected():
                break
            if event.type == "error":
                logger.warning("bus_error_sanitized", extra={"detail": str(event.data)[:2_000]})
                event.data = {"message": GENERIC_ERROR}
            yield event.to_sse()

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
