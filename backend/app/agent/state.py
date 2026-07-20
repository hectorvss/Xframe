"""
Estado del grafo.

Porta el patrón `AssistantState`/`PartialAssistantState` de `ee/hogai/utils/types/base.py`:

- Reductores anotados, para que la agregación del fan-out no necesite código de merge.
- Upsert de mensajes por ID (un mensaje que se actualiza no se duplica).
- Centinelas `CLEAR_*`, porque `None` significa "no cambies este campo", no "bórralo".
  Sin esto no se puede salir de un modo.

Regla dura heredada de PostHog: **nunca binarios ni URLs firmadas en el estado**. El
estado guarda `AssetRef` (id + tipo + estado); el cliente recibe el objeto enriquecido.
Un checkpoint con vídeos dentro es un checkpoint que no se puede leer.
"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated, Any, Literal, Sequence, Union
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Nodos y modos                                                                #
# --------------------------------------------------------------------------- #


class NodeName(StrEnum):
    START = "__start__"
    END = "__end__"
    ROOT = "root"
    ROOT_TOOLS = "root_tools"
    MEMORY_COLLECTOR = "memory_collector"


class AgentMode(StrEnum):
    """
    El modo determina el toolset. La restricción es estructural: en `PREPRODUCTION`
    las herramientas de generación no existen, así que no se pueden gastar créditos
    aunque el modelo se empeñe.
    """

    PREPRODUCTION = "preproduction"
    PRODUCTION = "production"
    EDIT = "edit"


JOB_EVENT_FLAG = "xframe_job_event"
"""
Marca de un mensaje que **no** escribió el usuario: un evento del sistema que abre turno.

Hoy solo lo pone la reanudación por jobs terminados (`app/jobs/resume.py`), que necesita
meter en el hilo "han aterrizado estos planos" sin que eso sea una petición nueva del
director. Va en `additional_kwargs` de un `HumanMessage` por dos razones prácticas:

- El frontend lo pinta distinto. Un aviso del sistema con la burbuja del usuario es una
  mentira sobre quién dijo qué, y el usuario acaba respondiendo a algo que él no pidió.
- El rol sigue siendo `human` porque un `SystemMessage` en mitad del historial se comporta
  de forma distinta en cada proveedor, y algunos lo reordenan o lo ignoran.

Deliberadamente **no** es `CONTEXT_MESSAGE_FLAG`. Los mensajes de contexto no abren turno
(`messages_since_last_human` los salta), y eso es correcto para ellos: son el estado del
editor adjunto a la petición del usuario. Un evento de jobs sí abre turno, y tiene que
hacerlo para que `count_tool_calls` cuente desde aquí. Si se marcara como contexto, el
turno reanudado heredaría el presupuesto de tool calls ya gastado del turno anterior y se
quedaría sin herramientas justo cuando le toca montar el corte.
"""


# Centinela: None significa "no cambies", este valor significa "bórralo".
# Debe ser str para que sobreviva a la serialización msgpack del checkpointer.
CLEAR_SUPERMODE: str = "__CLEAR_SUPERMODE__"


class SuperMode(StrEnum):
    PLAN = "plan"


# --------------------------------------------------------------------------- #
# Referencias a artefactos                                                     #
# --------------------------------------------------------------------------- #


class AssetRef(BaseModel):
    """Lo que va en el estado. El binario vive en storage; la URL se firma al enviar."""

    asset_id: str
    kind: Literal["image", "video", "audio", "cut"]
    status: Literal["generating", "ready", "failed"]
    shot_id: str | None = None


class JobResult(BaseModel):
    """Resultado de una tarea del fan-out. Se acumula con el reductor `append`."""

    job_id: str
    shot_id: str | None = None
    ok: bool
    asset: AssetRef | None = None
    error: str | None = None
    credits_charged: int = 0


class Todo(BaseModel):
    id: str
    text: str
    status: Literal["pending", "in_progress", "done"] = "pending"


# --------------------------------------------------------------------------- #
# Reductores                                                                   #
# --------------------------------------------------------------------------- #


def replace(_: Any | None, right: Any | None) -> Any | None:
    return right


def replace_if_not_none(left: Any | None, right: Any | None) -> Any | None:
    """`None` = "no toques este campo". Necesario para los updates parciales."""
    return right if right is not None else left


def replace_supermode(left: Any, right: Any) -> str | None:
    """Igual que arriba, pero con salida explícita vía centinela."""
    if right == CLEAR_SUPERMODE:
        return None
    return right if right is not None else left


def append(left: list | None, right: list | None) -> list:
    return [*(left or []), *(right or [])]


class ReplaceMessages(list):
    """
    Marcador: cuando el reductor recibe una lista de este tipo, sustituye en vez de
    fusionar. Es lo que permite compactar el historial.
    """


def add_and_merge_messages(
    left: Sequence[BaseMessage] | None,
    right: Sequence[BaseMessage] | None,
) -> list[BaseMessage]:
    """
    Fusiona por ID en vez de concatenar a ciegas.

    Un mensaje que ya existe se **actualiza en su sitio** (así un asset que pasa de
    `generating` a `ready` no aparece dos veces en el chat), y uno nuevo se añade al
    final. `ReplaceMessages` corta por lo sano para la compactación.
    """
    if isinstance(right, ReplaceMessages):
        return list(right)

    left = list(left or [])
    if not right:
        return left

    by_id = {m.id: i for i, m in enumerate(left) if getattr(m, "id", None)}
    merged = list(left)
    for msg in right:
        msg_id = getattr(msg, "id", None)
        if msg_id is not None and msg_id in by_id:
            merged[by_id[msg_id]] = msg
        else:
            if msg_id is not None:
                by_id[msg_id] = len(merged)
            merged.append(msg)
    return merged


AnyMessage = BaseMessage
"""
El tipo de los mensajes del estado.

