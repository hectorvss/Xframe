"""
Compactación del historial.

Ventana deslizante + resumen, portando `ConversationCompactionManager` de PostHog. La
mecánica es la suya: cuando la conversación pasa del techo de tokens, se resume todo lo
anterior a un punto de corte y se reemplaza el historial usando `ReplaceMessages`.

**Y aquí está el punto de correctitud más importante de todo el sistema.**

Un resumen es una compresión con pérdida, y lo que se pierde primero son los detalles
concretos: que Marco lleva chaqueta de cuero marrón, que el grano es de 35 mm empujado
un paso, que quedan pendientes los planos 7, 8 y 12. PostHog reinyecta la todo list y el
modo activo tras compactar. Nosotros tenemos que reinyectar eso **y además** la biblia de
estilo, las fichas de personaje y el estado operativo de producción.

La razón por la que esto importa más aquí que allí: si Max olvida un detalle, da una
respuesta peor y el usuario la corrige gratis. Si Xframe olvida que Marco lleva chaqueta
de cuero, genera un plano con otra chaqueta, y ese plano **ya se ha cobrado**. El fallo
se paga en créditos de generación, no en tokens.

La reinyección es **condicional**: solo se repone lo que no es evidente en la ventana
nueva. Reinyectar a ciegas gastaría, en cada compactación, el presupuesto que la
compactación acababa de liberar.

Orden fijo tras el resumen, de lo que menos se puede perder a lo que menos duele:
    resumen → memoria (biblia + fichas) → planos pendientes → todos → modo
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agent.state import (
    AgentMode,
    PartialXframeState,
    ReplaceMessages,
    Todo,
    XframeState,
)
from app.config import get_settings
from app.context.manager import (
    CONTEXT_MESSAGE_FLAG,
    context_message,
    context_message_kind,
    is_context_message,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Presupuesto                                                                  #
# --------------------------------------------------------------------------- #

CONVERSATION_WINDOW_SIZE = 100_000
"""Techo de tokens de la conversación. Por encima, se compacta."""

APPROXIMATE_TOKEN_LENGTH = 4
"""Caracteres por token. El mismo que usa el presupuesto de contexto, a propósito."""

WINDOW_MAX_MESSAGES = 16
WINDOW_MAX_TOKENS = 2_048
"""
Tamaño de la ventana que sobrevive sin resumir. Deliberadamente pequeño: el resumen es
quien carga con la historia, y la ventana solo tiene que dar continuidad inmediata.
"""

MIN_HUMAN_MESSAGES = 2
"""
Por debajo de esto no se compacta jamás. Resumir una conversación de dos mensajes
destruye más contexto del que ahorra, y encima cuesta una llamada.
"""


# --------------------------------------------------------------------------- #
# Prompts de reinyección                                                       #
# --------------------------------------------------------------------------- #

SUMMARY_PROMPT = """
Summarize the conversation so far so that work on this film project can continue without
it. Be exhaustive about decisions and specifics; brevity is not the goal, recoverability
is.

Your summary must contain these sections:

1. Primary request and intent — what the user is making, in their words.
2. Creative decisions — the look, the tone, the references agreed on, and any decision
   the user reversed (say what it was reversed FROM as well as TO).
3. Shots — every shot discussed, its narrative position, its status, and what was
   generated for it. Include shot ids.
4. Elements — every character, location and prop, with the physical details established.
5. Rejections and corrections — what the user rejected and the reason given. These are
   the most valuable lines in the summary: they are what stops the same credits being
   spent twice on the same mistake.
6. Errors and failures — failed generations and why.
7. Pending work — what remains, in the order it should be done.

Wrap your reasoning in <analysis> tags and the final summary in <summary> tags.
CRITICAL: keep concrete details. A summary that says "we discussed the character's look"
instead of "the character wears a brown leather jacket and has a scar over the left
eyebrow" is a failed summary.
""".strip()


SUMMARY_REINJECTION_PROMPT = """
<conversation_summary>
This summarizes the earlier part of this conversation, which has been compacted to save
context. Treat it as an accurate record of what was agreed.

{summary}
</conversation_summary>
""".strip()


MEMORY_REMINDER_PROMPT = """
<memory_reminder>
The conversation was just compacted. This is the project's creative memory, restated
because the messages that established it are no longer in your window. It is binding:
generate every shot from here on so it agrees with this.

