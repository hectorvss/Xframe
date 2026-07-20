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
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.state import (
    JOB_EVENT_FLAG,
    RECURSION_LIMIT,
    AgentMode,
    NodeName,
    XframeState,
)
from app.config import get_settings
from app.stream.bus import EventBus

logger = logging.getLogger(__name__)


def _as_text(content: Any) -> str:
    """
    Extrae el texto visible del contenido de un mensaje.

    Con la API `/v1/responses` —obligatoria en GPT-5.6 para poder usar herramientas— el
    contenido ya no es una cadena: es una lista de bloques tipados, y entre ellos viene el
    bloque `reasoning` con su `encrypted_content`. Serializar la lista entera mandaba al
    frontend el razonamiento cifrado en crudo como si fuera la respuesta del agente.

    Se conservan los bloques de texto y se descarta todo lo demás; el razonamiento no es
    para el usuario y además viene cifrado.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "output_text"):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


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
        system_event: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Ejecuta un turno y va publicando eventos. Los emite también por el bus para que
        un segundo cliente (o el mismo tras reconectar) pueda seguir la misma conversación.

        `system_event` abre un turno que **no ha pedido el usuario**: hoy, que las
        generaciones que el agente encoló ya han aterrizado (`app/jobs/resume.py`). Es
        excluyente con `message` —un turno lo abre alguien, y solo uno— y el mensaje que
        genera va marcado con `JOB_EVENT_FLAG` para que ni el frontend ni el modelo lo
        confundan con una petición nueva.

        El turno reanudado publica en el bus como cualquier otro. Si hay un cliente
        conectado, lo ve llegar por SSE sin haber preguntado nada; si no lo hay, el
        checkpoint guarda el resultado y al reconectar está.
        """
        config = {
            "configurable": {"thread_id": conversation_id},
            "recursion_limit": RECURSION_LIMIT,
        }

        graph_input = await self._resolve_input(
            config=config,
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
            message=message,
            ui_context=ui_context,
            resume_payload=resume_payload,
            system_event=system_event,
        )

        try:
            async for chunk in self._graph.astream(
                graph_input, config=config, stream_mode="messages"
            ):
                event = self._to_event(chunk)
                if event is not None:
                    await self._publish(conversation_id, event)
                    yield event
        except Exception:
            # El detalle va al log, nunca al evento. `main.py` sanea la salida de /chat,
            # pero el reenganche por SSE sirve lo que hay en el bus tal cual: si el
            # `str(e)` se publica, un error de asyncpg —con fragmentos de consulta y
            # nombres de columna— acaba en el cliente por esa segunda puerta.
            logger.exception("conversation_failed", extra={"conversation": conversation_id})
            event = {
                "type": "error",
                "message": "No se ha podido completar la petición. Inténtalo de nuevo.",
            }
            await self._publish(conversation_id, event)
            yield event

    async def _publish(self, conversation_id: str, event: dict[str, Any]) -> None:
        """
        El bus separa el tipo del cuerpo; nosotros llevamos el tipo dentro del dict porque
        es lo que consume el cliente SSE. Aquí se desempaqueta, en un solo sitio.
        """
        payload = {k: v for k, v in event.items() if k != "type"}
        await self._bus.publish(conversation_id, event["type"], payload)

    async def _resolve_input(
        self,
        *,
        config: dict[str, Any],
        conversation_id: str,
        project_id: str,
        user_id: str,
        message: str | None,
        ui_context: dict[str, Any] | None,
        resume_payload: dict[str, Any] | None,
        system_event: str | None = None,
    ) -> Any:
        """
        Tres casos, en este orden:

        1. Hay un interrupt pendiente y traemos respuesta → `Command(resume=...)`.
        2. Hay checkpoint con trabajo pendiente y no hay entrada nueva → `None`, que en
           LangGraph significa "sigue desde donde estabas".
        3. Turno normal → estado con el mensaje nuevo, del usuario o del sistema.
        """
        if resume_payload is not None:
            return Command(resume=resume_payload)

        snapshot = await self._graph.aget_state(config)
        has_pending = bool(snapshot and snapshot.next)

        # Un evento de sistema cuenta como entrada nueva. Si no se contase, un turno
        # anterior que quedó a medias absorbería el aviso: el grafo continuaría por donde
        # estaba y el mensaje que dice qué planos han aterrizado no llegaría a entrar en
        # el historial, que es justamente lo único que este camino existe para hacer.
        if has_pending and message is None and system_event is None:
            return None

        stored_mode = snapshot.values.get("mode") if snapshot else None
        if not stored_mode:
            # Sin checkpoint no hay modo en el estado, y caer siempre a preproducción
            # ignora lo que diga `conversations.mode`. Esa columna la escribe
            # `switch_mode` y es lo único que sobrevive a que el checkpoint se pierda o
            # se compacte, así que es la fuente de verdad al arrancar: sin esta consulta
            # nadie la leía jamás, una conversación en producción volvía a preproducción
            # en cuanto se reanudaba, y el modelo pedía una tool de generación que ya no
            # estaba montada.
            stored_mode = await self._stored_mode(conversation_id)

        # El `ui_context` es lo que el usuario tiene delante. La versión anterior lo
        # aceptaba como parámetro y no lo usaba nunca, así que "el frontend manda
        # objetos, no ids" era un no-op y el agente trabajaba a ciegas sobre el editor.
        ui = ui_context or {}

        return XframeState(
            project_id=project_id,
            user_id=user_id,
            conversation_id=conversation_id,
            mode=AgentMode(stored_mode) if stored_mode else AgentMode.PREPRODUCTION,
            open_tab=ui.get("open_tab"),
            selected_asset_ids=ui.get("selected_asset_ids") or None,
            messages=[self._entry_message(message, system_event)],
        )

    @staticmethod
    def _entry_message(message: str | None, system_event: str | None) -> HumanMessage:
        """
        El mensaje que abre el turno, sea del usuario o del sistema.

        El evento del sistema va con rol `human` y la marca `JOB_EVENT_FLAG` encima, no
        como `HumanMessage` a secas. Sin la marca, "han terminado estos seis planos"
        queda en el historial indistinguible de algo que el director escribió, y a partir
        de ahí el modelo razona sobre una conversación que no ocurrió — le contesta al
        usuario cosas que el usuario no ha dicho, y en el siguiente turno da por sentado
        que lo aprobó.
        """
        if system_event is not None:
            return HumanMessage(
                content=system_event,
                id=str(uuid4()),
                additional_kwargs={JOB_EVENT_FLAG: True},
            )
        return HumanMessage(content=message or "", id=str(uuid4()))


    @staticmethod
    async def _stored_mode(conversation_id: str) -> str | None:
        """Modo persistido de la conversación. `None` si no existe o si falla la consulta."""
        from app import db

        try:
            row = await db.fetchrow(
                "select mode from public.conversations where id = $1::uuid", conversation_id
            )
        except Exception:
            logger.exception("stored_mode_lookup_failed", extra={"conversation": conversation_id})
            return None
        return row["mode"] if row else None

    def _to_event(self, chunk: Any) -> dict[str, Any] | None:
        """Traduce el stream de LangGraph al protocolo que entiende el frontend."""
        try:
            message, metadata = chunk
        except (TypeError, ValueError):
            return None

        node = (metadata or {}).get("langgraph_node")

        # Solo hablan los nodos de la conversación. El colector de memoria también llama
        # a un modelo —destila la biblia de estilo en segundo plano— y su salida se estaba
        # transmitiendo al chat: el usuario veía pegado a cada respuesta el texto interno
        # del colector, incluido su marcador de fin. Lo que ese nodo produce es memoria,
        # no conversación, y cualquier nodo de fondo que se añada mañana queda cubierto
        # por esta lista en vez de aparecer en la interfaz sin que nadie lo note.
        if node and node not in (NodeName.ROOT, NodeName.ROOT_TOOLS):
            return None

        if raw_calls := getattr(message, "tool_calls", None):
            # Con `stream_mode="messages"` los `AIMessageChunk` llegan troceados y los
            # primeros traen el nombre a medias o vacío. Emitir esos produce un
            # `tool_start` fantasma con nombre "" que el frontend pinta como una
            # herramienta sin nombre. Solo se anuncian los que ya tienen nombre.
            names = [n for tc in raw_calls if (n := (tc.get("name") or "").strip())]
            if not names:
                return None
            return {"type": "tool_start", "tools": names}

        if message.__class__.__name__ == "ToolMessage":
            return {
                "type": "tool_result",
                "tool_call_id": getattr(message, "tool_call_id", None),
                "content": _as_text(message.content),
                "ui_payload": getattr(message, "artifact", None),
            }

        # Solo habla el modelo. Por el stream pasan también los `HumanMessage` que el
        # grafo inyecta —el del usuario y, sobre todo, los de contexto del proyecto— y
        # emitirlos hacía que el agente pareciera responder con el bloque
        # `<attached_context>` entero: el usuario veía su propio proyecto serializado en
        # XML como si fuera la respuesta.
        if message.__class__.__name__ not in ("AIMessage", "AIMessageChunk"):
            return None

        if text := _as_text(getattr(message, "content", None)):
            return {"type": "message_delta", "node": node, "content": text}

        return None


async def make_checkpointer() -> AsyncPostgresSaver:
    settings = get_settings()
    checkpointer = AsyncPostgresSaver.from_conn_string(settings.database_url)
    return checkpointer
