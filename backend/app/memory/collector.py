"""
Colector de memoria.

Porta el `MemoryCollectorNode` de PostHog (`chat_agent/memory/nodes.py`). Corre **en
paralelo** al root, con dos tools de escritura y una ventana de los últimos 10 mensajes,
y va destilando la biblia de estilo y las fichas de personaje a partir de lo que el
usuario aprueba y rechaza.

Tres decisiones que conviene justificar:

**Por qué en paralelo y no dentro del root.** El root está ocupado decidiendo qué
generar; meterle además la responsabilidad de mantener la memoria le añade tools que
compiten por su atención y tokens que compiten por su ventana. Separarlo cuesta una
llamada barata por turno y hace que la memoria se escriba aunque el root se equivoque.

**Por qué ventana de 10 mensajes.** La memoria destila hechos duraderos, y un hecho
duradero aparece en la conversación reciente o no aparece. Darle el historial entero
haría que redescubriera y reescribiera lo mismo en cada turno.

**Por qué las conversaciones del colector NO viven en el estado.** PostHog las guarda en
`memory_collection_messages`, pero `XframeState` está fijado y no tiene ese campo. En vez
de tocar un contrato cerrado, el bucle del colector es interno y acotado: entra, escribe
lo que tenga que escribir en un par de vueltas y sale devolviendo un estado parcial
vacío. La memoria ya es persistente en BD, así que no se pierde nada por no guardar el
andamiaje en el checkpoint.

Modelo barato (`config.model_fast`): la tarea es clasificar y reformular, no razonar.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field, ValidationError

from app.agent.state import PartialXframeState, XframeState
from app.config import get_settings
from app.context.manager import is_context_message
from app.memory.prompts import MEMORY_COLLECTOR_PROMPT, MEMORY_COLLECTOR_TOOL_ERROR_PROMPT
from app.memory.store import MemoryKind, ProjectMemoryStore

logger = logging.getLogger(__name__)

MEMORY_WINDOW = 10
"""Últimos mensajes que ve el colector."""

MAX_COLLECTOR_ITERATIONS = 3
"""
Techo del bucle interno. Sin él, un modelo que nunca dice "[Done]" convierte un nodo
barato en un bucle caro. Tres vueltas bastan para escribir dos o tres frases.
"""


# --------------------------------------------------------------------------- #
# Tools                                                                        #
# --------------------------------------------------------------------------- #
# Nombres de clase en minúscula a propósito: el nombre de la clase ES el nombre de la
# tool que ve el modelo. No renombrar a CamelCase.


class memory_append(BaseModel):
    """Appends one new atomic fact to the project's persistent creative memory."""

    kind: str = Field(
        description=(
            "Which memory to write to: style_bible, character_sheet, "
            "continuity_rules or director_prefs."
        )
    )
    memory_content: str = Field(
        description="One atomic factual sentence. No markdown, no bullet characters."
    )
    element_name: str | None = Field(
        default=None,
        description=(
            "Required for character_sheet: the name of the element (character, location "
            "or prop) this fact describes, exactly as it appears in the project."
        ),
    )


class memory_replace(BaseModel):
    """Replaces an existing fragment of the project's creative memory with another."""

    kind: str = Field(description="Which memory to edit.")
    original_fragment: str = Field(
        description="The existing line to replace, copied verbatim from the memory."
    )
    new_fragment: str = Field(description="What to replace it with.")
    element_name: str | None = Field(default=None, description="Required for character_sheet.")


memory_collector_tools = [memory_append, memory_replace]


# --------------------------------------------------------------------------- #
# Nodo                                                                         #
# --------------------------------------------------------------------------- #