{memory}
</memory_reminder>
""".strip()


PRODUCTION_REMINDER_PROMPT = """
<production_state>
Operational state of the project after compaction, in narrative order:

{shots}

Do not regenerate a shot that is already ready or approved. Check here before spending
credits.
</production_state>
""".strip()


TODO_REMINDER_PROMPT = """
<todo_reminder>
Your todo list is still active:

{todos}
</todo_reminder>
""".strip()


MODE_REMINDER_PROMPT = """
<mode_reminder>
You are in {mode} mode. The tools you have are the tools this mode allows.
</mode_reminder>
""".strip()


# --------------------------------------------------------------------------- #
# Estado operativo a reinyectar                                                #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class OperationalState:
    """
    Lo que hay que reponer tras compactar, además del resumen.

    Se pasa como dato y no se lee de BD aquí para que la compactación siga siendo
    testeable sin base de datos ni LLM. Quien la invoca ya tiene el contexto cargado.
    """

    memory: str = ""
    """Bloque de memoria ya formateado (`ProjectMemoryStore.format_for_prompt`)."""

    pending_shots: list[tuple[str, int | None, str]] = field(default_factory=list)
    """`(shot_id, position, status)` en orden narrativo. Todos los planos, no solo los pendientes:
    saber cuáles están listos es lo que evita el regenerado accidental."""

    todos: list[Todo] = field(default_factory=list)
    mode: AgentMode | None = None


@dataclass(slots=True)
class CompactionReport:
    """Telemetría. Sin esto no hay forma de saber si la reinyección está funcionando."""

    compacted: bool = False
    tokens_before: int = 0
    messages_before: int = 0
    messages_after: int = 0
    reinjected: list[str] = field(default_factory=list)
    window_boundary_found: bool = True

    def emit(self, *, project_id: str) -> None:
        if not self.compacted:
            return
        logger.info(
            "xframe conversation compacted",
            extra={
                "event": "xframe_conversation_compacted",
                "project_id": project_id,
                "tokens_before": self.tokens_before,
                "messages_before": self.messages_before,
                "messages_after": self.messages_after,
                "reinjected": self.reinjected,
                "window_boundary_found": self.window_boundary_found,
            },
        )


# --------------------------------------------------------------------------- #
# Compactador                                                                  #
# --------------------------------------------------------------------------- #

Summarizer = Callable[[Sequence[BaseMessage]], Awaitable[str]]


class ConversationCompactor:
    """
    Ventana deslizante + resumen, con reinyección del estado que el resumen no conserva.

    `summarize` se inyecta para poder testear la compactación entera sin LLM. En
    producción, si no se pasa, se usa `config.model_summarize`.
    """

    def __init__(self, *, summarize: Summarizer | None = None) -> None:
        self._summarize = summarize or _default_summarizer

    # -- decisión ----------------------------------------------------------- #

    def should_compact(self, messages: Sequence[BaseMessage]) -> bool:
        """
        ¿Toca compactar?

        Estimación por caracteres/4 y no conteo exacto por API: el conteo exacto cuesta
        una llamada de red en cada turno para responder a una pregunta cuya respuesta es
        "no" el 99% de las veces. Se acepta el error de la heurística porque el umbral
        (100k sobre ventanas mucho mayores) ya deja margen de sobra para equivocarse.
        """
        humans = [m for m in messages if isinstance(m, HumanMessage) and not is_context_message(m)]
        if len(humans) <= MIN_HUMAN_MESSAGES:
            return False
        return estimate_tokens(messages) > CONVERSATION_WINDOW_SIZE

    # -- ventana ------------------------------------------------------------ #

    @staticmethod
    def find_window_boundary(
        messages: Sequence[BaseMessage],
        *,
        max_messages: int = WINDOW_MAX_MESSAGES,
        max_tokens: int = WINDOW_MAX_TOKENS,
    ) -> str | None:
        """
        Punto de corte de la ventana, buscando hacia atrás desde el final.

        Gasta dos presupuestos a la vez (mensajes y tokens) y **exige que la ventana
        empiece en un mensaje humano o de asistente**. Nunca a mitad de una secuencia de
        tool calls: una ventana que arranca en un `ToolMessage` deja una respuesta de
        herramienta sin la llamada que la pidió, y eso lo rechaza la propia API.
        """
        boundary: str | None = None
        for message in reversed(messages):
            max_tokens -= estimate_message_tokens(message)
            max_messages -= 1
            if max_tokens < 0 or max_messages < 0:
                break
            if isinstance(message, ToolMessage):
                continue
            if isinstance(message, (HumanMessage, AIMessage)) and message.id:
                boundary = message.id
        return boundary

    # -- compactación -------------------------------------------------------- #

    async def compact(
        self,
        state: XframeState,
        operational: OperationalState | None = None,
    ) -> PartialXframeState:
        """
        Compacta si hace falta. Devuelve estado parcial vacío si no.

        El historial nuevo se entrega envuelto en `ReplaceMessages` para que el reductor
        `add_and_merge_messages` sustituya en vez de fusionar por id. Sin ese marcador, la
        compactación no compactaría nada: el reductor volvería a añadir los mensajes
        viejos junto al resumen.
        """
        messages = list(state.messages)
        report = CompactionReport(
            tokens_before=estimate_tokens(messages), messages_before=len(messages)
        )
        if not self.should_compact(messages):
            return PartialXframeState()

        operational = operational or _operational_from_state(state)

        boundary_id = self.find_window_boundary(messages)
        if boundary_id is None:
            # Ni un mensaje cabe en la ventana. Se copia el último humano al principio
            # con id nuevo, para que la petición viva del usuario sobreviva al recorte:
            # un resumen sin la pregunta que lo motivó no sirve para contestar.
            report.window_boundary_found = False
            window: list[BaseMessage] = _copy_last_human(messages)
            to_summarize = messages
        else:
            index = next(i for i, m in enumerate(messages) if m.id == boundary_id)
            window = messages[index:]
            to_summarize = messages[:index]

        if not to_summarize:
            return PartialXframeState()

        summary = await self._summarize(to_summarize)
        summary_message = context_message(
            SUMMARY_REINJECTION_PROMPT.format(summary=summary.strip()), kind="summary"
        )

        reminders = build_reminders(window, operational)
        report.reinjected = [context_message_kind(m) or "?" for m in reminders]

        new_messages: list[BaseMessage] = [summary_message, *reminders, *window]
        report.compacted = True
        report.messages_after = len(new_messages)
        report.emit(project_id=state.project_id)

        # `model_construct` y no el constructor normal: la validación de Pydantic
        # reconstruye `messages` como `list` corriente y se lleva por delante la subclase
        # `ReplaceMessages`. El reductor comprueba el tipo con `isinstance`, así que esa
        # coerción silenciosa haría que la compactación no compactara nada — el historial
        # viejo volvería a fusionarse junto al resumen. Los mensajes ya son objetos
        # válidos aquí, así que saltarse la validación no pierde nada.
        return PartialXframeState.model_construct(messages=ReplaceMessages(new_messages))


# --------------------------------------------------------------------------- #
# Reinyección                                                                  #
# --------------------------------------------------------------------------- #


def build_reminders(
    window: Sequence[BaseMessage], operational: OperationalState
) -> list[BaseMessage]:
    """
    Construye los recordatorios que hay que reponer tras el resumen.

    **Condicional**: cada bloque se omite si su información ya es evidente en la ventana
    nueva. Función pura, y por eso testeable: es la pieza cuyo fallo cuesta créditos, así
    que tiene que ser la más fácil de verificar del módulo.
    """
    reminders: list[BaseMessage] = []
    window_text = _window_text(window)

    # 1. Memoria — biblia de estilo y fichas de personaje. Va primero porque es lo único
    #    de esta lista cuya pérdida cuesta dinero en vez de tokens.
    if operational.memory.strip() and not _memory_evident(window):
        reminders.append(
            context_message(
                MEMORY_REMINDER_PROMPT.format(memory=operational.memory.strip()), kind="memory"
            )
        )

    # 2. Estado de producción — qué plano está listo y cuál no.
    if operational.pending_shots and not _production_evident(window_text, operational):
        lines = "\n".join(
            f"- shot {shot_id} (position {position if position is not None else '-'}): {status}"
            for shot_id, position, status in operational.pending_shots
        )
        reminders.append(
            context_message(PRODUCTION_REMINDER_PROMPT.format(shots=lines), kind="production")
        )

    # 3. Todo list.
    if operational.todos and not _todos_evident(window_text):
        lines = "\n".join(
            f"- [{'x' if t.status == 'done' else ' '}] {t.text}"
            f"{' (in progress)' if t.status == 'in_progress' else ''}"
            for t in operational.todos
        )
        reminders.append(context_message(TODO_REMINDER_PROMPT.format(todos=lines), kind="todo"))

    # 4. Modo activo. El último porque el modo también está en el estado del grafo y en
    #    el toolset: es el dato de esta lista con más redundancia fuera de la ventana.
    if operational.mode is not None and not _mode_evident(window_text, operational.mode):
        reminders.append(
            context_message(
                MODE_REMINDER_PROMPT.format(mode=operational.mode.value), kind="mode"
            )
        )

    return reminders


def _window_text(window: Sequence[BaseMessage]) -> str:
    return "\n".join(m.content for m in window if isinstance(m.content, str)).lower()


def _memory_evident(window: Sequence[BaseMessage]) -> bool:
    """
    ¿Está ya la memoria en la ventana?

    Solo cuenta un mensaje de contexto de tipo memoria o resumen de memoria — no que el
    texto "aparezca por ahí". Con la memoria se es conservador a propósito: reinyectarla
    de más cuesta unos cientos de tokens; de menos, un plano regenerado.
    """
    return any(context_message_kind(m) in ("memory", "onboarding") for m in window)


def _production_evident(window_text: str, operational: OperationalState) -> bool:
    """
    Evidente solo si la ventana menciona **todos** los planos que arrastramos.

    Todos y no alguno: el riesgo que se cubre es regenerar un plano que ya está listo, y
    para eso el modelo necesita el censo entero, no una muestra.
    """
    return all(shot_id.lower() in window_text for shot_id, _, _ in operational.pending_shots)


def _todos_evident(window_text: str) -> bool:
    return "<todo" in window_text or "todo_reminder" in window_text


def _mode_evident(window_text: str, mode: AgentMode) -> bool:
    return f"{mode.value} mode" in window_text or "<mode_reminder>" in window_text


def _copy_last_human(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Copia el último humano real con id nuevo. Sin él, la ventana no tiene pregunta."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and not is_context_message(message):
            return [HumanMessage(content=message.content, id=str(uuid4()))]
    return []


def _operational_from_state(state: XframeState) -> OperationalState:
    """Estado operativo deducible del grafo, cuando el llamante no aporta el de BD."""
    return OperationalState(todos=list(state.todos or []), mode=state.mode)


# --------------------------------------------------------------------------- #
# Conteo y resumen                                                             #
# --------------------------------------------------------------------------- #


def estimate_message_tokens(message: BaseMessage) -> int:
    """Estimación por caracteres/4, incluyendo los argumentos de las tool calls."""
    content = message.content
    chars = len(content) if isinstance(content, str) else len(str(content))
    for call in getattr(message, "tool_calls", None) or []:
        chars += len(str(call.get("args", "")))
    return chars // APPROXIMATE_TOKEN_LENGTH


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


async def _default_summarizer(messages: Sequence[BaseMessage]) -> str:
    """
    Resumidor por defecto: `config.model_summarize`, sin streaming.

    Limpia los `cache_control` antes de llamar: los breakpoints de caché no son válidos
    en la llamada de resumen y la API los rechaza. Import perezoso del proveedor para que
    el módulo se pueda importar sin `langchain_anthropic`.
    """

    settings = get_settings()
    from app import llm

    model = llm.chat_model("summarize", max_tokens=8_192, streaming=False)
    response = await model.ainvoke(
        [*_strip_cache_control(messages), HumanMessage(content=SUMMARY_PROMPT)]
    )
    return parse_summary(str(response.content))


def _strip_cache_control(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    cleaned: list[BaseMessage] = []
    for message in messages:
        if isinstance(message.content, list):
            message = message.model_copy(deep=True)
            for block in message.content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
        cleaned.append(message)
    return cleaned


def parse_summary(text: str) -> str:
    """
    Extrae `<summary>`, cayendo al texto entero si no está.

    Tolerante a propósito: un resumen sin las etiquetas sigue siendo un resumen útil, y
    perderlo por un fallo de formato costaría la conversación entera.
    """
    match = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()


__all__ = [
    "CONVERSATION_WINDOW_SIZE",
    "CONTEXT_MESSAGE_FLAG",
    "CompactionReport",
    "ConversationCompactor",
    "OperationalState",
    "build_reminders",
    "estimate_tokens",
    "parse_summary",
]
