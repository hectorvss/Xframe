"""
Los dos nodos del grafo.

Aquí vive todo lo que la topología no dice: montaje del toolset según el modo, inyección
del contexto, límites y su degradación, y ejecución de herramientas con las cuatro capas
de captura de errores.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.prompts.base import build_system_prompt
from app.agent.state import (
    MAX_GENERATIONS_PER_TURN,
    MAX_TOOL_CALLS,
    AgentMode,
    PartialXframeState,
    XframeState,
)
from app.config import get_settings
from app.tools.base import ToolContext, ToolFactory

logger = logging.getLogger(__name__)


class RootNode:
    """
    El LLM. Monta el toolset del modo, inyecta el contexto del proyecto y llama al modelo.
    """

    async def __call__(self, state: XframeState, config: dict[str, Any] | None = None) -> PartialXframeState:
        settings = get_settings()

        ctx = await self._build_tool_context(state)
        tools = await ToolFactory.build_for_mode(ctx)

        # Contexto del proyecto: va como mensaje justo antes del humano, NO en el system
        # prompt. Así entra en la caché de prompt y sobrevive a la compactación.
        from app.context.manager import ContextManager

        context_messages = await ContextManager(state.project_id).build_messages(state)

        system = build_system_prompt(mode=str(state.mode or AgentMode.PREPRODUCTION))

        model = ChatAnthropic(
            model=settings.model_root,
            api_key=settings.anthropic_api_key,
            max_tokens=8192,
            temperature=0.4,
        )

        # Degradación amable al llegar al límite: en vez de lanzar una excepción, le
        # quitamos las herramientas al modelo y le pedimos que cierre. Es el patrón de
        # PostHog, y evita que el usuario vea un error crudo a mitad de un trabajo largo.
        exhausted, reason = self._limits_exhausted(state)
        if exhausted:
            logger.info("limits_exhausted", extra={"reason": reason})
            messages = [
                SystemMessage(content=system),
                *context_messages,
                *state.messages,
                HumanMessage(content=self._closing_instruction(reason)),
            ]
            response = await model.ainvoke(messages)
        else:
            messages = [SystemMessage(content=system), *context_messages, *state.messages]
            response = await model.bind_tools(tools).ainvoke(messages)

        return PartialXframeState(messages=[response])

    async def _build_tool_context(self, state: XframeState) -> ToolContext:
        from app.jobs.credits import balance

        return ToolContext(
            project_id=state.project_id,
            user_id=state.user_id,
            conversation_id=state.project_id,
            mode=str(state.mode or AgentMode.PREPRODUCTION),
            credits_available=await balance(state.user_id),
        )

    def _limits_exhausted(self, state: XframeState) -> tuple[bool, str]:
        tool_calls = sum(
            len(getattr(m, "tool_calls", []) or []) for m in state.messages if isinstance(m, AIMessage)
        )
        if tool_calls >= MAX_TOOL_CALLS:
            return True, "tool_calls"
        if state.generations_this_turn >= MAX_GENERATIONS_PER_TURN:
            return True, "generations"
        return False, ""

    def _closing_instruction(self, reason: str) -> str:
        if reason == "generations":
            return (
                "You have reached the generation limit for this turn. Do not try to generate "
                "anything else. Tell the user what you produced, what is still pending, and "
                "let them ask you to continue."
            )
        return (
            "You have reached the tool call limit for this turn. Summarise what you did and "
            "what remains, and stop."
        )


class RootToolsNode:
    """
    Ejecuta UNA tool call — la identificada por `root_tool_call_id`. El paralelismo lo da
    el fan-out con `Send` del router, no un bucle aquí dentro.
    """

    async def __call__(self, state: XframeState, config: dict[str, Any] | None = None) -> PartialXframeState:
        tool_call = self._find_tool_call(state)
        if tool_call is None:
            logger.warning("tool_call_not_found", extra={"id": state.root_tool_call_id})
            return PartialXframeState()

        ctx = await RootNode()._build_tool_context(state)
        tools = {t.name: t for t in await ToolFactory.build_for_mode(ctx)}
        tool = tools.get(tool_call["name"])

        if tool is None:
            # Puede pasar legítimamente: el modelo pidió una tool que existe en otro modo.
            # Enumerar las disponibles le permite corregirse en el siguiente turno.
            content = (
                f"The tool '{tool_call['name']}' is not available in {state.mode} mode. "
                f"Available tools here: {', '.join(sorted(tools))}. "
                f"If you need a generation tool, switch to production mode first."
            )
            return PartialXframeState(
                messages=[ToolMessage(content=content, tool_call_id=tool_call["id"])]
            )

        content, ui_payload = await tool.bind_context(ctx)._arun(**tool_call["args"])

        message = ToolMessage(
            content=content,
            tool_call_id=tool_call["id"],
            artifact=ui_payload,
        )

        generations = 1 if getattr(tool, "consumes_credits", False) else 0
        return PartialXframeState(
            messages=[message],
            generations_this_turn=state.generations_this_turn + generations,
        )

    def _find_tool_call(self, state: XframeState) -> dict[str, Any] | None:
        for message in reversed(state.messages):
            for tc in getattr(message, "tool_calls", []) or []:
                if tc["id"] == state.root_tool_call_id:
                    return tc
        return None