class MemoryCollectorNode:
    """
    Nodo `MEMORY_COLLECTOR` del grafo.

    `element_resolver` traduce el nombre de un element a su `assets.id`, que es lo que
    `project_memory.element_id` referencia. El modelo trabaja con nombres porque es lo
    que ve en el contexto y lo que escribe el usuario con `@`; la BD trabaja con uuids.
    La traducción vive aquí para que ni el prompt ni el store tengan que saber del otro.
    """

    def __init__(
        self,
        project_id: str,
        *,
        store: ProjectMemoryStore | None = None,
        model: Any | None = None,
    ) -> None:
        self._project_id = project_id
        self._store = store or ProjectMemoryStore(project_id)
        self._model = model

    async def arun(self, state: XframeState, config: Any | None = None) -> PartialXframeState:
        """
        Destila la conversación reciente a memoria. Nunca modifica el estado.

        Cualquier fallo se traga y se registra: la memoria es una mejora, y un colector
        roto no puede impedir que el usuario reciba su respuesta.
        """
        try:
            await self._collect(state, config)
        except Exception:  # noqa: BLE001
            logger.exception("memory_collector_failed", extra={"project_id": self._project_id})
        return PartialXframeState()

    async def _collect(self, state: XframeState, config: Any | None) -> None:
        window = self._window(state.messages)
        if not window:
            return

        memory = await self._store.format_for_prompt(max_chars=6_000)
        system = MEMORY_COLLECTOR_PROMPT.format(
            memory=memory or "(empty — this is a brand new project)",
            date=date.today().isoformat(),
        )

        model = self._get_model()
        conversation: list[BaseMessage] = [HumanMessage(content=system), *window]

        for _ in range(MAX_COLLECTOR_ITERATIONS):
            response = await model.ainvoke(conversation, config=config)
            if _is_done(response):
                return
            conversation.append(response)
            conversation.extend(await self._run_tools(response))

    # -- ventana ----------------------------------------------------------- #

    @staticmethod
    def _window(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
        """
        Últimos `MEMORY_WINDOW` mensajes humanos y de asistente.

        Se descartan los `ToolMessage` y los mensajes de contexto: los primeros son
        ruido de fontanería y los segundos son el proyecto entero, que el colector no
        debe confundir con algo que el usuario acaba de decidir. Lo que queremos destilar
        es la conversación, no el inventario.
        """
        relevant = [
            m
            for m in messages
            if isinstance(m, (HumanMessage, AIMessage))
            and not is_context_message(m)
            and isinstance(m.content, str)
            and m.content.strip()
        ]
        return relevant[-MEMORY_WINDOW:]

    # -- tools ------------------------------------------------------------- #

    async def _run_tools(self, response: AIMessage) -> list[ToolMessage]:
        """
        Ejecuta las tool calls contra el store.

        Los `ValueError` del store vuelven como contenido del `ToolMessage`, no como
        excepción: están escritos para que el modelo los lea y se corrija en la vuelta
        siguiente (un "fragmento no encontrado" viene con la lista de líneas válidas).
        """
        out: list[ToolMessage] = []
        for call in getattr(response, "tool_calls", []) or []:
            name = call.get("name")
            try:
                schema = {"memory_append": memory_append, "memory_replace": memory_replace}[name]
                args = schema(**(call.get("args") or {}))
            except (KeyError, ValidationError) as e:
                out.append(
                    ToolMessage(
                        content=MEMORY_COLLECTOR_TOOL_ERROR_PROMPT.format(error=e),
                        tool_call_id=call.get("id", ""),
                    )
                )
                continue

            try:
                content = await self._apply(args)
            except ValueError as e:
                content = str(e)
            except Exception as e:  # noqa: BLE001
                logger.exception("memory_tool_failed", extra={"tool": name})
                content = f"The memory tool failed internally ({type(e).__name__}). Do not retry."
            out.append(ToolMessage(content=content, tool_call_id=call.get("id", "")))
        return out

    async def _apply(self, args: memory_append | memory_replace) -> str:
        kind = _parse_kind(args.kind)
        element_id = await self._resolve_element(kind, args.element_name)

        if isinstance(args, memory_append):
            await self._store.append(kind, args.memory_content, element_id)
            return "Memory appended."

        await self._store.replace(kind, args.original_fragment, args.new_fragment, element_id)
        return "Memory replaced."

    async def _resolve_element(self, kind: MemoryKind, name: str | None) -> str | None:
        """
        Nombre de element → `assets.id`.

        Solo aplica a `character_sheet`; el resto de memorias son del proyecto entero.
        Si el nombre no existe, se levanta un `ValueError` que enumera los que sí, para
        que el modelo se autocorrija en vez de crear una ficha huérfana.
        """
        if kind is not MemoryKind.CHARACTER_SHEET:
            return None
        if not name:
            raise ValueError("character_sheet requires element_name — which element does this describe?")

        from app import db

        row = await db.fetchrow(
            """
            select id from public.assets
             where project_id = $1::uuid and role is not null and lower(name) = lower($2)
             limit 1
            """,
            self._project_id,
            name.strip(),
        )
        if row:
            return str(row["id"])

        rows = await db.fetch(
            "select name from public.assets where project_id = $1::uuid and role is not null",
            self._project_id,
        )
        known = ", ".join(r["name"] for r in rows) or "(none yet)"
        raise ValueError(f"No element named '{name}'. Existing elements: {known}.")

    # -- modelo ------------------------------------------------------------ #

    def _get_model(self) -> Any:
        """
        Modelo barato con las dos tools atadas.

        Import perezoso de `langchain_anthropic` para que el módulo se pueda importar —
        y testear — sin el paquete del proveedor instalado.
        """
        if self._model is not None:
            return self._model
        from langchain_anthropic import ChatAnthropic

        settings = get_settings()
        self._model = ChatAnthropic(
            model=settings.model_fast,
            api_key=settings.anthropic_api_key,
            max_tokens=1_024,
            temperature=0.2,
            streaming=False,
        ).bind_tools(memory_collector_tools)
        return self._model


# --------------------------------------------------------------------------- #
# Utilidades                                                                   #
# --------------------------------------------------------------------------- #


def _is_done(response: Any) -> bool:
    """
    ¿Terminó el colector?

    Dos señales, igual que `check_memory_collection_completed`: el literal `[Done]` o la
    ausencia de tool calls. La segunda es la que de verdad corta el bucle, porque los
    modelos se olvidan del literal más a menudo de lo que uno querría.
    """
    if not isinstance(response, AIMessage):
        return True
    if not getattr(response, "tool_calls", None):
        return True
    content = response.content if isinstance(response.content, str) else ""
    return "[Done]" in content


def _parse_kind(value: str) -> MemoryKind:
    """Valida el tipo de memoria enumerando los válidos si falla."""
    try:
        return MemoryKind(value.strip().lower())
    except ValueError:
        valid = ", ".join(k.value for k in MemoryKind)
        raise ValueError(f"'{value}' is not a memory kind. Valid kinds: {valid}.") from None
