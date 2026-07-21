"""
Los dos nodos del grafo.

Aquí vive todo lo que la topología no dice: compactación, contexto, toolset según modo,
límites, ejecución de herramientas y recolección de memoria.

Nota de método, tras la auditoría del 20/07/2026: **cada llamada que cruza a otro módulo
está escrita contra la firma real, leída del fichero destino.** La versión anterior de
este fichero asumía nombres (`ContextManager`, `build_messages`) que no existían, y el
agente moría en la primera línea del primer nodo en cada mensaje.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app import llm
from app.agent.prompts.base import build_system_prompt
from app.agent.state import (
    MAX_GENERATIONS_PER_TURN,
    MAX_TOOL_CALLS,
    AgentMode,
    PartialXframeState,
    XframeState,
    count_tool_calls,
)
from app.tools.base import ToolContext, ToolFactory

logger = logging.getLogger(__name__)


class RootNode:
    """El LLM: compacta si hace falta, monta contexto y toolset, y llama al modelo."""

    async def __call__(
        self, state: XframeState, config: dict[str, Any] | None = None
    ) -> PartialXframeState:
        # 1. Compactación. Va ANTES de montar el contexto: si el historial no cabe,
        #    añadirle contexto encima solo empeora las cosas.
        #
        #    La reinyección de la biblia de estilo y de las fichas de personaje que hace
        #    el compactador no es una optimización: sin ella se rompe la continuidad
        #    visual entre planos, y ese fallo se paga en créditos, no en tokens.
        from app.agent.compaction import ConversationCompactor

        compaction = await ConversationCompactor().compact(state)
        compacted = compaction.messages
        messages = list(compacted) if compacted else list(state.messages)

        # 2. Contexto del proyecto, deduplicado contra el historial. Se inyecta como
        #    mensajes marcados justo antes del humano, no en el system prompt: así entra
        #    en la caché de prompt y sobrevive a la siguiente compactación.
        context_messages = await self._context_messages(state, messages)

        # 3. Toolset del modo. En preproducción las tools de generación no se montan.
        ctx = await self._build_tool_context(state)
        tools = await ToolFactory.build_for_mode(ctx)
        billable = {t.name for t in tools if getattr(t, "consumes_credits", False)}

        system = build_system_prompt(mode=str(state.mode or AgentMode.PREPRODUCTION))

        model = llm.chat_model("root", max_tokens=8192, temperature=0.4)

        # 4. Límites, con degradación amable: al alcanzarlos no se lanza una excepción,
        #    se le quitan las herramientas al modelo y se le pide que cierre. El usuario
        #    ve un cierre razonado en vez de un error a mitad de un trabajo largo.
        reason = self._exhausted(messages, billable)
        prelude = [SystemMessage(content=system), *context_messages]

        if reason:
            logger.info("limits_exhausted", extra={"reason": reason})
            response = await model.ainvoke(
                [*prelude, *messages, HumanMessage(content=self._closing(reason))]
            )
        else:
            response = await model.bind_tools(tools).ainvoke([*prelude, *messages])

        if compacted:
            # `compacted` es un `ReplaceMessages`: hay que devolverlo tal cual para que
            # el reductor sustituya el historial en vez de fusionarlo. Envolverlo en una
            # lista normal aquí anularía la compactación en silencio.
            from app.agent.state import ReplaceMessages

            return PartialXframeState.model_construct(
                messages=ReplaceMessages([*compacted, *context_messages, response])
            )

        return PartialXframeState(messages=[*context_messages, response])

    # -- piezas ------------------------------------------------------------ #

    async def _context_messages(self, state: XframeState, messages: list[Any]) -> list[Any]:
        from app.context.manager import XframeContextManager

        manager = XframeContextManager(state.project_id, state.user_id)
        return await manager.get_context_messages(
            messages,
            open_tab=state.open_tab or "assets",
            selected_asset_ids=state.selected_asset_ids,
            resource_refs=state.resource_refs,
        )

    async def _build_tool_context(self, state: XframeState) -> ToolContext:
        from app.jobs.credits import balance

        # Approval-sensitive tools need evidence from the actual human turn. Context
        # injections and automatic worker events are not user consent.
        user_message = ""
        for message in reversed(state.messages):
            if not isinstance(message, HumanMessage):
                continue
            flags = getattr(message, "additional_kwargs", {}) or {}
            if flags.get("xframe_context") or flags.get("xframe_job_event"):
                continue
            user_message = str(message.content or "")
            break

        return ToolContext(
            project_id=state.project_id,
            user_id=state.user_id,
            # El id de conversación real, no el del proyecto. Con el del proyecto, los
            # eventos del worker acababan en otra clave de Redis y el usuario no veía
            # aparecer ningún plano.
            conversation_id=state.conversation_id or state.project_id,
            mode=str(state.mode or AgentMode.PREPRODUCTION),
            credits_available=await balance(state.user_id),
            user_message=user_message,
            resource_refs=state.resource_refs or [],
        )

    def _exhausted(self, messages: list[Any], billable: set[str]) -> str:
        """Los contadores se derivan del turno en curso, no del historial completo."""
        if count_tool_calls(messages) >= MAX_TOOL_CALLS:
            return "tool_calls"
        if billable and count_tool_calls(messages, billable) >= MAX_GENERATIONS_PER_TURN:
            return "generations"
        return ""

    def _closing(self, reason: str) -> str:
        if reason == "generations":
            return (
                "You have reached the generation limit for this turn. Do not try to "
                "generate anything else. Tell the user what you produced, what is still "
                "pending, and let them ask you to continue."
            )
        return (
            "You have reached the tool call limit for this turn. Summarise what you did "
            "and what remains, and stop."
        )


class RootToolsNode:
    """
    Ejecuta UNA tool call — la de `root_tool_call_id`. El paralelismo lo da el fan-out
    con `Send` del router, no un bucle aquí dentro.
    """

    async def __call__(
        self, state: XframeState, config: dict[str, Any] | None = None
    ) -> PartialXframeState:
        tool_call = self._find(state)
        if tool_call is None:
            logger.warning("tool_call_not_found", extra={"id": state.root_tool_call_id})
            return PartialXframeState()

        # Todo lo que preceda a la tool va protegido. Sin este try, un fallo de BD al
        # construir el contexto sube sin capturar, LangGraph aborta el superstep y
        # **cancela las ramas hermanas**, dejando reservas de crédito huérfanas.
        try:
            ctx = await RootNode()._build_tool_context(state)
            tools = {t.name: t for t in await ToolFactory.build_for_mode(ctx)}
        except Exception as e:
            logger.exception("tool_setup_failed", extra={"tool": tool_call["name"]})
            return self._message(
                tool_call,
                f"Could not prepare the {tool_call['name']} tool: {type(e).__name__}. "
                f"This is an infrastructure problem on our side, not something you can "
                f"fix by adjusting arguments. Tell the user and stop.",
            )

        tool = tools.get(tool_call["name"])
        if tool is None:
            available = ", ".join(sorted(tools))
            return self._message(
                tool_call,
                f"The tool '{tool_call['name']}' is not available in {state.mode} mode. "
                f"Available here: {available}. If you need a generation tool, call "
                f"switch_mode to production first, and note the switch only takes effect "
                f"on your next message.",
            )

        # `ainvoke` y no `_arun`: es lo que valida los argumentos contra el args_schema
        # con los Literal poblados desde la BD. Llamando a `_arun` a pelo, un modelo
        # inventado no daba un ValidationError legible sino un TypeError que el agente
        # interpretaba como bug interno y tenía prohibido reintentar.
        result = await tool.bind_context(ctx).ainvoke(tool_call)

        content = getattr(result, "content", result)
        artifact = getattr(result, "artifact", None)

        update = PartialXframeState(
            messages=[ToolMessage(content=str(content), tool_call_id=tool_call["id"], artifact=artifact)]
        )

        # switch_mode tiene que devolver el modo en el estado; si solo lo escribe en la
        # tabla, nadie lo lee nunca y el agente se queda en preproducción para siempre.
        if tool_call["name"] == "switch_mode":
            if mode := self._mode_from(artifact):
                update.mode = mode

        return update

    def _find(self, state: XframeState) -> dict[str, Any] | None:
        for message in reversed(state.messages):
            for call in getattr(message, "tool_calls", None) or []:
                if call["id"] == state.root_tool_call_id:
                    return call
        return None

    def _message(self, tool_call: dict[str, Any], content: str) -> PartialXframeState:
        return PartialXframeState(
            messages=[ToolMessage(content=content, tool_call_id=tool_call["id"])]
        )

    def _mode_from(self, artifact: Any) -> AgentMode | None:
        raw = None
        if isinstance(artifact, dict):
            raw = artifact.get("mode")
        elif artifact is not None:
            raw = getattr(artifact, "mode", None)
        try:
            return AgentMode(str(raw)) if raw else None
        except ValueError:
            return None


class MemoryCollectorNode:
    """
    Destila la biblia de estilo en paralelo al turno.

    Adaptador sobre `memory.collector.MemoryCollectorNode`, que estaba escrito, probado
    y sin enganchar a ningún grafo — con lo que la biblia no se rellenaba nunca y el
    prompt le prometía al usuario una memoria que no existía.

    El adaptador existe solo porque el colector se instancia con `project_id`, que no se
    conoce hasta tener el estado en la mano. Los errores los gestiona él: la memoria es
    una mejora de calidad y un colector roto no puede impedir que el usuario responda.
    """

    async def __call__(
        self, state: XframeState, config: dict[str, Any] | None = None
    ) -> PartialXframeState:
        from app.memory.collector import MemoryCollectorNode as Collector
        from app.memory.onboarding import MemoryOnboarding

        # Arranque de la biblia. `should_run()` es idempotente y barato a propósito —una
        # consulta de existencia más un conteo—, así que se puede preguntar en cada turno.
        # Sin esto la biblia no tenía primera versión: el colector solo sabe *actualizar*
        # lo que ya existe, y el módulo de onboarding estaba escrito sin ningún importador.
        try:
            onboarding = MemoryOnboarding(state.project_id)
            if await onboarding.should_run():
                result = await onboarding.run(config=config)
                logger.info(
                    "memory_onboarding_ran",
                    extra={"project": state.project_id, "result": type(result).__name__},
                )
        except Exception:
            logger.exception("memory_onboarding_failed", extra={"project": state.project_id})

        return await Collector(state.project_id).arun(state, config)