Era una `Union[HumanMessage, AIMessage, ToolMessage, BaseMessage]` y eso rompía el turno
en cuanto una tool devolvía resultado. Al validar un `ToolMessage` contra la unión,
pydantic prueba sus miembros y llega a `AIMessage`, cuyo validador `mode="before"`
(`_backwards_compat_tool_calls`) hace `values.get(...)` sobre lo que le llegue: con una
instancia de mensaje en vez de un dict, `AttributeError: 'ToolMessage' object has no
attribute 'get'`, dentro del nodo `root_tools` y sin traza que apunte a este fichero.

`BaseMessage` a secas es la clase padre de todos, así que la comprobación es un
`isinstance` que pasa sin tocar la instancia: pydantic conserva el subtipo real —con su
`tool_call_id` y sus `tool_calls`— porque `revalidate_instances` es `never` por defecto.
La unión no aportaba nada que esto no dé.
"""


# --------------------------------------------------------------------------- #
# Estado                                                                       #
# --------------------------------------------------------------------------- #


class XframeState(BaseModel):
    """Estado completo del grafo. Se persiste en el checkpointer de Postgres."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: Annotated[list[AnyMessage], add_and_merge_messages] = Field(default_factory=list)

    project_id: str
    user_id: str

    mode: Annotated[AgentMode | None, replace_if_not_none] = None
    supermode: Annotated[str | None, replace_supermode] = None

    todos: Annotated[list[Todo] | None, replace_if_not_none] = None

    # Agregación del fan-out: cada subtarea aporta su resultado y el reductor los junta.
    job_results: Annotated[list[JobResult], append] = Field(default_factory=list)

    # Identidad de la rama dentro de un fan-out (patrón `Send` de PostHog).
    root_tool_call_id: Annotated[str | None, replace] = None

    # Se rellena en cada turno desde la BD; no se persiste como fuente de verdad.
    plan_approved: Annotated[bool | None, replace_if_not_none] = None

    # Qué está mirando el usuario. Viene del frontend en cada turno y alimenta al
    # ContextManager. Sin esto, el contexto que ve el agente es genérico.
    open_tab: Annotated[str | None, replace_if_not_none] = None
    selected_asset_ids: Annotated[list[str] | None, replace_if_not_none] = None

    conversation_id: Annotated[str | None, replace_if_not_none] = None
    """
    El `thread_id` de LangGraph, copiado al estado. Las tools lo necesitan para que el
    worker sepa a qué stream publicar; sin él, `_emit` sale por su return temprano y el
    usuario no ve aparecer ningún plano.
    """

    def model_copy_for_branch(self, tool_call_id: str) -> "XframeState":
        return self.model_copy(update={"root_tool_call_id": tool_call_id})


class PartialXframeState(BaseModel):
    """
    Lo que devuelve un nodo. Todos los campos opcionales: `None` = "no cambies".
    Devolver el estado completo desde un nodo es un bug esperando a pasar.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: list[AnyMessage] | None = None
    mode: AgentMode | None = None
    supermode: str | None = None
    todos: list[Todo] | None = None
    job_results: list[JobResult] | None = None
    root_tool_call_id: str | None = None
    plan_approved: bool | None = None
    open_tab: str | None = None
    selected_asset_ids: list[str] | None = None
    conversation_id: str | None = None


# --------------------------------------------------------------------------- #
# Límites                                                                      #
# --------------------------------------------------------------------------- #

MAX_TOOL_CALLS = 24
RECURSION_LIMIT = 96
MAX_GENERATIONS_PER_TURN = 12
"""
Tercer límite, el que PostHog no necesita: por recurso, no por tokens. Un bucle de
tool calls sale barato; un bucle de renders, no.
"""


def messages_since_last_human(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Los mensajes del turno en curso, es decir, desde la última entrada del usuario."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage) and not _is_context(messages[i]):
            return list(messages[i + 1 :])
    return list(messages)


def _is_context(message: BaseMessage) -> bool:
    """
    Los mensajes de contexto son `HumanMessage` marcados; no abren turno.

    La marca se importa de `context.manager` en vez de duplicar el literal aquí: copiar
    la cadena es exactamente el tipo de divergencia silenciosa que rompió las juntas de
    este backend la primera vez. El import es perezoso porque `context.manager` no
    importa `state`, pero no quiero crear la dependencia a nivel de módulo.
    """
    from app.context.manager import CONTEXT_MESSAGE_FLAG

    return bool(getattr(message, "additional_kwargs", {}).get(CONTEXT_MESSAGE_FLAG))


def count_tool_calls(messages: Sequence[BaseMessage], names: set[str] | None = None) -> int:
    """
    Cuenta tool calls del turno, opcionalmente filtrando por nombre.

    Se **deriva de los mensajes** en lugar de llevar un contador en el estado, y eso
    arregla dos bugs de una vez:

    - Un contador acumulado en el estado contaba las llamadas de **toda la conversación**,
      no las del turno: a partir de la nº24 el agente perdía las herramientas para siempre.
    - Bajo fan-out, las N ramas parten del mismo estado y el reductor era "gana el
      último", así que 12 renders paralelos contaban como 1 — el límite caro no aplicaba
      justo donde importa.

    Contando sobre los mensajes ambos casos salen exactos y sin coordinación entre ramas.
    """
    total = 0
    for message in messages_since_last_human(messages):
        for call in getattr(message, "tool_calls", None) or []:
            if names is None or call.get("name") in names:
                total += 1
    return total
