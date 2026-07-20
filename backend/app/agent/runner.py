"""
Runner: el puente entre una petición HTTP y el grafo.

Su responsabilidad principal es la **reanudación**. Porta `_init_or_update_state()` de
PostHog: según haya o no un checkpoint con nodos pendientes, se arranca de cero, se
continúa, o se responde a un interrupt.

Esto importa más aquí que en PostHog: nuestros turnos duran minutos porque hay renders de
por medio, así que la probabilidad de que el usuario cierre la pestaña a mitad no es
teórica. El worker sigue trabajando, los assets aterrizan en la BD, y al volver el usuario
retoma la conversación donde estaba.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.state import RECURSION_LIMIT, AgentMode, XframeState
from app.config import get_settings
from app.stream.bus import EventBus

logger = logging.getLogger(__name__)


class ConversationRunner:
    def __init__(self, checkpointer: AsyncPostgresSaver, bus: EventBus):
        self._graph = build_graph(checkpointer)
        self._checkpointer = checkpointer
        self._bus = bus

    async def run(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
        message: str | None,
        ui_context: dict[str, Any] | None = None,
        resume_payload: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Ejecuta un turno y va publicando eventos. Los emite también por el bus para que
        un segundo cliente (o el mismo tras reconectar) pueda seguir la misma conversación.
        """
        config = {
            "configurable": {"thread_id": conversation_id},
            "recursion_limit": RECURSION_LIMIT,
        }

        graph_input = await self._resolve_input(
            config=config,
            project_id=project_id,
            user_id=user_id,
            message=message,
            resume_payload=resume_payload,
        )

        try:
            async for chunk in self._graph.astream(
                graph_input, config=config, stream_mode="messages"
            ):
                event = self._to_event(chunk)
                if event is not None:
                    await self._bus.publish(conversation_id, event)
                    yield event
        except Exception as e:  # noqa: BLE001
            logger.exception("conversation_failed", extra={"conversation": conversation_id})
            event = {"type": "error", "message": str(e)}
            await self._bus.publish(conversation_id, event)
            yield event

    async def _resolve_input(
        self,
        *,
        config: dict[str, Any],
        project_id: str,
        user_id: str,
        message: str | None,
        resume_payload: dict[str, Any] | None,
    ) -> Any:
        """
        Tres casos, en este orden:

        1. Hay un interrupt pendiente y traemos respuesta → `Command(resume=...)`.
        2. Hay checkpoint con trabajo pendiente y no hay mensaje nuevo → `None`, que en
           LangGraph significa "sigue desde donde estabas".
        3. Turno normal → estado con el mensaje humano nuevo.
        """
        if resume_payload is not None:
            return Command(resume=resume_payload)

        snapshot = await self._graph.aget_state(config)
        has_pending = bool(snapshot and snapshot.next)

        if has_pending and message is None:
            return None

        return XframeState(
            project_id=project_id,
            user_id=user_id,
            mode=AgentMode(snapshot.values.get("mode")) if snapshot and snapshot.values.get("mode") else AgentMode.PREPRODUCTION,
            messages=[HumanMessage(content=message or "", id=str(uuid4()))],
        )

    def _to_event(self, chunk: Any) -> dict[str, Any] | None:
        """Traduce el stream de LangGraph al protocolo que entiende el frontend."""
        try:
            message, metadata = chunk
        except (TypeError, ValueError):
            return None

        node = (metadata or {}).get("langgraph_node")

        if getattr(message, "tool_calls", None):
            return {
                "type": "tool_start",
                "tools": [tc["name"] for tc in message.tool_calls],
            }

        if message.__class__.__name__ == "ToolMessage":
            return {
                "type": "tool_result",
                "tool_call_id": getattr(message, "tool_call_id", None),
                "content": message.content,
                "ui_payload": getattr(message, "artifact", None),
            }

        if content := getattr(message, "content", None):
            return {"type": "message_delta", "node": node, "content": content}

        return None


async def make_checkpointer() -> AsyncPostgresSaver:
    settings = get_settings()
    checkpointer = AsyncPostgresSaver.from_conn_string(settings.database_url)
    return checkpointer
