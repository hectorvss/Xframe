# Informe técnico: el NÚCLEO del agente Max AI de PostHog (`ee/hogai`)

> Objetivo: extraer los patrones reutilizables del bucle agéntico de PostHog para adaptarlos a un
> **agente de generación de cinematografías** (guion → shots → prompts de imagen/vídeo → render).
> Cada sección termina con un bloque **➜ TRANSFERIBLE A CINE** que marca explícitamente qué copiar.

Rutas base: `C:\ph\ee\hogai\`

---

## 0. Mapa de ficheros del núcleo

| Ruta | Qué es |
|---|---|
| `ee/hogai/core/base.py` | `BaseAssistantGraph`: constructor de grafos LangGraph + checkpointer global |
| `ee/hogai/core/loop_graph/graph.py` | `AgentLoopGraph`: el grafo de 2 nodos (ROOT ↔ ROOT_TOOLS) |
| `ee/hogai/core/loop_graph/nodes.py` | `AgentLoopGraphNode`: nodo delgado que delega en el *mode manager* |
| `ee/hogai/core/agent_modes/executables.py` | **El bucle agéntico real**: `AgentExecutable` (LLM) y `AgentToolsExecutable` (tools) |
| `ee/hogai/core/agent_modes/compaction_manager.py` | Compresión de historial por ventana + resumen |
| `ee/hogai/core/agent_modes/mode_manager.py` | Selección dinámica de modo → toolkit + prompt builder |
| `ee/hogai/core/agent_modes/factory.py` | `AgentModeDefinition` (dataclass de un modo) |
| `ee/hogai/core/agent_modes/toolkit.py` | `AgentToolkit` / `AgentToolkitManager`: composición de toolsets |
| `ee/hogai/core/agent_modes/prompt_builder.py` | Ensamblado de system prompts |
| `ee/hogai/core/agent_modes/presets/*.py` | Presets: product_analytics, sql, session_replay, flags, survey… |
| `ee/hogai/core/plan_mode/*` | Supermodo "plan": planificar → aprobar → ejecutar |
| `ee/hogai/core/title_generator/*` | Modelo barato para título+topic de la conversación |
| `ee/hogai/core/runner.py` | `BaseAgentRunner`: orquesta `astream`, errores, interrupts, reanudación |
| `ee/hogai/core/executor.py` | `AgentExecutor`: arranque de workflow Temporal + lectura del stream Redis |
| `ee/hogai/stream/redis_stream.py` | Protocolo de eventos hacia el frontend |
| `ee/hogai/chat_agent/stream_processor.py` | Reducción de eventos LangGraph → mensajes de cliente |
| `ee/hogai/django_checkpoint/checkpointer.py` | Checkpointer de LangGraph sobre Postgres |
| `ee/hogai/django_checkpoint/compaction.py` | Poda de checkpoints antiguos |
| `ee/hogai/llm.py` | `MaxChatAnthropic` / `MaxChatOpenAI`: wrappers multi-modelo |
| `ee/hogai/queue.py` | Cola de mensajes del usuario mientras el agente corre |
| `ee/hogai/utils/types/base.py` | **El estado** (`AssistantState`) y todos los tipos de mensaje |

---

## 1. Arquitectura del grafo (LangGraph)

### 1.1 El grafo es sorprendentemente pequeño

La lección más importante de todo el repositorio: **el grafo agéntico tiene exactamente dos nodos**.
Toda la complejidad vive en los *executables*, no en la topología.

`ee/hogai/core/loop_graph/graph.py` (fichero completo):

```python
from abc import abstractmethod
from collections.abc import Callable
from typing import Literal, cast

from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.base import BaseAssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName, AssistantState, PartialAssistantState

from .nodes import AgentLoopGraphNode, AgentLoopNodeType


class AgentLoopGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
    @property
    @abstractmethod
    def mode_manager_class(self) -> type[AgentModeManager]: ...

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.AGENT_EXECUTOR

    @property
    def state_type(self) -> type[AssistantState]:
        return AssistantState

    def add_agent_node(
        self, router: Callable[[AssistantState], AssistantNodeName] | None = None, is_start_node: bool = False
    ):
        root_node = AgentLoopGraphNode(self._team, self._user, self.mode_manager_class, AgentLoopNodeType.ROOT)
        self.add_node(AssistantNodeName.ROOT, root_node)
        if is_start_node:
            self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            self._has_start_node = True
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT,
            router or cast(Callable[[AssistantState], AssistantNodeName], root_node.router),
        )
        return self

    def add_agent_tools_node(self, router: Callable[[AssistantState], AssistantNodeName] | None = None):
        agent_tools_node = AgentLoopGraphNode(self._team, self._user, self.mode_manager_class, AgentLoopNodeType.TOOLS)
        self.add_node(AssistantNodeName.ROOT_TOOLS, agent_tools_node)
        self._graph.add_conditional_edges(
            AssistantNodeName.ROOT_TOOLS,
            router or cast(Callable[[AssistantState], AssistantNodeName], agent_tools_node.router),
            path_map={
                "root": AssistantNodeName.ROOT,
                "end": AssistantNodeName.END,
            },
        )
        return self

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        return self.add_agent_node(is_start_node=True).add_agent_tools_node().compile(checkpointer=checkpointer)
```

Topología resultante:

```
START ──▶ ROOT ──(conditional)──▶ [Send(ROOT_TOOLS) × N tool_calls]  ó  END
                                          │
                            ROOT_TOOLS ───┴──(conditional)──▶ ROOT  ó  END
```

La bifurcación **fan-out por `Send`** es la clave del paralelismo de herramientas
(`ee/hogai/core/agent_modes/executables.py`):

```python
    def router(self, state: AssistantState):
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            return AssistantNodeName.END
        return [
            Send(AssistantNodeName.ROOT_TOOLS, state.model_copy(update={"root_tool_call_id": tool_call.id}))
            for tool_call in last_message.tool_calls
        ]
```

Cada tool call se despacha como una **copia del estado con `root_tool_call_id` fijado**. El nodo de
tools solo mira ese ID. Es un patrón de map-reduce sobre el estado, muy limpio.

### 1.2 El grafo completo del chat agent

`ee/hogai/chat_agent/graph.py` compone el loop con nodos periféricos:

```python
    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        return (
            self.add_title_generator()
            .add_slash_command_handler()
            .add_memory_onboarding()
            .add_memory_collector()
            .add_memory_collector_tools()
            .add_root()
            .compile(checkpointer=checkpointer)
        )
```

Nótese el comentario en `add_root`, que es una advertencia operacional valiosa:

```python
    def add_root(self, router=None, tools_router=None):
        # Merge the agent graph into the main graph.
        # Subgraphs incorrectly merge messages, so please don't use them here.
        return self.add_agent_node(router=router).add_agent_tools_node(router=tools_router)
```

### 1.3 Clase base del grafo con contexto de "node path"

`ee/hogai/core/base.py` (completo, muy reutilizable):

```python
# Base checkpointer for all graphs
global_checkpointer = DjangoCheckpointer()

T = TypeVar("T")


def with_node_path(func: Callable[..., T]) -> Callable[..., T]:
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> T:
        with set_node_path(self.node_path):
            return func(self, *args, **kwargs)

    return wrapper


class BaseAssistantGraph(Generic[StateType, PartialStateType], ABC):
    _team: Team
    _user: User
    _graph: StateGraph
    _node_path: tuple[NodePath, ...]

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user
        self._has_start_node = False
        self._graph = StateGraph(self.state_type)
        self._node_path = (*(get_node_path() or ()), NodePath(name=self.graph_name.value))

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Wrap all public methods with the node path context
        for name, method in cls.__dict__.items():
            if callable(method) and not name.startswith("_") and name not in ("graph_name", "state_type", "node_path"):
                setattr(cls, name, with_node_path(method))

    @property
    @abstractmethod
    def state_type(self) -> type[StateType]: ...

    @property
    @abstractmethod
    def graph_name(self) -> AssistantGraphName: ...

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None) -> CompiledStateGraph:
        if not checkpointer and checkpointer is not False:
            checkpointer = None
        return self.compile(checkpointer=checkpointer)

    @property
    def node_path(self) -> tuple[NodePath, ...]:
        return self._node_path

    def add_edge(self, from_node: "MaxNodeName", to_node: "MaxNodeName"):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: "MaxNodeName", action: BaseAssistantNode | CompiledStateGraph):
        self._graph.add_node(node, action)
        return self

    def compile(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        # TRICKY: We check `is not None` because False has a special meaning of "no checkpointer", which we want to pass on
        compiled_graph = self._graph.compile(
            checkpointer=checkpointer if checkpointer is not None else global_checkpointer
        )
        return compiled_graph
```

El truco de `__init_subclass__` que envuelve automáticamente todos los métodos públicos con un
contextvar `node_path` es **muy elegante**: cualquier nodo creado dentro de un método del grafo hereda
la ruta jerárquica sin que el programador lo pase a mano. Esa ruta luego se usa para atribuir eventos
de streaming al tool call correcto.

`NodePath` (`ee/hogai/utils/types/base.py`):

```python
class NodePath(BaseModel):
    """Defines a vertice of the assistant graph path."""

    name: str
    message_id: str | None = None
    tool_call_id: str | None = None
```

### 1.4 El estado

`ee/hogai/utils/types/base.py`. Reductores de estado personalizados:

```python
def replace(_: Any | None, right: Any | None) -> Any | None:
    return right


def replace_if_not_none(left: Any | None, right: Any | None) -> Any | None:
    """Replace the left value with right only if right is not None."""
    return right if right is not None else left


# String sentinel for clearing supermode - must be a string for msgpack serialization
CLEAR_SUPERMODE: str = "__CLEAR_SUPERMODE__"


def replace_supermode(left: AgentMode | str | None, right: AgentMode | str | None) -> AgentMode | None:
    """Replace supermode with special handling for explicit clearing.

    - If right is CLEAR_SUPERMODE string, returns None (explicit clear)
    - If right is an AgentMode, returns right (explicit set)
    - If right is None, returns left (no change)
    """
    if right == CLEAR_SUPERMODE:
        return None
    result = right if right is not None else left
    if result == CLEAR_SUPERMODE:
        return None
    return cast("AgentMode", result)


def append(left: Sequence, right: Sequence) -> Sequence:
    return [*left, *right]


def merge_retry_counts(left: int, right: int) -> int:
    """Merges two retry counts by taking the maximum value."""
    return max(left, right)
```

El truco del `CLEAR_SUPERMODE` merece atención: en LangGraph, `None` significa "no cambies este campo",
así que **hace falta un centinela string para poder borrar un campo**. Y tiene que ser string porque el
checkpoint se serializa con msgpack.

El reductor de mensajes, que soporta *upsert por ID* y *reemplazo total* (esto último es lo que permite
la compactación):

```python
class ReplaceMessages(Generic[T], list[T]):
    """
    Replaces the existing messages with the new messages.
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
        def validate_replace_messages(value: Any) -> "ReplaceMessages[T]":
            if isinstance(value, ReplaceMessages):
                return value
            # Don't accept plain lists - let the union fall through to Sequence
            raise ValueError(f"Expected ReplaceMessages, got {type(value)}")

        return core_schema.no_info_plain_validator_function(
            validate_replace_messages,
            serialization=core_schema.plain_serializer_function_ser_schema(list, info_arg=False),
        )


def add_and_merge_messages(
    left_value: Sequence[AssistantMessageUnion], right_value: Sequence[AssistantMessageUnion]
) -> Sequence[AssistantMessageUnion]:
    """Merges two lists of messages, updating existing messages by ID.

    By default, this ensures the state is "append-only", unless the
    new message has the same ID as an existing message.
    """
    # coerce to list
    left = list(left_value)
    right = list(right_value)

    # assign missing ids
    for m in left:
        if m.id is None:
            m.id = str(uuid.uuid4())
    for m in right:
        if m.id is None:
            m.id = str(uuid.uuid4())

    if isinstance(right_value, ReplaceMessages):
        return right

    left_idx_by_id = {m.id: i for i, m in enumerate(left)}
    merged = left.copy()
    for m in right:
        if (existing_idx := left_idx_by_id.get(m.id)) is not None:
            merged[existing_idx] = m
        else:
            merged.append(m)
    return merged
```

El estado base, con los campos que gobiernan el bucle:

```python
class BaseState(BaseModel):
    """Base state class with reset functionality."""

    @classmethod
    def get_reset_state(cls) -> Self:
        """Returns a new instance with all fields reset to their default values."""
        return cls(**{k: v.default for k, v in cls.model_fields.items()})


class BaseStateWithMessages(BaseState):
    start_id: Optional[str] = Field(default=None)
    """
    The ID of the message from which the conversation started.
    """
    start_dt: Optional[datetime] = Field(default=None)
    """
    The datetime of the start of the conversation. Use this datetime to keep the cache.
    """
    graph_status: Optional[Literal["resumed", "interrupted", ""]] = Field(default=None)
    """
    Whether the graph was interrupted or resumed.
    """
    messages: Sequence[AssistantMessageUnion] = Field(default=[])
    """
    Messages exposed to the user.
    """
    agent_mode: Annotated[AgentMode | None, replace_if_not_none] = Field(default=None)
    """
    The mode of the agent.
    """
    supermode: Annotated[AgentMode | str | None, replace_supermode] = Field(default=None)
    """
    The supermode of the agent (e.g., PLAN, RESEARCH).
    Use CLEAR_SUPERMODE string to explicitly clear the supermode.
    """
```

Y los campos de control del loop (extracto de `_SharedAssistantState`):

```python
    root_conversation_start_id: Optional[str] = Field(default=None)
    """
    The ID of the message to start from to keep the message window short enough.
    """
    root_tool_call_id: Annotated[Optional[str], replace] = Field(default=None)
    """
    The ID of the tool call from the root node.
    """
    root_tool_calls_count: Annotated[Optional[int], replace] = Field(default=None)
    """
    Tracks the number of tool calls made by the root node to terminate the loop.
    """
    query_generation_retry_count: Annotated[int, merge_retry_counts] = Field(default=0)
    """
    Tracks the number of times the query generation has been retried.
    """


class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])


class PartialAssistantState(_SharedAssistantState):
    # This must be kept here, so we don't loose type annotation for the ReplaceMessages type.
    messages: ReplaceMessages[AssistantMessageUnion] | list[AssistantMessageUnion] = Field(default=[])
```

**Patrón de dos estados** (`State` completo + `PartialState` para las escrituras) — los nodos devuelven
`PartialAssistantState` y LangGraph aplica los reductores. Esto hace que sea imposible escribir sin querer
un campo entero.

### 1.5 Checkpointing

`ee/hogai/django_checkpoint/checkpointer.py` implementa `BaseCheckpointSaver` sobre Postgres con 3 tablas:
`ConversationCheckpoint` (JSON del checkpoint + metadata), `ConversationCheckpointBlob` (valores de canal
serializados por versión) y `ConversationCheckpointWrite` (escrituras pendientes de tareas).

El detalle crítico de concurrencia:

```python
        with transaction.atomic():
            # `put_writes` and `put` are concurrently called without guaranteeing the call order
            # so we need to ensure the checkpoint is created before creating writes.
            # Thread.lock() will prevent race conditions though to the same checkpoints within a single pod.
            checkpoint, _ = ConversationCheckpoint.objects.get_or_create(
                id=checkpoint_id, thread_id=thread_id, checkpoint_ns=checkpoint_ns
            )

            writes_to_create = []
            for idx, (channel, value) in enumerate(writes):
                type, blob = self.serde.dumps_typed(value)
                writes_to_create.append(
                    ConversationCheckpointWrite(
                        checkpoint=checkpoint, task_id=task_id, idx=idx, channel=channel, type=type, blob=blob,
                    )
                )

            # Setting update_conflicts=True to handle resume-from-interrupt scenarios.
            # When a tool calls interrupt() and later resumes, LangGraph may write to the
            # same (checkpoint_id, task_id, idx) combination. We want to ensure we update
            # existing writes on duplicate key.
            ConversationCheckpointWrite.objects.bulk_create(
                writes_to_create,
                update_conflicts=True,
                unique_fields=["checkpoint", "task_id", "idx"],
                update_fields=["channel", "type", "blob"],
            )
```

Y el versionado monótono de canales:

```python
    def get_next_version(self, current: Optional[str | int], channel: Optional[ChannelProtocol] = None) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
```

**Poda de checkpoints** (`ee/hogai/django_checkpoint/compaction.py`). Este docstring es una masterclass
sobre las trampas de borrar historial de LangGraph:

```python
def compact_thread(thread_id: str, checkpoint_ns: str = "") -> CompactionResult:
    """Collapse a conversation thread to its latest checkpoint, keeping it fully resumable.

    The latest checkpoint plus the blobs its `channel_versions` reference is a complete,
    resumable snapshot (the accumulating `messages` channel stores the whole history at its
    latest version). This relies on every channel persisting a *complete* value per version, which
    `DjangoCheckpointer._put` does today. A langgraph `DeltaChannel` would break it — the tip is
    rarely a delta snapshot point, so keeping only the tip would silently reconstruct that channel
    as empty. Max uses no delta channels; do not adopt one without revisiting this. Every older
    checkpoint, superseded blob version, and stale write is dead weight. Two storage traps make
    this more than a delete:

    - The `parent_checkpoint` self-FK cascades, so deleting an ancestor would take the tip with
      it. We null the tip's parent first to detach it from the chain.
    - A blob is owned (FK, cascade) by the checkpoint that created its version, which may be an
      ancestor. We reassign the blobs the tip still references to the tip before deleting, so
      the cascade can't remove a blob the tip needs.
    """
```

Con el guardarraíl de seguridad:

```python
def _is_safe_to_compact(conversation: Conversation) -> bool:
    """A thread is only safe to collapse when it has finished a turn and has no pending approval.

    Compaction nulls the tip's parent, which drops the parent's pending Sends — so any thread
    that is mid-run, being cancelled, or paused at an approval interrupt must be left untouched."""
    if conversation.status != Conversation.Status.IDLE:
        return False
    return not any(
        isinstance(decision, dict) and decision.get("decision_status") == "pending"
        for decision in (conversation.approval_decisions or {}).values()
    )
```

### 1.6 Cómo se reanuda una conversación

Todo pasa por `BaseAgentRunner._init_or_update_state()` (`ee/hogai/core/runner.py`). Es el corazón de la
reanudación y merece copiarse entero:

```python
    async def _init_or_update_state(self):
        config = self._get_config()

        last_recorded_dt = None
        if self._use_checkpointer:
            snapshot = await self._graph.aget_state(config)
            saved_state = validate_state_update(snapshot.values, self._state_type)
            last_recorded_dt = saved_state.start_dt

            # Add existing ids to streamed messages, so we don't send the messages again.
            for message in saved_state.messages:
                if message.id is not None:
                    self._stream_processor.mark_id_as_streamed(message.id)

            # If there are pending nodes (snapshot.next is non-empty), we need to resume.
            # This happens when:
            # 1. A tool called interrupt() for approval - snapshot.next will have pending nodes
            # 2. A NodeInterrupt was raised - graph_status will be "interrupted"
            if snapshot.next:
                self._state = saved_state
                if self._resume_payload:
                    # Resume with the payload using LangGraph's Command
                    # The interrupt() call will return this payload value

                    # Update approval_decisions status if this is an approval/rejection response
                    await self._update_approval_decision_status(self._resume_payload)

                    # If there's a new message alongside the resume (user sent message while approval pending),
                    # include it in the state update so the agent sees it as a proper HumanMessage
                    if self._latest_message:
                        return Command(resume=self._resume_payload, update={"messages": [self._latest_message]})
                    return Command(resume=self._resume_payload)
                elif saved_state.graph_status == "interrupted":
                    # NodeInterrupt without approval flow - add the new message and resume
                    if self._latest_message:
                        await self._graph.aupdate_state(config, self.get_resumed_state())
                    return None
                elif self._latest_message:
                    # Pending nodes but user sent a new message without resume_payload.
                    # This could be cancelled execution or user abandoning an approval interrupt.
                    # Start fresh with the new message.
                    pass  # Fall through to return initial state
                else:
                    # Pending nodes but no resume_payload, not interrupted, and no new message.
                    # This means an approval interrupt is waiting for user input.
                    # Return None to resume from checkpoint
                    return None

        # Add the latest message id to streamed messages, so we don't send it multiple times.
        if self._latest_message and self._latest_message.id is not None:
            self._stream_processor.mark_id_as_streamed(self._latest_message.id)

        initial_state = self.get_initial_state()
        if self._initial_state:
            for key, value in self._initial_state.model_dump(exclude_none=True).items():
                setattr(initial_state, key, value)

        # Reset the start_dt if the conversation has been running for more than 5 minutes.
        # Helps to keep the cache.
        if last_recorded_dt is not None:
            if datetime.now() - last_recorded_dt > timedelta(minutes=5):
                initial_state.start_dt = datetime.now()
        # No recorded start_dt, so we set it to the current time.
        else:
            initial_state.start_dt = datetime.now()

        self._state = initial_state
        return initial_state
```

Tres valores de retorno posibles, y esto es lo que hay que entender:
- `Command(resume=payload)` → LangGraph reanuda desde el `interrupt()` exacto.
- `None` → LangGraph reanuda el checkpoint tal cual (re-ejecuta los nodos pendientes).
- Un estado inicial → arranque limpio.

Detalle notable: `start_dt` se resetea si han pasado >5 min, **para invalidar la caché de prompts de
Anthropic de forma controlada** (el timestamp va inyectado en el system prompt, así que si no se
congelara, cada turno rompería la caché).

**Manejo de interrupts tras el stream** (misma clase, `astream`):

```python
            # Interrupt handling - runs after normal completion or GraphInterrupt
            if not self._use_checkpointer:
                # Subagents don't use the checkpointer, and we don't need to do interrupt handling.
                return

            # Check if the assistant has requested help.
            state = await self._graph.aget_state(config)

            # If graph completed successfully (no pending nodes) and we were previously interrupted,
            # reset graph_status so the next message can start fresh instead of trying to resume.
            if not state.next:
                current_state = validate_state_update(state.values, self._state_type)
                if current_state.graph_status == "interrupted":
                    await self._graph.aupdate_state(config, self._partial_state_type(graph_status=""))

            if state.next:
                interrupt_messages: list[Any] = []
                should_not_update_state = False
                for task in state.tasks:
                    for interrupt in task.interrupts:
                        if interrupt.value is None:
                            continue  # Skip None interrupts
                        interrupt_message: Any
                        if isinstance(interrupt.value, str):
                            interrupt_message = AssistantMessage(content=interrupt.value, id=str(uuid4()))
                            interrupt_messages.append(interrupt_message)
                            yield AssistantEventType.MESSAGE, interrupt_message
                        elif isinstance(interrupt.value, MultiQuestionForm):
                            # No need to yield a message here - the form will be displayed to the user through the tool call args
                            # and the answers comes through the tool call result ui_payload
                            should_not_update_state = True
                        elif isinstance(interrupt.value, ClientToolCallRequest):
                            # Nothing to stream (the tool call args are already in the thread); skipping
                            # the state update lets an abandoned round trip start fresh, like approvals
                            should_not_update_state = True
                        elif isinstance(interrupt.value, ApprovalRequest):
                            should_not_update_state = True
                            message_id = str(uuid4())
                            approval_payload = ApprovalPayload(
                                proposal_id=interrupt.value.proposal_id,
                                decision_status="pending",
                                tool_name=interrupt.value.tool_name,
                                preview=interrupt.value.preview,
                                payload=interrupt.value.payload,
                                original_tool_call_id=interrupt.value.original_tool_call_id,
                                message_id=message_id,
                            )
                            yield AssistantEventType.APPROVAL, approval_payload
                            # Store approval card metadata for persistence (page reload)
                            await self._store_approval_card_data(approval_payload)
                        else:
                            interrupt_message = interrupt.value
                            interrupt_messages.append(interrupt_message)
                            yield AssistantEventType.MESSAGE, interrupt_message

                # TRICKY: For approval interrupts, we intentionally do NOT call aupdate_state().
                if should_not_update_state:
                    return

                # For other interrupts (NodeInterrupt), update state
                state_update = self._partial_state_type(
                    messages=interrupt_messages,
                    graph_status="interrupted",
                )
                await self._graph.aupdate_state(config, state_update)
```

Y la razón de no llamar `aupdate_state` en aprobaciones, documentada en `_store_approval_card_data`:

```python
    async def _store_approval_card_data(self, approval: ApprovalPayload) -> None:
        """
        Store approval card metadata in conversation.approval_decisions.

        TRICKY: when we call aupdate_state(), LangGraph creates a NEW checkpoint. This new checkpoint
        does NOT preserve the pending nodes from snapshot.next, which breaks the resume flow:
        - On resume, we check if snapshot.next has pending nodes
        - If empty (because aupdate_state cleared it), we start a new graph execution
        - This causes the tool to call interrupt() again with a new proposal_id
        Solution: Store approval card metadata in a side-channel (conversation.approval_decisions)
        and have the ConversationSerializer reconstruct the data when loading the conversation.

        NOTE: We intentionally do NOT store 'payload' here. The payload is stored in the LangGraph
        checkpoint's interrupt value (single source of truth). The serializer fetches it from there.
        """
```

**➜ TRANSFERIBLE A CINE (arquitectura)**
- Copiar la topología de **2 nodos** literalmente: `ROOT` (LLM decide) ↔ `ROOT_TOOLS` (ejecuta
  `write_script`, `break_into_shots`, `generate_image_prompt`, `render_shot`, `assemble_timeline`).
  No hagas un grafo con un nodo por fase del pipeline: eso te obliga a un orden fijo y el usuario
  siempre querrá "vuelve al shot 4 y cámbiale la luz".
- El **fan-out con `Send`** es exactamente lo que necesitas para generar N shots en paralelo:
  `[Send(RENDER, state.model_copy(update={"shot_id": s.id})) for s in shots]`.
- El patrón `State` / `PartialState` + reductores personalizados: tu estado tendrá
  `script`, `shots: Annotated[list[Shot], upsert_by_id]`, `renders: Annotated[list[Render], append]`,
  `active_shot_id: Annotated[str|None, replace]`. Usa `upsert por ID` para los shots (el agente los
  revisa iterativamente) y `append` para los renders (histórico inmutable).
- El sistema de **aprobación con `interrupt()` + side-channel `approval_decisions`** es obligatorio para
  ti: renderizar vídeo cuesta dinero. Pon `render_shot` detrás de un `ApprovalRequest` con `preview`
  (el prompt final + el still de referencia) y `payload` (params de render). Copia el bug documentado:
  no llames `aupdate_state` mientras hay una aprobación pendiente.
- El truco de `start_dt` congelado para preservar la caché de prompts te ahorra mucho dinero cuando el
  system prompt lleva la biblia de estilo cinematográfico (que será larga).

---

## 2. El bucle agéntico

### 2.1 El nodo raíz

`ee/hogai/core/agent_modes/executables.py`. La clase `AgentExecutable` es **el corazón del sistema**.
Constantes de control:

```python
class AgentExecutable(BaseAgentLoopRootExecutable):
    MAX_TOOL_CALLS = 24
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 10240}
    """
    Determines the thinking configuration for the model.
    """
```

El método `arun` completo — nótese el orden: **resolver tools y prompts en paralelo → construir ventana →
comprobar tokens → comprimir si hace falta → invocar → contar tool calls**:

```python
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit_manager = self._toolkit_manager_class(
            team=self._team, user=self._user, context_manager=self.context_manager
        )
        prompt_builder = self._prompt_builder_class(
            team=self._team, user=self._user, context_manager=self.context_manager
        )
        tools, system_prompts = await asyncio.gather(
            *[toolkit_manager.get_tools(state, config), prompt_builder.get_prompts(state, config)]
        )

        tools = cast("list[MaxTool]", tools)
        model = self._get_model(state, tools)

        # Add context messages on start of the conversation.
        messages_to_replace: Sequence[AssistantMessageUnion] = []
        if self._is_first_turn(state) and (
            updated_messages := await self.context_manager.get_state_messages_with_context(state)
        ):
            messages_to_replace = updated_messages

        # Calculate the initial window.
        langchain_messages = self._construct_messages(
            messages_to_replace or state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )
        window_id = state.root_conversation_start_id
        start_id = state.start_id

        # Summarize the conversation if it's too long.
        current_token_count = await self._window_manager.calculate_token_count(
            model, langchain_messages, tools=tools, thinking_config=self.THINKING_CONFIG
        )
        if current_token_count > self._window_manager.CONVERSATION_WINDOW_SIZE:
            # Exclude the last message if it's the first turn.
            messages_to_summarize = langchain_messages[:-1] if self._is_first_turn(state) else langchain_messages
            summary = await AnthropicConversationSummarizer(
                self._team,
                self._user,
                extend_context_window=current_token_count > 195_000,
            ).summarize(messages_to_summarize)

            summary_message = ContextMessage(
                content=ROOT_CONVERSATION_SUMMARY_PROMPT.format(summary=summary),
                id=str(uuid4()),
            )

            # Insert the summary message before the last human message
            insertion_result = self._window_manager.update_window(
                messages_to_replace or state.messages,
                summary_message,
                state.agent_mode_or_default,
                start_id=start_id,
            )
            window_id = insertion_result.updated_window_start_id
            start_id = insertion_result.updated_start_id
            messages_to_replace = insertion_result.messages

            # Update the window
            langchain_messages = self._construct_messages(messages_to_replace, window_id, state.root_tool_calls_count)

        system_prompts = cast(list[BaseMessage], system_prompts)
        assert len(system_prompts) > 0
        # Mark the longest default prefix as cacheable
        add_cache_control(system_prompts[0], ttl="1h")

        message = await model.ainvoke(system_prompts + langchain_messages, config)

        generated_messages = self._process_output_message(message)

        # Set new tool call count
        tool_call_count = (state.root_tool_calls_count or 0) + 1 if generated_messages[-1].tool_calls else None

        # Replace the messages with the new message window
        new_messages: list[AssistantMessageUnion] | ReplaceMessages[AssistantMessageUnion]
        if messages_to_replace:
            new_messages = ReplaceMessages([*messages_to_replace, *generated_messages])
        else:
            new_messages = cast(list[AssistantMessageUnion], generated_messages)

        # NOTE: We intentionally do NOT extract the mode from switch_mode tool calls here.
        # The mode should only change AFTER the tools node validates and executes the tool.
        # If we set agent_mode prematurely, the tools node will use the wrong mode_registry
        # to validate the switch_mode call (e.g., trying to validate "plan" against the
        # plan mode registry which doesn't have "plan" as a valid mode).
        return PartialAssistantState(
            messages=new_messages,
            root_tool_calls_count=tool_call_count,
            root_conversation_start_id=window_id,
            start_id=start_id,
            agent_mode=state.agent_mode_or_default,
        )
```

### 2.2 Límite de iteraciones: la técnica de "desarmar al agente"

En vez de lanzar una excepción, cuando se llega al límite **se le quitan las herramientas al modelo** y
se le inyecta un mensaje humano forzando el cierre:

```python
    def _get_model(self, state: AssistantState, tools: list["MaxTool"]):
        ...
        # The agent can operate in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent doesn't have any other option but to exit.
        if self._is_hard_limit_reached(state.root_tool_calls_count):
            return base_model

        return base_model.bind_tools(tools, parallel_tool_calls=True)

    def _add_limit_message_if_reached(
        self, messages: list[BaseMessage], tool_calls_count: int | None
    ) -> list[BaseMessage]:
        """Append a hard limit reached message if the tool calls count is reached."""
        if self._is_hard_limit_reached(tool_calls_count):
            return [*messages, LangchainHumanMessage(content=ROOT_HARD_LIMIT_REACHED_PROMPT)]
        return messages

    def _is_hard_limit_reached(self, tool_calls_count: int | None) -> bool:
        return tool_calls_count is not None and tool_calls_count >= self.MAX_TOOL_CALLS
```

Prompt (`ee/hogai/core/agent_modes/prompts.py`):

```python
ROOT_HARD_LIMIT_REACHED_PROMPT = """
You have reached the maximum number of iterations, a security measure to prevent infinite loops. Now, summarize the conversation so far and answer my question if you can. Then, ask me if I'd like to continue what you were doing.
""".strip()
```

Hay un **segundo límite** en la capa de LangGraph, en `runner.py`:

```python
    def _get_config(self) -> RunnableConfig:
        config: RunnableConfig = {
            "recursion_limit": 96,
            ...
        }
```

Con su manejador, que ofrece continuar en vez de fallar:

```python
            except GraphRecursionError:
                recursion_limit_message = AssistantMessage(
                    content="I've reached the maximum number of steps. Would you like me to continue?",
                    id=str(uuid4()),
                )
                yield AssistantEventType.MESSAGE, recursion_limit_message

                if self._use_checkpointer:
                    await self._graph.aupdate_state(
                        config,
                        self._partial_state_type(messages=[recursion_limit_message]),
                    )
                return  # Don't run interrupt handling after recursion error
```

### 2.3 Ejecución de herramientas y taxonomía de errores

`AgentToolsExecutable.arun` (fichero completo arriba). Estructura:

1. Localiza el `AssistantMessage` que contiene el tool call (incluso si estamos reanudando de una
   aprobación, donde el último mensaje es ya un `AssistantToolCallMessage`).
2. Resuelve el toolkit **otra vez** (los tools son dinámicos por modo).
3. Si la tool no existe, devuelve un mensaje al agente en lugar de fallar:

```python
        # If the tool doesn't exist, return the message to the agent
        if not tool:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=ROOT_TOOL_DOES_NOT_EXIST,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )
```

```python
ROOT_TOOL_DOES_NOT_EXIST = """
This tool does not exist.
<system_reminder>
Only use tools that are available to you.
</system_reminder>
""".strip()
```

4. Fija el `node_path` para atribución de streaming:

```python
        # Tricky: set the node path associated with the tool call
        tool.set_node_path(
            (
                *self.node_path[:-1],
                NodePath(name=AssistantNodeName.ROOT_TOOLS, message_id=tool_call_message.id, tool_call_id=tool_call.id),
            )
        )
```

5. **Cuatro clases de error, con cuatro políticas distintas** — esto es lo más reutilizable:

```python
        except MaxToolError as e:
            # Error de dominio, esperado. Se le dice al agente qué pasó y CÓMO reintentar.
            logger.exception(
                "maxtool_error", extra={"tool": tool_call.name, "error": str(e), "retry_strategy": e.retry_strategy}
            )
            ...
            content = f"Tool failed: {e.to_summary()}.{e.retry_hint}"
            return PartialAssistantState(
                messages=[AssistantToolCallMessage(content=content, id=str(uuid4()), tool_call_id=tool_call.id)],
            )
        except ValidationError as e:
            # El LLM generó args inválidos. Se le devuelve el error de pydantic literal para que se autocorrija.
            logger.exception("Validation error calling tool", extra={"tool_name": tool_call.name, "error": str(e)})
            capture_exception(e, ...)
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="There was a validation error calling the tool: " + str(e),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )
        except GraphInterrupt:
            # GraphInterrupt is raised when a tool calls interrupt() for approval flow.
            # Let it propagate up to be handled by LangGraph's interrupt
            raise
        except Exception as e:
            # Bug nuestro. Se le PROHÍBE explícitamente reintentar sin permiso del usuario.
            logger.exception("Error calling tool", extra={"tool_name": tool_call.name, "error": str(e)})
            capture_exception(e, ...)
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="The tool raised an internal error. Do not immediately retry the tool call and explain to the user what happened. If the user asks you to retry, you are allowed to do that.",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
            )
```

6. Resultado: o bien un artefacto multi-mensaje, o un `AssistantToolCallMessage` con `ui_payload`:

```python
        if isinstance(result.artifact, ToolMessagesArtifact):
            return PartialAssistantState(messages=list(result.artifact.messages))

        tool_message = AssistantToolCallMessage(
            content=str(result.content) if result.content else "",
            ui_payload={tool_call.name: result.artifact},
            id=str(uuid4()),
            tool_call_id=tool_call.id,
        )
```

**`ui_payload` es un patrón clave**: separa el *texto que ve el LLM* del *objeto estructurado que renderiza
el frontend*. El LLM recibe "he creado el insight X"; el frontend recibe el JSON de la gráfica.

7. Router de vuelta:

```python
    def router(self, state: AssistantState) -> Literal["root", "end"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantToolCallMessage):
            return "root"  # Let the root either proceed or finish, since it now can see the tool call result
        return "end"
```

### 2.4 Errores a nivel de run (runner.py)

Taxonomía de excepciones LLM, cada una con contador Prometheus, mensaje distinto al usuario y decisión de
resetear o no el estado. Extracto representativo:

```python
            except LLM_CLIENT_EXCEPTIONS as e:
                # Client/validation errors (400, 422) - these won't resolve on retry
                if self._use_checkpointer:
                    await self._graph.aupdate_state(config, self._partial_state_type.get_reset_state())
                provider = resolve_llm_provider(e)
                LLM_CLIENT_ERROR_COUNTER.labels(provider=provider).inc()
                logger.exception("llm_client_error", error=str(e), provider=provider)
                posthoganalytics.capture_exception(e, ...)
                yield (
                    AssistantEventType.MESSAGE,
                    FailureMessage(
                        content="I'm unable to process this request. The conversation may be too long. Please start a new conversation.",
                        id=str(uuid4()),
                    ),
                )
                return  # Don't run interrupt handling after client errors
            except HTTPX_TRANSPORT_EXCEPTIONS as e:
                # Network-level transport errors (not LLM provider errors).
                # Tracked on a separate counter to avoid false provider alerts.
                ...
            except LLM_TRANSIENT_EXCEPTIONS as e:
                # Transient errors (5xx, rate limits, timeouts) - may resolve on retry
                ...
            except LLM_API_EXCEPTIONS as e:
                # Catch-all for other API errors (auth errors, etc.)
                ...
            except Exception as e:
                if self._use_checkpointer:
                    # Reset the state, so that the next generation starts from the beginning.
                    await self._graph.aupdate_state(config, self._partial_state_type.get_reset_state())

                if not isinstance(e, GenerationCanceled):
                    AGENT_RUN_UNHANDLED_ERROR_COUNTER.labels(error_type=type(e).__name__).inc()
                    logger.exception("Error in assistant stream", error=e)
                    self._capture_exception(e)

                    if self._use_checkpointer:
                        snapshot = await self._graph.aget_state(config)
                        state_snapshot = validate_state_update(snapshot.values, self._state_type)
                        # Some nodes might have already sent a failure message, so we don't want to send another one.
                        if not state_snapshot.messages or not isinstance(state_snapshot.messages[-1], FailureMessage):
                            yield AssistantEventType.MESSAGE, FailureMessage()
                return
```

Los reintentos de red los delega al SDK: `MaxChatMixin.model_post_init` fija `max_retries = 3` por defecto.

**➜ TRANSFERIBLE A CINE (bucle)**
- **Doble límite** (contador propio de tool calls + `recursion_limit` de LangGraph). Para cine el contador
  propio debe ser *por recurso*: `MAX_RENDERS = 8`, `MAX_PROMPT_REVISIONS = 20`. Un agente de vídeo en bucle
  quema créditos de API de generación, no solo tokens.
- **Desarmar en vez de excepcionar**: cuando llegas al límite de renders, quita `render_shot` del toolset y
  mete un `HumanMessage` diciendo "has agotado el presupuesto de render, resume lo hecho y pregunta al
  usuario si continúa". Mucho mejor UX que un error.
- **Las cuatro clases de error mapean 1:1 a tu dominio**:
  - `MaxToolError` → `RenderRejectedError` (moderación de contenido, prompt bloqueado) con `retry_hint`
    del tipo "reformula el prompt evitando X".
  - `ValidationError` → el LLM generó un `ShotSpec` inválido (aspect ratio imposible, duración > límite del
    modelo). Devuélvele el error de pydantic crudo; se autocorrige muy bien.
  - `GraphInterrupt` → aprobación de gasto.
  - `Exception` → bug tuyo; prohibición explícita de reintentar.
- **`ui_payload`**: imprescindible. El LLM ve "shot 3 renderizado, 4.2s, coherente con el 2"; el frontend
  recibe `{url, thumbnail, seed, model, params}`.
- El `retry_hint` en la excepción es un patrón infravalorado: la excepción de dominio lleva incorporada la
  instrucción de recuperación para el LLM.

---

## 3. Agent modes y presets

### 3.1 Qué es un modo

Un modo es la **tupla (descripción, toolkit, clase de nodo, clase de nodo de tools)**. Es todo.
`ee/hogai/core/agent_modes/factory.py` (completo):

```python
from dataclasses import dataclass

from posthog.schema import AgentMode

from .executables import AgentExecutable, AgentToolsExecutable
from .toolkit import AgentToolkit


@dataclass
class AgentModeDefinition:
    mode: AgentMode
    """The name of the agent's mode."""
    mode_description: str
    """The description of the agent's mode that will be injected into the tool. Keep it short and concise."""
    toolkit_class: type[AgentToolkit] = AgentToolkit
    """A custom toolkit class to use for the agent."""
    node_class: type[AgentExecutable] = AgentExecutable
    """A custom node class to use for the agent."""
    tools_node_class: type[AgentToolsExecutable] = AgentToolsExecutable
    """A custom tools node class to use for the agent."""
```

### 3.2 El mode manager: resolución dinámica en cada paso

`ee/hogai/core/agent_modes/mode_manager.py` (completo):

```python
class AgentModeManager(AssistantContextMixin, ABC):
    _state: AssistantState | None = None
    _node: Optional["AgentExecutable"] = None
    _tools_node: Optional["AgentToolsExecutable"] = None
    _supermode: AgentMode | None = None
    _mode: AgentMode

    def __init__(self, *, team, user, node_path, context_manager, state):
        self._team = team
        self._user = user
        self._node_path = node_path
        self._context_manager = context_manager
        self._state = state

        # Only set _mode if not already set by subclass
        # Subclasses may have different default modes based on supermode
        if not hasattr(self, "_mode"):
            # Validate mode is in registry, fall back to default mode if not
            if state.agent_mode and state.agent_mode not in self.mode_registry:
                self._mode = AgentMode.PRODUCT_ANALYTICS
            else:
                self._mode = state.agent_mode or AgentMode.PRODUCT_ANALYTICS

    @property
    @abstractmethod
    def mode_registry(self) -> dict[AgentMode, "AgentModeDefinition"]:
        raise NotImplementedError("Mode registry is not implemented")

    @property
    @abstractmethod
    def toolkit_class(self) -> type[AgentToolkit]: ...

    @property
    @abstractmethod
    def prompt_builder_class(self) -> type[AgentPromptBuilder]: ...

    @property
    @abstractmethod
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return AgentToolkitManager

    @property
    def node(self) -> "AgentExecutable":
        if not self._node:
            agent_definition = self.mode_registry[self._mode]
            toolkit_manager_class = self.toolkit_manager_class
            toolkit_manager_class.configure(
                agent_toolkit=self.toolkit_class,
                mode_toolkit=agent_definition.toolkit_class,
                mode_registry=self.mode_registry,
            )
            self._node = agent_definition.node_class(
                team=self._team,
                user=self._user,
                node_path=self._node_path,
                toolkit_manager_class=toolkit_manager_class,
                prompt_builder_class=self.prompt_builder_class,
            )
        return self._node

    @property
    def tools_node(self) -> "AgentToolsExecutable":
        if not self._tools_node:
            agent_definition = self.mode_registry[self._mode]
            toolkit_manager_class = self.toolkit_manager_class
            toolkit_manager_class.configure(
                agent_toolkit=self.toolkit_class,
                mode_toolkit=agent_definition.toolkit_class,
                mode_registry=self.mode_registry,
            )
            self._tools_node = agent_definition.tools_node_class(
                team=self._team, user=self._user, node_path=self._node_path,
                toolkit_manager_class=toolkit_manager_class,
            )
        return self._tools_node

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @mode.setter
    def mode(self, value: AgentMode):
        self._mode = value
        self._node = None
        self._tools_node = None
```

El nodo del grafo es un **cascarón** que instancia el manager en cada ejecución
(`ee/hogai/core/loop_graph/nodes.py`, completo):

```python
class AgentLoopNodeType(StrEnum):
    ROOT = "root"
    TOOLS = "tools"


class AgentLoopGraphNode(AssistantNode):
    def __init__(self, team, user, mode_manager_class, node_type, node_path=None):
        self._mode_manager_class = mode_manager_class
        self._node_type = node_type
        super().__init__(team, user, node_path)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        manager = self._mode_manager_class(
            team=self._team, user=self._user, node_path=self.node_path,
            context_manager=self.context_manager, state=state,
        )
        node = manager.node if self._node_type == AgentLoopNodeType.ROOT else manager.tools_node
        return await node(state, config)

    def router(self, state: AssistantState):
        # BUG: LangGraph calls this router when resuming an interruption, but there is no available config
        # This crashes the context manager because it doesn't have a config
        self._config = RunnableConfig(configurable={})
        manager = self._mode_manager_class(
            team=self._team, user=self._user, node_path=self.node_path,
            context_manager=self.context_manager, state=state,
        )
        node = manager.node if self._node_type == AgentLoopNodeType.ROOT else manager.tools_node
        next_node = node.router(state)
        return next_node
```

**Esta indirección es lo que hace que el grafo compilado sea estático pero el comportamiento dinámico.**
El grafo se compila una vez; el modo se resuelve del estado en cada tick.

### 3.3 Toolkits y composición del toolset

`ee/hogai/core/agent_modes/toolkit.py`:

```python
class AgentToolkit:
    POSITIVE_TODO_EXAMPLES: Sequence["TodoWriteExample"] | None = None
    """
    Positive examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should orchestrate complex tasks using provided tools.
    """
    NEGATIVE_TODO_EXAMPLES: Sequence["TodoWriteExample"] | None = None
    """
    Negative examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should **NOT** orchestrate tasks using provided tools.
    """

    def __init__(self, *, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @property
    def tools(self) -> list[type["MaxTool"]]:
        """
        Custom tools are tools that are not part of the default toolkit.
        """
        return []


class AgentToolkitManager:
    _mode_registry: dict[AgentMode, "AgentModeDefinition"]
    _agent_toolkit: type[AgentToolkit]
    _mode_toolkit: type[AgentToolkit]

    def __init__(self, *, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @classmethod
    def configure(cls, agent_toolkit, mode_toolkit, mode_registry):
        cls._agent_toolkit = agent_toolkit
        cls._mode_toolkit = mode_toolkit
        cls._mode_registry = mode_registry

    async def get_tools(self, state: AssistantState, config: RunnableConfig) -> list["MaxTool | dict[str, Any]"]:
        toolkits: list[type[AgentToolkit]] = [self._agent_toolkit, self._mode_toolkit]

        # Accumulate positive and negative examples from all toolkits
        positive_examples: list[TodoWriteExample] = []
        negative_examples: list[TodoWriteExample] = []
        for toolkit_class in toolkits:
            positive_examples.extend(toolkit_class.POSITIVE_TODO_EXAMPLES or [])
            negative_examples.extend(toolkit_class.NEGATIVE_TODO_EXAMPLES or [])

        # Initialize the static toolkit
        static_tools: list[Awaitable[MaxTool]] = []
        for toolkit_class in toolkits:
            toolkit = toolkit_class(team=self._team, user=self._user, context_manager=self._context_manager)
            for tool_class in toolkit.tools:
                if tool_class is TodoWriteTool:
                    if toolkit_class is self._mode_toolkit:
                        raise ValueError("TodoWriteTool is not allowed in the mode toolkit")
                    todo_future = cast(type[TodoWriteTool], tool_class).create_tool_class(
                        team=self._team, user=self._user, state=state, config=config,
                        context_manager=self._context_manager,
                        positive_examples=positive_examples,
                        negative_examples=negative_examples,
                    )
                    static_tools.append(todo_future)
                elif tool_class == SwitchModeTool:
                    if toolkit_class is self._mode_toolkit:
                        raise ValueError("SwitchModeTool is not allowed in the mode toolkit")
                    switch_mode_future = SwitchModeTool.create_tool_class(
                        team=self._team, user=self._user, state=state, config=config,
                        context_manager=self._context_manager,
                        mode_registry=self._mode_registry,
                        default_tool_classes=toolkit.tools,
                    )
                    static_tools.append(switch_mode_future)
                else:
                    tool_future = tool_class.create_tool_class(
                        team=self._team, user=self._user, state=state, config=config,
                        context_manager=self._context_manager,
                    )
                    static_tools.append(tool_future)

        return await asyncio.gather(*static_tools)
```

Toolset final = **toolkit común (`_agent_toolkit`) ∪ toolkit del modo (`_mode_toolkit`)**. Y dos tools son
especiales porque su *descripción se genera en runtime*: `TodoWriteTool` (recibe ejemplos acumulados de
ambos toolkits) y `SwitchModeTool` (recibe el registry completo para describir los modos disponibles).

### 3.4 `switch_mode`: la herramienta que reescribe el toolset

`ee/hogai/tools/switch_mode.py`. El prompt de la tool se construye dinámicamente:

```python
SWITCH_MODE_PROMPT = """
Use this tool to switch to a specialized mode with different tools and capabilities. Your conversation history and context are preserved across mode switches.

# Common tools (available in all modes)
{{{default_tools}}}

# Specialized modes
{{{available_modes}}}

Decision framework:
1. Check if you already have the necessary tools in your current mode
2. If not, identify which mode provides the tools you need
3. Switch to that mode using this tool

Switch when:
- You need a tool listed in another mode's toolkit (e.g., execute_sql is only in sql mode)
- The task type clearly maps to a specialized mode (SQL queries → sql mode, trend analysis → product_analytics mode)
- You've confirmed your current mode lacks required capabilities

Do NOT switch when:
- You can complete the task with your current tools
- The task is informational/explanatory (no tools needed)
- You're uncertain–check your current tools first

After switching, you'll have access to that mode's specialized tools while retaining access to all common tools.
""".strip()

SWITCH_MODE_TOOL_PROMPT = """
Successfully switched to {{{new_mode}}} mode. You now have access to this mode's specialized tools.
""".strip()

SWITCH_MODE_FAILURE_PROMPT = """
Failed to switch to {{{new_mode}}} mode. This mode does not exist. Available modes: {{{available_modes}}}.
""".strip()
```

Generación del catálogo de modos (nótese que **instancia realmente las tools de cada modo para poder
listar sus nombres** — el catálogo nunca miente):

```python
async def _get_modes_prompt(
    *, team, user, state=None, config=None, context_manager, mode_registry,
) -> str:
    """Get the prompt containing the description of the available modes."""

    all_futures: list[asyncio.Future[list[MaxTool]]] = []
    for definition in mode_registry.values():
        all_futures.append(
            asyncio.gather(
                *[
                    tool_class.create_tool_class(team=team, user=user, state=state, config=config)
                    for tool_class in definition.toolkit_class(
                        team=team, user=user, context_manager=context_manager
                    ).tools
                ]
            )
        )

    resolved_tools = await asyncio.gather(*all_futures)
    formatted_modes: list[str] = []
    for definition, tools in zip(mode_registry.values(), resolved_tools):
        formatted_modes.append(
            f"- {definition.mode.value} – {definition.mode_description}. [Mode tools: {', '.join([tool.get_name() for tool in tools])}]"
        )

    return "\n".join(formatted_modes)
```

Y el `args_schema` se genera con `create_model` para que el enum de modos válidos sea **exacto**:

```python
        ModeKind = Literal[*mode_registry.keys()]  # type: ignore
        args_schema = create_model(
            "SwitchModeToolArgs",
            __base__=BaseModel,
            new_mode=(
                ModeKind,
                Field(description="The name of the mode to switch to."),
            ),
        )

        return cls(
            team=team, user=user, state=state, config=config,
            description=description_prompt,
            args_schema=args_schema,
        )
```

La ejecución valida contra el registry y **nunca rompe**:

```python
    async def _arun_impl(self, new_mode: str) -> tuple[str, AgentMode | None]:
        if new_mode not in self._mode_registry:
            available = ", ".join(self._mode_registry.keys())
            return (
                format_prompt_string(SWITCH_MODE_FAILURE_PROMPT, new_mode=new_mode, available_modes=available),
                self._state.agent_mode,
            )

        return format_prompt_string(SWITCH_MODE_TOOL_PROMPT, new_mode=new_mode), cast(AgentMode, new_mode)
```

### 3.5 Un preset completo

`ee/hogai/core/agent_modes/presets/sql.py`. Un modo son ~30 líneas de código y ~80 de ejemplos few-shot:

```python
SQL_MODE_DESCRIPTION = "Specialized mode capable of generating and executing SQL queries. This mode allows you to query the ClickHouse database, which contains both data collected by PostHog (events, groups, persons, sessions) and data warehouse sources connected by the user, such as SQL tables, CRMs, and external systems. This mode can also be used to search for specific data that can be used in other modes."


class SQLAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_INSIGHT_WITH_SEGMENTATION,
            reasoning=POSITIVE_EXAMPLE_INSIGHT_WITH_SEGMENTATION_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS, reasoning=POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS_REASONING
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS,
            reasoning=POSITIVE_EXAMPLE_MULTIPLE_METRICS_ANALYSIS_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [
            ExecuteSQLTool,
        ]


sql_agent = AgentModeDefinition(
    mode=AgentMode.SQL,
    mode_description=SQL_MODE_DESCRIPTION,
    toolkit_class=SQLAgentToolkit,
    node_class=ChatAgentExecutable,
    tools_node_class=ChatAgentToolsExecutable,
)


chat_agent_plan_sql_agent = AgentModeDefinition(
    mode=AgentMode.SQL,
    mode_description=SQL_MODE_DESCRIPTION,
    toolkit_class=SQLAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
```

Los ejemplos few-shot son **pares (traza, razonamiento)**, no solo trazas. El razonamiento explica por qué
el agente hizo lo que hizo, que es lo que realmente transfiere:

```python
POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS = """
User: Has eleventy churned?
Assistant: Let me first check the insights or events and properties to understand how we can track churn.
*Uses the search tool to find insights and the read_taxonomy tool to find events and properties that can be used to track churn*
Assistant: I haven't found existing churn insights. Let me read the data warehouse schema to see what tables are available.
*Uses read_data with data_warehouse_schema to see core tables and available warehouse tables*
Assistant: I see there's a subscriptions table. Let me get its full schema.
*Uses read_data with data_warehouse_table to get the subscriptions table schema*
Assistant: Now I can write an SQL query to check if eleventy has churned based on their subscription status.
*Creates a todo list with the remaining steps to execute and analyze the query*
""".strip()

POSITIVE_EXAMPLE_COMPANY_CHURN_ANALYSIS_REASONING = """
The assistant used the todo list because:
1. First, the assistant searched existing insights and taxonomy to understand what's already available
2. Then progressively read the data warehouse: first the overview to see available tables, then specific table schemas
3. This progressive approach avoided loading unnecessary schema information while identifying the right data source
4. The todo list helps ensure every instance is tracked and updated systematically
""".strip()
```

### 3.6 Variantes de un mismo modo con `dataclasses.replace`

`presets/product_analytics.py` muestra el patrón de derivar variantes restringidas:

```python
class ProductAnalyticsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        *POSITIVE_TODO_EXAMPLES,
        TodoWriteExample(
            example=DASHBOARD_CREATION_TODO_EXAMPLE_EXAMPLE,
            reasoning=DASHBOARD_CREATION_TODO_EXAMPLE_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [CreateInsightTool, UpsertDashboardTool, UpsertAlertTool]


product_analytics_agent = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description=PRODUCT_ANALYTICS_MODE_DESCRIPTION,
    toolkit_class=ProductAnalyticsAgentToolkit,
    node_class=ChatAgentExecutable,
    tools_node_class=ChatAgentToolsExecutable,
)


class ReadOnlyProductAnalyticsAgentToolkit(AgentToolkit):
    """Product analytics toolkit for readonly operations — excludes UpsertDashboardTool (dangerous operation)."""

    POSITIVE_TODO_EXAMPLES = POSITIVE_TODO_EXAMPLES

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [CreateInsightTool]


subagent_product_analytics_agent = replace(product_analytics_agent, toolkit_class=ReadOnlyProductAnalyticsAgentToolkit)

chat_agent_plan_product_analytics_agent = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description=PRODUCT_ANALYTICS_MODE_DESCRIPTION,
    toolkit_class=ReadOnlyProductAnalyticsAgentToolkit,  # Only CreateInsightTool
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
```

### 3.7 Registries por contexto (y feature flags)

`ee/hogai/chat_agent/mode_manager.py`. Hay **cuatro registries distintos** para el mismo agente según el
contexto: normal, plan, subagente, y variantes por feature flag:

```python
DEFAULT_CHAT_AGENT_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
    AgentMode.SQL: sql_agent,
    AgentMode.SESSION_REPLAY: session_replay_agent,
    AgentMode.ERROR_TRACKING: error_tracking_agent,
    AgentMode.FLAGS: flags_agent,
    AgentMode.SURVEY: survey_agent,
    AgentMode.LLM_ANALYTICS: ai_observability_agent,
}

DEFAULT_CHAT_AGENT_PLAN_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: chat_agent_plan_product_analytics_agent,
    AgentMode.SQL: chat_agent_plan_sql_agent,
    AgentMode.SESSION_REPLAY: chat_agent_plan_session_replay_agent,
    AgentMode.EXECUTION: execution_agent,
    ...
}

SUBAGENT_CHAT_AGENT_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: subagent_product_analytics_agent,
    ...
}
```

Y la resolución:

```python
    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        if self._is_subagent:
            return self._subagent_mode_registry

        if self._supermode == AgentMode.PLAN:
            return get_plan_mode_registry(self._team, self._user)

        registry = get_execution_mode_registry(self._team, self._user)
        if has_plan_mode_feature_flag(self._team, self._user):
            registry[AgentMode.PLAN] = plan_agent
        return registry

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        if self._supermode == AgentMode.PLAN:
            return ChatAgentPlanPromptBuilder
        return ChatAgentPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        if self._supermode == AgentMode.PLAN:
            return ChatAgentPlanToolkit
        return ChatAgentToolkit
```

Nótese que `EXECUTION` y `PLAN` son **modos ficticios** que solo existen para disparar la transición:

```python
# Execution and plan mode definitions - fictitious modes used to trigger transition in and out of plan mode
execution_agent = AgentModeDefinition(
    mode=AgentMode.EXECUTION,
    mode_description="Switch to this mode when the user has approved your plan to proceed with execution.",
    toolkit_class=PlanModeSwitchAgentToolkit,
)

plan_agent = AgentModeDefinition(
    mode=AgentMode.PLAN,
    mode_description="Switch to this mode when you need to plan a complex task that requires multiple steps and approvals.",
    toolkit_class=PlanModeSwitchAgentToolkit,
)
```

### 3.8 Construcción del system prompt

`ee/hogai/core/agent_modes/prompt_builder.py`:

```python
class PromptBuilder(ABC, Generic[StateType]):
    @abstractmethod
    async def get_prompts(self, state: StateType, config: RunnableConfig) -> list[BaseMessage]: ...


class AgentPromptBuilder(PromptBuilder[AssistantState]):
    def __init__(self, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @abstractmethod
    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]: ...


class AgentPromptBuilderBase(AgentPromptBuilder, AssistantContextMixin, BillingPromptMixin):
    """Base class for agent prompt builders with shared logic for gathering context."""

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """Return the formatted system prompt. Must be implemented by subclasses."""
        ...

    def _get_core_memory_prompt(self) -> str:
        """Return the core memory prompt template. Override in subclasses if needed."""
        return CORE_MEMORY_PROMPT

    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        billing_prompt, core_memory, groups = await asyncio.gather(
            self._get_billing_prompt(),
            self._aget_core_memory_text(),
            self._context_manager.get_group_names(),
        )

        format_args = {
            "groups_prompt": f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            "core_memory": core_memory,
            "billing_context": billing_prompt,
        }

        return ChatPromptTemplate.from_messages(
            [
                ("system", self._get_system_prompt()),
                ("system", self._get_core_memory_prompt()),
            ],
            template_format="mustache",
        ).format_messages(**format_args)
```

**Dos mensajes de sistema separados a propósito**: el primero es el prompt estático largo (cacheable con
TTL de 1h, ver `add_cache_control(system_prompts[0], ttl="1h")` en `arun`); el segundo es la memoria del
usuario, que cambia. Separarlos maximiza el hit rate de la caché.

El system prompt se ensambla por **slots de mustache** (`ee/hogai/chat_agent/prompt_builder.py`):

```python
    def _get_system_prompt(self) -> str:
        if has_plan_mode_feature_flag(self._team, self._user):
            switching_to_plan = SWITCHING_TO_PLAN_PROMPT
        else:
            switching_to_plan = ""
        return format_prompt_string(
            AGENT_PROMPT,
            role=ROLE_PROMPT,
            tone_and_style=TONE_AND_STYLE_PROMPT,
            writing_style=WRITING_STYLE_PROMPT,
            proactiveness=PROACTIVENESS_PROMPT,
            basic_functionality=BASIC_FUNCTIONALITY_PROMPT,
            slash_commands=SLASH_COMMANDS_PROMPT,
            switching_modes=SWITCHING_MODES_PROMPT,
            task_management=TASK_MANAGEMENT_PROMPT,
            doing_tasks=DOING_TASKS_PROMPT,
            product_advocacy=PRODUCT_ADVOCACY_PROMPT,
            tool_usage_policy=TOOL_USAGE_POLICY_PROMPT,
            switching_to_plan=switching_to_plan,
        )
```

**➜ TRANSFERIBLE A CINE (modos)**
Este es, con diferencia, **el patrón más valioso del repo para tu caso**. Un pipeline de cinematografía
tiene fases con toolsets y estéticas de razonamiento completamente distintas. Modos propuestos:

| Modo | `mode_description` | Toolkit |
|---|---|---|
| `screenwriting` | "Escribir y refinar el guion, estructura narrativa, beats, diálogo." | `write_treatment`, `write_scene`, `revise_scene` |
| `shot_design` | "Descomponer escenas en shots: encuadre, lente, movimiento, duración." | `break_into_shots`, `edit_shot`, `reorder_shots`, `read_style_bible` |
| `prompt_engineering` | "Traducir un shot a prompts de imagen/vídeo para un modelo concreto." | `draft_image_prompt`, `draft_video_prompt`, `lookup_model_capabilities` |
| `rendering` | "Ejecutar generaciones y evaluar resultados." | `render_still`, `render_clip` (con aprobación), `score_output` |
| `editorial` | "Ensamblar timeline, ritmo, continuidad, música." | `assemble_timeline`, `check_continuity`, `export` |
| `plan` (supermodo) | "Planificar el proyecto antes de gastar créditos." | solo lectura |

Puntos concretos a copiar:
- **Toolkit común ∪ toolkit de modo**: `read_project`, `read_style_bible`, `todo_write`, `switch_mode`
  deben estar siempre; el resto es por modo.
- **`_get_modes_prompt` instanciando las tools reales** para que el catálogo nunca mienta. Si añades una
  tool a `rendering`, el prompt de `switch_mode` se actualiza solo.
- **`ModeKind = Literal[*registry.keys()]`** generado dinámicamente: elimina la clase entera de errores
  "modo inexistente".
- **Variantes read-only con `dataclasses.replace`**: fundamental para el modo plan (donde el agente puede
  *diseñar* shots pero no *renderizar*) y para subagentes.
- **Modos ficticios `PLAN`/`EXECUTION`** como disparadores de transición: reutilizable tal cual.
- **Ejemplos few-shot (traza + razonamiento) por modo**, no globales. El razonamiento de "por qué leí el
  style bible antes de escribir el prompt" es lo que enseña de verdad.

---

## 4. Compaction manager

`ee/hogai/core/agent_modes/compaction_manager.py`. Hay **dos mecanismos combinados**:

1. **Ventana deslizante** (`root_conversation_start_id`): solo los mensajes desde ese ID entran al prompt.
2. **Resumen LLM** que se inyecta como `ContextMessage` justo antes del nuevo inicio de ventana.

### 4.1 Constantes y estructura

```python
class InsertionResult(BaseModel):
    messages: Sequence[AssistantMessageUnion]
    updated_start_id: str
    updated_window_start_id: str


class ConversationCompactionManager(ABC):
    """
    Manages conversation window boundaries, message filtering, and summarization decisions.
    """

    CONVERSATION_WINDOW_SIZE = 100_000
    """
    Determines the maximum number of tokens allowed in the conversation window.
    """
    APPROXIMATE_TOKEN_LENGTH = 4
    """
    Determines the approximate number of characters per token.
    """
```

### 4.2 Búsqueda del límite de ventana

Se recorre **hacia atrás** desde el final, gastando presupuesto de mensajes y de tokens, y solo se acepta
como frontera un `HumanMessage` o un `AssistantMessage` (nunca un tool result huérfano):

```python
    def find_window_boundary(self, messages: Sequence[T], max_messages: int = 10, max_tokens: int = 1000) -> str | None:
        """
        Find the optimal window start ID based on message count and token limits.
        Ensures the window starts at a human or assistant message.
        """

        new_window_id: str | None = None
        for message in reversed(messages):
            # Handle limits before assigning the window ID.
            max_tokens -= self._get_estimated_assistant_message_tokens(message)
            max_messages -= 1
            if max_tokens < 0 or max_messages < 0:
                break

            # Assign the new new window ID.
            if message.id is not None:
                if isinstance(message, HumanMessage):
                    new_window_id = message.id
                if isinstance(message, AssistantMessage):
                    new_window_id = message.id

        return new_window_id

    def get_messages_in_window(self, messages: Sequence[T], window_start_id: str | None = None) -> Sequence[T]:
        """
        Filter messages to only those within the conversation window.
        """
        if window_start_id is not None:
            return self._get_conversation_window(messages, window_start_id)
        return messages

    def _get_conversation_window(self, messages: Sequence[T], start_id: str) -> Sequence[T]:
        """
        Get messages from the start_id onwards.
        """
        for idx, message in enumerate(messages):
            if message.id == start_id:
                return messages[idx:]
        return messages
```

### 4.3 Conteo de tokens: heurística barata + conteo real

```python
    async def should_compact_conversation(
        self, model: BaseChatModel, messages: list[BaseMessage], tools: LangchainTools | None = None, **kwargs
    ) -> bool:
        """
        Determine if the conversation should be summarized based on token count.
        Avoids summarizing if there are only two human messages or fewer.
        """
        return await self.calculate_token_count(model, messages, tools, **kwargs) > self.CONVERSATION_WINDOW_SIZE

    async def calculate_token_count(
        self, model: BaseChatModel, messages: list[BaseMessage], tools: LangchainTools | None = None, **kwargs
    ) -> int:
        """
        Calculate the token count for a conversation.
        """
        # Avoid summarizing the conversation if there is only two human messages.
        human_messages = [message for message in messages if isinstance(message, LangchainHumanMessage)]
        if tools:
            # Filter out server-side tools for token counting purposes
            tools = [
                tool
                for tool in tools
                if not (isinstance(tool, dict) and tool.get("type", "").startswith("web_search_"))
            ]
        if len(human_messages) <= 2:
            tool_tokens = self._get_estimated_tools_tokens(tools) if tools else 0
            return sum(self._get_estimated_langchain_message_tokens(message) for message in messages) + tool_tokens
        return await self._get_token_count(model, messages, tools, **kwargs)
```

Optimización interesante: si la conversación es corta (≤2 mensajes humanos), usa la heurística chars/4 y
se ahorra una llamada de red al endpoint de conteo de Anthropic.

Heurísticas:

```python
    def _get_estimated_assistant_message_tokens(self, message: AssistantMessageUnion) -> int:
        """
        Estimate token count for a message using character/4 heuristic.
        """
        char_count = 0
        if isinstance(message, HumanMessage):
            char_count = len(message.content)
        elif isinstance(message, AssistantMessage):
            char_count = len(message.content) + sum(
                len(json.dumps(m.args, separators=(",", ":"))) for m in message.tool_calls or []
            )
        elif isinstance(message, AssistantToolCallMessage):
            char_count = len(message.content)
        return round(char_count / self.APPROXIMATE_TOKEN_LENGTH)

    def _get_estimated_langchain_message_tokens(self, message: BaseMessage) -> int:
        char_count = 0
        if isinstance(message.content, str):
            char_count = len(message.content)
        else:
            for content in message.content:
                if isinstance(content, str):
                    char_count += len(content)
                elif isinstance(content, dict):
                    char_count += self._count_json_tokens(content)
        if isinstance(message, LangchainAIMessage) and message.tool_calls:
            for tool_call in message.tool_calls:
                char_count += len(json.dumps(tool_call, separators=(",", ":")))
        return round(char_count / self.APPROXIMATE_TOKEN_LENGTH)

    def _get_estimated_tools_tokens(self, tools: LangchainTools) -> int:
        """
        Estimate token count for tools by converting them to JSON schemas.
        """
        if not tools:
            return 0

        total_chars = 0
        for tool in tools:
            tool_schema = convert_to_openai_tool(tool)
            total_chars += self._count_json_tokens(tool_schema)
        return round(total_chars / self.APPROXIMATE_TOKEN_LENGTH)

    def _count_json_tokens(self, json_data: dict) -> int:
        return len(json.dumps(json_data, separators=(",", ":")))
```

Conteo real vía API de Anthropic (la subclase concreta, incluyendo tools y thinking en el cálculo):

```python
class AnthropicConversationCompactionManager(ConversationCompactionManager):
    async def _get_token_count(
        self,
        model: ChatAnthropic,
        messages: list[BaseMessage],
        tools: LangchainTools | None = None,
        thinking_config: dict[str, Any] | None = None,
        **kwargs,
    ) -> int:
        return await database_sync_to_async(model.get_num_tokens_from_messages, thread_sensitive=False)(
            messages, thinking=thinking_config, tools=tools
        )
```

### 4.4 Inserción del resumen: tres casos

```python
    def update_window(
        self,
        messages: Sequence[T],
        summary_message: ContextMessage,
        agent_mode: AgentMode,
        start_id: str | None = None,
    ) -> InsertionResult:
        """Finds the optimal position to insert the summary message in the conversation window."""
        window_start_id_candidate = self.find_window_boundary(messages, max_messages=16, max_tokens=2048)
        start_message = find_start_message(messages, start_id)
        if not start_message:
            raise ValueError("Start message not found")

        start_message_copy = start_message.model_copy(deep=True)
        start_message_copy.id = str(uuid4())

        # The last messages were too large to fit into the window. Copy the last human message to the start of the window.
        if not window_start_id_candidate:
            return self._handle_no_window_boundary(messages, summary_message, start_message_copy, agent_mode)

        # Find the updated window
        start_message_idx = find_start_message_idx(messages, window_start_id_candidate)
        new_window = messages[start_message_idx:]

        # If the start human message is in the window, insert the summary message before it
        # and update the window start.
        if start_id and next((m for m in new_window if m.id == start_id), None):
            return self._handle_start_in_window(
                messages, summary_message, start_id, window_start_id_candidate, agent_mode,
            )

        # If the start message is not in the window, insert the summary message and human message at the start of the window.
        return self._handle_start_outside_window(
            new_window, summary_message, start_message_copy, window_start_id_candidate, agent_mode,
            all_messages=messages,
        )
```

El detalle sutil: **se clona el mensaje humano original con un ID nuevo** y se pone al inicio de la ventana.
Así el agente, tras la compactación, sigue viendo cuál era la petición original aunque haya quedado fuera
de la ventana.

### 4.5 Recordatorios reinyectados tras compactar

Esto es lo que evita la amnesia post-compactación. Tras el resumen se reinyectan (a) la lista de TODOs y
(b) el modo activo, **solo si no son evidentes en la nueva ventana**:

```python
    def _insert_reminders_after_summary(
        self,
        messages: Sequence[T],
        summary_id: str,
        agent_mode: AgentMode,
        all_messages: Sequence[T] | None = None,
        window_messages: Sequence[T] | None = None,
    ) -> Sequence[T]:
        """
        Insert both todo reminder (if needed) and mode reminder (if needed) after summary.
        Order: summary → todo reminder → mode reminder → rest
        """
        if all_messages is None:
            all_messages = messages
        if window_messages is None:
            window_messages = messages

        # Determine what needs to be inserted
        reminders_to_insert: list[T] = []

        # 1. Todo reminder (if needed)
        if todo_reminder := self._get_todo_reminder_message(all_messages, window_messages):
            reminders_to_insert.append(cast(T, todo_reminder))

        # 2. Mode reminder (if needed)
        if mode_reminder := self._get_mode_message_with_context(window_messages, all_messages, agent_mode):
            reminders_to_insert.append(cast(T, mode_reminder))

        # If nothing to insert, return original messages
        if not reminders_to_insert:
            return messages

        # Insert all reminders right after summary
        summary_idx = next(i for i, msg in enumerate(messages) if msg.id == summary_id)
        result: Sequence[T] = [
            *messages[: summary_idx + 1],
            *reminders_to_insert,
            *messages[summary_idx + 1 :],
        ]
        return result
```

```python
    def _get_mode_message_with_context(
        self,
        window_messages: Sequence[AssistantMessageUnion],
        all_messages: Sequence[AssistantMessageUnion],
        agent_mode: AgentMode,
    ) -> ContextMessage | None:
        """
        Get mode reminder message with context-aware checking.
        Only injects a reminder if the mode is not evident in the window.
        """
        # Check if initial mode message exists in the window (not full history,
        # since compaction may have moved it outside the window)
        if self._has_initial_mode_message(window_messages):
            return None
        # Check if mode is evident in the current window
        if self._is_mode_evident_in_window(window_messages):
            return None
        return ContextMessage(
            content=ROOT_AGENT_MODE_REMINDER_PROMPT.format(mode=agent_mode.value),
            id=str(uuid4()),
        )

    def _is_mode_evident_in_window(self, messages: Sequence[AssistantMessageUnion]) -> bool:
        """
        Check if the current agent mode is evident in the conversation window.
        Returns True if there's a switch_mode tool call for the current mode in the messages.
        """
        for message in messages:
            if isinstance(message, AssistantMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.name == AssistantTool.SWITCH_MODE:
                        return True
        return False
```

```python
    def _get_todo_reminder_message(self, messages: Sequence[T], window_messages: Sequence[T]) -> HumanMessage | None:
        """
        Create a todo reminder message if:
        1. A TODO_WRITE tool call exists in the conversation
        2. That todo message is NOT in the new window
        """
        # Find the last TODO_WRITE tool call
        todo_message = self._find_last_todo_write_message(messages)
        if not todo_message:
            return None

        # Check if it's already in the window
        if self._is_todo_in_window(todo_message, window_messages):
            return None

        # Extract the todo list from the tool call
        if not todo_message.tool_calls:
            return None

        todo_tool_call = next(
            (tc for tc in todo_message.tool_calls if tc.name == AssistantTool.TODO_WRITE),
            None,
        )
        if not todo_tool_call:
            return None

        # Format the reminder message using TodoWriteTool
        try:
            todo_content = TodoWriteTool.format_todo_list(todo_tool_call.args)
        except ValidationError:
            return None

        reminder_content = format_prompt_string(ROOT_TODO_REMINDER_PROMPT, todo_content=todo_content)
        return HumanMessage(content=reminder_content, id=str(uuid4()))
```

Prompts de reinyección (`ee/hogai/core/agent_modes/prompts.py`):

```python
ROOT_AGENT_MODE_REMINDER_PROMPT = """
<system_reminder>
You are currently in {mode} mode. This mode was enabled earlier in the conversation.
</system_reminder>
""".strip()

ROOT_CONVERSATION_SUMMARY_PROMPT = """
This session continues from a prior conversation that exceeded the context window. A summary of that conversation is provided below:
{summary}
""".strip()

ROOT_TODO_REMINDER_PROMPT = """
{{{todo_content}}}

<system_reminder>The above is your latest generated todo list. Use it to continue your work.</system_reminder>
""".strip()
```

### 4.6 El resumidor y su prompt

`ee/hogai/utils/conversation_summarizer/summarizer.py`:

```python
class ConversationSummarizer:
    def __init__(self, team: Team, user: User):
        self._user = user
        self._team = team

    async def summarize(self, messages: Sequence[BaseMessage]) -> str:
        prompt = self._construct_messages(messages)
        model = self._get_model()
        chain = prompt | model | StrOutputParser() | self._parse_xml_tags
        response: str = await chain.ainvoke({})  # Do not pass config here, so the node doesn't stream
        return response

    @abstractmethod
    def _get_model(self): ...

    def _construct_messages(self, messages: Sequence[BaseMessage]):
        return (
            ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT)])
            + messages
            + ChatPromptTemplate.from_messages([("user", USER_PROMPT)])
        )

    def _parse_xml_tags(self, message: str) -> str:
        """
        Extract analysis and summary tags from a message.
        """
        summary = message  # fallback to original message

        # Extract summary tag content
        summary_match = re.search(r"<summary>(.*?)</summary>", message, re.DOTALL | re.IGNORECASE)
        if summary_match:
            summary = summary_match.group(1).strip()

        return summary


class AnthropicConversationSummarizer(ConversationSummarizer):
    def __init__(self, team: Team, user: User, extend_context_window: bool | None = False):
        super().__init__(team, user)
        self._extend_context_window = extend_context_window

    def _get_model(self):
        # Haiku has 200k token limit. Sonnet has 1M token limit (GA on claude-sonnet-4-6).
        return MaxChatAnthropic(
            model="claude-sonnet-4-6" if self._extend_context_window else "claude-haiku-4-5",
            streaming=False,
            stream_usage=False,
            max_tokens=8192,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
        )

    def _construct_messages(self, messages: Sequence[BaseMessage]):
        """Removes cache_control headers."""
        messages_without_cache: list[BaseMessage] = []
        for message in messages:
            if isinstance(message.content, list):
                message = message.model_copy(deep=True)
                for content in message.content:
                    if isinstance(content, dict) and "cache_control" in content:
                        content.pop("cache_control")
            messages_without_cache.append(message)

        return super()._construct_messages(messages_without_cache)
```

Detalle: **quita los `cache_control`** antes de resumir. Si no, gastarías breakpoints de caché (Anthropic
solo permite 4) en una llamada de un solo uso.

**El prompt de resumen completo** (`ee/hogai/utils/conversation_summarizer/prompts.py`) — es una adaptación
directa del `/compact` de Claude Code y es de lo más valioso del repo:

```python
SYSTEM_PROMPT = """
You are PostHog AI, the friendly and knowledgeable AI agent of PostHog.
You are tasked with summarizing conversations.
""".strip()

USER_PROMPT = """
Create a comprehensive summary of the conversation to date, ensuring you capture the user's specific requests and your prior responses.
This summary should be thorough in capturing research concepts, key insights, and relevant data that would be essential for continuing product management work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, research concepts and patterns
   - Specific relevant data and details like:
     - events, properties, property values, users, groups, etc
     - insights
     - user or group behavior through analysis of session recordings
     - freshly created entities by you
  - Errors that you ran into and how you fixed them
  - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Verify for accuracy and completeness, addressing each required element thoroughly.

Your summary must include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail.
2. Key Research Concepts: List all important research concepts, approaches, and metrics discussed.
3. Relevant Data: Enumerate specific data entities examined, modified, or created. Prioritize the most recent messages.
4. Problem Solving: Outline problems solved and any ongoing issue-fixing efforts.
5. All User Messages: Compile a complete list of every user message (excluding tool outputs). These form the core evidence of user feedback and evolving intent.
6. Pending Tasks: Enumerate unfinished tasks the user asked you to handle.
7. Current Work: Provide a detailed account of what was being worked on immediately prior to this summary request, focusing closely on the most recent user and assistant exchanges. Include relevant data if relevant.

Here's an example of how your output must be structured:

<example>
<analysis>
[Detail your thought process and confirm that every required point is covered completely and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Research Concepts:
   - [Concept 1]
   - [Concept 2]
   - [...]

3. Relevant Data:
   - [Insight 1]
      - [Summary of why this file is important]
      - [Summary of the changes made to this insight, if any]
      - [Details]
   - [Event 2]
      - [Details]
   - [...]

4. Problem Solving:
   [Description of solved problems and ongoing troubleshooting]

5. All User Messages:
    - [Detailed non-tool use user message]
    - [...]

6. Pending Tasks:
   - [Task 1]
   - [Task 2]
   - [...]

7. Current Work:
   [Precise description of current work]
</summary>
</example>

Please provide a comprehensive, accurate summary of the conversation so far following the provided structure.

**CRITICAL**: keep important details
""".strip()
```

**➜ TRANSFERIBLE A CINE (compactación)**
Un proyecto de cinematografía revienta la ventana de contexto muy rápido (descripciones de shots +
prompts largos + feedback iterativo). Adaptación directa:

- Copia `CONVERSATION_WINDOW_SIZE = 100_000` y el patrón de dos niveles (heurística chars/4 barata →
  conteo real solo cuando importa).
- Reescribe las 7 secciones del `USER_PROMPT` a tu dominio. Propuesta:
  1. **Petición y visión**: qué pidió el usuario, tono, referencias, duración objetivo.
  2. **Biblia de estilo consolidada**: paleta, lentes, ratio, gradación, referencias visuales acordadas.
  3. **Estado del guion**: escenas escritas y su estado (borrador/aprobada).
  4. **Inventario de shots**: por cada shot, id, escena, encuadre, prompt final, estado de render, URL,
     seed. Prioriza los más recientes.
  5. **Todos los mensajes del usuario**: literal, esto es crítico — el feedback estético ("menos saturado",
     "que no se vea la cara") es exactamente lo que se pierde al resumir.
  6. **Tareas pendientes**.
  7. **Trabajo actual**.
- **La reinyección de recordatorios es aún más importante en tu caso**: además de TODO y modo, reinyecta
  **la biblia de estilo y los seeds/IDs de los assets ya generados**. Un agente de vídeo que olvida el seed
  de referencia rompe la continuidad visual del proyecto entero. Añade un
  `_get_style_bible_reminder_message()` análogo a `_get_todo_reminder_message`.
- La **clonación del mensaje humano original con ID nuevo** al inicio de la ventana: en cine, clona también
  el brief original del proyecto.
- Modelo barato (Haiku) para resumir, escalando a Sonnet solo si `>195k` tokens. Igual para ti.
- Quitar `cache_control` antes de resumir: bug sutil que te ahorrarás.

---

## 5. Plan mode

Es un **supermodo**: un eje ortogonal al modo. `state.supermode == PLAN` cambia el registry, el prompt
builder y el toolkit; `state.agent_mode` sigue variando dentro del plan.

`ee/hogai/core/plan_mode/executables.py` (completo):

```python
class PlanModeExecutable(AgentExecutable):
    """
    Base executable for plan mode agents.
    Sets supermode=PLAN when entering plan mode on first turn or new human message.
    """

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        should_set_plan_mode = not state.supermode or (state.messages and isinstance(state.messages[-1], HumanMessage))

        if should_set_plan_mode:
            new_state = state.model_copy(update={"agent_mode": AgentMode.SQL, "supermode": AgentMode.PLAN})
        else:
            new_state = state

        result = await super().arun(new_state, config)

        # NOTE: Mode transitions (e.g., switch_mode("execution")) are handled in
        # PlanModeToolsExecutable.arun() AFTER the tool validates and executes.
        # This ensures the tool validates against the correct mode_registry.

        # Ensure supermode and agent_mode are persisted to the checkpoint on first turn
        if should_set_plan_mode:
            result = result.model_copy(update={"supermode": AgentMode.PLAN, "agent_mode": AgentMode.SQL})

        return result


class PlanModeToolsExecutable(AgentToolsExecutable):
    @abstractmethod
    async def get_transition_prompt(self) -> str:
        """The prompt to display to the user when transitioning to the next mode."""
        ...

    @property
    @abstractmethod
    def transition_supermode(self) -> AgentMode | str | None:
        """The supermode value after transition completes.

        This should match the transition_supermode from the corresponding PlanModeExecutable.
        Used to detect when a transition happened in the previous root node.
        """
        ...

    def _get_current_tool_call(self, state: AssistantState) -> AssistantToolCall | None:
        """Get the current tool call being processed."""
        if not state.root_tool_call_id:
            return None

        for msg in reversed(state.messages):
            if isinstance(msg, AssistantMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.id == state.root_tool_call_id:
                        return tc
        return None

    def _is_switch_mode_tool_call(self, state: AssistantState) -> bool:
        """Check if the current tool call is switch_mode."""
        tool_call = self._get_current_tool_call(state)
        return tool_call is not None and tool_call.name == "switch_mode"

    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        """Check if we should transition based on the tool result.

        Override this in subclasses to define transition conditions.
        Default: transition when switch_mode tool is called and result.agent_mode
        matches the expected transition target.
        """
        return False  # Subclasses should override

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        result = await super().arun(state, config)

        # Check if we should transition AFTER the tool successfully executed
        if self._is_switch_mode_tool_call(state) and self._should_transition(state, result):
            # Apply the supermode transition
            result = result.model_copy(
                update={
                    "agent_mode": AgentMode.PRODUCT_ANALYTICS,
                    "supermode": self.transition_supermode,
                }
            )

            # Replace the tool call message content with the transition prompt
            last_message = result.messages[-1] if result.messages else None
            if isinstance(last_message, AssistantToolCallMessage):
                transition_prompt = await self.get_transition_prompt()
                updated_message = last_message.model_copy(update={"content": transition_prompt})
                result = result.model_copy(update={"messages": [*result.messages[:-1], updated_message]})

        return result
```

**Idea central**: el resultado del tool call `switch_mode` se **reescribe** con un prompt de transición que
contiene el catálogo completo de capacidades del nuevo modo. Es decir, cruzar la frontera plan→ejecución
inyecta el manual de la fase siguiente justo donde el agente lo va a leer.

La implementación concreta (`ee/hogai/chat_agent/executables.py`):

```python
SWITCH_TO_EXECUTION_MODE_PROMPT = """
Planning complete. Switched to execution mode, which defaults to product analytics mode.

Available tools and modes:
## Common tools
{{{default_tools}}}

## Specialized modes
{{{available_modes}}}

You MUST continue executing the plan until it is complete. Do not respond with text only - proceed with tool calls until you have completed the tasks.
"""

SWITCH_TO_PLAN_MODE_PROMPT = """
You have successfully switched to plan mode to help structure your task.
"""
```

```python
class ChatAgentPlanToolsExecutable(PlanModeToolsExecutable):
    @property
    def transition_supermode(self) -> str:
        # Chat agent exits plan mode entirely (supermode becomes None via CLEAR_SUPERMODE)
        return CLEAR_SUPERMODE

    async def get_transition_prompt(self) -> str:
        from ee.hogai.chat_agent.mode_manager import get_execution_mode_registry  # circular import

        execution_registry = get_execution_mode_registry(self._team, self._user)

        default_tools, available_modes = await asyncio.gather(
            _get_default_tools_prompt(team=self._team, user=self._user, default_tool_classes=DEFAULT_TOOLS),
            _get_modes_prompt(
                team=self._team, user=self._user,
                context_manager=self.context_manager,
                mode_registry=execution_registry,
            ),
        )

        return format_prompt_string(
            SWITCH_TO_EXECUTION_MODE_PROMPT,
            default_tools=default_tools,
            available_modes=available_modes,
        )

    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        # Transition when switching from plan mode to execution mode
        # The tool has already validated and set result.agent_mode = EXECUTION
        return state.supermode == AgentMode.PLAN and result.agent_mode == AgentMode.EXECUTION
```

### 5.1 Los prompts de plan mode

`ee/hogai/core/plan_mode/prompts.py` (completo). El plan es un **artefacto visible para el usuario** (un
notebook), no un scratchpad interno:

```python
PLANNING_TASK_PROMPT = """
<planning_task>
As a second task, create a single-page notebook plan explaining exactly how you'll accomplish the user's request.

*IMPORTANT*: This notebook should NOT be a draft. The user must be able to see this plan.

<plan_notebook_template>
# [Task Title]

## Understanding the Problem
[Core question/goal and business impact]

## Approach
1. **[Step Name]**: [What to do] because [reasoning]
2. **[Step Name]**: [What to do] because [reasoning]
[Continue for all steps]

## Key Metrics
- **[Metric]**: [Why it's relevant]
- **[Metric]**: [Why it's relevant]

## Expected Outcome
[What we expect to deliver or discover]
</plan_notebook_template>

# Requirements
- Make it actionable and self-contained
- Expose your reasoning ("I will do X because Y")
- Use business terms, not technical implementation
- Focus on WHAT to accomplish, not HOW the tools work
</planning_task>
""".strip()

EXECUTION_CAPABILITIES_PROMPT = """
<execution_capabilities>
After planning, you will switch to execution mode. Here is what will be available:

## Common tools (available in all modes)
{{{default_tools}}}

## Specialized modes (switchable during execution)
{{{available_modes}}}

Use this information to create realistic, actionable plans. Only reference tools and capabilities that are actually available.
</execution_capabilities>
""".strip()
```

La última línea de `EXECUTION_CAPABILITIES_PROMPT` es clave: **el planificador ve el catálogo real de tools
de la fase de ejecución** para no planificar cosas imposibles.

`ee/hogai/chat_agent/prompts/plan.py`:

```python
CHAT_PLAN_MODE_PROMPT = """
<goal>
You are currently operating in planning mode.
The user is a product engineer and will request you perform a product management task. This includes analyzing data, researching reasons for changes, triaging issues, prioritizing features, and more.

You have up to three tasks to perform in this session:
1. (If needed) Clarify the user's request by asking targeted questions, using the create_form tool
2. Write a plan using the `finalize_plan` tool
3. Get user approval, then switch to `execution` mode using switch_mode to proceed with the actual task

To achieve these tasks, you should:
- Use the `todo_write` tool to plan the task if required
- Use the available search tools to understand the project, taxonomy, and the user's query. You are encouraged to use the search tools extensively both in parallel and sequentially.
- Plan the task using all tools available to you
- Tool results and user messages may include <system_reminder> tags. <system_reminder> tags contain useful information and reminders. They are NOT part of the user's provided input or the tool result.
</goal>
"""

CHAT_ONBOARDING_TASK_PROMPT = """
<initial_clarifications_task>
Before planning, evaluate whether clarification is needed.

# Evaluate clarity first
Assess the user's request against these criteria:
- Is the objective specific and actionable?
- Can you determine the scope (users, timeframe, metrics) from context or research?
- Are the success criteria implied or stated?

If the request is already clear and specific (e.g., "build a revenue dashboard for the last 30 days", "show me why signups dropped last week"), skip clarification entirely and proceed directly to planning.

# When to ask questions
Only ask questions when there is genuine ambiguity that would lead to a meaningfully different plan. Do NOT ask questions you can answer through research using the available search tools.

# If clarification is needed
Use the create_form tool with at most 3 targeted questions. Only ask about areas where the answer would change your approach:
- **Core objective**: Only if the goal is unclear or could mean very different things
- **Scope**: Only if critical dimensions (users, timeframe, features) are ambiguous and can't be inferred
- **Success metrics**: Only if the user hasn't implied what "good" looks like

# Requirements
- Research first, ask second: use search tools to fill gaps before asking the user
- Skip questions the user has already answered in their request
- Never ask all areas just to be thorough — only ask what changes the plan
- Natural, conversational tone
</initial_clarifications_task>
"""
```

Y el criterio de **cuándo** entrar en plan mode, con ejemplos positivos y negativos:

```python
SWITCHING_TO_PLAN_PROMPT = """
<plan_mode>
Switch to `plan` mode using switch_mode to plan a complex task that requires multiple steps and approvals. Getting user approval on your approach before executing prevents wasted effort and ensures alignment.

## When to switch to plan mode

Use plan mode proactively when ANY of these conditions apply:

1. **Multi-step analysis**: The task requires investigating multiple metrics, funnels, or data sources
   - Example: "Why did our conversion rate drop last week?"
   - Example: "Help me understand our user retention patterns"

2. **Complex feature setup**:  Setting up features with multiple components or configurations
   - Example: "Build a dashboard to track our product-market fit metrics"
   - Example: "Create a weekly executive dashboard reporting on user engagement"

3. **Investigation or debugging**: Diagnosing issues that require exploring multiple hypotheses
   - Example: "Our signup funnel is broken somewhere, help me find where"
   - Example: "Figure out why session recordings show errors for some users"

4. **Strategic analysis**: Tasks requiring research, comparison, or recommendations
   - Example: "Compare our mobile vs desktop user behavior"
   - Example: "Which features should we prioritize based on usage data?"

5. **User frustration**: Redoing a task that the user is frustrated with
   - Example: "I'm frustrated with the way our users are interacting with the product, help me understand why"

## When NOT to use plan mode

Skip plan mode for simple, single-step tasks:
- "Show me pageviews for the last 7 days"
- "How many users signed up yesterday?"
- "What's our current conversion rate?"
- "Create a simple event trend chart"

## Examples

<example>
User: "Why did our activation rate drop by 15% this month?"
Action: Switch to plan mode - requires investigating multiple metrics, comparing time periods, and exploring hypotheses.
</example>

<example>
User: "Help me set up cohort analysis to track user retention by signup source"
Action: Switch to plan mode - requires understanding data structure, creating cohorts, and building multiple visualizations.
</example>

<example>
User: "Show me the trend for $pageview events"
Action: Stay in current mode - simple query that can be answered directly.
</example>

<example>
User: "I want to understand why users are churning after the trial period"
Action: Switch to plan mode - open-ended investigation requiring multiple analyses and user approval on approach.
</example>
</plan_mode>
"""
```

El prompt builder del plan mode monta el system prompt con slots distintos
(`ee/hogai/chat_agent/prompts/plan.py`):

```python
CHAT_PLAN_AGENT_PROMPT = """
{{{role}}}

{{{plan_mode}}}

{{{tone_and_style}}}

{{{writing_style}}}

{{{basic_functionality}}}

{{{slash_commands}}}

{{{switching_modes}}}

{{{task_management}}}

{{{product_advocacy}}}

{{{onboarding_task}}}

{{{planning_task}}}

{{{switch_to_execution}}}

{{{tool_usage_policy}}}

{{{billing_context}}}

{{{execution_capabilities}}}

{{{groups_prompt}}}
""".strip()
```

**➜ TRANSFERIBLE A CINE (plan mode)**
Plan mode es **la pieza que más directamente encaja** con un agente de cine, porque tu pipeline es
literalmente "planificar antes de gastar".

- Copia el patrón supermodo/modo: `supermode ∈ {PLAN, PRODUCTION}` × `mode ∈ {screenwriting, shot_design,
  prompt_engineering, rendering, editorial}`. En `PLAN` **ningún modo expone tools de render**.
- El **plan como artefacto visible** es exactamente tu *treatment* / *shot list*. Adapta
  `plan_notebook_template`:

```
# [Título del proyecto]

## Concepto
[Idea central, tono, referencia visual, público]

## Biblia de estilo
- **Paleta**: [...] porque [...]
- **Óptica/formato**: [ratio, lente, grano] porque [...]
- **Referencias**: [...]

## Estructura
1. **[Escena]**: [qué ocurre] — [nº shots estimado] — porque [...]

## Shot list preliminar
| # | Escena | Encuadre | Movimiento | Duración | Modelo sugerido |

## Presupuesto estimado
- [N] stills × [coste], [M] clips × [coste] = [total]

## Resultado esperado
[Duración final, formato de entrega]
```

- `EXECUTION_CAPABILITIES_PROMPT` es crítico para ti: el planificador **debe** ver qué modelos de
  generación hay disponibles y sus límites (duración máxima de clip, resoluciones, si soporta
  image-to-video, coste) para no planificar shots imposibles. Inyecta ahí tu catálogo de modelos.
- `CHAT_ONBOARDING_TASK_PROMPT` ("investiga primero, pregunta después, máximo 3 preguntas") aplica tal cual:
  las preguntas de cine son tono / duración / formato de entrega.
- El **prompt de transición que reescribe el resultado del tool call** — úsalo para inyectar, al pasar a
  producción, la biblia de estilo consolidada + el presupuesto aprobado.
- La lista de "cuándo NO usar plan mode" evita que el agente escriba un treatment de tres páginas cuando
  el usuario solo pidió "hazme un clip de 3 segundos de una ola".

---

## 6. Streaming

Tres capas: **grafo → dispatcher/stream processor → Redis → HTTP/SSE**.

### 6.1 Modos de stream de LangGraph

`runner.py`:

```python
    async def astream(
        self,
        stream_message_chunks: bool = True,
        stream_subgraphs: bool = True,
        stream_first_message: bool = True,
        stream_only_assistant_messages: bool = False,
    ) -> AsyncGenerator[AssistantOutput]:
        state = await self._init_or_update_state()
        config = self._get_config()

        stream_mode: list[StreamMode] = ["values", "custom"]
        if stream_message_chunks:
            stream_mode.append("messages")

        generator: AsyncIterator[Any] = self._graph.astream(
            state, config=config, stream_mode=stream_mode, subgraphs=stream_subgraphs
        )
```

- `values` → snapshots de estado completos.
- `custom` → eventos que los nodos emiten a mano vía `get_stream_writer()`.
- `messages` → chunks token a token del LLM.

Y el bucle de consumo:

```python
            self._pending_conversation_update = False
            try:
                async for update in generator:
                    if messages := await self._process_update(update):
                        for message in messages:
                            if isinstance(message, get_args(AssistantStreamedMessageUnion)):
                                message = cast(AssistantStreamedMessageUnion, message)
                                yield AssistantEventType.MESSAGE, message

                            if stream_only_assistant_messages:
                                continue

                            if isinstance(message, AssistantGenerationStatusEvent):
                                yield AssistantEventType.STATUS, message
                            elif isinstance(message, AssistantUpdateEvent | SubagentUpdateEvent):
                                yield AssistantEventType.UPDATE, message

                    # Re-yield the conversation when the title generator has
                    # produced a title. Checked after _process_update so the
                    # flag set by ConversationTitleAction is picked up.
                    if self._pending_conversation_update:
                        self._pending_conversation_update = False
                        yield AssistantEventType.CONVERSATION, self._conversation
```

### 6.2 El vocabulario de acciones

`ee/hogai/utils/types/base.py` — las acciones que un nodo puede emitir:

```python
class MessageAction(BaseModel):
    type: Literal["MESSAGE"] = "MESSAGE"
    message: AssistantMessageUnion


class MessageChunkAction(BaseModel):
    type: Literal["MESSAGE_CHUNK"] = "MESSAGE_CHUNK"
    message: AIMessageChunk


class NodeStartAction(BaseModel):
    type: Literal["NODE_START"] = "NODE_START"


class NodeEndAction(BaseModel, Generic[PartialStateType]):
    type: Literal["NODE_END"] = "NODE_END"
    state: PartialStateType | None = None


class UpdateAction(BaseModel):
    type: Literal["UPDATE"] = "UPDATE"
    content: str | AssistantToolCall


class ConversationTitleAction(BaseModel):
    type: Literal["CONVERSATION_TITLE"] = "CONVERSATION_TITLE"
    title: str
    topic: str | None = None


AssistantActionUnion = (
    MessageAction | MessageChunkAction | NodeStartAction | NodeEndAction | UpdateAction | ConversationTitleAction
)


class AssistantDispatcherEvent(BaseModel):
    action: AssistantActionUnion = Field(discriminator="type")
    node_path: tuple[NodePath, ...] | None = None
    node_name: str
    node_run_id: str
```

Y los tipos de salida hacia el cliente:

```python
AssistantOutput = (
    tuple[Literal[AssistantEventType.CONVERSATION], Conversation]
    | tuple[Literal[AssistantEventType.MESSAGE], AssistantStreamedMessageUnion]
    | tuple[Literal[AssistantEventType.STATUS], AssistantGenerationStatusEvent]
    | tuple[Literal[AssistantEventType.UPDATE], AssistantUpdateEvent | SubagentUpdateEvent]
    | tuple[Literal[AssistantEventType.APPROVAL], ApprovalPayload]
)
```

### 6.3 El stream processor

`ee/hogai/chat_agent/stream_processor.py`. Reduce acciones a mensajes de cliente, con deduplicación por ID
y filtrado por "verbosidad" del nodo:

```python
class BaseStreamProcessor(AssistantStreamProcessorProtocol, Generic[StateType]):
    """
    Base stream processor that reduces streamed actions to client-facing messages.
    """

    _verbose_nodes: set[MaxNodeName]
    """Nodes that emit messages."""
    _streaming_nodes: set[MaxNodeName]
    """Nodes that produce streaming messages."""
    _chunks: dict[str, AIMessageChunk]
    """Tracks the current message chunk."""
    _state: StateType | None
    """Tracks the current state."""
    _state_type: type[StateType]
    """The type of the state."""

    def __init__(self, team, user, verbose_nodes, streaming_nodes, state_type):
        self._team = team
        self._user = user
        # If a node is streaming node, it should also be verbose.
        self._verbose_nodes = verbose_nodes | streaming_nodes
        self._streaming_nodes = streaming_nodes
        self._streamed_update_ids: set[str] = set()
        self._chunks = {}
        self._state_type = state_type
        self._state = None
        self._artifact_manager = ArtifactManager(self._team, self._user)

    async def process(self, event: AssistantDispatcherEvent) -> list[AssistantResultUnion] | None:
        """
        Reduce streamed actions to client messages.
        """
        action = event.action

        if isinstance(action, NodeStartAction):
            self._chunks[event.node_run_id] = AIMessageChunk(content="")
            return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)]

        if isinstance(action, NodeEndAction):
            if event.node_run_id in self._chunks:
                del self._chunks[event.node_run_id]
            return await self._handle_node_end(event, action)

        if isinstance(action, MessageChunkAction) and (results := self._handle_message_stream(event, action.message)):
            return results

        if isinstance(action, MessageAction):
            message = action.message
            if result := await self._handle_message(event, message):
                return [result]

        if isinstance(action, UpdateAction) and (update_event := self._handle_update_message(event, action)):
            return [update_event]

        return None
```

Deduplicación (la regla de oro del streaming: **sin ID = efímero/progresivo, con ID = persistente y
deduplicable**):

```python
    def _should_emit_message(self, message_id: str | None) -> bool:
        """
        Check if message should be emitted (not already streamed) and mark as streamed.

        Messages without IDs are always emitted (they're progressive streaming messages).
        Messages with IDs are deduplicated to avoid sending the same message twice.
        """
        if message_id is None:
            return True
        if message_id in self._streamed_update_ids:
            return False
        self._streamed_update_ids.add(message_id)
        return True
```

Acumulación de deltas:

```python
    def _handle_message_stream(
        self, event: AssistantDispatcherEvent, message: AIMessageChunk
    ) -> list[AssistantResultUnion] | None:
        """
        Process LLM chunks from "messages" stream mode.

        With dispatch pattern, complete messages are dispatched by nodes.
        This handles AIMessageChunk for ephemeral streaming (responsiveness).
        """
        node_name = cast(MaxNodeName, event.node_name)
        run_id = event.node_run_id

        if node_name not in self._streaming_nodes:
            return None
        if run_id not in self._chunks:
            self._chunks[run_id] = AIMessageChunk(content="")

        # Merge message chunks
        self._chunks[run_id] = merge_message_chunk(self._chunks[run_id], message)

        # Stream ephemeral messages (no ID = not persisted).
        # normalize_ai_message() returns a list when server_tool_use blocks are present,
        # but we only stream the latest message for incremental updates
        messages = normalize_ai_message(self._chunks[run_id])
        return [messages[-1]] if messages else None
```

**Atribución de eventos anidados al tool call correcto** — aquí se paga el `node_path`:

```python
    def _handle_update_message(
        self, event: AssistantDispatcherEvent, action: UpdateAction
    ) -> AssistantUpdateEvent | SubagentUpdateEvent | None:
        """Handle AssistantMessage that has a parent, creating an AssistantUpdateEvent."""
        if not event.node_path or not action.content:
            return None

        # Find the closest tool call id to the update.
        parent_path = next((path for path in reversed(event.node_path) if path.tool_call_id), None)
        # Updates from the top-level graph nodes are not supported.
        if not parent_path:
            return None

        tool_call_id = parent_path.tool_call_id
        message_id = parent_path.message_id

        if not message_id or not tool_call_id:
            return None

        if isinstance(action.content, AssistantToolCall):
            return SubagentUpdateEvent(id=message_id, tool_call_id=tool_call_id, content=action.content)

        return AssistantUpdateEvent(id=message_id, tool_call_id=tool_call_id, content=action.content)
```

Y la distinción raíz vs anidado — los mensajes de subgrafos se descartan **salvo** artefactos y fallos:

```python
    def _is_message_from_nested_node_or_graph(self, node_path: tuple[NodePath, ...]) -> bool:
        """Check if the message is from a nested node or graph."""
        if not node_path:
            return False
        # The first path is always the top-level graph.
        if len(node_path) > 2:
            # The second path can is a top-level node.
            # But we have to check the next node to see if it's a nested node or graph.
            return find_subgraph(node_path[2:])

        return False

    def _handle_special_child_message(
        self, message: AssistantStreamedMessageUnion
    ) -> AssistantStreamedMessageUnion | None:
        """
        Handle special message types that have parents.

        These messages are returned as-is regardless of where in the nesting hierarchy they are.
        """
        # These message types are always returned as-is
        if isinstance(message, FailureMessage | ArtifactMessage):
            return message

        return None
```

Enriquecimiento de artefactos (referencia ligera en el estado → contenido completo al cliente):

```python
        # ArtifactRefMessage must always be enriched with content, regardless of nesting level
        if isinstance(message, ArtifactRefMessage):
            try:
                enriched_message = await self._artifact_manager.aenrich_message(message)
            except (ValueError, KeyError) as e:
                logger.warning("Failed to enrich ArtifactMessage", error=str(e), artifact_id=message.artifact_id)
                enriched_message = None
            # If the message is not enriched, return None.
            if not enriched_message:
                return None
            message = enriched_message
```

`ArtifactRefMessage` en el estado, `ArtifactMessage` (con contenido) al cliente:

```python
class ArtifactRefMessage(BaseAssistantMessage):
    """Backend-only artifact message without the enriched content field."""

    content_type: ArtifactContentType
    artifact_id: str
    source: ArtifactSource
```

### 6.4 Transporte: Redis Streams

`ee/hogai/stream/redis_stream.py`. Eventos serializados con discriminador `type`:

```python
class ConversationEvent(BaseModel):
    type: Literal["conversation"]
    payload: UUID  # conversation id


class MessageEvent(BaseModel):
    type: Literal[AssistantEventType.MESSAGE]
    payload: AssistantStreamedMessageUnion


class UpdateEvent(BaseModel):
    type: Literal[AssistantEventType.UPDATE]
    payload: AssistantUpdateEvent | SubagentUpdateEvent


class GenerationStatusEvent(BaseModel):
    type: Literal[AssistantEventType.STATUS]
    payload: AssistantGenerationStatusEvent


class StatusPayload(BaseModel):
    status: Literal["complete", "error"]
    error: Optional[str] = None


class StreamStatusEvent(BaseModel):
    type: Literal["STREAM_STATUS"] = "STREAM_STATUS"
    payload: StatusPayload


class ApprovalEvent(BaseModel):
    type: Literal[AssistantEventType.APPROVAL]
    payload: ApprovalPayload


StreamEventUnion = (
    ConversationEvent | MessageEvent | GenerationStatusEvent | UpdateEvent | StreamStatusEvent | ApprovalEvent
)


class StreamEvent(BaseModel):
    event: StreamEventUnion = Field(discriminator="type")
    timestamp: float = Field(default_factory=time.time)
```

Configuración y claves (nótese la clave separada por subagente):

```python
# Redis stream configuration
CONVERSATION_STREAM_MAX_LENGTH = 1000  # Maximum number of messages to keep in stream
CONVERSATION_STREAM_CONCURRENT_READ_COUNT = 8
CONVERSATION_STREAM_PREFIX = "conversation-stream:"
CONVERSATION_STREAM_TIMEOUT = 30 * 60  # 30 minutes


def get_conversation_stream_key(conversation_id: UUID) -> str:
    """Get the Redis stream key for a conversation."""
    return f"{CONVERSATION_STREAM_PREFIX}{conversation_id}"


def get_subagent_stream_key(conversation_id: UUID, tool_call_id: str) -> str:
    """Get the Redis stream key for a subagent tool execution."""
    return f"{CONVERSATION_STREAM_PREFIX}{conversation_id}:{tool_call_id}"
```

Lectura con `XREAD` bloqueante y terminación por evento de estado:

```python
    async def read_stream(
        self,
        start_id: str = "0",
        block_ms: int = 50,  # Block for 50ms waiting for new messages
        count: Optional[int] = CONVERSATION_STREAM_CONCURRENT_READ_COUNT,
    ) -> AsyncGenerator[StreamEvent]:
        current_id = start_id
        start_time = asyncio.get_running_loop().time()
        last_iteration_time = None

        while True:
            ...
            if asyncio.get_running_loop().time() - start_time > self._timeout:
                raise StreamError("Stream timeout - conversation took too long to complete")

            try:
                messages = await self._redis_client.xread(
                    {self._stream_key: current_id}, block=block_ms, count=count,
                )

                if not messages:
                    # No new messages after blocking, continue polling
                    continue

                for _, stream_messages in messages:
                    for stream_id, message in stream_messages:
                        current_id = stream_id
                        data = self._serializer.deserialize(message)

                        latency = time.time() - data.timestamp
                        REDIS_TO_CLIENT_LATENCY_HISTOGRAM.observe(latency)

                        if isinstance(data.event, StreamStatusEvent):
                            if data.event.payload.status == "complete":
                                return
                            elif data.event.payload.status == "error":
                                error = data.event.payload.error or "Unknown error"
                                if error:
                                    raise StreamError(error)
                                continue

                        else:
                            yield data

            except redis_exceptions.ConnectionError:
                raise StreamError("Connection lost to conversation stream")
            except redis_exceptions.TimeoutError:
                raise StreamError("Stream read timeout")
            except redis_exceptions.RedisError:
                raise StreamError("Stream read error")
            except Exception:
                raise StreamError("Unexpected error reading conversation stream")
```

Escritura, con marca de finalización garantizada incluso en error:

```python
    async def write_to_stream(
        self,
        generator: AsyncGenerator[AssistantOutput],
        callback: Callable[[], None] | None = None,
        emit_completion: bool = True,
    ) -> None:
        try:
            await self._redis_client.expire(self._stream_key, self._timeout)

            last_iteration_time = None
            async for chunk in generator:
                ...
                message = self._serializer.dumps(chunk)
                if message is not None:
                    await self._redis_client.xadd(
                        self._stream_key, message, maxlen=self._max_length, approximate=True,
                    )
                if callback:
                    callback()

            if emit_completion:
                await self._write_status(StatusPayload(status="complete"))

        except Exception as e:
            await self._write_status(StatusPayload(status="error", error=str(e)))
            raise StreamError("Failed to write to stream")
```

Los eventos `ACK` se filtran: solo sirven para heartbeat de Temporal, no llegan al cliente:

```python
    def _to_status_event(self, event: AssistantGenerationStatusEvent) -> GenerationStatusEvent | None:
        if isinstance(event, AssistantGenerationStatusEvent) and event.type == AssistantGenerationStatusType.ACK:
            # we don't need to send ACK messages to the client
            # they are only used to trigger temporal heartbeats
            return None

        return GenerationStatusEvent(type=AssistantEventType.STATUS, payload=event)
```

### 6.5 Reconexión

`ee/hogai/core/executor.py`. **Redis como buffer desacopla la ejecución de la conexión HTTP**: si el
usuario recarga la página, se reengancha al stream leyendo desde `"0"`:

```python
    async def astream(self, workflow: type[AgentBaseWorkflow], inputs: Any) -> AsyncGenerator[AssistantOutput, Any]:
        """Stream agent workflow updates from Redis stream."""
        # If this is a reconnection attempt, we resume streaming
        if self._conversation.status != Conversation.Status.IDLE and self._reconnectable:
            if hasattr(inputs, "message") and inputs.message is not None:
                raise ValueError("Cannot resume streaming with a new message")
            async for chunk in self.stream_conversation():
                yield chunk
        else:
            # Otherwise, process the new message (new generation) or resume generation (no new message)
            async for chunk in self.start_workflow(workflow, inputs):
                yield chunk
```

Nota valiosa sobre OpenTelemetry + generadores asíncronos (bug real, documentado):

```python
        # Use start_span + use_span (without making the span "current" across yields).
        # `start_as_current_span` inside an async generator attaches the span to the running
        # task's contextvars; when the generator yields, the consumer task resumes with that
        # context still set, leaking this span as the consumer's "current span". We scope
        # the current-span context only around the non-yielding bookkeeping so child spans
        # still parent correctly, while yields run outside the attached context.
        # See https://github.com/open-telemetry/opentelemetry-python/issues/2606.
```

### 6.6 Cola de mensajes durante la generación

`ee/hogai/queue.py`: el usuario puede escribir mientras el agente trabaja; se encolan máximo 2 mensajes
con lock distribuido sobre el cache de Django.

```python
MAX_QUEUE_MESSAGES = 2
QUEUE_CACHE_TIMEOUT_SECONDS = 60 * 60


class ConversationQueueMessage(TypedDict):
    id: str
    content: str
    created_at: str
    contextual_tools: dict[str, Any] | None
    ui_context: dict[str, Any] | None
    billing_context: dict[str, Any] | None
    agent_mode: str | None
    session_id: str | None


@dataclass
class ConversationQueueStore:
    conversation_id: str
    max_messages: int = MAX_QUEUE_MESSAGES
    cache_timeout_seconds: int = QUEUE_CACHE_TIMEOUT_SECONDS

    @asynccontextmanager
    async def _async_lock(self, timeout: float = 5.0):
        cache = caches["default"]
        lock_key = self._lock_key()
        start_time = time.monotonic()
        while not cache.add(lock_key, "1", timeout=timeout):
            if time.monotonic() - start_time > timeout:
                raise TimeoutError(f"Failed to acquire lock after {timeout}s")
            await asyncio.sleep(0.01)
        try:
            yield
        finally:
            cache.delete(lock_key)

    def enqueue(self, message: ConversationQueueMessage) -> builtins.list[ConversationQueueMessage]:
        with self._lock():
            queue = self.list()
            if len(queue) >= self.max_messages:
                raise QueueFullError
            queue.append(message)
            self.save(queue)
            return queue

    async def requeue_front_async(self, message: ConversationQueueMessage) -> builtins.list[ConversationQueueMessage]:
        async with self._async_lock():
            queue = self.list()
            if len(queue) >= self.max_messages:
                queue = queue[: self.max_messages - 1]
            queue.insert(0, message)
            self.save(queue)
            return queue
```

**➜ TRANSFERIBLE A CINE (streaming)**
Un agente de vídeo tiene tareas de minutos, no de segundos. La arquitectura de PostHog está literalmente
diseñada para eso y es **el diseño que debes copiar**:

- **Redis Stream como buffer entre worker y HTTP**. Renderizar un clip tarda 60-180s; el usuario cerrará la
  pestaña. Con este diseño, vuelve y se reengancha desde `"0"`. Sin él, pierdes el trabajo.
- **Cinco tipos de evento** mapean directo: `MESSAGE` (texto del agente), `UPDATE` (progreso dentro de un
  tool call — perfecto para "render 34%"), `STATUS`, `APPROVAL` (gasto), `CONVERSATION` (título/metadata).
  Añade `ARTIFACT` para stills y clips.
- **`ArtifactRefMessage` (estado) vs `ArtifactMessage` (cliente)** es *obligatorio* para ti: en el estado
  del grafo guardas `{artifact_id, content_type: "video", source}`, nunca el binario ni el base64. El
  checkpoint se mantiene pequeño y el enriquecimiento a URL firmada ocurre en el stream processor. Sin esto
  tus checkpoints de Postgres explotan.
- **`node_path` → `tool_call_id`** para atribuir progreso al render correcto cuando corren 5 shots en
  paralelo. `SubagentUpdateEvent(id=message_id, tool_call_id=..., content=...)` es exactamente el evento de
  "el shot 3 va por el 60%".
- **Regla ID/sin-ID** para deltas vs mensajes finales: adóptala tal cual.
- **`StreamStatusEvent{complete|error}`** como terminador explícito del stream, en vez de depender del
  cierre de conexión.
- La **cola de máximo 2 mensajes** con `requeue_front`: en cine el usuario dirá "para, cambia la paleta"
  mientras renderizas. Encólalo y aplícalo al terminar el shot en curso.

---

## 7. Multi-modelo, fallbacks y coste

### 7.1 Selección por tarea

No hay un router de modelos; **cada tarea elige su modelo en su propio sitio**. Inventario:

| Tarea | Modelo | Config | Fichero |
|---|---|---|---|
| Bucle agéntico principal | `claude-sonnet-4-6` | thinking 10240, max_tokens 16384, effort medium | `core/agent_modes/executables.py` |
| Bucle (conversaciones legacy) | `claude-sonnet-4-5` | thinking 1024, max_tokens 8192 | ídem |
| Resumen de conversación | `claude-haiku-4-5` | max_tokens 8192, sin streaming | `utils/conversation_summarizer/summarizer.py` |
| Resumen de conversación enorme (>195k) | `claude-sonnet-4-6` | ventana de 1M | ídem |
| Título + clasificación de topic | `gpt-4.1-nano` | temp 0.7, max 100/200 tokens, structured output | `core/title_generator/nodes.py` |

El selector del bucle principal:

```python
    def _get_model(self, state: AssistantState, tools: list["MaxTool"]):
        model_name = "claude-sonnet-4-6"
        if self._has_legacy_summarize_sessions_messages(state.messages):
            model_name = "claude-sonnet-4-5"

        is_sonnet_4_5 = model_name == "claude-sonnet-4-5"

        gateway_kwargs = self._get_gateway_kwargs()
        is_routing_through_llm_gateway = bool(gateway_kwargs)

        base_model = MaxChatAnthropic(
            model=model_name,
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            betas=[
                "interleaved-thinking-2025-05-14",
                "fine-grained-tool-streaming-2025-05-14",
            ],
            max_tokens=8192 if is_sonnet_4_5 else 16384,
            thinking=self.THINKING_CONFIG if not is_sonnet_4_5 else {"type": "enabled", "budget_tokens": 1024},
            # langchain-anthropic 0.3.x doesn't have a first-class effort field;
            # forward it via model_kwargs so the Anthropic API receives output_config.
            model_kwargs={"output_config": {"effort": "medium"}} if not is_sonnet_4_5 else {},
            conversation_start_dt=state.start_dt,
            billable=True,
            bypass_proxy=is_routing_through_llm_gateway,
            posthog_properties=self._get_agent_mode_posthog_properties(state),
            **gateway_kwargs,
        )

        if self._is_hard_limit_reached(state.root_tool_calls_count):
            return base_model

        return base_model.bind_tools(tools, parallel_tool_calls=True)
```

El *downgrade* de modelo por compatibilidad de historial es un caso real interesante:

```python
    @staticmethod
    def _has_legacy_summarize_sessions_messages(messages: Sequence[AssistantMessageUnion]) -> bool:
        """Detect pre-migration summarize_sessions AssistantMessages with meta.form.

        Before the migration, summarize_sessions returned a ToolMessagesArtifact containing
        an AssistantMessage with meta.form (the "Open report" button). This AssistantMessage
        converts to a trailing AIMessage, causing a prefill error with Sonnet 4.6.
        Sonnet 4.5 handles this gracefully, so we fall back to it for legacy conversations.
        """
        for message in messages:
            if (
                isinstance(message, AssistantMessage)
                and message.meta
                and message.meta.form
                and any(
                    option.href and option.href.startswith("/session-summaries/")
                    for option in message.meta.form.options
                )
            ):
                return True
        return False
```

Modelo barato para el título, con **fallback a título-solo si falla la clasificación estructurada**:

```python
    def _generate_title_and_topic(self, user_input: str, config: RunnableConfig) -> tuple[str, str | None]:
        try:
            runnable = (
                ChatPromptTemplate.from_messages(
                    [("system", TITLE_AND_TOPIC_GENERATION_PROMPT), ("user", "{user_input}")]
                )
                | self._topic_model
            )
            result = cast(TitleAndTopic, runnable.invoke({"user_input": user_input}, config=config))
            return result.title, result.topic
        except Exception:
            # Never break title generation on a classification failure, fall back to title-only.
            logger.exception("title_topic_generation_failed, falling back to title-only")
            return self._generate_title_only(user_input, config), None

    def _build_model(self, *, max_completion_tokens: int, topic_classification: bool) -> MaxChatOpenAI:
        return MaxChatOpenAI(
            model="gpt-4.1-nano",
            temperature=0.7,
            max_completion_tokens=max_completion_tokens,
            user=self._user,
            team=self._team,
            streaming=False,
            stream_usage=False,
            disable_streaming=True,
            billable=True,
            posthog_properties={"topic_classification": topic_classification},
        )

    @property
    def _topic_model(self):
        return self._build_model(max_completion_tokens=200, topic_classification=True).with_structured_output(
            TitleAndTopic, method="json_schema", include_raw=False
        )
```

### 7.2 Fallbacks de proveedor: el LLM gateway

Enrutamiento A/B entre Anthropic directo y Bedrock, controlado por feature flag, **puramente por cabeceras
HTTP** (`ee/hogai/core/agent_modes/executables.py`):

```python
    def _get_llm_gateway_product(self) -> str:
        return "django"

    def _get_gateway_kwargs(self) -> dict[str, Any]:
        variant = get_llm_gateway_variant(self._team, self._user)
        if variant == "control":
            return {}
        if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
            logger.warning(
                "llm_gateway settings are not configured",
                product=self._get_llm_gateway_product(),
                team_id=self._team.id,
                variant=variant,
            )
            return {}

        headers: dict[str, str] = {
            "X-POSTHOG-FLAG-phai-llm-gateway": variant,
        }

        if variant == "gateway-bedrock":
            headers["X-PostHog-Provider"] = "bedrock"
        elif variant == "gateway-anthropic":
            headers["X-PostHog-Use-Bedrock-Fallback"] = "true"

        return {
            "anthropic_api_url": f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{self._get_llm_gateway_product()}",
            "anthropic_api_key": settings.LLM_GATEWAY_API_KEY,
            "default_headers": headers,
        }
```

Es decir: **el fallback de proveedor no vive en el código Python**, vive en un gateway. El código solo
decide a qué URL apuntar y qué cabeceras mandar. Muy limpio.

Los reintentos son del SDK (`ee/hogai/llm.py`):

```python
    def model_post_init(self, __context: Any) -> None:
        if self.max_retries is None:
            self.max_retries = 3
        if self.stream_usage is None:
            self.stream_usage = True
```

### 7.3 Los wrappers: `MaxChatMixin`

`ee/hogai/llm.py`. Este mixin es directamente copiable:

```python
class MaxChatMixin(BaseModel):
    # We don't want to validate Django models here.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user: User
    team: Team
    max_retries: int | None = None
    stream_usage: bool | None = None
    conversation_start_dt: datetime.datetime | None = None
    """
    The datetime of the start of the conversation. If not provided, the current time will be used.
    """
    billable: bool = False
    """
    Whether the generation will be marked as billable in the usage report for calculating AI billing credits.
    """
    inject_context: bool = True
    """
    Whether to inject project/org/user context into the system prompt.
    Set to False to disable automatic context injection.
    """
    posthog_properties: dict[str, Any] | None = None
    """
    Additional PostHog properties to be added to the $ai_generation event.
    These will be merged with the standard properties like $ai_billable and team_id.
    """
```

**Inyección automática de contexto** — el truco: se inserta al *final del bloque de system messages*, no al
principio, para no romper el prefijo cacheado:

```python
    def _enrich_messages(self, messages: list[list[BaseMessage]], project_org_user_variables: dict[str, Any]):
        messages = messages.copy()
        for i in range(len(messages)):
            message_sublist = messages[i]
            # In every sublist (which becomes a separate generation) insert our shared prompt at the very end
            # of the system messages block
            for msg_index, msg in enumerate(message_sublist):
                if isinstance(msg, SystemMessage):
                    continue  # Keep going
                else:
                    # Here's our end of the system messages block
                    copied_list = message_sublist.copy()
                    copied_list.insert(msg_index, self._get_project_org_system_message(project_org_user_variables))
                    messages[i] = copied_list
                    break
        return messages
```

**Control de facturación** con override a nivel de workflow (p.ej. sesiones impersonadas de soporte no
cobran):

```python
BILLING_SKIPPED_COUNTER = Counter(
    "posthog_ai_billing_skipped_total",
    "Number of AI generations where billing was skipped due to workflow-level override (e.g., impersonation)",
    ["model"],
)


    def _get_effective_billable(self) -> bool:
        """
        Determine the effective billable status for this generation.
        Combines model-level billable setting with workflow-level override from config.
        When is_agent_billable is False (e.g., impersonated sessions), billing is skipped
        regardless of the model's billable setting.
        """
        config = ensure_config()
        is_agent_billable = (config.get("configurable") or {}).get("is_agent_billable", True)

        effective_billable = self.billable and is_agent_billable

        if self.billable and not is_agent_billable:
            # This is really annoying given the interface differences between model providers
            # Once we are behind a proxy, this can be simplified.
            model_name = getattr(self, "model", None) or getattr(self, "model_name", "unknown")
            BILLING_SKIPPED_COUNTER.labels(model=model_name).inc()
            logger.warning("Billing skipped for generation due to workflow-level override")

        return effective_billable

    def _with_posthog_properties(self, kwargs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return a shallow copy of kwargs with PostHog properties, billable flag, and team_id injected into metadata."""
        new_kwargs = dict(kwargs or {})
        metadata = dict(new_kwargs.get("metadata") or {})

        posthog_props = dict(self.posthog_properties or {})
        posthog_props["$ai_billable"] = self._get_effective_billable()
        posthog_props["team_id"] = self.team.id
        posthog_props.setdefault("ai_product", "posthog_ai")

        metadata["posthog_properties"] = posthog_props
        new_kwargs["metadata"] = metadata

        return new_kwargs
```

El contexto inyectado (nótese cómo el prompt enseña convenciones de URL, algo muy exportable):

```python
PROJECT_ORG_USER_CONTEXT_PROMPT = """
You are currently in project {{{project_name}}}, which is part of the {{{organization_name}}} organization.
The user's name appears to be {{{user_full_name}}} ({{{user_email}}}). Feel free to use their first name when greeting. DO NOT use this name if it appears possibly fake.
All PostHog app URLs must use root-relative paths starting with `/`, without a domain (no us.posthog.com, eu.posthog.com, app.posthog.com), and omit the `/project/:id/` prefix. Never include `/-/` in URLs. Never use relative paths like `../` or `./` — always start with `/`.
Use Markdown with descriptive anchor text, for example "[Cohorts view](/cohorts)".

Key URL patterns:
- Dashboard: `/dashboard/<id>`, e.g. `/dashboard/12345`
- Insights: `/insights/<short_id>`, e.g. `/insights/abc123`
- Settings: `/settings/<section-id>` where section IDs use hyphens, e.g. `/settings/organization-members`, `/settings/environment-replay`, `/settings/user-api-keys`
- Data management: `/data-management/events`, `/data-management/properties`
- Billing: `/organization/billing`
Current time in the project's timezone, {{{project_timezone}}}: {{{project_datetime}}}.
{{#person_on_events_enabled}}
Person-on-events mode is enabled. When querying `person.properties.*` on the events table, values reflect what was set at the time the event was ingested, not the person's current value. The same person can have different property values across different events. Do not suggest workarounds for "query-time" person properties.
{{/person_on_events_enabled}}
{{^person_on_events_enabled}}
Person properties are query-time in this project. `person.properties.*` on the events table always returns the person's current (latest) value, regardless of when the event occurred.
{{/person_on_events_enabled}}
""".strip()
```

Y una optimización de coste en evals:

```python
# https://platform.openai.com/docs/guides/flex-processing
OPENAI_FLEX_MODELS = ["o3", "o4-mini", "gpt5", "gpt5-mini", "gpt5-nano"]

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if settings.IN_EVAL_TESTING and not self.service_tier and self.model_name in OPENAI_FLEX_MODELS:
            self.service_tier = "flex"  # 50% cheaper than default tier, but slower
```

### 7.4 Estrategia de caché de prompts

Tres piezas coordinadas:

1. System prompt largo con TTL de 1h (`arun`): `add_cache_control(system_prompts[0], ttl="1h")`.
2. Un breakpoint efímero al final del historial:

```python
    def _add_cache_control_to_last_message(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Add cache control to the last message."""
        for i in range(len(messages) - 1, -1, -1):
            maybe_content_arr = messages[i].content
            if (
                isinstance(messages[i], LangchainHumanMessage | LangchainAIMessage)
                and isinstance(maybe_content_arr, list)
                and len(maybe_content_arr) > 0
                and isinstance(maybe_content_arr[-1], dict)
            ):
                maybe_content_arr[-1]["cache_control"] = {"type": "ephemeral"}
                break
        return messages
```

3. `start_dt` congelado 5 minutos para que el timestamp del system prompt no invalide la caché en cada turno.

**➜ TRANSFERIBLE A CINE (multi-modelo)**
- **Selección por tarea, no router genérico.** Tu tabla será: guion → Opus/Sonnet (razonamiento largo);
  descomposición en shots → Sonnet; escritura de prompts de imagen → Sonnet o incluso Haiku con few-shots
  fuertes; resumen → Haiku; título del proyecto → nano. Copia el patrón de tener la elección **junto al
  código de la tarea**, no en un módulo de routing central: se lee mejor y evita acoplamiento.
- El `MaxChatMixin` es **directamente copiable**: `user`/`project`, `billable`, `posthog_properties`,
  inyección automática de contexto. Para cine, `inject_context` inyectaría la **biblia de estilo + formato
  de entrega + modelos de generación disponibles** en todas las llamadas.
- El **gateway con cabeceras** es el patrón correcto para tu multi-proveedor de generación de vídeo
  (Runway/Kling/Veo/Higgsfield): un gateway propio con fallback y el código Python solo eligiendo variante.
  Mucho mejor que un `try/except` por proveedor en el agente.
- **Caché de prompts**: tu system prompt llevará la biblia de estilo, que es larga y estable → TTL 1h en
  el bloque 0. El truco de congelar el timestamp 5 minutos te aplicará igual.
- **`$ai_billable` + contador de `billing_skipped`**: para vídeo necesitas trazar coste **por render**, no
  solo por tokens. Extiende `posthog_properties` con `{model, resolution, duration_s, credits}` y emítelo
  desde la tool de render.
- El `service_tier = "flex"` en evals: aplícalo a tus batch renders no interactivos.

---

## 8. Resumen ejecutivo: los 12 patrones a robar

1. **Grafo de 2 nodos** (ROOT ↔ TOOLS) con fan-out `Send` por tool call. No modeles el pipeline como grafo.
2. **State / PartialState** con reductores anotados (`replace`, `append`, `upsert por ID`, centinela para
   borrar).
3. **`AgentModeDefinition`** = (descripción, toolkit, node_class, tools_node_class). Modos = fases del
   pipeline.
4. **`switch_mode` autogenerado** desde el registry, con `Literal[*registry.keys()]` y catálogo de tools
   real.
5. **Toolkit común ∪ toolkit de modo**, con tools cuya descripción se genera en runtime.
6. **Doble límite** (contador de tool calls + recursion limit) y **desarmar en vez de excepcionar**.
7. **Cuatro clases de error** con cuatro políticas de recuperación, cada una con su prompt para el LLM.
8. **Compactación**: ventana deslizante + resumen estructurado en 7 secciones + **reinyección de
   recordatorios** (TODO, modo, y en tu caso: biblia de estilo y seeds).
9. **Plan mode como supermodo**, con el plan como artefacto visible y el catálogo de capacidades de
   ejecución inyectado en el planificador.
10. **`ArtifactRefMessage` en el estado / `ArtifactMessage` al cliente**: nunca metas binarios en el
    checkpoint.
11. **Redis Stream como buffer** → reconexión gratis, imprescindible para tareas de minutos.
12. **`interrupt()` + aprobación con side-channel** antes de cualquier operación cara o irreversible.

### Lo que NO copiaría

- El acoplamiento a Django/Temporal si tu stack no lo tiene ya (el patrón sí, la implementación no).
- `pickle` en el serializador de Redis — usa JSON/msgpack.
- La proliferación de campos específicos de dominio en `_SharedAssistantState` (~30 campos de PostHog en
  un estado compartido). Empieza con un estado más disciplinado: los datos específicos de una tool deberían
  ir en artefactos referenciados, no en el estado raíz.
