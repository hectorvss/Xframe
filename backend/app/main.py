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
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.runner import ConversationRunner, make_checkpointer
from app.db import close_pool, init_pool
from app.stream.bus import EventBus

logger = logging.getLogger(__name__)

_runner: ConversationRunner | None = None
_bus: EventBus | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _runner, _bus
    await init_pool()
    _bus = EventBus()
    await _bus.connect()
    checkpointer = await make_checkpointer()
    async with checkpointer as cp:
        await cp.setup()
        _runner = ConversationRunner(cp, _bus)
        yield
    await _bus.close()
    await close_pool()


app = FastAPI(title="Xframe Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    if _runner is None:
        raise HTTPException(503, "agent not ready")

    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(401, "missing user")

    async def stream() -> AsyncIterator[str]:
        async for event in _runner.run(
            conversation_id=req.conversation_id,
            project_id=req.project_id,
            user_id=user_id,
            message=req.message,
            ui_context=req.ui_context,
            resume_payload=req.resume,
        ):
            if await request.is_disconnected():
                # No abortamos nada: los jobs en curso son del worker y deben seguir.
                logger.info("client_disconnected", extra={"conv": req.conversation_id})
                break
            yield _sse(event)
        yield _sse({"type": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/conversations/{conversation_id}/stream")
async def reattach(conversation_id: str, request: Request) -> StreamingResponse:
    """
    Reengancharse a una conversación en curso. `Last-Event-ID` permite recuperar lo que
    se perdió mientras el cliente estuvo desconectado — por eso el bus es un Redis Stream
    y no un pub/sub.
    """
    if _bus is None:
        raise HTTPException(503, "bus not ready")

    last_id = request.headers.get("last-event-id")

    async def stream() -> AsyncIterator[str]:
        async for event_id, event in _bus.subscribe(conversation_id, last_id=last_id):
            if await request.is_disconnected():
                break
            yield _sse(event, event_id)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
