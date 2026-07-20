# Sistema de herramientas y artefactos de PostHog Max AI (`ee/hogai`)

> Análisis técnico del sistema de tools del agente de PostHog, con vistas a portarlo a un
> agente de generación de cinematografías/vídeo (guion, shot list, imagen, vídeo, timeline, estilo).
> Todas las rutas son absolutas sobre el checkout en `C:\ph`.

---

## Índice

1. [El contrato de una herramienta (`MaxTool`)](#1-el-contrato-de-una-herramienta-maxtool)
2. [Validación de argumentos y errores auto-corregibles](#2-validación-de-argumentos-y-errores-auto-corregibles)
3. [El sistema de artefactos](#3-el-sistema-de-artefactos)
4. [Herramientas de escritura vs lectura, confirmaciones, idempotencia](#4-escritura-vs-lectura-confirmaciones-idempotencia)
5. [Integración MCP](#5-integración-mcp)
6. [Patrones de redacción de `description`](#6-patrones-de-redacción-de-description)
7. [Plan de transferencia al agente de cinematografías](#7-plan-de-transferencia-al-agente-de-cinematografías)

---

## 1. El contrato de una herramienta (`MaxTool`)

**Fichero:** `C:\ph\ee\hogai\tool.py`

`MaxTool` extiende `langchain_core.tools.BaseTool` y añade cinco cosas que LangChain no da:
contexto de tenant (team/user), control de acceso, flujo de aprobación humana, inyección de
prompt contextual, y un canal de "artefacto" que se convierte en UI.

### 1.1 Campos del contrato

```python
class MaxTool(AssistantContextMixin, AssistantDispatcherMixin, BaseTool):
    # LangChain's default is just "content", but we always want to return the tool call artifact too
    # - it becomes the `ui_payload`
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    billable: bool = False
    """Whether LLM generations triggered by this tool should count toward billing."""

    context_prompt_template: str | None = None
    """The template for context associated with this tool, that will be injected into the root node's context messages.
    Use this if you need to strongly steer the root node in deciding _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """

    _config: RunnableConfig
    _state: AssistantState
    _context_manager: AssistantContextManager
    _node_path: tuple[NodePath, ...]
```

Los tres campos obligatorios heredados de `BaseTool` son:

| Campo | Tipo | Notas |
|---|---|---|
| `name` | `Literal[AssistantTool.X]` o `Literal["x"]` | **Debe existir en el enum `AssistantTool` compartido con el frontend TypeScript** |
| `description` | `str` | El prompt de la herramienta; frecuentemente una constante multi-KB en `prompts.py` |
| `args_schema` | `type[BaseModel]` | Modelo Pydantic; puede construirse dinámicamente |

Un ejemplo mínimo completo (`C:\ph\ee\hogai\tools\create_notebook\tool.py`):

```python
class CreateNotebookToolArgs(BaseModel):
    content: str | None = Field(
        default=None,
        description="The notebook content in markdown format. Use this to show the notebook to the user immediately (it will be streamed). Use <insight>artifact_id</insight> tags to reference existing visualization artifacts.",
    )
    draft_content: str | None = Field(
        default=None,
        description="The notebook content in markdown format for a draft. Use this to save a draft without showing it to the user. ...",
    )
    title: str = Field(description="A descriptive title for the notebook.")
    artifact_id: str | None = Field(
        default=None, description="The ID of an existing notebook artifact that you want to update."
    )
    save_to_notebook: bool = Field(
        default=False,
        description="Set to true ONLY when the user explicitly asks to save/persist the notebook to the database.",
    )


class CreateNotebookTool(MaxTool):
    name: Literal[AssistantTool.CREATE_NOTEBOOK] = AssistantTool.CREATE_NOTEBOOK
    args_schema: type[BaseModel] = CreateNotebookToolArgs
    description: str = CREATE_NOTEBOOK_PROMPT

    async def _arun_impl(self, title: str, content: str | None = None, ...) -> tuple[str, Any]:
        ...
        return "", ToolMessagesArtifact(messages=[...])
```

### 1.2 Registro: `__init_subclass__` (auto-registro por herencia)

No hay decorador `@register`. **El simple hecho de heredar de `MaxTool` registra la clase**, y
además valida el nombre contra el enum compartido con el frontend:

```python
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    if not cls.__name__.endswith("Tool"):
        raise ValueError("The name of a MaxTool subclass must end with 'Tool', for clarity")
    try:
        accepted_name = AssistantTool(cls.name)
    except ValueError:
        raise ValueError(
            f"MaxTool name '{cls.name}' is not a recognized AssistantTool value. Fix this name, or update AssistantTool in schema-assistant-messages.ts and run `pnpm schema:build`"
        )
    CONTEXTUAL_TOOL_NAME_TO_TOOL[accepted_name] = cls
```

Dos invariantes fuertes muy transferibles:
- **Convención de nombre de clase forzada en tiempo de import** (`*Tool`).
- **El nombre de la tool es un enum compartido backend↔frontend.** Si el LLM llama a una tool,
  el frontend sabe renderizarla porque el identificador está en un contrato tipado común.
  Un typo revienta al importar, no en producción.

### 1.3 El registro y el descubrimiento por producto

**Fichero:** `C:\ph\ee\hogai\registry.py` (completo)

```python
import pkgutil
import importlib
from typing import TYPE_CHECKING

from posthog.schema import AssistantTool

import products

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool

CONTEXTUAL_TOOL_NAME_TO_TOOL: dict[AssistantTool, type["MaxTool"]] = {}


def _import_max_tools() -> None:
    """TRICKY: Dynamically import max_tools from all products"""
    for module_info in pkgutil.iter_modules(products.__path__):
        if module_info.name in ("conftest", "test"):
            continue  # We mustn't import test modules in prod
        try:
            importlib.import_module(f"products.{module_info.name}.backend.max_tools")
        except ModuleNotFoundError:
            pass  # Skip if backend or max_tools doesn't exist - note that the product's dir needs a top-level __init__.py


def get_contextual_tool_class(tool_name: str) -> type["MaxTool"] | None:
    """Get the tool class for a given tool name, handling circular import."""
    _import_max_tools()  # Ensure max_tools are imported

    try:
        return CONTEXTUAL_TOOL_NAME_TO_TOOL[AssistantTool(tool_name)]
    except (KeyError, ValueError):
        return None
```

Cada "producto" del monorepo expone opcionalmente `products/<x>/backend/max_tools.py`; el registry
barre el paquete `products` y lo importa. **Convención sobre configuración**: para añadir una
herramienta nueva de un producto no se toca ningún fichero central.

Además, `C:\ph\ee\hogai\tools\__init__.py` usa **carga perezosa PEP 562** para romper ciclos de
import (crítico cuando las tools importan el propio agente):

```python
_TOOL_MODULES: dict[str, str] = {
    "CallMCPServerTool": ".call_mcp_server.tool",
    "CreateInsightTool": ".create_insight",
    "CreateNotebookTool": ".create_notebook",
    "ExecuteSQLTool": ".execute_sql.tool",
    "ReadDataTool": ".read_data",
    ...
}

def load_all_tools() -> None:
    """Import every tool submodule so the MCP tools self-register via
    @mcp_tool_registry.register. Called by the registry on demand — registration is
    decoupled from package import so that importing the package (or a single tool) stays
    cheap and cycle-free. Idempotent: re-imports are dict lookups in sys.modules.
    """
    for submodule in dict.fromkeys(_TOOL_MODULES.values()):
        importlib.import_module(submodule, __name__)


def __getattr__(name: str) -> Any:
    submodule = _TOOL_MODULES.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(submodule, __name__)
    return getattr(module, name)
```

### 1.4 Tres capas de disponibilidad de herramientas

**Fichero:** `C:\ph\ee\hogai\chat_agent\toolkit.py`

**(a) Toolkit estático por modo de agente.** Las tools se agrupan por "modo" (chat, plan, …):

```python
DEFAULT_TOOLS: list[type[MaxTool]] = [
    ReadTaxonomyTool, ReadDataTool, SearchTool, ListDataTool, ListFeatureFlagsTool,
    TodoWriteTool, SwitchModeTool, CreateFormTool, CreateNotebookTool,
    ListLLMSkillsTool, GetLLMSkillTool, GetLLMSkillFileTool,
]

class ChatAgentPlanToolkit(AgentToolkit):
    """Agent toolkit for plan mode with base tools + plan-specific tools."""
    @property
    def tools(self) -> list[type[MaxTool]]:
        tools: list[type[MaxTool]] = [
            ReadTaxonomyTool, SearchTool, TodoWriteTool, SwitchModeTool,
            CreateFormTool, FinalizePlanTool,
        ]
        if has_memory_tool_feature_flag(self._team, self._user):
            tools.append(ManageMemoriesTool)
        return tools


class ChatAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type[MaxTool]]:
        # TRICKY: DO NOT EXTEND THE TOOLKIT HERE. THE TOOLS HERE ARE USED ACROSS ALL AGENT MODES.
        tools = list(DEFAULT_TOOLS)
        if has_phai_tasks_feature_flag(self._team, self._user):
            tools.extend(TASK_TOOLS)
        if has_task_tool_feature_flag(self._team, self._user):
            tools.append(TaskTool)
        if has_memory_tool_feature_flag(self._team, self._user):
            tools.append(ManageMemoriesTool)
        return tools
```

En modo `plan` el agente **no tiene** `ReadDataTool` ni `CreateNotebookTool` — sólo puede
investigar y `FinalizePlanTool`. Es una máquina de estados aplicada al toolset: el modo controla
lo que el agente *puede físicamente hacer*, no sólo lo que se le pide en el system prompt.

**(b) Herramientas contextuales según la pantalla en la que está el usuario.** El frontend envía
`configurable.contextual_tools` en el `RunnableConfig`, un dict `{tool_name: contexto}`:

```python
# C:\ph\ee\hogai\context\context.py
def get_contextual_tools(self) -> dict[str, dict[str, Any]]:
    """
    Extracts contextual tools from the runnable config, returning a mapping of available contextual tool names to context.
    """
    contextual_tools = (self._config.get("configurable") or {}).get("contextual_tools") or {}
    if not isinstance(contextual_tools, dict):
        return {}
    return contextual_tools
```

Y el toolkit manager las instancia y deduplica:

```python
# C:\ph\ee\hogai\chat_agent\toolkit.py
class ChatAgentToolkitManager(AgentToolkitManager):
    async def get_tools(self, state: AssistantState, config: RunnableConfig) -> list[MaxTool | dict[str, Any]]:
        available_tools = await super().get_tools(state, config)

        tool_names = self._context_manager.get_contextual_tools().keys()
        awaited_contextual_tools: list[Awaitable[MaxTool]] = []
        for tool_name in tool_names:
            ContextualMaxToolClass = get_contextual_tool_class(tool_name)
            if ContextualMaxToolClass is None:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            awaited_contextual_tools.append(
                ContextualMaxToolClass.create_tool_class(
                    team=self._team, user=self._user, state=state,
                    config=config, context_manager=self._context_manager,
                )
            )

        contextual_tools = await asyncio.gather(*awaited_contextual_tools)

        # Deduplicate contextual tools
        initialized_tool_names = {tool.get_name() for tool in available_tools if isinstance(tool, MaxTool)}
        for tool in contextual_tools:
            if tool.get_name() not in initialized_tool_names:
                available_tools.append(tool)

        # Add MCP server tool if user has installations and flag is enabled
        if has_mcp_servers_feature_flag(self._team, self._user):
            mcp_tool = await CallMCPServerTool.create_tool_class(
                team=self._team, user=self._user, state=state,
                config=config, context_manager=self._context_manager,
            )
            if mcp_tool._installations:
                available_tools.append(mcp_tool)

        # Web Search isn't supported by AWS Bedrock as primary provider
        variant = get_llm_gateway_variant(self._team, self._user)
        uses_bedrock_primary = (
            variant == "gateway-bedrock" and settings.LLM_GATEWAY_URL and settings.LLM_GATEWAY_API_KEY
        )
        if not uses_bedrock_primary:
            available_tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": 5})

        return available_tools
```

Fíjate en el detalle de robustez: **si el frontend anuncia una tool que el backend no conoce
(despliegue desincronizado), se ignora en silencio en vez de romper la conversación.**

**(c) Inyección de contexto al system prompt.** Cada tool contextual puede inyectar una frase que
le dice al LLM *cuándo* usarla, formateada con el contexto que envió el frontend:

```python
# C:\ph\ee\hogai\context\context.py
async def _get_contextual_tools_prompt(self) -> str | None:
    from ee.hogai.registry import get_contextual_tool_class

    contextual_tools_prompt: list[str] = []
    for tool_name, tool_context in self.get_contextual_tools().items():
        tool_class = get_contextual_tool_class(tool_name)
        if tool_class is None:
            continue
        tool = await tool_class.create_tool_class(team=self._team, user=self._user, context_manager=self)
        tool_prompt = tool.format_context_prompt_injection(tool_context)
        contextual_tools_prompt.append(f"<{tool_name}>\n{tool_prompt}\n</{tool_name}>")

    if contextual_tools_prompt:
        tools = "\n".join(contextual_tools_prompt)
        return CONTEXTUAL_TOOLS_REMINDER_PROMPT.format(tools=tools)
    return None
```

La sustitución de placeholders es deliberadamente conservadora, porque los prompts contienen
bloques de código con llaves:

```python
_CONTEXT_PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")

def format_context_prompt_injection(self, context: dict[str, Any]) -> str | None:
    if not self.context_prompt_template:
        return None
    formatted_context = {
        key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
    }
    # Only substitute `{valid_identifier}` placeholders. Plain `str.format` parses
    # any `{...}` — including literal code blocks like `fun onEvent(event) { ... }`
    # in prompt templates — as placeholders, which raises on substitution.
    # `{{` / `}}` are honored as literal-brace escapes for backwards compatibility.
    tool_name = self.get_name()

    def _substitute(match: re.Match[str]) -> str:
        text = match.group(0)
        if text == "{{":
            return "{"
        if text == "}}":
            return "}"
        key = match.group(1)
        if key not in formatted_context:
            logger.warning(
                f"Context prompt template for {tool_name} expects key {key} but it is not present in the context"
            )
            return "None"
        value = formatted_context[key]
        return "None" if value is None else str(value)

    return _CONTEXT_PLACEHOLDER_RE.sub(_substitute, self.context_prompt_template)
```

### 1.5 `create_tool_class`: la factoría que hace la herramienta dinámica

Este es probablemente **el patrón más valioso de todo el sistema**. La clase no se instancia
directamente; hay una factoría async sobreescribible que puede reescribir `name`, `description` y
`args_schema` en función del tenant, feature flags y permisos:

```python
@classmethod
async def create_tool_class(
    cls,
    *,
    team: Team,
    user: User,
    node_path: tuple[NodePath, ...] | None = None,
    state: AssistantState | None = None,
    config: RunnableConfig | None = None,
    context_manager: AssistantContextManager | None = None,
) -> Self:
    """
    Factory that creates a tool class.

    Override this factory to dynamically modify the tool name, description, args schema, etc.
    """
    return cls(
        team=team, user=user, node_path=node_path, state=state, config=config, context_manager=context_manager
    )
```

Y el `__init__` acepta overrides de los tres campos del contrato:

```python
def __init__(
    self, *, team: Team, user: User,
    node_path: tuple[NodePath, ...] | None = None,
    state: AssistantState | None = None,
    config: RunnableConfig | None = None,
    name: str | None = None,
    description: str | None = None,
    args_schema: type[BaseModel] | None = None,
    context_manager: AssistantContextManager | None = None,
    **kwargs,
):
    tool_kwargs: dict[str, Any] = {}
    if name is not None:
        tool_kwargs["name"] = name
    if description is not None:
        tool_kwargs["description"] = description
    if args_schema is not None:
        tool_kwargs["args_schema"] = args_schema

    super().__init__(**tool_kwargs, **kwargs)
    self._team = team
    self._user = user
    if node_path is None:
        self._node_path = get_node_path() or ()
    else:
        self._node_path = node_path
    self._state = state if state else AssistantState(messages=[])
    self._config = config if config else RunnableConfig(configurable={})
    self._context_manager = context_manager or AssistantContextManager(team, user, self._config)
```

**Caso 1 — description dinámica** (`C:\ph\ee\hogai\tools\execute_sql\tool.py`): la descripción se
compone inyectando la documentación de funciones SQL soportadas.

```python
@classmethod
async def create_tool_class(cls, *, team, user, node_path=None, state=None, config=None, context_manager=None) -> Self:
    prompt = format_prompt_string(
        EXECUTE_SQL_SYSTEM_PROMPT,
        sql_expressions_docs=SQL_EXPRESSIONS_DOCS,
        sql_supported_functions_docs=SQL_SUPPORTED_FUNCTIONS_DOCS,
        sql_supported_aggregations_docs=SQL_SUPPORTED_AGGREGATIONS_DOCS,
    )
    return cls(team=team, user=user, state=state, node_path=node_path, config=config, description=prompt)
```

**Caso 2 — `args_schema` dinámico con `Literal` construido en runtime**
(`C:\ph\ee\hogai\tools\read_taxonomy\tool.py`). Los "grupos" son entidades definidas por cada
cliente, así que el enum de valores válidos se construye desde la BD:

```python
@classmethod
async def create_tool_class(cls, *, team, user, node_path=None, state=None, config=None, context_manager=None) -> Self:
    context_manager = AssistantContextManager(team, user, config)
    group_names = await context_manager.get_group_names()

    # Create Literal type with actual entity names
    EntityKind = Literal["person", "session", *group_names]  # type: ignore

    ReadEntityPropertiesWithGroups = create_model(
        "ReadEntityProperties",
        __base__=ReadEntityProperties,
        entity=(
            EntityKind,
            Field(description=ReadEntityProperties.model_fields["entity"].description),
        ),
    )
    ...
    class ReadTaxonomyToolArgsWithGroups(BaseModel):
        query: ReadTaxonomyQueryWithGroups = Field(..., discriminator="kind")

    return cls(
        team=team, user=user, state=state, config=config, node_path=node_path,
        args_schema=ReadTaxonomyToolArgsWithGroups,
        context_manager=context_manager,
    )
```

**Caso 3 — unión discriminada variable según permisos** (`C:\ph\ee\hogai\tools\read_data\tool.py`).
Este es el patrón "una tool, N sub-operaciones" que evita la explosión de herramientas:

```python
kinds: list[type[BaseModel]] = []
prompt_vars: dict[str, str] = {}

if not context_manager:
    context_manager = AssistantContextManager(team, user, config)

has_billing_access = await context_manager.check_user_has_billing_access()
if has_billing_access:
    prompt_vars["billing_prompt"] = READ_DATA_BILLING_PROMPT
    kinds.append(ReadBillingInfo)

has_audit_logs_access = await context_manager.check_has_audit_logs_access()
if has_audit_logs_access:
    prompt_vars["activity_log_prompt"] = READ_DATA_ACTIVITY_LOG_PROMPT
    kinds.append(ReadActivityLog)

has_bk = await database_sync_to_async(has_business_knowledge_feature_flag)(team)
if has_bk and await database_sync_to_async(has_ready_sources)(team.id):
    prompt_vars["business_knowledge_prompt"] = READ_DATA_BK_PROMPT
    kinds.append(ReadBusinessKnowledgeDocument)

if has_customer_analytics_mode_feature_flag(team, user):
    prompt_vars["account_prompt"] = READ_DATA_ACCOUNT_PROMPT
    kinds.append(ReadAccount)

base_kinds: tuple[type[BaseModel], ...] = (
    ReadDataWarehouseSchema, ReadDataWarehouseTableSchema, ReadInsight, ReadDashboard,
    ReadErrorTrackingIssue, ReadArtifact, ReadNotebook, ReadSurvey,
    ReadFeatureFlag, ReadExperiment, ReadLLMTrace,
)
ReadDataKind = Union[tuple(base_kinds + tuple(kinds))]  # type: ignore[valid-type]

ReadDataToolArgs = create_model(
    "ReadDataToolArgs",
    __base__=BaseModel,
    query=(
        ReadDataKind,
        Field(discriminator="kind"),
    ),
)

description = format_prompt_string(READ_DATA_PROMPT, template_format="mustache", **prompt_vars).strip()

return cls(
    team=team, user=user, state=state, node_path=node_path, config=config,
    args_schema=ReadDataToolArgs,
    description=description,
    context_manager=context_manager,
)
```

**La clave: `prompt_vars` y `kinds` crecen juntos.** El esquema y la descripción se mantienen
sincronizados por construcción — si el usuario no tiene acceso a billing, ni el esquema acepta
`kind="billing_info"` ni la descripción menciona billing. El LLM **nunca ve** capacidades que no
puede ejercer, lo que elimina toda una clase de alucinaciones.

Y el despacho en el cuerpo se hace con `match` estructural sobre el modelo validado:

```python
async def _arun_impl(self, query: dict) -> tuple[str, ToolMessagesArtifact | None]:
    validated_query = _InternalReadDataToolArgs(query=query).query
    match validated_query:
        case ReadBillingInfo():
            has_access = await self._context_manager.check_user_has_billing_access()
            if not has_access:
                raise MaxToolFatalError(BILLING_INSUFFICIENT_ACCESS_PROMPT)
            ...
        case ReadDataWarehouseSchema():
            return await self._read_data_warehouse_schema(), None
        case ReadArtifact() as schema:
            return await self._read_artifact(schema.artifact_id), None
        case ReadNotebook() as schema:
            return await self._read_notebook(schema.notebook_id), None
        case ReadInsight() as schema:
            return await self._read_insight(schema.insight_id, schema.execute)
        ...
```

Nótese la **doble comprobación de permisos**: aunque el esquema no ofrezca `ReadBillingInfo` a
quien no tiene acceso, el cuerpo lo vuelve a verificar. Defensa en profundidad frente a un LLM que
invente un `kind`.

### 1.6 Pipeline de ejecución

```python
def _run(self, *args, config: RunnableConfig, **kwargs):
    """LangChain default runner."""
    self._check_resource_access()
    try:
        return self._run_with_context(*args, **kwargs)
    except NotImplementedError:
        pass
    return async_to_sync(self._arun_with_context)(*args, **kwargs)

async def _arun(self, *args, config: RunnableConfig, **kwargs):
    """LangChain default runner."""
    # using database_sync_to_async because UserAccessControl is fully sync
    await database_sync_to_async(self._check_resource_access)()
    try:
        return await self._arun_with_context(*args, **kwargs)
    except NotImplementedError:
        pass
    return await super()._arun(*args, config=config, **kwargs)

def _run_with_context(self, *args, **kwargs):
    """Sets the context for the tool."""
    with set_node_path(self.node_path):
        if permission_check_result := async_to_sync(self._check_dangerous_operation)(**kwargs):
            return permission_check_result
        return self._run_impl(*args, **kwargs)

async def _arun_with_context(self, *args, **kwargs):
    """Sets the context for the tool. Checks for approved/dangerous operations before executing."""
    with set_node_path(self.node_path):
        if permission_check_result := await self._check_dangerous_operation(**kwargs):
            return permission_check_result
        return await self._arun_impl(*args, **kwargs)
```

Orden de ejecución: **acceso a recursos → node path (trazabilidad) → aprobación humana → cuerpo**.

El `node_path` es un contextvar que identifica jerárquicamente dónde está el agente
(root → tools → subagente → tool), y se usa para el streaming, tracing OTel y para localizar el
`tool_call_id` original:

```python
@property
def node_name(self) -> str:
    return f"max_tool.{self.get_name()}"

@property
def node_path(self) -> tuple[NodePath, ...]:
    return (*self._node_path, NodePath(name=self.node_name))

@property
def _original_tool_call_id(self) -> str | None:
    """Get the original tool_call_id from the AssistantMessage that invoked this tool."""
    if self._node_path:
        # Find the first NodePath with a tool_call_id
        for path in reversed(self._node_path):
            if path.tool_call_id:
                return path.tool_call_id
    return None
```

### 1.7 Control de acceso declarativo

```python
def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
    """
    Declare what resource-level access this tool requires to be used.

    Override this method to specify access requirements for your tool.
    The check runs before `_arun_impl` is called.

    Returns:
        List of (resource, required_level) tuples.
        Empty list means no access control check (default for backward compatibility).

    Examples:
        # Tool that creates feature flags
        return [("feature_flag", "editor")]

        # Tool that reads insights
        return [("insight", "viewer")]

        # Tool that needs multiple permissions
        return [("dashboard", "editor"), ("insight", "viewer")]
    """
    return []

def _check_resource_access(self) -> None:
    """
    Checks all resource-level access requirements declared in `get_required_resource_access()`.
    Raises MaxToolAccessDeniedError if any check fails.
    """
    required_access = self.get_required_resource_access()
    if not required_access:
        return

    for resource, required_level in required_access:
        if not self.user_access_control.check_access_level_for_resource(resource, required_level):
            raise MaxToolAccessDeniedError(resource, required_level, action="use")

async def check_object_access(
    self, obj, required_level: AccessControlLevel, *, resource: str | None = None, action: str = "access",
) -> None:
    """
    Check object-level access for a specific model instance.
    Raises MaxToolAccessDeniedError if user lacks required access.
    """
    has_access = await database_sync_to_async(self.user_access_control.check_access_level_for_object)(
        obj, required_level
    )
    if not has_access:
        resource_name = resource or obj._meta.model_name
        raise MaxToolAccessDeniedError(resource_name, required_level, action=action)
```

Uso en las tools de escritura:

```python
# C:\ph\ee\hogai\tools\create_insight.py
def get_required_resource_access(self):
    """Creating an insight requires editor-level access to insights."""
    return [("insight", "editor")]

# C:\ph\ee\hogai\tools\upsert_dashboard\tool.py
def get_required_resource_access(self):
    return [("dashboard", "editor")]
```

### 1.8 `MaxSubtool`: lógica reutilizable sin exponerla al LLM

No todo lo que ejecuta el agente es una tool visible. `MaxSubtool` es un ejecutor interno,
invocado desde dentro de una `MaxTool`, sin `args_schema` ni `description`:

```python
class MaxSubtool(AssistantDispatcherMixin, ABC):
    _config: RunnableConfig

    def __init__(self, *, team: Team, user: User, state: AssistantState,
                 config: RunnableConfig, context_manager: AssistantContextManager,
                 node_path: tuple[NodePath, ...] | None = None):
        self._team = team
        self._user = user
        self._state = state
        self._context_manager = context_manager
        self._node_path = node_path or get_node_path() or ()

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        pass

    @property
    def node_name(self) -> str:
        return f"max_subtool.{self.__class__.__name__}"
```

Ejemplo: `EntitySearchTool(MaxSubtool)` en
`C:\ph\ee\hogai\tools\full_text_search\tool.py` implementa la búsqueda de entidades y la usa
`SearchTool`; no aparece en el toolset del LLM. Esto mantiene el número de herramientas visibles
bajo (crítico para la precisión del LLM) mientras se reutiliza la lógica.

---

## 2. Validación de argumentos y errores auto-corregibles

### 2.1 `tool_errors.py` — completo y literal

**Fichero:** `C:\ph\ee\hogai\tool_errors.py`

```python
from typing import Literal


class MaxToolError(Exception):
    """
    Base exception for MaxTool failures. All errors produce tool messages visible to LLM but not end users.

    Error Handling Strategy:
    - MaxToolFatalError: Show-stoppers that cannot be recovered from (e.g., permissions, missing config)
    - MaxToolTransientError: Intermittent issues that can be retried without changes (e.g., rate limits, timeouts)
    - MaxToolRetryableError: Solvable issues that can be fixed with adjusted inputs (e.g., invalid parameters)
    - Generic Exception: Unknown failures, treated as fatal (safety net)

    When raising these exceptions, provide actionable context about:
    - What went wrong
    - Why it went wrong (for retryable errors)
    - What can be done about it (for retryable errors)
    """

    def __init__(self, message: str):
        """
        Args:
            message: Detailed, actionable error message that helps the LLM understand what went wrong
        """
        super().__init__(message)

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        """
        Returns the retry strategy for this error:
        - "never": Do not retry (fatal errors)
        - "once": Retry once without changes (transient errors)
        - "adjusted": Retry with adjusted inputs (solvable errors)
        """
        return "never"

    @property
    def retry_hint(self) -> str:
        """
        Returns the retry hint message to append to error messages for the LLM.
        """
        retry_hints = {
            "never": "",
            "once": " You may retry this operation once without changes.",
            "adjusted": " You may retry with adjusted inputs.",
        }
        return retry_hints[self.retry_strategy]

    def to_summary(self, max_length: int = 500) -> str:
        """
        Create a truncated summary for context management.

        Args:
            max_length: Maximum length of the error message before truncation

        Returns:
            Formatted string with exception class name and truncated message
        """
        exception_name = self.__class__.__name__
        exception_msg = str(self).strip()
        if len(exception_msg) > max_length:
            exception_msg = exception_msg[:max_length] + "…"
        return f"{exception_name}: {exception_msg}"


class MaxToolFatalError(MaxToolError):
    """
    Fatal error that cannot be recovered from. Do not retry.
    """

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "never"


class MaxToolTransientError(MaxToolError):
    """
    Transient error due to temporary service issues. Can be retried once without changes.
    """

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "once"


class MaxToolRetryableError(MaxToolError):
    """
    Solvable error that can be fixed with adjusted inputs. Can be retried with corrections.
    """

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "adjusted"


class MaxToolAccessDeniedError(MaxToolFatalError):
    """
    Access denied error when user doesn't have permission to use a tool or access a resource.
    This is a fatal error - the user needs to contact their admin to get access.
    """

    def __init__(
        self,
        resource: str,
        required_level: str,
        action: str = "access",
    ):
        self.resource = resource
        self.required_level = required_level
        self.action = action

        message = f"The user does not have {required_level} access to {action} {resource}s. Suggest the user to contact their project admin to request access."
        super().__init__(message)
```

Tres ideas de diseño:
1. **La taxonomía del error codifica la política de reintento**, no el sitio de la llamada.
   `retry_strategy` es una propiedad de la clase de excepción.
2. **`retry_hint` es lenguaje natural dirigido al LLM.** El agente no ve un código de error, ve
   `"You may retry with adjusted inputs."`.
3. **`to_summary(max_length=500)` trunca para gestión de contexto.** Un stacktrace de 20 KB de una
   base de datos no debe comerse la ventana de contexto.

Además, `MaxToolAccessDeniedError` incluye la **acción remediadora dirigida al usuario final**
dentro del mensaje al LLM: *"Suggest the user to contact their project admin"*. El LLM traduce el
error de permisos a una recomendación accionable en vez de decir "error 403".

### 2.2 El bucle que atrapa los errores y realimenta al LLM

**Fichero:** `C:\ph\ee\hogai\core\agent_modes\executables.py`, clase `AgentToolsExecutable`.

Este es el corazón: el nodo del grafo que invoca la tool y convierte cualquier fallo en un
`AssistantToolCallMessage` que vuelve al LLM.

```python
# Tool doesn't exist -> tell the LLM instead of crashing
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

# Tricky: set the node path associated with the tool call
tool.set_node_path(
    (
        *self.node_path[:-1],
        NodePath(name=AssistantNodeName.ROOT_TOOLS, message_id=tool_call_message.id, tool_call_id=tool_call.id),
    )
)

try:
    tool_span_attributes: dict[str, str | int] = {
        "posthog_ai.tool_name": tool_call.name,
        "posthog_ai.team_id": self._team.id,
    }
    if tool_call.id is not None:
        tool_span_attributes["posthog_ai.tool_call_id"] = tool_call.id
    with _tracer.start_as_current_span("posthog_ai.tool.invoke", attributes=tool_span_attributes):
        result = await tool.ainvoke(
            ToolCall(type="tool_call", name=tool_call.name, args=tool_call.args, id=tool_call.id),
            config=config,
        )
        # Keep the type-mismatch raise inside the span so OTel records the exception
        # on the tool.invoke span rather than on its (unrelated) parent.
        if not isinstance(result, LangchainToolMessage):
            raise ValueError(
                f"Tool '{tool_call.name}' returned {type(result).__name__}, expected LangchainToolMessage"
            )

    # Track successful tool execution
    user_distinct_id = self._get_user_distinct_id(config)
    if user_distinct_id:
        with _tracer.start_as_current_span("posthoganalytics.capture"):
            await database_sync_to_async(posthoganalytics.capture)(
                distinct_id=user_distinct_id,
                event="ai tool executed",
                properties={**self._get_debug_props(config), "tool_name": tool_call.name},
                groups=groups(None, self._team),
                send_feature_flags=True,
            )
except MaxToolError as e:
    logger.exception(
        "maxtool_error", extra={"tool": tool_call.name, "error": str(e), "retry_strategy": e.retry_strategy}
    )
    user_distinct_id = self._get_user_distinct_id(config)
    capture_exception(
        e,
        distinct_id=user_distinct_id,
        properties={
            **self._get_debug_props(config),
            "tool": tool_call.name,
            "retry_strategy": e.retry_strategy,
        },
    )

    if user_distinct_id:
        posthoganalytics.capture(
            distinct_id=user_distinct_id,
            event="max_tool_error",
            properties={
                **self._get_debug_props(config),
                "tool_name": tool_call.name,
                "error_type": e.__class__.__name__,
                "retry_strategy": e.retry_strategy,
                "error_message": str(e),
            },
            groups=groups(None, self._team),
        )

    content = f"Tool failed: {e.to_summary()}.{e.retry_hint}"
    return PartialAssistantState(
        messages=[
            AssistantToolCallMessage(
                content=content,
                id=str(uuid4()),
                tool_call_id=tool_call.id,
            )
        ],
    )
except ValidationError as e:
    logger.exception("Validation error calling tool", extra={"tool_name": tool_call.name, "error": str(e)})
    capture_exception(
        e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
    )
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
    logger.exception("Error calling tool", extra={"tool_name": tool_call.name, "error": str(e)})
    capture_exception(
        e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
    )
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

Cuatro capas de captura, en orden de especificidad:

| Excepción | Mensaje al LLM |
|---|---|
| `MaxToolError` | `Tool failed: {ClassName}: {msg truncado}.{retry_hint}` |
| `ValidationError` (Pydantic) | `There was a validation error calling the tool: {errores completos de Pydantic}` |
| `GraphInterrupt` | Re-lanzada — es el flujo de aprobación, no un fallo |
| `Exception` | Mensaje genérico **con instrucción explícita de no reintentar automáticamente** |

El caso `ValidationError` merece destacarse: **el mensaje de error de Pydantic se pasa íntegro al
LLM**. Pydantic ya produce errores estructurados de altísima calidad (`field required`,
`Input should be one of: 'trends', 'funnel', 'retention'`, con la ruta al campo), y los LLMs
modernos se auto-corrigen con ellos de forma muy fiable. No hay que traducirlos.

El caso genérico también es notable: en lugar de callar, el prompt del error **instruye al agente
sobre política de reintento** (`Do not immediately retry ... If the user asks you to retry, you are
allowed to do that`) — evita bucles infinitos de fallo pero deja la puerta abierta a la iniciativa
del usuario.

### 2.3 Errores lanzados vs errores devueltos

Hay dos convenciones distintas y conscientes:

**(a) Lanzar `MaxToolError`** — para fallos que requieren la maquinaria de telemetría/reintentos:

```python
# C:\ph\ee\hogai\tools\read_taxonomy\tool.py
def _run_impl(self, query: dict[str, Any]) -> tuple[str, Any]:
    # Langchain can't parse a dynamically created Pydantic model, so we need to additionally validate the query here.
    try:
        validated_query = ReadTaxonomyToolArgs(query=query).query
    except ValidationError as e:
        raise MaxToolRetryableError(str(e))

    toolkit = TaxonomyAgentToolkit(self._team, self._user)

    try:
        res = execute_taxonomy_query(validated_query, toolkit, self._team, self._user)
    except ValueError as e:
        raise MaxToolRetryableError(str(e))

    return res, None
```

```python
# C:\ph\ee\hogai\tools\upsert_dashboard\tool.py
missing_ids = [insight_id for insight_id, artifact in zip(action.insight_ids, artifacts) if artifact is None]
if missing_ids:
    raise MaxToolRetryableError(format_prompt_string(MISSING_INSIGHT_IDS_PROMPT, missing_ids=missing_ids))
```

**(b) Devolver `(mensaje_de_error, None)`** — para errores de *dominio* previstos, que forman parte
del flujo normal de conversación y no son incidencias:

```python
# C:\ph\ee\hogai\tools\create_notebook\tool.py
if content is not None and draft_content is not None:
    return "Error: Cannot provide both 'content' and 'draft_content'. Use exactly one.", None

if content is None and draft_content is None:
    return "Error: Either 'content' or 'draft_content' must be provided.", None
```

```python
# C:\ph\ee\hogai\tools\execute_sql\tool.py
try:
    await self._quality_check_output(output=parsed_query)
except PydanticOutputParserException as e:
    return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), None
...
try:
    result = await insight_context.execute_and_format()
except MaxToolRetryableError as e:
    return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), None
except Exception:
    return EXECUTE_SQL_UNRECOVERABLE_ERROR_PROMPT, None
```

**Heurística: si es un fallo que quieres ver en tu dashboard de errores, lánzalo; si es una rama
esperada del diálogo, devuélvelo.** Ambos llegan al LLM como texto; la diferencia es telemetría.

### 2.4 Errores como prompts, no como strings

Los mensajes de error importantes se guardan en `prompts.py` con `<system_reminder>` para dirigir
el comportamiento del agente tras el fallo:

```python
# C:\ph\ee\hogai\tools\create_insight.py
INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT = """
<system_reminder>
Inform the user that you've encountered an error during the creation of the insight. Afterwards, try to generate a new insight with a different query.
Terminate if the error persists.
</system_reminder>
""".strip()

INSIGHT_TOOL_HANDLED_FAILURE_PROMPT = """
The agent has encountered the error while creating an insight.

Generated output:
```
{{{output}}}
```

Error message:
```
{{{error_message}}}
```

{{{system_reminder}}}
""".strip()

INSIGHT_TOOL_UNHANDLED_FAILURE_PROMPT = """
The agent has encountered an unknown error while creating an insight.
{{{system_reminder}}}
""".strip()
```

Y el uso:

```python
try:
    dict_state = await graph.ainvoke(new_state)
except SchemaGenerationException as e:
    return format_prompt_string(
        INSIGHT_TOOL_HANDLED_FAILURE_PROMPT,
        output=e.llm_output,
        error_message=e.validation_message,
        system_reminder=INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT,
    ), None
```

Fíjate en que **se devuelve al LLM tanto el output que generó como el mensaje de validación**.
Sin el output, el modelo no puede razonar sobre qué escribió mal. Este par
(*lo que produjiste* + *por qué falló* + *qué hacer ahora*) es la receta completa de la
auto-corrección.

---

## 3. El sistema de artefactos

Un **artefacto** es un objeto persistido, con ID estable, que (a) el usuario ve renderizado en la
UI, (b) el agente puede referenciar en turnos posteriores, y (c) puede componerse dentro de otros
artefactos. Es la diferencia entre "el agente te describe un gráfico" y "el agente crea un gráfico
que existe".

### 3.1 `types.py` — completo y literal

**Fichero:** `C:\ph\ee\hogai\artifacts\types.py`

```python
"""Shared type definitions for artifact system."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from posthog.schema import (
    ArtifactSource,
    ErrorBlock,
    LoadingBlock,
    MarkdownBlock,
    NotebookArtifactContent,
    SessionReplayBlock,
    VisualizationArtifactContent,
    VisualizationBlock,
)

from products.product_analytics.backend.models.insight import Insight


class VisualizationRefBlock(BaseModel):
    """Reference to a visualization artifact - stored in DB, enriched to VisualizationBlock when streaming."""

    type: Literal["visualization_ref"] = "visualization_ref"
    artifact_id: str
    title: str | None = None


# Type alias for blocks that can be stored in a notebook artifact
StoredBlock = MarkdownBlock | VisualizationRefBlock | SessionReplayBlock | LoadingBlock

# Type alias for enriched blocks (after resolving refs)
EnrichedBlock = MarkdownBlock | VisualizationBlock | SessionReplayBlock | LoadingBlock | ErrorBlock


class StoredNotebookArtifactContent(BaseModel):
    """Notebook content as stored in the database - contains ref blocks that need enrichment."""

    content_type: Literal["notebook"] = "notebook"
    blocks: list[StoredBlock]
    title: str | None = None


# Content types for storage (includes StoredNotebookArtifactContent with ref blocks)
StoredContent = VisualizationArtifactContent | StoredNotebookArtifactContent

# Content types for streaming to frontend (enriched, no ref blocks)
ArtifactContent = VisualizationArtifactContent | NotebookArtifactContent


ContentT = TypeVar("ContentT", bound=ArtifactContent)

# Generic type vars for result wrappers (using StoredContent as bound to support notebooks)
T = TypeVar("T", bound=StoredContent)
S = TypeVar("S", bound=ArtifactSource)
M = TypeVar("M")


class StateArtifactResult(BaseModel, Generic[T]):
    source: Literal[ArtifactSource.STATE] = ArtifactSource.STATE
    content: T


class DatabaseArtifactResult(BaseModel, Generic[T]):
    source: Literal[ArtifactSource.ARTIFACT] = ArtifactSource.ARTIFACT
    content: T


class ModelArtifactResult(BaseModel, Generic[T, S, M]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    source: S
    content: T
    model: M


# Result type for visualization artifacts (can come from state, database, or saved insights)
VisualizationWithSourceResult = (
    StateArtifactResult[VisualizationArtifactContent]
    | DatabaseArtifactResult[VisualizationArtifactContent]
    | ModelArtifactResult[VisualizationArtifactContent, Literal[ArtifactSource.INSIGHT], Insight]
)

# Result type for notebook artifacts (can only come from database)
NotebookWithSourceResult = DatabaseArtifactResult[StoredNotebookArtifactContent]

# Generic result type for any artifact
ArtifactWithSourceResult = VisualizationWithSourceResult | NotebookWithSourceResult
```

**Las dos distinciones centrales:**

1. **`StoredContent` vs `ArtifactContent`** — lo que se guarda ≠ lo que se envía a la UI. El
   notebook guarda `VisualizationRefBlock` (una referencia con `artifact_id`); al hacer streaming
   se resuelve a `VisualizationBlock` (con la query completa). Esto significa: **si actualizas un
   gráfico, todos los documentos que lo referencian se actualizan automáticamente.** No hay copias
   desincronizadas.

2. **`ArtifactSource`** — un mismo `artifact_id` puede resolverse desde tres orígenes distintos:
   `STATE` (efímero, en memoria en la conversación), `ARTIFACT` (fila en `AgentArtifact`) o
   `INSIGHT` (entidad de producto guardada). El agente usa el mismo ID en los tres casos; la
   resolución de origen es transparente.

### 3.2 `manager.py` — completo y literal

**Fichero:** `C:\ph\ee\hogai\artifacts\manager.py`

```python
from collections.abc import Sequence
from typing import Literal, cast, overload
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import ArtifactContentType, ArtifactMessage, ArtifactSource, VisualizationMessage

from posthog.models import User
from posthog.models.team import Team

from products.posthog_ai.backend.models.assistant import AgentArtifact

from ee.hogai.artifacts.handlers import (
    EnrichmentContext,
    NotebookArtifactManagerMixin,
    VisualizationArtifactManagerMixin,
    get_handler_for_content_class,
    get_handler_for_content_type,
    get_handler_for_db_type,
)
from ee.hogai.artifacts.types import ArtifactContent, ContentT, StoredContent
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantMessageUnion


class ArtifactManager(
    VisualizationArtifactManagerMixin,
    NotebookArtifactManagerMixin,
    AssistantContextMixin,
):
    """
    Manages creation and retrieval of agent artifacts.
    """

    def __init__(self, team: Team, user: User, config: RunnableConfig | None = None):
        self._team = team
        self._user = user
        self._config = config or {}

    # -------------------------------------------------------------------------
    # Creation
    # -------------------------------------------------------------------------

    def create_message(
        self,
        artifact_id: str,
        source: ArtifactSource = ArtifactSource.ARTIFACT,
        content_type: ArtifactContentType = ArtifactContentType.VISUALIZATION,
    ) -> ArtifactRefMessage:
        """Create an artifact message."""
        return ArtifactRefMessage(
            content_type=content_type,
            artifact_id=artifact_id,
            source=source,
            id=str(uuid4()),
        )

    async def acreate(
        self,
        content: StoredContent,
        name: str,
    ) -> AgentArtifact:
        """Create and persist an artifact."""
        if not self._config:
            raise ValueError("Config is required")

        conversation = await self._aget_conversation(cast(UUID, self._get_thread_id(self._config)))

        if conversation is None:
            raise ValueError("Conversation not found")

        db_type = self._get_db_type_for_content(content)

        artifact = AgentArtifact(
            name=name[:400],
            type=db_type,
            data=content.model_dump(mode="json", exclude_none=True),
            conversation=conversation,
            team=self._team,
        )
        await artifact.asave()

        return artifact

    async def aupdate(
        self,
        artifact_id: str,
        content: StoredContent,
    ) -> AgentArtifact:
        """Update an existing artifact."""
        try:
            artifact = await AgentArtifact.objects.aget(short_id=artifact_id, team=self._team)
        except AgentArtifact.DoesNotExist:
            raise ValueError(f"Artifact with short_id={artifact_id} not found")
        artifact.data = content.model_dump(mode="json", exclude_none=True)
        await artifact.asave()
        return artifact

    # -------------------------------------------------------------------------
    # Content retrieval
    # -------------------------------------------------------------------------

    @overload
    async def aget(self, artifact_id: str, expected_type: type[ContentT]) -> ContentT: ...

    @overload
    async def aget(self, artifact_id: str, expected_type: None = None) -> ArtifactContent: ...

    async def aget(self, artifact_id: str, expected_type: type[ContentT] | None = None) -> ArtifactContent | ContentT:
        """Retrieve artifact content by ID from the database.

        Args:
            artifact_id: The artifact's short ID.
            expected_type: Optional content class to validate and narrow the return type.
                          If provided, raises TypeError if the content doesn't match.

        Returns:
            The artifact content, narrowed to expected_type if provided.

        Raises:
            AgentArtifact.DoesNotExist: If artifact not found.
            TypeError: If expected_type provided but content doesn't match.
        """
        stored_contents = await self._afetch_artifact_contents([artifact_id])
        stored_content = stored_contents.get(artifact_id)
        if stored_content is None:
            raise AgentArtifact.DoesNotExist(f"Artifact with id={artifact_id} not found")

        # Use handler for enrichment (generic for all types)
        handler = get_handler_for_content_class(type(stored_content))
        context = EnrichmentContext(team=self._team, artifact_id=artifact_id)
        content: ArtifactContent = await handler.aenrich(stored_content, context)

        if expected_type is not None and not isinstance(content, expected_type):
            raise TypeError(
                f"Expected content type={expected_type.__name__}, got content type={type(content).__name__}"
            )
        return cast(ContentT, content) if expected_type else content

    async def aenrich_message(
        self,
        message: ArtifactRefMessage,
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> ArtifactMessage | None:
        """
        Convert an artifact ref message to an enriched artifact message with content.
        Fetches content based on source: State (from messages), Artifact (from DB), or Insight (from DB).
        """
        # Handle visualization artifacts
        if message.source == ArtifactSource.STATE:
            if state_messages is None:
                raise ValueError("state_messages required for State source")
            messages_for_lookup: Sequence[AssistantMessageUnion] = state_messages
        else:
            messages_for_lookup = [message]

        contents = await self._aget_contents_by_id(messages_for_lookup, aggregate_by="message_id")
        content = contents.get(message.id or "")

        if content is None:
            return None

        return self._to_artifact_message(message, content)

    async def aenrich_messages(
        self, messages: Sequence[AssistantMessageUnion], artifacts_only: bool = False
    ) -> list[AssistantMessageUnion | ArtifactMessage]:
        """
        Enrich state messages with artifact content.
        """
        contents_by_id = await self._aget_contents_by_id(messages, aggregate_by="message_id")

        result: list[AssistantMessageUnion | ArtifactMessage] = []
        for message in messages:
            if isinstance(message, ArtifactRefMessage):
                content = contents_by_id.get(message.id or "")
                if content:
                    result.append(self._to_artifact_message(message, content))
            elif not isinstance(message, VisualizationMessage) and not artifacts_only:
                # Pass through non-artifact messages, but skip VisualizationMessage (they are already filtered in the state, just a precaution)
                result.append(message)

        return result

    async def aget_conversation_artifacts(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[ArtifactMessage], int]:
        """Get all artifacts created in a conversation, by the agent and subagents."""
        offset = offset or 0
        conversation_id = cast(UUID, self._get_thread_id(self._config))
        artifacts = AgentArtifact.objects.filter(team=self._team, conversation_id=conversation_id)
        count = await artifacts.acount()

        if limit:
            artifacts = artifacts[offset : offset + limit]
        elif offset:
            artifacts = artifacts[offset:]

        result: list[ArtifactMessage] = []
        async for artifact in artifacts:
            artifact_type = cast(AgentArtifact.Type, artifact.type)
            handler = get_handler_for_db_type(artifact_type)
            if handler is None:
                continue

            stored_content = handler.validate(artifact.data)

            # Use handler for enrichment (generic for all types)
            context = EnrichmentContext(team=self._team, artifact_id=artifact.short_id)
            content: ArtifactContent = await handler.aenrich(stored_content, context)

            result.append(
                ArtifactMessage(
                    id=artifact.short_id,
                    artifact_id=artifact.short_id,
                    source=ArtifactSource.ARTIFACT,
                    content=content,
                )
            )
        return result, count

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _get_db_type_for_content(self, content: StoredContent) -> AgentArtifact.Type:
        """Get the database type for a content object using handlers."""
        handler = get_handler_for_content_class(type(content))
        return handler.db_type

    def _to_artifact_message(self, message: ArtifactRefMessage, content: ArtifactContent) -> ArtifactMessage:
        """Convert an ArtifactRefMessage to an ArtifactMessage."""
        return ArtifactMessage(
            id=message.id,
            artifact_id=message.artifact_id,
            source=message.source,
            content=content,
        )

    async def _afetch_artifact_contents(self, artifact_ids: list[str]) -> dict[str, StoredContent]:
        """Batch fetch artifact contents from the database."""
        if not artifact_ids:
            return {}
        artifacts = AgentArtifact.objects.filter(short_id__in=artifact_ids, team=self._team)
        result: dict[str, StoredContent] = {}
        async for artifact in artifacts:
            artifact_type = cast(AgentArtifact.Type, artifact.type)
            handler = get_handler_for_db_type(artifact_type)
            if handler is None:
                continue
            result[artifact.short_id] = handler.validate(artifact.data)
        return result

    async def _aget_contents_by_id(
        self,
        messages: Sequence[AssistantMessageUnion],
        aggregate_by: Literal["message_id", "artifact_id"] = "message_id",
        filter_by_artifact_ids: list[str] | None = None,
    ) -> dict[str, ArtifactContent]:
        """
        Get artifact content for all artifact messages, keyed by aggregation ID.

        Delegates to handlers which know how to fetch from their supported sources.
        Contents are enriched via handler's enrich method.

        Args:
            messages: The messages to scan for artifact references.
            aggregate_by: How to key results - "message_id" or "artifact_id".
            filter_by_artifact_ids: If provided, only return contents for these artifact IDs.

        Returns:
            Dict mapping aggregation IDs to their artifact content.
        """
        filter_set = set(filter_by_artifact_ids) if filter_by_artifact_ids else None

        # Group messages by content_type, tracking aggregation IDs
        ids_by_content_type: dict[ArtifactContentType, list[str]] = {}
        aggregation_map: dict[str, str] = {}  # artifact_id -> aggregation_id

        for message in messages:
            if not isinstance(message, ArtifactRefMessage) or not message.id:
                continue
            if filter_set and message.artifact_id not in filter_set:
                continue

            aggregation_id = message.id if aggregate_by == "message_id" else message.artifact_id
            aggregation_map[message.artifact_id] = aggregation_id

            if message.content_type not in ids_by_content_type:
                ids_by_content_type[message.content_type] = []
            ids_by_content_type[message.content_type].append(message.artifact_id)

        # Fetch and enrich using handlers
        result: dict[str, ArtifactContent] = {}

        for content_type, artifact_ids in ids_by_content_type.items():
            handler = get_handler_for_content_type(content_type)
            if handler is None:
                continue

            fetch_results = await handler.alist(self._team, artifact_ids, messages)

            for artifact_id, fetch_result in zip(artifact_ids, fetch_results):
                if fetch_result is None:
                    continue
                enrich_ctx = EnrichmentContext(team=self._team, state_messages=messages, artifact_id=artifact_id)
                enriched: ArtifactContent = await handler.aenrich(fetch_result.content, enrich_ctx)
                agg_id = aggregation_map.get(artifact_id)
                if agg_id is not None:
                    result[agg_id] = enriched

        return result
```

Observaciones de diseño:
- El artefacto se ancla a la **conversación** (`conversation=conversation`) además del tenant.
  Esto da gratis `aget_conversation_artifacts()`: "todo lo que este agente ha producido en esta
  sesión", paginable.
- `data` es un `JSONField` con `content.model_dump(mode="json", exclude_none=True)`. El esquema
  vive en Pydantic, no en columnas SQL. Evolucionar el esquema de un artefacto no requiere
  migración.
- `_aget_contents_by_id` **agrupa por tipo y hace fetch en lote** (`short_id__in=[...]`). Con un
  notebook que referencia 15 gráficos, es 1 query, no 15.
- `aget()` usa `@overload` para que `aget(id, VisualizationArtifactContent)` devuelva el tipo
  estrecho — el type checker atrapa el error de tipo de artefacto en tiempo de desarrollo.

### 3.3 El registro de handlers

**Fichero:** `C:\ph\ee\hogai\artifacts\handlers\base.py`

```python
@dataclass
class EnrichmentContext:
    """Context passed to handlers during enrichment."""

    team: Team
    state_messages: Sequence[AssistantMessageUnion] | None = None
    artifact_id: str | None = None


class ArtifactHandler(ABC, Generic[T_Stored, T_Enriched]):
    """
    Base class for artifact type handlers.

    Each artifact type (visualization, notebook, etc.) has a handler that:
    - Declares which sources it supports (STATE, ARTIFACT, INSIGHT)
    - Knows how to fetch from each source
    - Handles enrichment (e.g., resolving refs to full content)
    """

    # Type metadata - subclasses must define these
    content_class: type[T_Stored]
    enriched_class: type[T_Enriched]
    db_type: AgentArtifact.Type
    content_type: ArtifactContentType

    @abstractmethod
    async def alist(
        self, team: Team, ids: list[str], state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> list[Any]:
        """
        Fetch content by IDs with source tracking.

        Returns:
            Ordered list matching input IDs (None for missing artifacts).
            Each handler returns its specific result wrapper type.
        """
        ...

    @abstractmethod
    async def aenrich(self, content: T_Stored, context: EnrichmentContext) -> T_Enriched:
        """
        Transform stored content to enriched content for streaming.

        For types where stored == enriched (e.g., visualizations), this is a no-op.
        For types with refs (e.g., notebooks), this resolves refs to full content.
        """
        ...

    def validate(self, data: dict) -> T_Stored:
        """
        Validate and parse raw data into content model.
        """
        return self.content_class.model_validate(data)

    @abstractmethod
    def get_metadata(self, content: T_Stored) -> dict[str, Any]:
        """
        Extract display metadata from artifact content.

        Returns dict with type-specific fields for display (e.g., name, description, title).
        """
        ...


# Single registry mapping content class -> handler instance
HANDLER_REGISTRY: dict[type, ArtifactHandler] = {}


def register_handler(handler_class: type[T_Handler]) -> type[T_Handler]:
    """
    Class decorator to register a handler.

    Usage:
        @register_handler
        class VisualizationHandler(ArtifactHandler[...]):
            ...
    """
    instance = handler_class()
    HANDLER_REGISTRY[instance.content_class] = instance
    return handler_class


def get_handler_for_content_class(content_class: type) -> ArtifactHandler:
    """Get handler for a content class."""
    handler = HANDLER_REGISTRY.get(content_class)
    if handler is None:
        raise ValueError(f"Unknown content type={content_class.__name__}")
    return handler


def get_handler_for_db_type(db_type: AgentArtifact.Type) -> ArtifactHandler | None:
    """Get handler for a database type (iterates registry - only 2 handlers)."""
    for handler in HANDLER_REGISTRY.values():
        if handler.db_type == db_type:
            return handler
    return None


def get_handler_for_content_type(content_type: ArtifactContentType) -> ArtifactHandler | None:
    """Get handler for a content type enum (iterates registry - only 2 handlers)."""
    for handler in HANDLER_REGISTRY.values():
        if handler.content_type == content_type:
            return handler
    return None
```

El `ArtifactManager` no sabe nada de visualizaciones ni notebooks: sólo consulta el registro.
Añadir un tipo de artefacto nuevo = escribir un handler y decorarlo con `@register_handler`.

### 3.4 Handler con resolución de referencias (composición)

**Fichero:** `C:\ph\ee\hogai\artifacts\handlers\notebook.py` — el ejemplo interesante, porque
**un notebook contiene visualizaciones por referencia**:

```python
@register_handler
class NotebookHandler(ArtifactHandler[StoredNotebookArtifactContent, NotebookArtifactContent]):
    """
    Handler for notebook artifacts.

    Notebooks are only stored in the ARTIFACT source (AgentArtifact table).
    They contain VisualizationRefBlock references that need to be enriched
    to full VisualizationBlock content when streaming.
    """

    content_class = StoredNotebookArtifactContent
    enriched_class = NotebookArtifactContent
    db_type = AgentArtifact.Type.NOTEBOOK
    content_type = ArtifactContentType.NOTEBOOK

    async def aenrich(
        self,
        content: StoredNotebookArtifactContent,
        context: EnrichmentContext,
    ) -> NotebookArtifactContent:
        """
        Enrich notebook by resolving VisualizationRefBlock references.

        Converts VisualizationRefBlock → VisualizationBlock (with full query data)
        or ErrorBlock (if artifact not found).
        """
        # Collect all artifact IDs from VisualizationRefBlock
        viz_ids = [block.artifact_id for block in content.blocks if isinstance(block, VisualizationRefBlock)]

        # Fetch visualization contents using the visualization handler
        viz_contents = await self._list_visualization_contents(viz_ids, context.team, context.state_messages)

        # Build enriched blocks
        enriched_blocks: list[EnrichedBlock] = []
        for block in content.blocks:
            if isinstance(block, VisualizationRefBlock):
                viz_content = viz_contents.get(block.artifact_id)
                if viz_content is None:
                    # Artifact not found - generate error block
                    enriched_blocks.append(
                        ErrorBlock(
                            message=f"Visualization not found: {block.artifact_id}",
                            artifact_id=block.artifact_id,
                        )
                    )
                elif not is_supported_query(viz_content.query):
                    # Query type not supported for rendering
                    enriched_blocks.append(
                        ErrorBlock(
                            message=f"Unsupported query type: {type(viz_content.query).__name__}",
                            artifact_id=block.artifact_id,
                        )
                    )
                else:
                    # Valid visualization - cast is safe now after runtime validation
                    enriched_blocks.append(
                        VisualizationBlock(
                            query=cast(Any, viz_content.query),
                            title=block.title or viz_content.name,
                        )
                    )
            else:
                # Pass through other block types unchanged
                enriched_blocks.append(block)

        is_saved = False
        if context.artifact_id:
            is_saved = await notebooks.anotebook_exists(context.team.id, context.artifact_id)

        return NotebookArtifactContent(
            blocks=enriched_blocks,
            title=content.title,
            is_saved=is_saved,
        )
```

**El patrón de degradación elegante es clave**: una referencia rota no rompe el documento, se
convierte en un `ErrorBlock` renderizable. El usuario ve "Visualization not found: abc123" en su
sitio, y el resto del informe sigue funcionando. En un agente de vídeo, esto es exactamente lo que
quieres cuando un shot de un timeline apunta a un clip que falló al generarse.

### 3.5 Handler multi-origen

**Fichero:** `C:\ph\ee\hogai\artifacts\handlers\visualization.py`

```python
@register_handler
class VisualizationHandler(ArtifactHandler[VisualizationArtifactContent, VisualizationArtifactContent]):
    """
    Handler for visualization artifacts.

    Visualizations can come from three sources:
    - STATE: In-memory VisualizationMessage in conversation state
    - ARTIFACT: Saved in AgentArtifact table
    - INSIGHT: Saved as Insight model

    No enrichment needed - stored content is already in final form.
    """

    content_class = VisualizationArtifactContent
    enriched_class = VisualizationArtifactContent  # Same, no enrichment
    db_type = AgentArtifact.Type.VISUALIZATION
    content_type = ArtifactContentType.VISUALIZATION

    async def alist(
        self, team: Team, ids: list[str], state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> list[VisualizationWithSourceResult | None]:
        """
        Fetch visualizations with source tracking and Insight models.

        Returns ordered list matching input IDs (None for missing IDs).
        """
        if not ids:
            return []

        results_map: dict[str, VisualizationWithSourceResult] = {}
        remaining = set(ids)

        # 1. Check state messages first
        if state_messages:
            for artifact_id in list(remaining):
                content = self._from_state(artifact_id, state_messages)
                if content is not None:
                    results_map[artifact_id] = StateArtifactResult(content=content)
                    remaining.discard(artifact_id)

        # 2. Check artifact DB
        if remaining:
            db_contents = await self._from_db(list(remaining), team)
            for artifact_id, content in db_contents.items():
                results_map[artifact_id] = DatabaseArtifactResult(content=content)
                remaining.discard(artifact_id)

        # 3. Check insights table - get both content AND model in single query
        if remaining:
            insight_results = await self._from_insights_with_models(list(remaining), team)
            for artifact_id, (content, model) in insight_results.items():
                results_map[artifact_id] = ModelArtifactResult(
                    source=ArtifactSource.INSIGHT,
                    content=content,
                    model=model,
                )

        # Return ordered list matching input
        return [results_map.get(artifact_id) for artifact_id in ids]

    async def aenrich(self, content, context) -> VisualizationArtifactContent:
        """No enrichment needed for visualizations."""
        return content

    def get_metadata(self, content: VisualizationArtifactContent) -> dict[str, Any]:
        return {"name": content.name, "description": content.description}
```

Cascada de resolución con eliminación progresiva (`remaining`): estado en memoria → artefactos de
la conversación → entidades guardadas del producto. **El coste es proporcional a lo que no se
encuentra en el nivel más barato.**

### 3.6 Cómo una tool produce un artefacto: el flujo completo

Tres piezas: `ToolMessagesArtifact`, `ArtifactRefMessage` y el retorno `(content, artifact)`.

```python
# C:\ph\ee\hogai\tool.py
class ToolMessagesArtifact(BaseModel):
    """Return messages directly. Use with `artifact`."""

    messages: Sequence[AssistantMessageUnion]
```

Ejemplo canónico — `ExecuteSQLTool` (`C:\ph\ee\hogai\tools\execute_sql\tool.py`):

```python
# Display an ephemeral visualization message to the user.
artifact = await self._context_manager.artifacts.acreate(
    VisualizationArtifactContent(query=artifact_query, name=viz_title, description=viz_description),
    "SQL Query",
)
artifact_message = self._context_manager.artifacts.create_message(
    artifact_id=artifact.short_id,
    source=ArtifactSource.ARTIFACT,
    content_type=ArtifactContentType.VISUALIZATION,
)

insight_context = InsightContext(
    team=self._team,
    query=artifact_query,
    name=viz_title,
    description=viz_description,
    insight_id=artifact_message.artifact_id,
    user=self._user,
)

try:
    result = await insight_context.execute_and_format()
except MaxToolRetryableError as e:
    return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), None
except Exception:
    return EXECUTE_SQL_UNRECOVERABLE_ERROR_PROMPT, None

tool_payload: str | dict[str, object]
if display or chart_settings:
    # Full node so the SQL editor can adopt the visualization settings, not just the SQL
    tool_payload = artifact_query.model_dump(mode="json", exclude_none=True)
elif filters is not None:
    tool_payload = source_query.model_dump(mode="json", exclude_none=True)
else:
    tool_payload = artifact_query.source.query

return "", ToolMessagesArtifact(
    messages=[
        artifact_message,
        AssistantToolCallMessage(
            content=result,
            id=str(uuid4()),
            tool_call_id=self.tool_call_id,
            ui_payload={self.get_name(): tool_payload},
        ),
    ]
)
```

Analicemos el retorno, que es sutil pero crucial:

- **`content = ""`** (string vacío). Cuando se devuelve un `ToolMessagesArtifact`, el ejecutor
  descarta el content y usa los mensajes tal cual.
- **`messages[0] = artifact_message`** — un `ArtifactRefMessage`: sólo un puntero
  (`artifact_id`, `source`, `content_type`). La UI lo hidrata; el LLM ve un ID corto.
- **`messages[1] = AssistantToolCallMessage`** — lo que el LLM lee (`content=result`, la tabla de
  resultados formateada) más `ui_payload`, que es un canal lateral **sólo para el frontend**
  (aquí: la query completa, para que el editor SQL del usuario la adopte).

**La separación `content` / `ui_payload` es el patrón clave de todo el sistema.** El LLM recibe una
representación textual barata; el frontend recibe la estructura completa. Nunca metes 40 KB de JSON
en la ventana de contexto para que el usuario vea un gráfico.

El ejecutor lo desempaqueta así (`C:\ph\ee\hogai\core\agent_modes\executables.py`):

```python
if isinstance(result.artifact, ToolMessagesArtifact):
    return PartialAssistantState(
        messages=list(result.artifact.messages),
    )

tool_message = AssistantToolCallMessage(
    content=str(result.content) if result.content else "",
    ui_payload={tool_call.name: result.artifact},
    id=str(uuid4()),
    tool_call_id=tool_call.id,
)
```

Es decir: **una tool tiene dos modos de retorno**. `(content, dict)` para el caso simple
(el dict va a `ui_payload` bajo la clave del nombre de la tool), o
`("", ToolMessagesArtifact(...))` para control total sobre los mensajes emitidos.

### 3.7 Referenciar artefactos: el ciclo se cierra

El notebook referencia gráficos con una sintaxis de etiqueta que el LLM escribe en markdown:

```
# How to use the <insight>insight_id</insight> tag:
You can use the <insight>insight_id</insight> tag to reference existing visualization insights.
Use the list_data tool with kind=artifacts to retrieve artifact ids, when in doubt.
```

Y el agente descubre qué artefactos existen mediante `read_data`/`list_data`:

```python
case ReadArtifact() as schema:
    return await self._read_artifact(schema.artifact_id), None
```

**Bucle completo:** `execute_sql` crea un artefacto → devuelve `artifact_id` en el mensaje →
el LLM lo tiene en su contexto → `create_notebook` lo incrusta con `<insight>abc123</insight>` →
`NotebookHandler.aenrich` lo resuelve al renderizar. Y si el agente pierde el ID,
`list_data kind=artifacts` se lo devuelve.

Esto es **exactamente** el mecanismo que necesitas para "genera 8 imágenes → móntalas en un
timeline → re-renderiza el timeline cuando regeneres la imagen 3".

---

## 4. Escritura vs lectura, confirmaciones, idempotencia

### 4.1 Clasificación observada

| Tipo | Ejemplos | Access control | Aprobación | Artefacto |
|---|---|---|---|---|
| **Lectura pura** | `read_taxonomy`, `read_data`, `search`, `list_data` | ninguno o `viewer` | no | no |
| **Lectura + efímero** | `execute_sql` | no | no | sí (transitorio) |
| **Escritura transitoria** | `create_notebook` (default) | no | no | sí (sólo conversación) |
| **Escritura persistente** | `create_insight`, `upsert_dashboard`, `create_notebook(save_to_notebook=True)` | `editor` | condicional | sí (persistido) |
| **Punto de control** | `finalize_plan` | no | **siempre** | sí |

**El gradiente transitorio→persistente es el patrón más transferible.** Por defecto, la salida
del agente es un artefacto efímero visible sólo en la conversación; sólo se persiste si el usuario
lo pide explícitamente:

```
# Transient vs saved notebooks:
- By default, notebooks are created as transient artifacts visible only in this conversation. Do NOT share URLs or references to notebook pages for transient artifacts.
- Set save_to_notebook=True ONLY when the user explicitly asks to save, persist, or create a permanent notebook.
- When updating an artifact that is already saved to the database, the saved notebook is automatically updated too.
```

Esto reduce drásticamente el coste de que el agente se equivoque: crear basura en la conversación
es gratis, ensuciar el workspace del usuario no.

### 4.2 El mecanismo de aprobación (`interrupt` de LangGraph)

Dos hooks sobreescribibles en `MaxTool`:

```python
async def is_dangerous_operation(self, *args, **kwargs) -> bool:
    """
    Override to mark certain operations as requiring user approval.

    Returns True if the operation should require explicit user approval
    before being executed. The default implementation returns False.
    """
    return False

async def format_dangerous_operation_preview(self, *args, **kwargs) -> str:
    """
    Override to provide a human-readable preview of the dangerous operation.
    This is shown to the user when asking for approval. Should clearly
    describe what will happen if the operation is approved.

    This method can make async calls (e.g., database queries) to build a rich preview.
    """
    return f"Execute {self.name} operation"
```

Y la implementación completa del flujo:

```python
PENDING_APPROVAL_STATUS: Literal["pending_approval"] = "pending_approval"


class ApprovalRequest(BaseModel):
    """
    Interrupt payload when a tool operation requires user approval.
    This is passed to interrupt() and surfaced to the FE. When the user approves or rejects,
    """

    status: Literal["pending_approval"] = PENDING_APPROVAL_STATUS
    proposal_id: str
    tool_name: str
    preview: str
    payload: dict[str, Any]
    original_tool_call_id: str | None = None


async def _check_dangerous_operation(self, **kwargs) -> tuple[str, Any] | None:
    if not await self.is_dangerous_operation(**kwargs):
        return None

    # Handle dangerous operation approval flow
    # Pre-compute preview before calling _handle_dangerous_operation
    preview = await self.format_dangerous_operation_preview(**kwargs)
    dangerous_result = self._handle_dangerous_operation(preview=preview, **kwargs)
    if dangerous_result is not None:
        return dangerous_result
    return None


def _handle_dangerous_operation(self, preview: str | None = None, **kwargs) -> tuple[str, Any] | None:
    """
    Handle dangerous operation approval flow using LangGraph's interrupt().

    If the operation is dangerous, this method calls interrupt() which pauses execution
    and returns an ApprovalRequest to the frontend. When the user approves or rejects,
    the graph is resumed with a Command(resume=payload) and interrupt() returns that payload.

    Args:
        preview: Human-readable preview of the operation. Must be provided when the operation
                 is dangerous (pre-computed async by the caller).
    """
    if preview is None:
        raise ValueError("preview must be provided for dangerous operations")

    proposal_id = str(uuid.uuid4())
    serialized_payload = self._serialize_kwargs_for_storage(kwargs)

    approval_request = ApprovalRequest(
        proposal_id=proposal_id,
        tool_name=self.name,
        preview=preview,
        payload=serialized_payload,
        original_tool_call_id=self._original_tool_call_id,
    )

    # Call interrupt() - execution pauses here and ApprovalRequest is sent to frontend
    # When resumed with Command(resume=response), interrupt() returns the response
    response = interrupt(approval_request)
    try:
        approval_resume_payload = ApprovalResumePayload.model_validate(response)
    except ValidationError as e:
        raise MaxToolRetryableError(f"Invalid response from the user: {e}")

    # Handle the response from the user
    if approval_resume_payload.action == "approve":
        if updated_payload := approval_resume_payload.payload:
            # User approved - update kwargs with any modifications and proceed
            kwargs.update(self._reconstruct_kwargs_from_payload(updated_payload))
        return None  # Continue with _arun_impl
    else:
        # User rejected
        feedback = approval_resume_payload.feedback or ""
        if feedback:
            return (
                f"The user rejected this operation with the following feedback: {feedback}. "
                "Please acknowledge their feedback and adjust your approach accordingly.",
                None,
            )
        return (
            "The user rejected this operation. "
            "Please acknowledge their decision and ask if they would like to proceed differently.",
            None,
        )


def _reconstruct_kwargs_from_payload(self, payload: dict) -> dict:
    """Reconstruct kwargs from stored payload (Pydantic deserialization)."""
    args_schema = getattr(self, "args_schema", None)
    if args_schema is not None and isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
        try:
            validated_args = args_schema.model_validate(payload)
            return {field_name: getattr(validated_args, field_name) for field_name in validated_args.model_fields}
        except Exception as e:
            logger.warning(f"Failed to reconstruct kwargs from payload: {e}, using raw payload")
    return payload


def _serialize_kwargs_for_storage(self, kwargs: dict) -> dict:
    """Serialize kwargs for cache storage, converting Pydantic models to dicts."""
    serialized = {}
    for key, value in kwargs.items():
        if isinstance(value, BaseModel):
            serialized[key] = value.model_dump()
        else:
            serialized[key] = value
    return serialized
```

Tres propiedades excelentes de este diseño:

1. **El usuario puede EDITAR los argumentos antes de aprobar.** `approval_resume_payload.payload`
   se re-valida contra `args_schema` y sustituye los kwargs. No es un sí/no: es un
   "sí, pero con estos cambios".
2. **El rechazo no es un error, es feedback conversacional.** Devuelve un string que instruye al
   agente a *reconocer* el feedback y ajustar el enfoque. El agente no reintenta a ciegas.
3. **`GraphInterrupt` se re-lanza explícitamente** en el ejecutor, para no confundir una pausa de
   aprobación con un fallo.

### 4.3 Aprobación condicional basada en el impacto real

Este es el detalle más refinado. `upsert_dashboard` **sólo pide aprobación si la operación
destruye algo**, y lo calcula haciendo un diff real contra la BD antes de preguntar:

```python
# C:\ph\ee\hogai\tools\upsert_dashboard\tool.py
async def is_dangerous_operation(self, *, action: UpsertDashboardAction, **kwargs) -> bool:
    """Update operations that delete existing insights are dangerous."""
    if isinstance(action, UpdateDashboardToolArgs) and action.insight_ids:
        dashboard = await self._get_dashboard(action.dashboard_id)
        sorted_tiles = await self._get_dashboard_sorted_tiles(dashboard)
        diff = await self._get_update_diff(sorted_tiles, action.insight_ids)
        return len(diff["deleted"]) > 0
    return False

async def format_dangerous_operation_preview(self, *, action: UpsertDashboardAction, **kwargs) -> str:
    """
    Build a rich preview showing dashboard details and what will be modified.
    """
    if isinstance(action, CreateDashboardToolArgs):
        raise MaxToolFatalError("Create dashboard operation is not dangerous.")

    dashboard = await self._get_dashboard(action.dashboard_id)
    sorted_tiles = await self._get_dashboard_sorted_tiles(dashboard)
    diff = await self._get_update_diff(sorted_tiles, action.insight_ids or [])

    def get_insight_name(insight: Insight) -> str:
        return insight.name or insight.derived_name or f"Insight #{insight.short_id or insight.id}"

    def get_artifact_name(artifact: VisualizationWithSourceResult) -> str:
        return artifact.content.name or "Insight"

    def join(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    created_list = [get_artifact_name(artifact) for artifact in diff["created"]]
    deleted_list = [get_insight_name(tile.insight) for tile in diff["deleted"] if tile.insight is not None]

    return format_prompt_string(
        PERMISSION_REQUEST_PROMPT,
        dashboard_name=dashboard.name or f"Dashboard #{dashboard.id}",
        new_dashboard_name=action.name,
        new_dashboard_description=action.description,
        deleted_insights=join(deleted_list),
        deleted_count=pluralize(len(deleted_list), "insight"),
        new_insights=join(created_list),
        added_count=pluralize(len(created_list), "insight"),
    )
```

**Crear = sin fricción. Añadir = sin fricción. Borrar = confirmación con el diff exacto,
listando por nombre lo que se va a perder.** La fricción es proporcional al daño potencial y
reversibilidad, no al hecho de "escribir".

### 4.4 Aprobación incondicional como punto de control

`finalize_plan` (`C:\ph\ee\hogai\tools\finalize_plan\tool.py`) usa el mismo mecanismo pero con un
propósito distinto: no es seguridad, es un **gate de producto**. El agente no puede pasar de la
fase de planificación a la de ejecución sin que el humano vea y apruebe el plan.

```python
class FinalizePlanTool(MaxTool):
    name: Literal[AssistantTool.FINALIZE_PLAN] = AssistantTool.FINALIZE_PLAN
    args_schema: type[BaseModel] = FinalizePlanToolArgs
    description: str = FINALIZE_PLAN_PROMPT

    async def is_dangerous_operation(self, **kwargs) -> bool:
        """Finalizing a plan always requires user approval or rejection."""
        return True

    async def format_dangerous_operation_preview(self, **kwargs) -> str:
        """
        Build a rich preview showing plan details and what will be modified.
        """
        plan = kwargs.get("plan")
        if not plan:
            return f"Execute {self.name} operation"

        return f"PostHog AI's plan:\n\n{plan}"

    async def _arun_impl(self, title: str, plan: str, artifact_id: str | None = None) -> tuple[str, Any]:
        artifact, status, _blocks = await create_or_update_notebook_artifact(
            artifacts_manager=self._context_manager.artifacts,
            content=plan,
            title="PostHog AI's plan: " + title,
            artifact_id=artifact_id,
        )

        message = f"The plan notebook artifact has been created with artifact_id: {artifact.short_id}."
        if status == ArtifactStatus.FAILED_TO_UPDATE:
            message = f"Failed to update the existing plan notebook artifact. A new artifact has been created with artifact_id: {artifact.short_id}."
        elif status == ArtifactStatus.UPDATED:
            message = f"The plan notebook artifact with artifact_id {artifact_id} has been updated."

        message += " The user has approved the plan. You can now start executing the plan."

        artifact_message = self._context_manager.artifacts.create_message(
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
            content_type=ArtifactContentType.NOTEBOOK,
        )

        return "", ToolMessagesArtifact(
            messages=[
                artifact_message,
                AssistantToolCallMessage(content=message, tool_call_id=self.tool_call_id, id=str(uuid.uuid4())),
            ]
        )
```

Nótese el `message += " The user has approved the plan. You can now start executing the plan."`
— tras la aprobación, el mensaje al LLM **le confirma explícitamente que tiene luz verde**.
El estado de aprobación se comunica en lenguaje natural dentro del historial.

### 4.5 Idempotencia: el patrón "upsert" y `ArtifactStatus`

Ninguna herramienta de escritura tiene un `create` y un `update` separados. Todas siguen el mismo
patrón: **un parámetro opcional de ID que conmuta entre creación y actualización.**

**(a) Unión discriminada explícita** (`upsert_dashboard`):

```python
class CreateDashboardToolArgs(BaseModel):
    """Schema to create a new dashboard with provided insights."""

    action: Literal["create"] = "create"
    insight_ids: list[str] = Field(
        description="The IDs of the insights to be included in the dashboard. It might be a mix of existing and new insights."
    )
    name: str = Field(
        description="A short and concise (3-7 words) name of the dashboard. It will be displayed as a header in the dashboard tile."
    )
    description: str = Field(description="A short and concise description of the dashboard.")


class UpdateDashboardToolArgs(BaseModel):
    """Schema to update an existing dashboard with provided insights."""

    action: Literal["update"] = "update"
    dashboard_id: str = Field(description="Provide the ID of the dashboard to be update it.")
    insight_ids: list[str] | None = Field(
        description="The IDs of the insights for the dashboard. Replaces all existing insights.",
        default=None,
    )
    layout_mode: Literal["preserve_existing", "reflow_all"] = Field(
        description="How to handle existing tile layouts when insight_ids are provided. Use preserve_existing by default. Use reflow_all only when the user explicitly asks to rearrange or reorder tiles.",
        default="preserve_existing",
    )
    name: str | None = Field(
        description="A short and concise (3-7 words) name of the dashboard. If not provided, the dashboard name will not be updated.",
        default=None,
    )
    description: str | None = Field(
        description="A short and concise description of the dashboard. If not provided, the dashboard description will not be updated.",
        default=None,
    )


UpsertDashboardAction = CreateDashboardToolArgs | UpdateDashboardToolArgs


class UpsertDashboardToolArgs(BaseModel):
    action: UpsertDashboardAction = Field(
        description="The action to perform. Either create a new dashboard or update an existing one.",
        discriminator="action",
    )
```

El discriminador de Pydantic hace que **sea imposible construir una llamada inválida**: no puedes
mandar `dashboard_id` en un create ni omitirlo en un update. El error de validación es preciso y
auto-corregible.

Y la semántica de reemplazo es declarada de forma inequívoca en la description:

```
When `insight_ids` is provided, it replaces all dashboard insights with the provided insights.
You can use insight_ids to add, replace, or remove insights.
By default, keep existing insight tile layouts unchanged (`layout_mode="preserve_existing"`).
Use `layout_mode="reflow_all"` whenever the user explicitly asks to change placement/order, including phrases like:
- reorder/rearrange/reflow the dashboard
- move an insight before/after another insight
- insert an insight between two insights
- place an insight first/last/at the top
Keep `layout_mode="preserve_existing"` for plain add/remove/replace requests where layout should stay unchanged.
When using `layout_mode="reflow_all"`, tile coordinates are recomputed in the order of `insight_ids`.

Example: Dashboard has [A, B, C] (in layout order). Use `insight_ids=[A, C]` (same insight IDs, omitting B).
Result: A and C keep their existing tile layouts, B's tile is soft-deleted, and no new tiles are created.
```

Este bloque es un modelo a seguir: **semántica de reemplazo total declarada + un ejemplo concreto
con IDs + qué pasa con el estado que no se menciona.** El `layout_mode` es la solución al problema
clásico de "el agente reordena todo cuando sólo querías añadir un elemento".

Además `has_changes` evita escrituras vacías:

```python
async def _handle_update(self, action: UpdateDashboardToolArgs) -> tuple[str, dict | None]:
    """Handle UPDATE action: update an existing dashboard."""
    dashboard = await self._get_dashboard(action.dashboard_id)
    has_changes = action.insight_ids or action.name is not None or action.description is not None
    if not has_changes:
        return UPDATE_NO_CHANGES_PROMPT, None
```

**(b) `artifact_id` opcional** (`create_notebook`, `finalize_plan`) — el mismo helper hace create
o update y devuelve un enum de estado:

```python
artifact, status, blocks = await create_or_update_notebook_artifact(
    artifacts_manager=self._context_manager.artifacts,
    content=notebook_content,
    title=title,
    artifact_id=artifact_id,
)
```

`ArtifactStatus` tiene tres valores — `CREATED`, `UPDATED` y **`FAILED_TO_UPDATE`** — y el fallo de
actualización **degrada a creación** en lugar de fallar:

```python
message = (
    f"The notebook artifact has been created with artifact_id: {artifact.short_id}. "
    "This is a transient artifact visible only in this conversation. "
    "The user can save it by clicking 'Create notebook' in the UI, or ask you to save it."
)
if status == ArtifactStatus.FAILED_TO_UPDATE:
    message = (
        f"Failed to update the existing notebook artifact. "
        f"A new artifact has been created with artifact_id: {artifact.short_id}. "
        "This is a transient artifact visible only in this conversation."
    )
elif status == ArtifactStatus.UPDATED:
    message = f"The notebook artifact with artifact_id {artifact_id} has been updated."
```

**El mensaje de retorno siempre contiene el `artifact_id` resultante y qué ocurrió realmente.**
Si el agente pidió actualizar `abc123` pero se creó `xyz789`, el LLM se entera y usa el ID nuevo
a partir de ahí. Esta honestidad sobre el resultado es lo que evita que el agente opere sobre
referencias fantasma.

### 4.6 Transaccionalidad y auditoría

`upsert_dashboard` importa `django.db.transaction` y reporta cada acción:

```python
dashboard = await self._create_dashboard_with_tiles(action.name, action.description, insights)
# AI dashboards are always built from scratch (no template, no duplicate); set the same provenance
# props the serializer create() path emits so `from_template`/`duplicated` filters include AI traffic.
await self._report_dashboard_action(
    dashboard,
    "dashboard created",
    {
        "from_template": False,
        "template_key": None,
        "duplicated": False,
        "duplicated_from_dashboard_id": None,
    },
)
await self._report_new_insights(validated_artifacts, insights)
```

Las escrituras del agente emiten **los mismos eventos de producto que las escrituras humanas**,
con provenance explícita. La analítica del producto no distingue rutas.

### 4.7 Ejecución en cliente

Un tercer tipo de "handoff", además de aprobación: pausar y delegar la ejecución al frontend
(útil para operaciones que sólo el navegador puede hacer — leer el DOM, acceder a un canvas, un
editor local):

```python
class ClientToolCallRequest(BaseModel):
    """Interrupt payload when a tool hands execution to its client-side handler.

    Nothing is streamed: the frontend detects the pending call from the thread, runs the
    registered handler, and resumes with a ClientToolResultPayload.
    """

    tool_name: str
    original_tool_call_id: str | None = None


def request_client_execution(self) -> dict[str, Any]:
    """Pause the graph until this tool's frontend handler resumes the conversation.

    The handler receives this tool call's arguments. Returns the handler's result dict;
    validate its domain shape in the calling tool.
    """
    response = interrupt(
        ClientToolCallRequest(tool_name=self.name, original_tool_call_id=self._original_tool_call_id)
    )
    try:
        payload = ClientToolResultPayload.model_validate(response)
    except ValidationError as e:
        raise MaxToolRetryableError(f"Invalid client tool result: {e}")
    # All interrupts pending in one superstep receive the same resume value — fail loudly on misdelivery
    if payload.tool_call_id and self._original_tool_call_id and payload.tool_call_id != self._original_tool_call_id:
        raise MaxToolRetryableError("The client tool result was addressed to a different tool call")
    return payload.result
```

El comentario sobre el superstep es una lección aprendida en producción: con llamadas paralelas,
todos los `interrupt()` pendientes reciben el mismo valor de resume, así que hay que **verificar
que el resultado corresponde a tu tool_call_id** y fallar ruidosamente si no.

---

## 5. Integración MCP

Hay **dos** integraciones MCP, en direcciones opuestas. No confundirlas.

### 5.1 PostHog como SERVIDOR MCP (`mcp_tool.py`)

**Fichero:** `C:\ph\ee\hogai\mcp_tool.py` — completo y literal

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from posthog.models import Team, User

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class MCPTool(ABC, Generic[ArgsT]):
    """
    Base class for tools executable via MCP callers.

    Unlike MaxTool, this interface:
    - Only takes args (no LangChain state, config, context_manager)
    - Team/user stored as instance fields from API authentication
    - No artifact creation (returns data directly)
    - Raises MaxToolError on failure (matching MaxTool conventions)
    """

    name: str
    args_schema: type[ArgsT]

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    @abstractmethod
    async def execute(self, args: ArgsT) -> str:
        """
        Execute the tool with validated args.

        Returns:
            Content string for LLM consumption.

        Raises:
            MaxToolRetryableError: For errors that can be fixed with adjusted inputs.
            MaxToolFatalError: For errors that cannot be recovered from.
        """
        pass


@dataclass(frozen=True)
class MCPToolRegistration:
    tool_cls: type[MCPTool[Any]]
    scopes: list[str]


class MCPToolRegistry:
    """Singleton registry for MCP tools."""

    _instance: "MCPToolRegistry | None" = None
    _tools: dict[str, MCPToolRegistration]

    def __new__(cls) -> "MCPToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(self, scopes: list[str] | None = None):
        """Decorator factory to register an MCP tool with optional scopes."""

        def decorator[T: MCPTool[Any]](cls: type[T]) -> type[T]:
            self._tools[cls.name] = MCPToolRegistration(
                tool_cls=cls,
                scopes=scopes or [],
            )
            return cls

        return decorator

    def _ensure_loaded(self) -> dict[str, MCPToolRegistration]:
        # Tools self-register on import, so every read must trigger the import first. Keep the
        # load-then-read invariant in one place — function-local import to avoid the tools <-> mcp_tool cycle.
        from ee.hogai.tools import load_all_tools  # noqa: PLC0415 - ensure tools are registered

        load_all_tools()
        return self._tools

    def get(self, name: str, team: Team, user: User) -> MCPTool[Any] | None:
        """Get an MCP tool instance by name, constructed with team/user."""
        registration = self._ensure_loaded().get(name)
        if registration:
            return registration.tool_cls(team=team, user=user)
        return None

    def get_scopes(self, name: str) -> list[str]:
        """Get the required scopes for a registered MCP tool."""
        registration = self._ensure_loaded().get(name)
        if registration:
            return registration.scopes
        return []

    def get_names(self) -> list[str]:
        """Get list of registered MCP tool names."""
        return list(self._ensure_loaded().keys())


mcp_tool_registry = MCPToolRegistry()
```

**La observación arquitectónica clave:** `MCPTool` es un **contrato deliberadamente más pobre** que
`MaxTool`. Sin estado de conversación, sin config de LangChain, sin artefactos, sin aprobación
humana — sólo `(args) -> str`. Autenticación por API key con scopes, no por sesión.

En la práctica, una capacidad se expone en ambos mundos escribiendo el núcleo una vez y dos
adaptadores finos. Compárense:
- `C:\ph\ee\hogai\tools\execute_sql\tool.py` (`MaxTool`, produce artefacto de visualización)
- `C:\ph\ee\hogai\tools\execute_sql\mcp_tool.py` (`MCPTool`, devuelve el resultado en texto)
- `C:\ph\ee\hogai\tools\read_taxonomy\core.py` (lógica compartida) + `tool.py` + `mcp_tool.py`

`read_taxonomy` es el caso más limpio: `core.py` (5,9 KB) tiene los modelos y `execute_taxonomy_query`;
`tool.py` (7,1 KB) y `mcp_tool.py` (1,2 KB) son envolturas. **El adaptador MCP son ~40 líneas.**

### 5.2 PostHog como CLIENTE MCP (`call_mcp_server`)

**Fichero:** `C:\ph\ee\hogai\tools\call_mcp_server\tool.py`

El problema: el usuario instala N servidores MCP arbitrarios, cada uno con M tools. Exponerlos
todos como tools nativas al LLM haría explotar el toolset. La solución de PostHog:
**UNA sola tool con descubrimiento en dos fases.**

```python
class CallMCPServerToolArgs(BaseModel):
    server_url: str = Field(description="URL of the MCP server to call")
    tool_name: str = Field(
        description="Name of the tool to invoke on the server, or '__list_tools__' to discover available tools"
    )
    arguments: dict = Field(default_factory=dict, description="Arguments to pass to the tool")


class CallMCPServerTool(MaxTool):
    name: Literal[AssistantTool.CALL_MCP_SERVER] = AssistantTool.CALL_MCP_SERVER
    description: str = "No MCP servers installed."
    args_schema: type[BaseModel] = CallMCPServerToolArgs

    _allowed_server_urls: set[str]
    _installations: list
    _installations_by_url: dict[str, dict]
    _server_headers: dict[str, dict[str, str]]
    # {server_url: {tool_name: approval_state}} — lazily populated to minimize DB reads; also seeded by _get_cached_tool_list to avoid double lookup when calling __list_tools__
    _approval_cache: dict[str, dict[str, str]]

    @classmethod
    async def create_tool_class(cls, *, team, user, node_path=None, state=None, config=None, context_manager=None) -> Self:
        installations = await database_sync_to_async(_get_installations)(team, user)

        if not installations:
            description = "No MCP servers are installed. This tool is not available."
        else:
            server_lines = "\n".join(f"- {inst['display_name']}: {inst['url']}" for inst in installations)
            description = (
                "Call a tool on a user-installed MCP server. "
                "The user has the following MCP servers installed:\n"
                f"{server_lines}\n\n"
                "To discover what tools a server offers, call this with tool_name='__list_tools__' "
                "and the server_url. Then use the returned tool definitions to make actual tool calls."
            )

        allowed_urls = {inst["url"] for inst in installations}
        server_headers = _build_server_headers(installations)

        instance = cls(
            team=team, user=user, node_path=node_path, state=state,
            config=config, context_manager=context_manager,
            description=description,
        )
        instance._allowed_server_urls = allowed_urls
        instance._installations = installations
        instance._installations_by_url = {inst["url"]: inst for inst in installations}
        instance._server_headers = server_headers
        instance._approval_cache = {}
        return instance
```

**La description se genera desde la BD del usuario**: lista sus servidores instalados con nombre y
URL. El LLM sabe qué existe sin que ninguna tool esté hard-codeada.

El formateo de tools remotas para el LLM:

```python
class MCPToolProperty(BaseModel, extra="ignore"):
    type: str | list[str] = "any"
    description: str = ""

    @property
    def type_display(self) -> str:
        if isinstance(self.type, list):
            return " | ".join(self.type)
        return self.type


class MCPToolInputSchema(BaseModel, extra="ignore"):
    properties: dict[str, MCPToolProperty] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class MCPToolDefinition(BaseModel, extra="ignore"):
    name: str
    description: str = "No description"
    inputSchema: MCPToolInputSchema = Field(default_factory=MCPToolInputSchema)

    def format_for_llm(self) -> str:
        if not self.inputSchema.properties:
            params_str = "    (no parameters)"
        else:
            parts = []
            for param_name, param_info in self.inputSchema.properties.items():
                req = " (required)" if param_name in self.inputSchema.required else ""
                parts.append(f"    - {param_name}: {param_info.type_display}{req} — {param_info.description}")
            params_str = "\n".join(parts)
        return f"- **{self.name}**: {self.description}\n  Parameters:\n{params_str}"
```

`extra="ignore"` en todos los modelos: los servidores externos mandan campos arbitrarios y no
deben romper el parseo. Y las definiciones malformadas se saltan individualmente:

```python
def _format_tool_list(self, server_url: str, raw_tools: list[dict], approval_states: dict[str, str]) -> str:
    tools: list[MCPToolDefinition] = []
    hidden_do_not_use = 0
    needs_approval_names: list[str] = []
    for raw in raw_tools:
        try:
            tool = MCPToolDefinition.model_validate(raw)
        except ValidationError:
            logger.warning("Skipping malformed tool definition from MCP server", server_url=server_url, raw=raw)
            continue
        state = approval_states.get(tool.name, _APPROVAL_DEFAULT)
        if state == "do_not_use":
            # Invisible to the agent — matches the `do_not_use` semantics in the proxy path.
            hidden_do_not_use += 1
            continue
        if state == "needs_approval":
            needs_approval_names.append(tool.name)
        tools.append(tool)

    if not tools:
        return "This MCP server has no tools available."

    formatted = "\n\n".join(t.format_for_llm() for t in tools)
    notes: list[str] = []
    if needs_approval_names:
        notes.append(
            "The following tools require explicit user approval before each call; the user will be "
            "prompted when you invoke them: " + ", ".join(sorted(needs_approval_names))
        )
    if hidden_do_not_use:
        notes.append(f"{hidden_do_not_use} tool(s) on this server were hidden because the user disabled them.")
    footer = ("\n\n" + "\n".join(notes)) if notes else ""
    return f"Tools available on {server_url}:\n\n{formatted}{footer}"
```

**Al LLM se le avisa por adelantado de qué tools van a pedir aprobación.** Puede planificar en
consecuencia (agrupar acciones, avisar al usuario) en vez de sorprenderse.

Modelo de permisos por tool remota, con tres estados: `allowed` / `needs_approval` (default) /
`do_not_use`:

```python
_APPROVAL_DEFAULT = "needs_approval"

async def is_dangerous_operation(
    self, *, server_url: str, tool_name: str, arguments: dict | None = None, **_kwargs
) -> bool:
    # Tool discovery should never require approval
    if tool_name == "__list_tools__":
        return False
    # Unknown server_url will be rejected by _validate_server_url during
    # execution; don't gate approval on it.
    if server_url not in self._allowed_server_urls:
        return False
    state = await self._resolve_approval_state(server_url, tool_name)
    return state == "needs_approval"

async def format_dangerous_operation_preview(
    self, *, server_url: str, tool_name: str, arguments: dict | None = None, **_kwargs
) -> str:
    inst = self._installations_by_url.get(server_url, {})
    display = inst.get("display_name") or server_url
    if arguments:
        try:
            args_str = json.dumps(arguments, indent=2, default=str)
        except (TypeError, ValueError):
            args_str = repr(arguments)
        args_block = f"\n\n```json\n{args_str}\n```"
    else:
        args_block = "\n\n*(no arguments)*"
    return f"PostHog AI wants to call **{tool_name}** on **{display}**.{args_block}"
```

**Seguro por defecto**: una tool remota desconocida requiere aprobación explícita hasta que el
usuario diga lo contrario. El preview muestra los argumentos exactos en JSON.

Seguridad de red — doble validación (allowlist del usuario + política SSRF):

```python
def _validate_server_url(self, server_url: str) -> None:
    if server_url not in self._allowed_server_urls:
        raise MaxToolFatalError(
            f"Server URL '{server_url}' is not in the user's installed MCP servers. "
            f"Allowed URLs: {', '.join(sorted(self._allowed_server_urls))}"
        )
    allowed, error = is_url_allowed(server_url)
    if not allowed:
        raise MaxToolFatalError(f"MCP server URL blocked by security policy")
```

(Nótese que el mensaje de bloqueo por política **no filtra el motivo** al LLM, mientras que el
de allowlist sí lista las URLs válidas — es información que el usuario ya posee.)

Gestión de tokens OAuth: refresco proactivo + reintento con refresco:

```python
async def _arun_impl(self, server_url: str, tool_name: str, arguments: dict | None = None) -> tuple[str, None]:
    self._validate_server_url(server_url)

    # Use per-installation cache for `__list_tools__` if available to avoid unnecessary server calls and token refreshes.
    if tool_name == "__list_tools__":
        cached = await self._get_cached_tool_list(server_url)
        if cached is not None:
            return cached, None

    await self._try_proactive_token_refresh(server_url)

    try:
        result = await self._call_server(server_url, tool_name, arguments)
        return result, None
    except MCPClientError as e:
        raise MaxToolRetryableError(f"MCP server error: {e}")


async def _call_server(self, server_url: str, tool_name: str, arguments: dict | None) -> str:
    try:
        return await self._attempt_call(server_url, tool_name, arguments)
    except MCPClientError:
        # Refresh auth in case that was the issue and retry the tool call once.
        await self._refresh_auth_or_mark_reauth(server_url)
        return await self._attempt_call(server_url, tool_name, arguments)


async def _refresh_auth_or_mark_reauth(self, server_url: str) -> None:
    try:
        await self._refresh_token_for_server(server_url)
    except Exception:
        inst = self._get_installation(server_url)
        await database_sync_to_async(_mark_needs_reauth_sync)(inst["id"])
        raise MaxToolFatalError(
            f"Authentication failed for {server_url} and token refresh failed. "
            "Ask the user to re-authenticate with this MCP server in the MCP store settings page."
        )
```

El error final es `Fatal` (no reintentable) **y contiene la instrucción exacta para el usuario**
("re-authenticate ... in the MCP store settings page"). El agente puede resolver el problema del
usuario aunque él no pueda.

Y el audit trail, con una nota explícita de privacidad:

```python
# Basic audit trail for who exercises which installation (especially
# shared credentials), mirroring the proxy path. Metadata only —
# never arguments or results.
logger.info(
    "mcp_store max tool call",
    team_id=self._team.id,
    installation_id=str(inst["id"]),
    scope=inst.get("scope", "personal"),
    user_id=self._user.id,
    tool_name=tool_name,
)
```

---

## 6. Patrones de redacción de `description`

Las descriptions de PostHog son documentos de 1-8 KB, no frases. Están en `prompts.py` separados
del código. Extraigo los patrones recurrentes.

### 6.1 Estructura canónica

```
<qué hace, una frase>

# Use this when:
- <disparador 1>
- <disparador 2>

# When NOT to use this tool
- <anti-disparador>

# Parameters:
- <param>: <semántica> <default>

# <Reglas de dominio / workflow numerado>

# Best practices:

# Example
<bloque literal>

<example>
User: ...
Assistant: ...
<reasoning>...</reasoning>
</example>
```

### 6.2 Patrón: `Use this when` + `When NOT to use`

Casi todas las descriptions tienen ambas listas. La negativa es la que más precisión aporta.
`C:\ph\ee\hogai\tools\read_taxonomy\tool.py`:

```
# Examples of when to use the read_taxonomy tool

<example>
User: What event can I use to track revenue?
Assistant: I'm going to retrieve events and event properties to help you find the event you're looking for.
*Retrieves events*
Assistant: I've found a few matching events. I'm going to retrieve event properties to help you find the event you're looking for.
*Retrieves event properties for each event*
Assistant: I've found a few matching properties. I'm going to retrieve sample property values for each property to verify they can be used for revenue tracking.
*Retrieves sample property values for each event property*
Assistant: I've found matching combinations...

<reasoning>
The assistant used the read_taxonomy tool because:
1. The user is asking about **their custom data schema** in PostHog.
2. The assistant needs to find a specific combination of events, properties, and property values that can be used to track revenue.
</reasoning>
</example>

# Examples of when NOT to use the read_taxonomy tool

<example>
User: What system properties does PostHog capture?
Assistant: I'm going to search PostHog documentation to find the system properties that are automatically captured by SDKs.
*Begins searching PostHog documentation*

<reasoning>
The assistant did not use the read_taxonomy tool because it is an informational request. The user is simply asking for documentation search.
</reasoning>
</example>
```

**Los ejemplos son diálogos multi-turno con `<reasoning>` explícito.** No se limita a decir *qué*
hacer: modela el proceso de decisión y la *secuencia* de llamadas (eventos → propiedades → valores
de muestra). Enseña un algoritmo, no un mapeo.

### 6.3 Patrón: combatir el conocimiento previo del modelo

El párrafo más importante de `read_taxonomy`:

```
Each event, action, and entity has its own data schema. You must verify that specific combinations exist before using it anywhere else.
Events or properties starting from "$" are system properties automatically captured by SDKs.
Do not rely on your training data or PostHog defaults for events or properties. Always use this tool to confirm what actually exists in the user's project before referencing any event, property, or property value.
```

*"Do not rely on your training data"* — dicho explícitamente. Cuando la herramienta accede a datos
específicos del usuario, hay que decirle al modelo que su conocimiento previo es inaplicable.

### 6.4 Patrón: desambiguar herramientas solapadas dentro de la propia description

`C:\ph\ee\hogai\tools\read_data\prompts.py`:

```
Use this tool to read user data created in PostHog. This tool returns data that the user manually creates in PostHog.

This tool should be used for direct retrieval (by ID, name, etc.). Use the search tool instead for finding entities by name, description. If the search tool doesn't return matching entities, try pagination instead using the list_data tool.
```

**Cada tool nombra a sus vecinas y dice cuándo cederles el paso.** Esto es mucho más eficaz que
intentar arbitrar entre tools desde el system prompt global.

### 6.5 Patrón: workflow numerado

```
You MUST use this tool when:
- Working with SQL.
- The request is about data warehouse, connected data sources, etc.

Workflow:
1. Start with `data_warehouse_schema` to see available tables
2. Use `data_warehouse_table` with a specific `table_name` to get schema details for warehouse tables you need
```

Cuando hay una secuencia obligatoria (barato-general → caro-específico), se numera. Evita que el
agente pida el detalle caro de 40 tablas.

### 6.6 Patrón: exclusividad mutua explícita

```
# Content vs Draft Content:
You must use EXACTLY ONE of these parameters:
- `content`: Use this when you want to show the notebook to the user immediately. The notebook will be streamed as you write it.
- `draft_content`: Use this when you want to save a draft without showing it to the user. Useful for writing a first version before it's ready, of for taking intermediate finding notes before writing the final version.
```

Pydantic no expresa fácilmente "exactamente uno de estos dos", así que se declara en prosa Y se
valida en el cuerpo con un mensaje de error espejo:

```python
if content is not None and draft_content is not None:
    return "Error: Cannot provide both 'content' and 'draft_content'. Use exactly one.", None
```

### 6.7 Patrón: ejemplo de formato de salida literal

`create_notebook` incluye un ejemplo completo de markdown de salida, con las etiquetas de
referencia in situ:

```
# Example content format:
```
# Weekly Analytics Report

## Key Metrics Overview

Here's the main trends insight showing our weekly active users:

<insight>abc123</insight>

As we can see, there's been a 15% increase week-over-week.

## Funnel Analysis

Our signup funnel shows the following conversion rates:

<insight>def456</insight>

### Recommendations

1. Focus on improving step 2 to 3 conversion
2. Consider A/B testing the signup flow
```
```

Para cualquier tool que produzca contenido estructurado, **un ejemplo completo vale más que
cualquier especificación**.

### 6.8 Patrón: instrucciones de estilo/densidad

```
# Best practices:
The document should be structured as a series of sections, each with a heading and a body.
Try to use each section to answer a single question or provide a single insight.
Don't be verbose, get straight to the point. Data-heavy short documents are preferred over long documents.
Don't repeat yourself. If you've already mentioned an insight or artifact in a previous section, don't mention it again.
```

Y en `finalize_plan`:

```
## Format guidelines
- Use `#` and `##` headings to organize sections
- Keep explanations concise - let the data speak
- One insight per section, don't repeat visualizations
- Use bullet points for recommendations or action items
```

### 6.9 Patrón: descriptions de campo con umbrales numéricos

```python
viz_title: str = Field(
    description="Short, concise name of the SQL query (2-5 words) that will be displayed as a header in the visualization."
)
viz_description: str = Field(
    description="Short, concise summary of the SQL query (1 sentence) that will be displayed as a description in the visualization."
)
```

```python
name: str = Field(
    description="A short and concise (3-7 words) name of the dashboard. It will be displayed as a header in the dashboard tile."
)
```

Dos elementos siempre presentes: **el límite numérico** (2-5 palabras, 1 frase) y **dónde se va a
renderizar** ("displayed as a header in the dashboard tile"). Decirle al modelo dónde acaba el
texto le hace calibrar el registro y la longitud mucho mejor que un límite abstracto.

Para campos opcionales, se declara el comportamiento por omisión:

```python
name: str | None = Field(
    description="A short and concise (3-7 words) name of the dashboard. If not provided, the dashboard name will not be updated.",
    default=None,
)
```

### 6.10 Patrón: `ONLY when the user explicitly asks`

Fórmula recurrente para conmutadores de riesgo:

```python
save_to_notebook: bool = Field(
    default=False,
    description="Set to true ONLY when the user explicitly asks to save/persist the notebook to the database.",
)
```

```python
layout_mode: Literal["preserve_existing", "reflow_all"] = Field(
    description="How to handle existing tile layouts when insight_ids are provided. Use preserve_existing by default. Use reflow_all only when the user explicitly asks to rearrange or reorder tiles.",
    default="preserve_existing",
)
```

`ONLY` en mayúsculas + `explicitly asks` + un default seguro. Y en la description larga, se
enumeran las **frases literales** que disparan el modo no-default:

```
Use `layout_mode="reflow_all"` whenever the user explicitly asks to change placement/order, including phrases like:
- reorder/rearrange/reflow the dashboard
- move an insight before/after another insight
- insert an insight between two insights
- place an insight first/last/at the top
```

### 6.11 Patrón: `<system_reminder>` para dirigir el post-fallo

```python
INSIGHT_TOOL_CONTEXT_PROMPT_TEMPLATE = """
The user is currently editing an insight (aka query). Here is that insight's current definition, which can be edited using the `create_insight` tool:

```json
{current_query}
```

<system_reminder>
Do not remove any fields from the current insight definition. Do not change any other fields than the ones the user asked for. Keep the rest as is.
</system_reminder>
""".strip()
```

Estado actual en JSON + una restricción de edición mínima en `<system_reminder>`. Es la solución al
problema clásico de "le pedí cambiar el color y me reescribió toda la configuración".

---

## 7. Plan de transferencia al agente de cinematografías

### 7.1 Mapeo de conceptos

| PostHog | Agente de vídeo |
|---|---|
| `AgentArtifact` (fila JSON, `short_id`, atado a conversación) | `Asset` — guion, shot list, imagen, clip, timeline |
| `VisualizationArtifactContent` | `ImageArtifactContent`, `VideoClipArtifactContent` |
| `StoredNotebookArtifactContent` con `VisualizationRefBlock` | `TimelineArtifactContent` con `ShotRefBlock` |
| `ArtifactSource.STATE / ARTIFACT / INSIGHT` | `PREVIEW` (baja res, efímero) / `ARTIFACT` (conversación) / `LIBRARY` (proyecto guardado) |
| `execute_sql` → gráfico | `generate_image` / `generate_video` → clip |
| `create_notebook` → informe con gráficos | `edit_timeline` → timeline con clips |
| `upsert_dashboard` (borra tiles) | `edit_timeline` (borra shots) → aprobación con diff |
| `finalize_plan` | `approve_shot_list` — gate guion→producción |
| `read_taxonomy` (esquema del usuario) | `read_style_library` (estilos/LUTs/personajes del proyecto) |
| `read_data` (unión discriminada) | `read_asset` con `kind` |
| Modo `plan` vs `chat` | Modo `preproducción` vs `producción` |

### 7.2 Directamente transferible (copiar casi tal cual)

**1. `tool_errors.py` — cópialo entero.** Sólo renombra `MaxTool*` → `MediaTool*`. La taxonomía
never/once/adjusted mapea perfectamente al dominio de vídeo:

| Fallo | Clase |
|---|---|
| Créditos agotados, modelo no disponible en tu plan, prompt rechazado por el filtro de contenido | `MediaToolFatalError` |
| Timeout del proveedor de generación, 429, GPU no disponible | `MediaToolTransientError` |
| Aspect ratio no soportado, duración > máx del modelo, `seed_image_id` inexistente, prompt supera el límite de tokens | `MediaToolRetryableError` |

Añade una subclase propia del dominio:

```python
class ContentPolicyError(MediaToolFatalError):
    """The generation provider rejected the prompt on content-policy grounds."""

    def __init__(self, provider: str, category: str | None = None):
        detail = f" (category: {category})" if category else ""
        super().__init__(
            f"{provider} rejected this prompt on content-policy grounds{detail}. "
            "Do not retry the same prompt. Rephrase the shot description to avoid the flagged content, "
            "or tell the user which element needs to change."
        )
```

**2. El bucle de captura de `executables.py`.** Cuatro capas: error de dominio con `retry_hint`,
`ValidationError` de Pydantic pasado íntegro, interrupción re-lanzada, genérico con
"no reintentes inmediatamente". Es prácticamente idéntico en cualquier agente.

**3. Los cuatro campos del contrato de `MaxTool`**: `response_format="content_and_artifact"`,
`context_prompt_template`, `create_tool_class()`, `get_required_resource_access()`.

**4. El registro de handlers de artefactos completo** (`base.py` + `manager.py`). Sustituye
`VisualizationHandler`/`NotebookHandler` por `ImageHandler`/`ClipHandler`/`TimelineHandler`.
El `ArtifactManager` no necesita cambios estructurales.

**5. La separación `content` / `ui_payload`.** Crítica en vídeo: el LLM debe recibir
`"Generated clip clip_a3f (4.2s, 1920x1080, style: noir). Preview: 8 keyframes described as ..."`,
nunca base64 ni URLs de un GB. El `ui_payload` lleva las URLs firmadas al reproductor.

**6. `is_dangerous_operation` + `format_dangerous_operation_preview`**, con el diff calculado
antes de preguntar.

**7. El patrón de exposición dual `MaxTool`/`MCPTool`**: núcleo en `core.py`, dos adaptadores.

### 7.3 Adaptaciones específicas del dominio

**(a) El coste y la latencia importan mucho más — añade una dimensión "caro" al contrato.**

En PostHog la fricción es proporcional al *daño*. En generación de vídeo hay una segunda
dimensión: el *coste irreversible en dinero y minutos*. Un `generate_video` de 10 s puede costar
varios dólares y tardar 3 minutos, y no es destructivo — pero sí es caro.

```python
class MediaTool(MaxTool):
    estimated_cost_credits: int = 0
    """Rough credit cost of one invocation. Used for budget gating and previews."""

    async def is_expensive_operation(self, **kwargs) -> bool:
        """Whether this call should be confirmed on cost grounds, independent of destructiveness."""
        return self.estimated_cost_credits > 0

    async def format_cost_preview(self, **kwargs) -> str:
        return f"This will use approximately {self.estimated_cost_credits} credits."
```

Y encadénalo con el mismo `interrupt()`. Sugerencia de política, siguiendo el gradiente de PostHog:

| Operación | Confirmación |
|---|---|
| `generate_image` (una, borrador) | no |
| `generate_image` (lote > 8) | sí, coste |
| `generate_video` (< 5 s, borrador) | no |
| `generate_video` (final, alta res) | sí, coste + preview del prompt |
| `edit_timeline` que elimina shots | sí, diff (patrón `upsert_dashboard`) |
| `render_final` | siempre |
| `apply_style` a todo el proyecto | sí, diff de cuántos shots afecta |

**(b) Operaciones de larga duración — PostHog no tiene esto y es tu mayor gap.**

Todas las tools de PostHog completan en segundos. Una generación de vídeo no. Dos patrones a
combinar:

- El `LoadingBlock` ya existe en `StoredBlock` de PostHog:
  `StoredBlock = MarkdownBlock | VisualizationRefBlock | SessionReplayBlock | LoadingBlock`.
  Úsalo: crea el artefacto en estado `pending` inmediatamente, devuelve el ID al LLM, y deja que la
  UI muestre el placeholder mientras el job corre.
- El estado del job se consulta con una tool aparte, siguiendo el patrón de `TASK_TOOLS` de
  PostHog (`C:\ph\ee\hogai\chat_agent\toolkit.py`: `CreateTaskTool`, `RunTaskTool`,
  `GetTaskRunTool`, `GetTaskRunLogsTool`, `ListTaskRunsTool`).

```python
async def _arun_impl(self, shot_description: str, ...) -> tuple[str, Any]:
    artifact = await self._context_manager.artifacts.acreate(
        VideoClipArtifactContent(status="pending", prompt=shot_description, ...),
        f"Clip: {shot_description[:60]}",
    )
    job_id = await enqueue_generation(artifact.short_id, ...)
    artifact_message = self._context_manager.artifacts.create_message(
        artifact_id=artifact.short_id,
        source=ArtifactSource.ARTIFACT,
        content_type=ArtifactContentType.VIDEO_CLIP,
    )
    return "", ToolMessagesArtifact(
        messages=[
            artifact_message,
            AssistantToolCallMessage(
                content=(
                    f"Video generation started. artifact_id: {artifact.short_id}, job_id: {job_id}. "
                    f"Estimated time: ~{eta}s. The clip is showing as a placeholder in the timeline. "
                    "Continue with other work; use check_generation with this job_id to poll status. "
                    "Do NOT call generate_video again for this shot."
                ),
                tool_call_id=self.tool_call_id,
                id=str(uuid4()),
            ),
        ]
    )
```

Ese `"Do NOT call generate_video again for this shot"` es la aplicación directa de la lección de
`upsert_dashboard`: **el mensaje de retorno debe evitar activamente el mal comportamiento
siguiente más probable.**

**(c) Idempotencia bajo coste: la clave de contenido.**

`create_or_update_notebook_artifact` es barato de reintentar. Una regeneración de vídeo no.
Añade deduplicación por hash del input:

```python
content_key = hashlib.sha256(
    json.dumps({"prompt": prompt, "seed": seed, "model": model, "style_id": style_id,
                "duration": duration, "aspect_ratio": aspect_ratio}, sort_keys=True).encode()
).hexdigest()

existing = await find_artifact_by_content_key(self._team, conversation, content_key)
if existing and not force_regenerate:
    return (
        f"An identical clip already exists: artifact_id {existing.short_id}. "
        "Reusing it instead of regenerating (this saved credits). "
        "Pass force_regenerate=True if you specifically want a new variation.",
        None,
    )
```

Y el parámetro correspondiente, con la fórmula `ONLY when`:

```python
force_regenerate: bool = Field(
    default=False,
    description="Set to true ONLY when the user explicitly asks for a new variation of a shot that already exists with identical parameters. Regenerating costs credits and produces a different result.",
)
```

**(d) `read_style_library` — el equivalente de `read_taxonomy`, con su párrafo anti-alucinación.**

El error más caro de un agente de vídeo es inventarse un estilo, un LUT o un personaje que no
existe en el proyecto, y descubrirlo tras 3 minutos de render. Copia literalmente la retórica:

```
Use this tool to explore the project's style library: visual styles, LUTs, character references, location plates, and camera presets.
Each project defines its own styles and references. You must verify that a specific style_id or character_id exists before using it in any generation call.
Do not rely on your training data or on well-known film styles by name. Always use this tool to confirm what actually exists in this project before referencing any style, character, or preset in generate_image, generate_video, or apply_style.

# Query types
- kind: "styles" — list available visual styles. Optional: `limit`, `offset`.
- kind: "style_detail" — full definition of a style. Required: `style_id`.
- kind: "characters" — list character references with their reference images.
- kind: "character_detail" — Required: `character_id`.
- kind: "camera_presets" — list camera movement/lens presets.
```

**(e) El modo `plan` de PostHog es tu preproducción — y es el patrón más infravalorado.**

Recordemos que en modo `plan`, `ChatAgentPlanToolkit` **no incluye** las tools de escritura. Aplícalo:

```python
class PreProductionToolkit(AgentToolkit):
    """The agent can research, script and storyboard — but physically cannot spend credits."""
    @property
    def tools(self) -> list[type[MediaTool]]:
        return [
            ReadStyleLibraryTool,
            ReadAssetTool,
            SearchReferencesTool,
            WriteScriptTool,       # texto, gratis
            CreateShotListTool,    # texto, gratis
            TodoWriteTool,
            ApproveShotListTool,   # is_dangerous_operation -> True siempre
        ]


class ProductionToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type[MediaTool]]:
        return [
            *PreProductionToolkit_readonly_tools,
            GenerateImageTool,
            GenerateVideoTool,
            EditTimelineTool,
            ApplyStyleTool,
            CheckGenerationTool,
            RenderFinalTool,
        ]
```

**Es imposible que el agente queme créditos antes de que el humano apruebe la shot list**, porque
las herramientas de generación no están en su toolset. Esto es una garantía estructural, no una
instrucción en el prompt que el modelo puede ignorar bajo presión.

`ApproveShotListTool` copia `FinalizePlanTool` literalmente, incluyendo el
`message += " The user has approved the shot list. You can now start generating."`.

**(f) Timeline = notebook.** El mapeo es 1:1 y deberías explotarlo al máximo:

```python
class ShotRefBlock(BaseModel):
    """Reference to a generated clip - stored in DB, enriched to ShotBlock when streaming."""

    type: Literal["shot_ref"] = "shot_ref"
    artifact_id: str
    title: str | None = None
    in_point: float | None = None
    out_point: float | None = None
    transition: Literal["cut", "dissolve", "fade"] = "cut"


StoredTimelineBlock = ShotRefBlock | TitleCardBlock | AudioRefBlock | GapBlock
EnrichedTimelineBlock = ShotBlock | TitleCardBlock | AudioBlock | GapBlock | ErrorBlock


class StoredTimelineArtifactContent(BaseModel):
    content_type: Literal["timeline"] = "timeline"
    blocks: list[StoredTimelineBlock]
    title: str | None = None
    fps: int = 24
    resolution: tuple[int, int] = (1920, 1080)
```

Beneficios que vienen gratis del diseño de PostHog:
- **Regenerar un clip actualiza todos los timelines que lo usan.** El timeline guarda una
  referencia, no una copia.
- **Un clip que falló se convierte en `ErrorBlock`, no rompe el timeline.** Réplica exacta de
  `aenrich` de `NotebookHandler`: si `viz_content is None` → `ErrorBlock`. En vídeo:
  clip pendiente → `LoadingBlock`; clip fallido → `ErrorBlock` con el motivo.
- **El timeline sigue siendo texto para el LLM** — una lista de refs con in/out points, no vídeo.
  El LLM puede razonar sobre montaje sin ver un solo frame.
- **La sintaxis `<insight>abc123</insight>` se convierte en `<shot>clip_a3f</shot>`**, y el
  parser (`C:\ph\ee\hogai\tools\create_notebook\parsing.py`) es adaptable casi directamente.

**(g) `apply_style` es un `upsert_dashboard` con diff.** Aplicar un estilo a todo un proyecto es
masivo y semi-destructivo (invalida clips ya generados). Calcula el impacto antes de preguntar:

```python
async def is_dangerous_operation(self, *, style_id: str, scope: str, **kwargs) -> bool:
    affected = await self._get_affected_clips(scope)
    already_generated = [c for c in affected if c.status == "complete"]
    return len(already_generated) > 0

async def format_dangerous_operation_preview(self, *, style_id: str, scope: str, **kwargs) -> str:
    affected = await self._get_affected_clips(scope)
    already_generated = [c for c in affected if c.status == "complete"]
    style = await self._get_style(style_id)
    return (
        f"Apply style **{style.name}** to {scope}.\n\n"
        f"This will invalidate and require regenerating {len(already_generated)} already-generated clip(s):\n"
        + "\n".join(f"- {c.title}" for c in already_generated)
        + f"\n\nEstimated cost to regenerate: ~{sum(c.cost for c in already_generated)} credits."
    )
```

**(h) Contextual tools por vista del editor.** El equivalente exacto del
`create_insight` contextual (aparece cuando estás editando un insight):

- Usuario mirando el timeline → `edit_timeline` disponible, con
  `context_prompt_template = "The user is currently viewing the timeline: {current_timeline}. Shots can be reordered or replaced with the edit_timeline tool."`
- Usuario con un clip seleccionado → `regenerate_shot`, con el prompt y los parámetros actuales
  inyectados y un `<system_reminder>` de edición mínima, calcado del de `create_insight`:

```python
REGENERATE_SHOT_CONTEXT_PROMPT = """
The user is currently editing a shot. Here is its current generation config, which can be edited using the `regenerate_shot` tool:

```json
{current_shot_config}
```

<system_reminder>
Do not remove any fields from the current shot config. Do not change any other fields than the ones the user asked for. Keep the rest as is — in particular keep `seed` unchanged unless the user explicitly asks for a different variation, since changing it discards visual continuity with adjacent shots.
</system_reminder>
""".strip()
```

Ese añadido sobre el `seed` es exactamente el tipo de regla de dominio que las descriptions de
PostHog codifican y que evita el fallo más frustrante para el usuario.

### 7.4 Lo que NO deberías copiar

- **El `AssistantTool` enum global compartido con TypeScript.** Es correcto para PostHog (frontend
  y backend en un monorepo, con `pnpm schema:build`). Si tu frontend está desacoplado, esta
  validación en `__init_subclass__` se convierte en un acoplamiento de despliegue doloroso. Adopta
  el auto-registro pero **sustituye la validación contra el enum por una comprobación de
  unicidad** del nombre.
- **El barrido `pkgutil` de `products/`.** Sólo tiene sentido con una estructura de monorepo por
  producto. Un `_TOOL_MODULES` explícito como el de `tools/__init__.py` es más simple y suficiente.
- **`MAX_TOOL_CALLS = 24`.** Ese límite está calibrado para tools de segundos. Con generaciones de
  minutos, el límite útil es de tiempo/coste acumulado, no de número de llamadas.

### 7.5 Orden de implementación sugerido

1. `tool_errors.py` (copia literal, renombrado) — es la base de todo lo demás.
2. `MediaTool` base con `create_tool_class`, `response_format="content_and_artifact"`,
   `_arun_impl`, `get_required_resource_access`.
3. El bucle ejecutor con las cuatro capas de captura.
4. `artifacts/base.py` + `manager.py` + `ImageHandler` (el más simple, `aenrich` no-op).
5. Primera tool de escritura: `generate_image`, con artefacto y `ui_payload`.
6. `TimelineHandler` con `ShotRefBlock` → `ShotBlock`/`ErrorBlock`/`LoadingBlock`.
7. `is_dangerous_operation` + jobs asíncronos con `LoadingBlock`.
8. Modos preproducción/producción con toolkits distintos + `ApproveShotListTool`.
9. `read_style_library` con unión discriminada y el párrafo anti-alucinación.
10. Adaptador MCP para exponer la biblioteca de assets a agentes externos.

---

## Índice de ficheros citados

| Ruta | Contenido |
|---|---|
| `C:\ph\ee\hogai\tool.py` | `MaxTool`, `MaxSubtool`, `ToolMessagesArtifact`, `ApprovalRequest`, `ClientToolCallRequest` |
| `C:\ph\ee\hogai\registry.py` | Registro de tools contextuales, descubrimiento por producto |
| `C:\ph\ee\hogai\tool_errors.py` | Taxonomía de errores con `retry_strategy` |
| `C:\ph\ee\hogai\mcp_tool.py` | `MCPTool`, `MCPToolRegistry` (PostHog como servidor MCP) |
| `C:\ph\ee\hogai\tools\__init__.py` | Carga perezosa PEP 562, `load_all_tools()` |
| `C:\ph\ee\hogai\core\agent_modes\executables.py` | Bucle del agente, `AgentToolsExecutable` (captura de errores) |
| `C:\ph\ee\hogai\chat_agent\toolkit.py` | Toolkits por modo, tools contextuales, inyección MCP y web_search |
| `C:\ph\ee\hogai\context\context.py` | `get_contextual_tools()`, `_get_contextual_tools_prompt()` |
| `C:\ph\ee\hogai\artifacts\types.py` | `StoredContent` vs `ArtifactContent`, wrappers de origen |
| `C:\ph\ee\hogai\artifacts\manager.py` | `ArtifactManager` (crear, actualizar, obtener, enriquecer) |
| `C:\ph\ee\hogai\artifacts\handlers\base.py` | `ArtifactHandler`, `HANDLER_REGISTRY`, `@register_handler` |
| `C:\ph\ee\hogai\artifacts\handlers\visualization.py` | Handler multi-origen (STATE/ARTIFACT/INSIGHT) |
| `C:\ph\ee\hogai\artifacts\handlers\notebook.py` | Handler con resolución de refs y degradación a `ErrorBlock` |
| `C:\ph\ee\hogai\tools\execute_sql\tool.py` | Tool que produce artefacto + `ui_payload` |
| `C:\ph\ee\hogai\tools\create_notebook\tool.py` | Artefactos transitorios vs guardados, `ArtifactStatus` |
| `C:\ph\ee\hogai\tools\finalize_plan\tool.py` | Aprobación incondicional como gate de fase |
| `C:\ph\ee\hogai\tools\upsert_dashboard\tool.py` | Upsert discriminado, aprobación condicional con diff |
| `C:\ph\ee\hogai\tools\upsert_dashboard\prompts.py` | `UPSERT_DASHBOARD_TOOL_PROMPT`, `PERMISSION_REQUEST_PROMPT` |
| `C:\ph\ee\hogai\tools\create_insight.py` | Description dinámica, prompts de fallo con `<system_reminder>` |
| `C:\ph\ee\hogai\tools\read_data\tool.py` | Unión discriminada dinámica según permisos, despacho con `match` |
| `C:\ph\ee\hogai\tools\read_data\prompts.py` | Descriptions compuestas por sección |
| `C:\ph\ee\hogai\tools\read_taxonomy\tool.py` | `args_schema` dinámico con `Literal` desde BD |
| `C:\ph\ee\hogai\tools\full_text_search\tool.py` | `MaxSubtool` (lógica no expuesta al LLM) |
| `C:\ph\ee\hogai\tools\call_mcp_server\tool.py` | Cliente MCP: descubrimiento en 2 fases, aprobación por tool |
