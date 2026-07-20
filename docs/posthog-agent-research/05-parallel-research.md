# Subsistemas avanzados de Max AI (PostHog) — análisis técnico

Base: `C:\ph\ee\hogai`. Destino: agente de generación de cinematografías (guion → shot list → prompts → generación paralela de imágenes/vídeos → ensamblado).

---

## 1. EJECUCIÓN PARALELA DE TAREAS

Ruta: `ee/hogai/chat_agent/parallel_task_execution/{nodes.py, mixins.py, prompts.py}`

### 1.1 El contrato de tipos

`ee/hogai/chat_agent/parallel_task_execution/nodes.py`:

```python
# Type definitions for task execution
# Each task is represented as a tuple containing:
# 1. The task item with metadata (id, description, status)
# 2. Any input artifacts from previous tasks
# 3. A callable that returns a coroutine to execute the actual task logic
# Note: The callable can return None to indicate a task that produces no result
TaskExecutionCoroutineCallable = Callable[[dict], Coroutine[Any, Any, TaskResult | None]]
TaskExecutionInputTuple = tuple[AssistantToolCall, list[TaskArtifact], TaskExecutionCoroutineCallable]

StateT = TypeVar("StateT", bound=BaseState)
PartialStateT = TypeVar("PartialStateT", bound=BaseStateWithTasks)
```

La clave arquitectónica: **una tarea = (metadatos, artefactos de entrada, corrutina)**. La corrutina recibe un `dict` plano, no argumentos posicionales, lo que permite que el runner sea totalmente agnóstico del tipo de trabajo.

### 1.2 El nodo base

```python
class BaseTaskExecutorNode(BaseAssistantNode[StateT, PartialStateT], Generic[StateT, PartialStateT]):
    """
    Abstract base class for task execution nodes that handles parallel task execution.

    Key features:
    - Parallel execution of multiple independent tasks
    - Real-time progress updates via reasoning messages or task execution messages
    - Graceful error handling with task isolation (one task failure doesn't affect others)
    - Artifact tracking and dependency management between tasks

    Subclasses must implement:
    - _aget_input_tuples(): Convert state into executable task tuples
    - _aget_final_state(): Aggregate results into final state
    """

    _reasoning_callback: Callable[[str, str | None], Coroutine[Any, Any, None]]

    async def arun(self, state: StateT, config: RunnableConfig) -> PartialStateT:
        if not isinstance(state, BaseStateWithMessages):
            raise ValueError("State is not a BaseStateWithMessages")
        messages = state.messages
        last_message = find_last_message_of_type(messages, AssistantMessage)
        if not last_message or not last_message.tool_calls:
            raise ValueError("No last message found or no tool calls found")
        tool_calls = last_message.tool_calls
        self.dispatcher.message(last_message)
        return await self.aexecute(tool_calls, config)
```

Nótese que **el fan-out lo decide el LLM**: el modelo emite N `tool_calls` en un solo mensaje (gracias a `parallel_tool_calls=True`, ver §2.3), y cada tool call se convierte en una tarea concurrente. No hay un planificador separado.

### 1.3 Orquestación y agregación

```python
    async def aexecute(self, tool_calls: list[AssistantToolCall], config: RunnableConfig) -> PartialStateT:
        """
        Core execution logic that orchestrates parallel task execution.

        This method:
        1. Retrieves tasks to execute from the tool calls
        2. Sets up progress callbacks based on task count
        3. Executes tasks in parallel
        4. Updates task statuses in real-time
        5. Aggregates results into final state
        """
        # Get the tasks and their execution coroutines
        input_tuples = await self._aget_input_tuples(tool_calls)
        if len(input_tuples) == 0:
            raise ValueError("No input tuples provided")

        # Execute tasks in parallel and collect results as they complete
        task_results: list[TaskResult] = []
        messages = []
        async for task_id, task_result in self._aexecute_tasks(config, input_tuples):
            task_results.append(task_result)

            message = AssistantToolCallMessage(
                content=task_result.result,
                id=str(uuid.uuid4()),
                tool_call_id=task_id,
            )
            messages.append(message)
            self.dispatcher.message(message)

        # Aggregate all results into the final state
        return await self._aget_final_state(task_results)
```

El streaming es **por-tarea-completada**: cada resultado se emite al usuario en cuanto llega (`self.dispatcher.message(message)`), sin esperar al batch completo.

### 1.4 El motor concurrente (bloque literal completo)

```python
    async def _aexecute_tasks(
        self, config: RunnableConfig, input_tuples: list[TaskExecutionInputTuple]
    ) -> AsyncIterator[tuple[str, TaskResult]]:
        """
        Execute multiple tasks in parallel and yield results as they complete.

        This method implements true parallel execution by:
        1. Starting all tasks immediately as asyncio tasks
        2. Yielding results in completion order (fastest task first)
        3. Continuing execution even if individual tasks fail
        4. Canceling remaining tasks if a critical error occurs
        """
        try:
            # Start all tasks in parallel immediately
            tasks_with_ids: list[tuple[str, asyncio.Task[TaskResult]]] = []

            for task, artifacts, task_callable in input_tuples:
                # Create input dictionary containing all necessary data for task execution
                input_dict = {
                    "task_id": task.id,
                    "task": task,
                    "artifacts": artifacts,  # Previous tasks' outputs that this task depends on
                    "config": config,
                }

                # Create wrapper coroutine that calls the task callable with the input
                # This closure captures the callable and input_dict for each task
                async def execute_task(callable_func=task_callable, input_data=input_dict):
                    return await callable_func(input_data)

                # Create and start asyncio task immediately - they run concurrently
                async_task = asyncio.create_task(execute_task())
                tasks_with_ids.append((task.id, async_task))

            # Create mapping for tracking pending tasks
            # Maps asyncio.Task -> task_id for result correlation
            pending_tasks = {task: task_id for task_id, task in tasks_with_ids}

            # Yield results as each task completes (in completion order, not submission order)
            while pending_tasks:
                # Wait for ANY task to complete and immediately yield its result
                done, _ = await asyncio.wait(pending_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)

                # Process and yield results immediately as they complete
                for completed_task in done:
                    task_id = pending_tasks.pop(completed_task)
                    try:
                        task_result = await completed_task
                        if task_result is not None:
                            yield task_id, task_result
                    except Exception as task_error:
                        # Log the error but continue processing other tasks
                        # This ensures one task failure doesn't stop the entire batch
                        logger.exception(f"Task {task_id} failed", error=str(task_error))
                        continue

        except Exception as e:
            # Critical error occurred - clean up and re-raise
            capture_exception(e)

            # Cancel any remaining running tasks to prevent resource leaks
            for _, async_task in tasks_with_ids:
                if not async_task.done():
                    async_task.cancel()
            raise
```

**Detalles críticos a copiar:**

1. `async def execute_task(callable_func=task_callable, input_data=input_dict)` — el truco de los **argumentos por defecto para capturar el valor del bucle**. Sin esto, todas las closures capturarían la última iteración. Es el bug clásico de Python en fan-out.
2. `asyncio.wait(..., return_when=asyncio.FIRST_COMPLETED)` en bucle `while pending_tasks` en lugar de `asyncio.gather`. Da **orden de finalización**, no de envío → el usuario ve el shot más rápido primero.
3. El `try/except Exception ... continue` dentro del bucle de resultados: **aislamiento de fallos**. Un shot que falla no tumba los otros 11.
4. El `except` exterior cancela las tareas pendientes para evitar fugas de recursos.

### 1.5 Fallos parciales: dos estrategias distintas

**(a) Fallo blando — se devuelve un `TaskResult` con `status=FAILED`** (`mixins.py`):

```python
        if len(subgraph_result_messages) == 0 or not subgraph_result_messages[-1]:
            logger.warning("Task failed: no messages received from insights subgraph", task_id=task.id)
            return TaskResult(
                id=task.id,
                result="",
                artifacts=[],
                status=TaskExecutionStatus.FAILED,
            )
        ...
        artifacts = await self._extract_artifacts(subgraph_result_messages, task)
        if len(artifacts) == 0:
            response += "\n\nNo artifacts were generated."
            logger.warning("Task failed: no artifacts extracted", task_id=task.id)
            return TaskResult(id=task.id, result=response, artifacts=[], status=TaskExecutionStatus.FAILED)

        return TaskResult(
            id=task.id,
            result=response,
            artifacts=artifacts,
            status=TaskExecutionStatus.COMPLETED,
        )
```

Y en `_execute_search_insights`, incluso se capturan las excepciones dentro de la tarea:

```python
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Task failed with exception: {e}", task_id=task.id)
            return TaskResult(id=task.id, result="", artifacts=[], status=TaskExecutionStatus.FAILED)
```

**(b) Fallo con umbral — abortar si demasiadas subtareas fallan.** Este patrón está en `ee/hogai/videos/session_moments.py` (§4) y es el más relevante para nosotros:

```python
        # Check if enough moments were generated
        expected_min_moments = ceil(len(moments_input) * failed_moments_min_ratio)
        if expected_min_moments > len(moment_to_asset_id):
            exception_message = f"Not enough moments were generated ..."
            logger.exception(exception_message)
            # Remove all the generated videos to not bloat the database
            asset_ids = list(moment_to_asset_id.values())
            await ExportedAsset.objects.filter(id__in=asset_ids).adelete()
            raise Exception(exception_message)
        return moment_to_asset_id
```

Es decir: **política de ratio mínimo de éxito + rollback/limpieza de los artefactos parciales**. Compárese con la constante correspondiente en `ee/hogai/session_summaries/constants.py`:

```python
FAILED_MOMENTS_MIN_RATIO = 0.5  # If less than 50% of moments failed to generate videos, fail the analysis
# Continue if `successes >= max(min(FLOOR, ceil(total/2)), total * RATIO)` (floor capped at majority of input).
GROUP_SUMMARY_MIN_SUCCESS_FLOOR = 3
GROUP_SUMMARY_MIN_SUCCESS_RATIO = 0.3
```

### 1.6 Cada subtarea es un subgrafo completo, no una llamada suelta

`mixins.py`, `WithInsightCreationTaskExecution._execute_create_insight`:

```python
    async def _execute_create_insight(self, input_dict: dict) -> TaskResult | None:
        """Execute a single task using the full insights pipeline."""
        from ee.hogai.chat_agent.insights_graph.graph import InsightsGraph

        task = cast(AssistantToolCall, input_dict["task"])
        artifacts = input_dict["artifacts"]
        config = input_dict.get("config")

        self._current_task_id = task.id
        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"
        query = task.args["query_description"]

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(task_prompt=query)

        human_message = HumanMessage(content=formatted_instructions, id=str(uuid.uuid4()))
        input_state = AssistantState(
            messages=[human_message],
            start_id=human_message.id,
            root_tool_call_id=task_tool_call_id,
            root_tool_insight_plan=query,
        )

        subgraph_result_messages: list[AssistantMessageUnion] = []
        assistant_graph = InsightsGraph(self._team, self._user).compile_full_graph()
        try:
            async for chunk in assistant_graph.astream(
                input_state, config, subgraphs=True, stream_mode=["updates"],
            ):
                if not chunk:
                    continue
                update = extract_stream_update(chunk)
                if is_value_update(update):
                    _, content = update
                    node_name = next(iter(content.keys()))
                    messages = content[node_name]["messages"]
                    subgraph_result_messages.extend(messages)
                    for message in messages:
                        self.dispatcher.message(message)
        except Exception as e:
            capture_exception(e)
            raise
```

Cada subtarea instancia **su propio grafo con su propio estado aislado** (`AssistantState` fresco) y hace streaming de vuelta al dispatcher padre. Aislamiento de estado total entre subtareas concurrentes.

### 1.7 El prompt de subtarea

`ee/hogai/chat_agent/parallel_task_execution/prompts.py` — este prompt existe para un único fin: **impedir que la subtarea pregunte al usuario**, porque no hay usuario al otro lado de una subtarea paralela.

```
AGENT_SUBGRAPH_SYSTEM_PROMPT = """
You are a research assistant executing specific analysis tasks. Your goal is to complete the requested analysis with the available data without asking clarifying questions.
CRITICAL INSTRUCTIONS:
- IMPORTANT: DO NOT ask the user for clarification or additional information
- Work with the data and context you have available
- Make reasonable assumptions when details are unclear
- If you cannot complete a task due to missing data, state what data is missing and provide the best analysis possible with available information
- Focus on providing actionable insights rather than asking questions
TASK EXECUTION APPROACH:
1. Analyze the task request and identify the key metrics/data needed
2. Use available data sources to fulfill the request
3. Make reasonable assumptions about time ranges, filters, or parameters if not specified
4. Provide clear, actionable insights based on the analysis
5. If data is limited, explain the limitations but still provide useful analysis
EXAMPLES OF GOOD RESPONSES:
- "Based on the available pageview data, here's the trends chart for the last 30 days..."
...
EXAMPLES TO AVOID:
- "Could you clarify which specific metrics you'd like to see?"
- "What time range would you prefer for this analysis?"
...
Remember: Your role is to execute the research task efficiently without back-and-forth clarification.
"""

AGENT_TASK_PROMPT_TEMPLATE = (
    AGENT_SUBGRAPH_SYSTEM_PROMPT + "\n\nCurrent task: {task_prompt}\n"
    "Execute this analysis task completely and autonomously. Use your best judgment for any unclear aspects and provide comprehensive insights."
)
```

### ▶ MAPEO A CINEMATOGRAFÍAS

| PostHog | Nuestro agente |
|---|---|
| `AssistantToolCall` (una por insight) | Un shot de la shot list (`shot_id`, `prompt`, `duration`, `aspect`) |
| `TaskExecutionInputTuple` | `(ShotSpec, [assets_previos], render_coroutine)` |
| `_aget_input_tuples()` | Convierte la shot list en N corrutinas de generación |
| `_aexecute_tasks()` | **Copiar tal cual.** Lanza N generaciones de imagen/vídeo en Higgsfield/Runway/Kling |
| `yield` en orden de finalización | El usuario ve los shots renderizados según llegan, no en orden de guion |
| `TaskResult(status=FAILED)` | Shot fallido → placeholder / reintento / marca en el ensamblado |
| `failed_moments_min_ratio` + borrado de assets | Si <50% de shots renderizan, abortar la cinematografía y **borrar los assets parciales** (cuestan dinero y ocupan storage) |
| `TaskArtifact` con `task_id` | El asset (URL de imagen/vídeo) devuelto por shot, referenciable en el ensamblado |
| `AGENT_SUBGRAPH_SYSTEM_PROMPT` | Prompt del generador de shot: prohibido pedir aclaraciones, asumir defaults de cámara/lente/luz |
| Subgrafo completo por tarea | Cada shot puede ser un mini-pipeline: prompt → imagen keyframe → img2vid → upscale |

Un detalle a **no** copiar directamente: no hay límite de concurrencia (`Semaphore`). PostHog lanza todo a la vez. Con APIs de generación de vídeo con rate limits y coste por llamada, hay que envolver `execute_task` en un `asyncio.Semaphore(N)`.

---

## 2. RESEARCH AGENT

Ruta: `ee/hogai/research_agent/{graph.py, runner.py, mode_manager.py, executables.py, prompts/}`

### 2.1 Arquitectura: dos "supermodos" secuenciales

`ee/hogai/research_agent/graph.py` es sorprendentemente pequeño:

```python
class ResearchAgentGraph(AgentLoopGraph):
    @property
    def mode_manager_class(self) -> type[ResearchAgentModeManager]:
        return ResearchAgentModeManager

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.DEEP_RESEARCH

    def compile_full_graph(self, checkpointer=None):
        return (
            self.add_agent_node(is_start_node=True)
            .add_agent_tools_node()
            .add_title_generator()
            .compile(checkpointer=checkpointer)
        )
```

El grafo es sólo **agente ↔ herramientas** (bucle ReAct clásico). Toda la complejidad está en el *mode manager*: qué prompt de sistema y qué toolkit se inyectan según el estado.

`ee/hogai/research_agent/mode_manager.py` define dos niveles:

- **supermode**: `PLAN` → `RESEARCH`. Cambia el prompt de sistema y el toolkit global.
- **mode**: `PRODUCT_ANALYTICS | SQL | SESSION_REPLAY | ERROR_TRACKING | FLAGS | LLM_ANALYTICS`. Cambia las herramientas de dominio.

```python
    @property
    def supermode_registries(self):
        default_mode_registry = {
            AgentMode.SQL: research_agent_sql_agent,
            AgentMode.LLM_ANALYTICS: research_agent_ai_observability_agent,
            AgentMode.SESSION_REPLAY: research_agent_session_replay_agent,
            AgentMode.ERROR_TRACKING: research_agent_error_tracking_agent,
            AgentMode.PRODUCT_ANALYTICS: research_agent_product_analytics_agent,
            AgentMode.FLAGS: research_agent_flags_agent,
        }
        return {
            AgentMode.PLAN: {
                **default_mode_registry,
                AgentMode.RESEARCH: research_agent,   # sólo desde PLAN se puede saltar a RESEARCH
            },
            AgentMode.RESEARCH: default_mode_registry,
        }

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        return ResearchAgentPromptBuilder if self._supermode == AgentMode.RESEARCH else PlanAgentPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        return ResearchAgentToolkit if self._supermode == AgentMode.RESEARCH else PlanAgentToolkit
```

Toolkits distintos por fase:

```python
DEFAULT_TOOLS: list[type["MaxTool"]] = [
    ReadTaxonomyTool, SearchTool, TodoWriteTool, SwitchModeTool, CreateNotebookTool, TaskTool,
]

class PlanAgentToolkit(AgentToolkit):
    @property
    def tools(self): return [*DEFAULT_TOOLS, CreateFormTool, FinalizePlanTool]

class ResearchAgentToolkit(AgentToolkit):
    @property
    def tools(self): return DEFAULT_TOOLS
```

`CreateFormTool` (preguntar al usuario) y `FinalizePlanTool` **sólo existen en modo PLAN**. Una vez en RESEARCH, el agente físicamente no puede preguntar. La restricción se impone por disponibilidad de herramientas, no por prompt.

### 2.2 La transición PLAN → RESEARCH

`ee/hogai/research_agent/executables.py`:

```python
SWITCH_TO_RESEARCH_MODE_PROMPT = """
Successfully switched to research mode. Planning is over, you can now proceed with the actual research.

You MUST continue executing the plan until it is complete. Do not respond with text only - proceed with tool calls until you have completed the tasks.
"""


class ResearchAgentToolsExecutable(PlanModeToolsExecutable):
    @property
    def transition_supermode(self) -> AgentMode:
        return AgentMode.RESEARCH

    async def get_transition_prompt(self) -> str:
        return SWITCH_TO_RESEARCH_MODE_PROMPT

    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        # Transition when switch_mode tool switches to RESEARCH mode while in PLAN supermode
        return state.supermode == AgentMode.PLAN and result.agent_mode == AgentMode.RESEARCH
```

### 2.3 Configuración del modelo

```python
class ResearchAgentExecutable(PlanModeExecutable):
    MAX_TOOL_CALLS = 1_000_000
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 4096}
    MAX_TOKENS = 16_384

    def _get_model(self, state: AssistantState, tools: list["MaxTool"]):
        is_research_mode = state.supermode == AgentMode.RESEARCH
        model_name = "claude-opus-4-6" if is_research_mode else "claude-sonnet-4-6"

        base_model = MaxChatAnthropic(
            model=model_name,
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            betas=["interleaved-thinking-2025-05-14"],
            max_tokens=self.MAX_TOKENS,
            thinking=self.THINKING_CONFIG,
            conversation_start_dt=state.start_dt,
            billable=True,
        )

        return base_model.bind_tools(tools, parallel_tool_calls=True)
```

Puntos: **modelo más potente en la fase cara** (Opus para research, Sonnet para plan), `interleaved-thinking` beta (razonar *entre* tool calls, no sólo antes), `MAX_TOOL_CALLS = 1_000_000` (efectivamente sin límite: el agente para cuando termina, no cuando se agota un contador), y `parallel_tool_calls=True` que es lo que habilita el fan-out de §1.

### 2.4 El bucle: draft-driven research

Éste es el corazón conceptual. `ee/hogai/research_agent/prompts/research.py`:

```
RESEARCH_MODE_PROMPT = """
<goal>
You are currently operating as a research agent.
...
Your workflow follows a draft-first approach where the draft notebook guides all research:
1. **Create an initial draft** (using `create_notebook` with `draft_content`) that contains your hypotheses, expected findings, and open questions - this draft is intentionally incomplete and uncertain
2. **Let the draft drive research** - examine your draft to identify what's uncertain or unverified, then use tools to resolve those specific uncertainties
3. **Revise the draft after each finding** - integrate new information immediately, replacing hypotheses with verified facts
4. **Repeat until complete** - continue the research-revise cycle until no uncertainties remain
5. **Publish the final report** (using `create_notebook` with `content`) once the draft has evolved into a fully verified document

Guidelines:
- Avoid asking users clarifying questions - the user has already provided all the information you need
- Use the `todo_write` tool to track which sections of your draft still need verification
- The draft notebook is your source of truth - always consult it to decide what to research next
- Each tool call should target a specific uncertainty in your current draft
- Decompose complex investigations using the `task` tool for parallel verification
- **Do as many iterations as necessary** to revise the draft notebook - do not settle for a draft with remaining [UNVERIFIED] or [TODO] markers when more research could resolve them, and always ask yourself if one more round of revision/research would bring more value to the user
- **If in doubt, stop** - it is better to publish a report that honestly marks remaining uncertainties than to fabricate or speculate beyond what the data supports, or to iterate just for the sake of it
</goal>
""".strip()
```

Y el mecanismo concreto de terminación:

```
RESEARCH_TASK_PROMPT = """
<research_task>
Your research follows a continuous draft-refinement cycle:

1. **Draft first** - Write an initial draft with your best hypotheses, marking uncertain claims with [UNVERIFIED] and gaps with [TODO: question]
2. **Identify uncertainties** - Scan your draft for [UNVERIFIED] claims and [TODO] gaps - these are your research targets
3. **Investigate** - Use tools to verify or refute the most important uncertainty. Run parallel investigations for independent questions.
4. **Revise immediately** - Update the draft with findings: replace [UNVERIFIED] with verified facts, fill [TODO] gaps, or remove disproven hypotheses
5. **Repeat** - Return to step 2 until no uncertainties remain
6. **Finalize** - Publish the clean draft as the final report

# Example cycle
Initial draft section:
```
## Conversion Rate Analysis
[UNVERIFIED] Conversion rates have dropped significantly in October
[TODO: Quantify the drop and identify start date]
[TODO: Identify which user segments are most affected]
```

After first research cycle:
```
## Conversion Rate Analysis
Conversion rates dropped **30%** starting October 1st (verified via funnel analysis)
[UNVERIFIED] Mobile users appear most affected based on initial segmentation
[TODO: Confirm mobile vs desktop breakdown with statistical significance]
```

After second cycle:
```
## Conversion Rate Analysis
Conversion rates dropped **30%** starting October 1st (verified via funnel analysis)
Mobile users experienced a **42% drop** vs **18% for desktop** (p<0.01)
[TODO: Investigate mobile-specific checkout flow changes]
```

The cycle continues until all sections are fully verified with no remaining [UNVERIFIED] or [TODO] markers.
</research_task>
"""
```

**La idea genial**: el criterio de terminación del bucle no es un contador ni una decisión difusa del LLM — es una **condición sintáctica verificable sobre un artefacto persistente**: "¿queda algún `[UNVERIFIED]` o `[TODO]` en el documento?". El documento *es* la lista de tareas. Esto convierte un bucle agéntico abierto en algo con estado inspeccionable y condición de parada objetiva.

Y `REPORT_PROMPT` formaliza los marcadores:

```
# Draft structure
Use explicit markers to track verification status:
- `[UNVERIFIED]` - Claims based on hypothesis or incomplete data, requiring verification
- `[TODO: specific question]` - Gaps that need investigation
- `[VERIFIED]` - (optional) Claims confirmed by data - or simply state facts without markers

Your draft should read like a final report, except with uncertainty markers showing what still needs work.
...
# Requirements
- Always include an **Executive Summary table** at the top of the final report summarizing key findings
- Reference insights using <insight>{{artifact_id}}</insight> tags with the insight's id
- Each research action should target a specific [UNVERIFIED] or [TODO] in your draft
- DO NOT add data points that do not derive from the insights generated during this research (no "outside" knowledge)
- DO NOT infer patterns without data to support them
- DO NOT make things up - better to mark as [TODO] than include unverified information
- Each insight can be referenced only ONCE in the whole report
```

`<insight>{{artifact_id}}</insight>` es cómo se **embeben artefactos binarios/estructurados dentro de un documento de texto** generado por el LLM. El LLM nunca manipula la gráfica; sólo escribe su ID.

### 2.5 La fase de planificación

`ee/hogai/research_agent/prompts/plan.py`:

```
PLAN_MODE_PROMPT = """
<goal>
You are currently operating in planning mode.
...
You have three tasks to perform in this session:
1. Clarify the user's request by asking up to 4 questions, using the create_form tool
2. Write a research plan using the `finalize_plan` tool
3. Get user approval, then switch to `research` mode using switch_mode to proceed with the actual research
...
- Tool results and user messages may include <system_reminder> tags. <system_reminder> tags contain useful information and reminders. They are NOT part of the user's provided input or the tool result.
</goal>
"""

ONBOARDING_TASK_PROMPT = """
<initial_clarifications_task>
After the user has sent their request, your first task is to clarify the task by asking the user up to 4 questions, using a form.

# Ground your questions
Before asking these questions, you should research the user's project data using the read and search tools, to ground your questions.

# Questions areas
Cover these 4 essential areas (keep it focused):
- **Core objective**: What specific question are they trying to answer or goal they want to achieve?
- **Scope**: Which users, timeframe, and features/funnels matter?
- **Success metrics**: What KPIs define success? Any comparison points?
- **Context**: Recent changes, working hypotheses, or constraints?

# Requirements
- Be thorough but concise - this is your only chance to gather context
- IMPORTANT: If the user's input already provides details for any areas, acknowledge what they've shared and skip those questions
- Aim for 4 questions maximum, but use fewer if the user has already covered some areas
- Natural, conversational tone - like a helpful analyst's first meeting
</initial_clarifications_task>
"""
```

"**Ground your questions**": investigar *antes* de preguntar, para preguntar cosas informadas. Y "esto es tu única oportunidad de recopilar contexto" — un solo formulario, no un ping-pong.

### 2.6 Gestión de todos

`ee/hogai/research_agent/prompts/base.py`, `TASK_MANAGEMENT_PROMPT`:

```
You have access to the `todo_write` tool for managing and planning tasks. Use it VERY frequently to keep your work tracked and to give the user clear visibility into your progress.
The tool is also EXTREMELY useful for planning—especially for breaking larger, complex tasks into smaller steps. If you don't use it during planning, you may miss important tasks, which is unacceptable.

It's critical to mark todos as completed the moment you finish a task. Do not batch multiple completions.
```

### ▶ MAPEO A CINEMATOGRAFÍAS

| PostHog | Nuestro agente |
|---|---|
| supermode `PLAN` | **Fase de guion**: clarificar la idea con un formulario de ≤4 preguntas (tono, duración, estilo visual, referencias), producir el treatment |
| `create_form` + `finalize_plan` (sólo en PLAN) | Formulario de brief creativo + aprobación del guion antes de gastar créditos de generación |
| supermode `RESEARCH` | **Fase de producción**: sin preguntas, ejecutar hasta terminar |
| `SWITCH_TO_RESEARCH_MODE_PROMPT` ("Do not respond with text only") | Evita que el agente se quede describiendo lo que va a hacer en vez de generar |
| Draft con `[UNVERIFIED]`/`[TODO]` | **Shot list con marcadores de estado**: `[PENDING]`, `[GENERATING]`, `[NEEDS_RETAKE: motivo]`, `[APPROVED]`. Bucle: ¿queda algún shot no aprobado? → siguiente iteración |
| Notebook como fuente de verdad | El documento de shot list es el estado del proyecto; el agente lo relee para decidir qué renderizar |
| `<insight>{{artifact_id}}</insight>` | `<shot>{{asset_id}}</shot>` — el guion final referencia assets por ID, el ensamblador los resuelve |
| "Each insight referenced only ONCE" | Cada asset generado se usa una sola vez en el timeline (evita duplicados en el montaje) |
| Modelo Opus en research / Sonnet en plan | Modelo caro sólo para escribir prompts de shot; modelo barato para la conversación de brief |
| `parallel_tool_calls=True` | Sin esto no hay fan-out de §1 |
| modos SQL/Replay/Analytics | Modos por *tipo de shot*: `t2i`, `i2v`, `v2v`, `upscale`, `audio` — cada uno con su toolkit |

---

## 3. SANDBOX

Ruta: `ee/hogai/sandbox/{executor.py, types.py, mapping.py}`

### 3.1 Qué es realmente

No es un `exec()` con guardarraíles. Es una **delegación completa a infraestructura externa**: el código generado se ejecuta dentro de un contenedor gestionado por un workflow de Temporal (`ProcessTaskWorkflow`, producto "tasks"), y PostHog sólo hace de *relay* de eventos. El proceso Python de Django nunca ejecuta código del LLM.

Arquitectura: `Django view → tasks_facade.create_and_run_task() → Temporal workflow → contenedor sandbox → agente ACP → Redis Stream → SSE al navegador`.

### 3.2 Protocolo ACP

`ee/hogai/sandbox/types.py` (completo):

```python
# ACP (Agent Communication Protocol) notification methods
ACP_NOTIFICATION_TYPE = "notification"
ACP_METHOD_SESSION_UPDATE = "session/update"

# Sandbox-specific notification methods
TURN_COMPLETE_METHOD = "_posthog/turn_complete"

# Stop reasons
STOP_REASON_END_TURN = "end_turn"


def is_turn_complete(event: dict) -> bool:
    """Check if an ACP event signals the agent finished a turn.

    Matches both the raw ACP prompt response (``result.stopReason == "end_turn"``)
    and the synthetic ``_posthog/turn_complete`` notification.
    """
    if event.get("type") != ACP_NOTIFICATION_TYPE:
        return False
    notification = event.get("notification", {})
    if notification.get("method") == TURN_COMPLETE_METHOD:
        return True
    result = notification.get("result")
    return isinstance(result, dict) and result.get("stopReason") == STOP_REASON_END_TURN


ACP_SESSION_UPDATE_AGENT_MESSAGE_CHUNK = "agent_message_chunk"


class SandboxSeedEvent(BaseModel):
    """Event written to the Redis stream to initialize it before the relay starts."""
    type: Literal["STREAM_STATUS"] = "STREAM_STATUS"
    status: str = "initializing"


class ACPTextContent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    text: str = ""


class ACPSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")
    sessionUpdate: str
    content: ACPTextContent | None = None
```

`model_config = ConfigDict(extra="allow")` en todos los modelos ACP: **tolerancia hacia adelante**. El sandbox puede emitir campos que el backend aún no conoce sin romper el parseo.

### 3.3 Ciclo de vida y snapshots

`ee/hogai/sandbox/executor.py`:

```python
SANDBOX_TURN_IDLE_TIMEOUT = 60  # seconds of silence before ending the per-turn stream (safety fallback)
SANDBOX_STREAM_TTL = 3600  # seconds before the Redis stream key expires
```

Gate de permisos primero:

```python
    if not settings.DEBUG and not has_sandbox_mode_feature_flag(team, user):
        raise exceptions.PermissionDenied("Sandbox mode is not enabled for this user.")
```

Reanudación desde snapshot cuando el sandbox previo ha muerto:

```python
        if task_run.is_terminal:
            snapshot_ext_id = (task_run.state or {}).get("snapshot_external_id")
            if not snapshot_ext_id:
                raise exceptions.ValidationError("Sandbox session has ended and no snapshot is available.")

            new_run = tasks_facade.create_run(
                task_run.task_id,
                mode="interactive",
                extra_state={
                    "snapshot_external_id": snapshot_ext_id,
                    "resume_from_run_id": str(task_run.id),
                    "pending_user_message": content,
                },
            )
```

Y si sigue vivo, se le manda un *signal* de Temporal en vez de crear un run nuevo:

```python
            client = sync_connect()
            handle = client.get_workflow_handle(task_run.workflow_id)

            async def _send_signal():
                await handle.signal(ProcessTaskWorkflow.send_followup_message, content)

            asgi_async_to_sync(_send_signal)()
```

Persistencia del mapping conversación↔sandbox en Redis, con reconstrucción desde la BD si Redis expiró:

```python
    mapping = get_sandbox_mapping(conversation_id)

    # Reconstruct mapping from conversation fields if Redis expired
    if not mapping and conversation.sandbox_task_id and conversation.sandbox_run_id:
        mapping = {
            "task_id": str(conversation.sandbox_task_id),
            "run_id": str(conversation.sandbox_run_id),
        }
```

### 3.4 El relay: desacoplar el timeout del generador

Esto es un patrón fino y reutilizable:

```python
    # Use a queue to decouple the idle-timeout from the async generator.
    # asyncio.wait_for on __anext__() would cancel and close the generator,
    # so we run the reader in a background task instead.
    class _Sentinel(enum.Enum):
        END = "end"

    event_queue: asyncio.Queue[dict[str, Any] | _Sentinel] = asyncio.Queue()

    async def _reader() -> None:
        try:
            async for ev in redis_stream.read_stream(start_id=start_id):
                await event_queue.put(ev)
        except TaskRunStreamError as exc:
            await event_queue.put({"_error": str(exc)})
        finally:
            await event_queue.put(_Sentinel.END)

    reader_task = asyncio.create_task(_reader())
    agent_text_chunks: list[str] = []

    try:
        event_count = 0
        saw_data = False
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=SANDBOX_TURN_IDLE_TIMEOUT)
            except TimeoutError:
                if saw_data:
                    logger.info("sandbox_stream_turn_idle", run_id=run_id, total_events=event_count)
                    break
                # Haven't seen any data yet; keep waiting (sandbox still booting)
                continue
            ...
```

La distinción `saw_data`: **el timeout de arranque en frío es infinito, el de inactividad es 60s**. Un sandbox arrancando puede tardar mucho; uno que ya emitió y se calló 60s, ha terminado.

Reanudación sin replay:

```python
def _get_latest_stream_id(run_id: str) -> str:
    """Return the latest entry ID in the task-run Redis stream.

    Used for follow-up messages so we only read events generated AFTER
    the current position (avoiding replay of previous turns).
    """
    stream_key = get_task_run_stream_key(run_id)
    conn = get_redis_connection("default")
    try:
        entries = conn.xrevrange(stream_key, count=1)
        if entries:
            return entries[0][0].decode()
    except Exception:
        logger.warning("_get_latest_stream_id_failed", run_id=run_id, exc_info=True)
    return "0"
```

### ▶ MAPEO A CINEMATOGRAFÍAS

Aplicabilidad **media** — no generamos código arbitrario. Pero sí:

- Si el agente genera **scripts de FFmpeg / edición / After Effects expressions / Remotion**, deben ejecutarse en un contenedor efímero exactamente así, nunca en el proceso de la app.
- **Redis Streams + SSE como bus de progreso** es directamente reutilizable para reportar progreso de renders largos (`shot 3/12 · 47%`) al frontend, con `start_id` para que un reload del navegador no reproduzca todo el historial.
- El patrón **cola + `wait_for` sobre la cola, no sobre el generador** es exactamente lo que necesitamos para renders: timeout infinito mientras la API de vídeo está en cola, timeout corto tras la última señal de progreso.
- **Snapshots** → un proyecto de cinematografía debe poder reanudarse: assets ya generados + estado del timeline persistidos, para no re-renderizar (y re-pagar) lo hecho.
- `SANDBOX_STREAM_TTL = 3600` y `expires_after` en assets → política de caducidad para no acumular vídeos.

---

## 4. `ee/hogai/videos/`

Sólo dos ficheros. Es el subsistema más directamente análogo al nuestro, aunque en sentido inverso (comprensión en vez de generación).

### 4.1 `utils.py` (completo)

```python
def _extract_duration_s(media_info: MediaInfo) -> int:
    for track in media_info.tracks:
        if track.track_type == "General":
            if track.duration is None:
                raise ValueError("General track duration is None")
            # Convert ms to seconds, ceil to avoid grey "not-rendered" frames at the start
            return int(math.ceil(track.duration / 1000.0))
    raise ValueError("No General track found in video to extract duration from")


def get_video_duration_s(video_bytes: bytes) -> int:
    """Extract duration in seconds from video bytes."""
    return _extract_duration_s(MediaInfo.parse(BytesIO(video_bytes)))


def get_video_duration_from_path_s(path: str) -> int:
    """Extract duration in seconds from a video file on disk."""
    return _extract_duration_s(MediaInfo.parse(path))
```

Usa `pymediainfo`, no ffprobe. Y el `math.ceil` con su comentario sobre frames grises es el tipo de detalle que sólo aparece tras sufrirlo.

### 4.2 `session_moments.py` — el pipeline

Tipos de entrada/salida:

```python
@dataclass(frozen=True)
class SessionMomentInput:
    moment_id: str      # ID to identify the moment in mappings (for example, event_uuid)
    timestamp_s: int    # Timestamp to start the video from
    duration_s: int     # How long the video should be
    prompt: str         # Prompt to validate the moment


@dataclass(frozen=True)
class SessionMomentOutput(SessionMomentInput):
    asset_id: int              # Asset ID of the stored video
    video_description: str     # Description of the moment, generated by LLM
    created_at: datetime
    expires_after: datetime
    model_id: str              # What model was used to analyze the video
```

`SessionMomentOutput(SessionMomentInput)` — la salida **hereda** de la entrada. El artefacto lleva siempre su spec original consigo. Trazabilidad gratis.

Pipeline de dos fases:

```python
    async def analyze(
        self, moments_input: list[SessionMomentInput], expires_after_days: int, failed_moments_min_ratio: float
    ) -> list[SessionMomentOutput]:
        # Generate mapping of moments to moment ids
        moment_id_to_moment = {moment.moment_id: moment for moment in moments_input}
        # Generate mapping of created videos (asset IDs) to moment ids
        moment_id_to_asset_id = await self._generate_videos_for_moments(
            moments_input=moments_input,
            expires_after_days=expires_after_days,
            failed_moments_min_ratio=failed_moments_min_ratio,
        )
        # Analyze videos with LLM
        results = await self._analyze_moment_videos_with_llm(
            moment_id_to_asset_id=moment_id_to_asset_id,
            moment_id_to_moment=moment_id_to_moment,
            expires_after_days=expires_after_days,
        )
        return results
```

Fan-out con `TaskGroup` (alternativa a §1.4, más compacta cuando no hace falta streaming incremental):

```python
    async def _generate_videos_for_moments(self, moments_input, expires_after_days, failed_moments_min_ratio) -> dict[str, int]:
        """Generate videos for moments and return mapping of moment_id to asset_id"""
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for moment in moments_input:
                tasks[moment.moment_id] = tg.create_task(
                    self._generate_video_for_single_moment(moment=moment, expires_after_days=expires_after_days)
                )
        # Collect asset IDs
        moment_to_asset_id: dict[str, int] = {}
        for moment_id, task in tasks.items():
            res: int | Exception = task.result()
            if isinstance(res, Exception):
                logger.exception(f"Failed to generate video for moment {moment_id} ...: {res}")
                # Not failing explicitly to avoid failing all the generations if one fails
                continue
            moment_to_asset_id[moment_id] = res
        # Check if enough moments were generated
        expected_min_moments = ceil(len(moments_input) * failed_moments_min_ratio)
        if expected_min_moments > len(moment_to_asset_id):
            exception_message = f"Not enough moments were generated ..."
            logger.exception(exception_message)
            # Remove all the generated videos to not bloat the database
            asset_ids = list(moment_to_asset_id.values())
            await ExportedAsset.objects.filter(id__in=asset_ids).adelete()
            raise Exception(exception_message)
        return moment_to_asset_id
```

**Truco esencial con `TaskGroup`**: las tareas hijas **devuelven** la excepción en vez de lanzarla:

```python
    async def _generate_video_for_single_moment(self, moment, expires_after_days) -> int | Exception:
        try:
            ...
        except Exception as err:  # Workflow retries exhausted
            # Let caller handle the error
            return err
```

Si lanzaran, `TaskGroup` cancelaría todas las hermanas. Devolviendo `int | Exception` se preserva el aislamiento de fallos. Es el equivalente al `try/except ... continue` de §1.4 pero adaptado a `TaskGroup`.

Generación del vídeo vía workflow de Temporal con reintentos y timeout:

```python
            exported_asset = await ExportedAsset.objects.acreate(
                team_id=self.team_id,
                export_format=MOMENT_VIDEO_EXPORT_FORMAT,
                export_context={
                    "session_recording_id": self.session_id,
                    "timestamp": moment.timestamp_s,
                    "duration": moment.duration_s,
                    "playback_speed": SHORT_VALIDATION_VIDEO_PLAYBACK_SPEED,
                    "show_metadata_footer": True,
                },
                created_by=self.user,
                created_at=created_at,
                expires_after=expires_after,
                is_system=True,
            )
            # Generate a video through Temporal workflow
            client = await async_connect()
            await client.execute_workflow(
                "rasterize-recording",
                RasterizeRecordingInputs(exported_asset_id=exported_asset.id),
                id=f"session-moment-video-export_{self.session_id}_{moment.moment_id}_{uuid.uuid4()}",
                task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                execution_timeout=timedelta(minutes=30),
                search_attributes=TypedSearchAttributes(
                    search_attributes=[
                        SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=self.team_id),
                        SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=self.session_id),
                    ]
                ),
            )
            return exported_asset.id
```

`execution_timeout=timedelta(minutes=30)` por vídeo. Los renders son lentos y eso está asumido en el diseño.

Almacenamiento dual (BD o object storage), transparente para el consumidor:

```python
            asset = await ExportedAsset.objects.aget(id=asset_id)
            if asset.content:
                # Content stored directly in database
                content = bytes(asset.content)
            elif asset.content_location:
                # Content stored in object storage
                content = await database_sync_to_async(object_storage.read_bytes, thread_sensitive=False)(
                    asset.content_location
                )
```

Limpieza en caso de fallo del LLM:

```python
        except Exception as err:
            logger.exception(...)
            # If the LLM validation fails - ensure to remove the generated video to not bloat the database,
            # as it would be linked to the summary (to reuse) only after the LLM video validation is completed
            await ExportedAsset.objects.filter(id=asset_id).adelete()
            return err
```

### 4.3 El proveedor Gemini

```python
class GeminiVideoUnderstandingProvider:
    """Interface for Gemini video understanding"""

    # https://ai.google.dev/gemini-api/docs/video-understanding#supported-formats
    SUPPORTED_VIDEO_MIME_TYPES: list[str] = [
        "video/x-flv", "video/quicktime", "video/mpeg", "video/mpegs", "video/mpg",
        "video/mp4", "video/webm", "video/wmv", "video/3gpp",
    ]

    VIDEO_MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20MB

    def __init__(self, model_id: str):
        self.model_id = model_id
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment or settings")
        # Using default Gemini client as workaround, as PostHog wrapper doesn't support async yet
        self.client = Client(api_key=api_key)

    async def understand_video(
        self, video_bytes: bytes, mime_type: str, prompt: str,
        start_offset_s: int | None = None, end_offset_s: int | None = None, trace_id: str | None = None,
    ) -> str | None:
        if mime_type not in self.SUPPORTED_VIDEO_MIME_TYPES:
            logger.exception(f"... not in a supported MIME type (trace_id:{trace_id}): {mime_type}")
            return None
        if not len(video_bytes):
            logger.exception(f"Video bytes for understanding video are empty (trace_id: {trace_id})")
            return None
        if len(video_bytes) > self.VIDEO_MAX_SIZE_BYTES:
            logger.exception(f"Video bytes for understanding video are too large (trace_id: {trace_id})")
            return None
        try:
            video_part_config: dict[str, str | Blob | VideoMetadata] = {
                "inline_data": Blob(data=video_bytes, mime_type=mime_type)
            }
            video_metadata_config = {}
            if start_offset_s:
                video_metadata_config["start_offset"] = f"{start_offset_s}s"
            if end_offset_s:
                video_metadata_config["end_offset"] = f"{end_offset_s}s"
            if video_metadata_config:
                video_part_config["video_metadata"] = VideoMetadata(**video_metadata_config)
            video_part = Part(**video_part_config)
            prompt_part = Part(text=prompt)
            contents = Content(parts=[video_part, prompt_part])
            response = await self.client.aio.models.generate_content(
                model=self.model_id, contents=contents,
            )
            return response.text
        except APIError as e:
            logger.exception(f"Gemini API error while understanding video (trace_id: {trace_id}): {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error while understanding video (trace_id: {trace_id}): {e}")
            return None
```

Validación **antes** de gastar la llamada: MIME soportado, no vacío, <20MB. Y `VideoMetadata(start_offset/end_offset)` permite analizar un tramo de un vídeo largo sin recortarlo.

Constantes de dominio en `ee/hogai/session_summaries/constants.py`:

```python
SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO = 7
VALIDATION_VIDEO_DURATION = 12
VALIDATION_VIDEO_PLAYBACK_SPEED = 8  # We don't need minor details, as LLM needs 1 frame per second
SHORT_VALIDATION_VIDEO_PLAYBACK_SPEED = 1  # For short videos (10s validation chunks), stick to "render fully"
FAILED_MOMENTS_MIN_RATIO = 0.5
EXPIRES_AFTER_DAYS = 90  # How long to store the videos used for validation
MOMENT_VIDEO_EXPORT_FORMAT = "video/webm"
FULL_VIDEO_EXPORT_FORMAT = "video/mp4"
DEFAULT_VIDEO_UNDERSTANDING_MODEL = "gemini-3-flash-preview"
MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S = 15
MIN_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S = 10  # Sessions below this activity threshold don't show much
MAX_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S = 3600
```

`VALIDATION_VIDEO_PLAYBACK_SPEED = 8` con el comentario "*LLM needs 1 frame per second*": **acelerar 8× el vídeo para que el LLM lo procese 8× más barato** sin perder información útil, porque Gemini muestrea ~1 fps. Es un hack de coste excelente.

También hay templates de validación por vídeo en `ee/hogai/session_summaries/session/templates/video-validation/`: `description-prompt.djt`, `validation-prompt.djt`, `validation-system-prompt.djt`. Es decir, **el vídeo generado se re-analiza con un LLM para verificar que contiene lo que se afirmaba**.

### ▶ MAPEO A CINEMATOGRAFÍAS

Este subsistema es prácticamente nuestro pipeline al revés, y su bucle de verificación es lo más valioso:

| PostHog | Nuestro agente |
|---|---|
| `SessionMomentInput(moment_id, timestamp_s, duration_s, prompt)` | `ShotSpec(shot_id, prompt, duration_s, aspect, seed, ref_image)` |
| `SessionMomentOutput(SessionMomentInput)` — hereda | `ShotResult` hereda de `ShotSpec`: el asset lleva su spec |
| `_generate_videos_for_moments` con `TaskGroup` | **Copiar tal cual** para el fan-out de renders |
| Hijos que `return err` en vez de `raise` | Imprescindible: un shot fallido no debe cancelar los otros 11 |
| `failed_moments_min_ratio` + `delete()` de assets | Si el batch va mal, abortar y limpiar (los assets cuestan) |
| `execution_timeout=timedelta(minutes=30)` | Timeout por shot en la API de generación |
| `expires_after` / `EXPIRES_AFTER_DAYS = 90` | Caducidad de renders intermedios |
| `content` en BD vs `content_location` en S3 | Assets pequeños inline, vídeos en object storage |
| `understand_video(video_bytes, prompt)` | **Bucle de QA visual**: analizar cada shot generado con Gemini y comprobar si cumple el prompt. Esto cierra el ciclo draft→verify de §2 sobre píxeles |
| templates `video-validation/` | Prompts de validación: "¿aparece el sujeto descrito? ¿la cámara hace el movimiento pedido? ¿hay artefactos/manos deformes?" → `[NEEDS_RETAKE]` |
| `PLAYBACK_SPEED = 8` | Acelerar el vídeo antes de mandarlo a QA para pagar menos tokens |
| `VIDEO_MAX_SIZE_BYTES` / MIME check previo | Validar antes de gastar la llamada |
| `get_video_duration_s` + `math.ceil` | Necesario en el ensamblado para calcular el timeline real, no el nominal |

---

## 5. SESSION SUMMARIES — map-reduce sobre volúmenes grandes

Ruta: `ee/hogai/session_summaries/`

```
session_summaries/
├── constants.py
├── utils.py                      # load_custom_template, tokenización, shorten_url
├── llm/{call.py, consume.py}     # llamada + parseo/validación/retry
├── session/                      # MAP: una sesión → un resumen
│   ├── input_data.py, output_data.py, prompt_data.py, stringify.py, summarize_session.py
│   └── templates/
│       ├── identify-objectives/{system-prompt.djt, prompt.djt, example.yml}
│       └── video-validation/{description-prompt.djt, validation-prompt.djt, validation-system-prompt.djt}
└── session_group/                # REDUCE: N resúmenes → patrones
    ├── patterns.py, stringify.py, summarize_session_group.py
    └── templates/
        ├── patterns_extraction/{system-prompt.djt, prompt.djt, example.yml}
        ├── patterns_assignment/{system-prompt.djt, prompt.djt, example.yml}
        └── patterns_combining/{system-prompt.djt, prompt.djt, example.yml}
```

### 5.1 Las cuatro etapas

1. **MAP**: cada sesión → resumen estructurado (YAML) individual. Paralelo.
2. **EXTRACTION**: chunks de resúmenes → listas de patrones. Paralelo por chunk.
3. **COMBINING**: N listas de patrones → una lista deduplicada. Éste es el *reduce* real.
4. **ASSIGNMENT**: patrones + resúmenes → qué evento concreto pertenece a qué patrón. Paralelo en chunks de 10.

Es un map-reduce en el que **cada etapa es una llamada a LLM con su propia terna de templates**.

### 5.2 La arquitectura de templates — el patrón más reutilizable del repo

Cada etapa tiene exactamente tres ficheros:

- `system-prompt.djt` — rol y criterios de calidad. Estable.
- `prompt.djt` — plantilla Django con placeholders de datos. Variable.
- `example.yml` — ejemplo del formato de salida, **inyectado dentro del prompt**.

Cargador genérico, en `ee/hogai/session_summaries/utils.py`:

```python
def load_custom_template(template_dir: Path, template_name: str, context: dict | None = None) -> str:
    """
    Load and render a template from the session summary templates directory.
    ...
```

Y las tres funciones generadoras, en `ee/hogai/session_summaries/session_group/summarize_session_group.py`. **Nótese que las tres son idénticas en forma**:

```python
def generate_session_group_patterns_extraction_prompt(
    session_summaries_str: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> PatternsPrompt:
    if extra_summary_context is None:
        extra_summary_context = ExtraSummaryContext()
    combined_session_summaries = "\n\n".join(session_summaries_str)
    template_dir = Path(__file__).parent / "templates" / "patterns_extraction"
    system_prompt = load_custom_template(template_dir, "system-prompt.djt")
    patterns_example = load_custom_template(template_dir, "example.yml")
    patterns_prompt = load_custom_template(
        template_dir,
        "prompt.djt",
        {
            "SESSION_SUMMARIES": combined_session_summaries,
            "PATTERNS_EXTRACTION_EXAMPLE": patterns_example,
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    return PatternsPrompt(patterns_prompt=patterns_prompt, system_prompt=system_prompt)


def generate_session_group_patterns_assignment_prompt(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_str: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> PatternsPrompt:
    ...
    template_dir = Path(__file__).parent / "templates" / "patterns_assignment"
    system_prompt = load_custom_template(template_dir, "system-prompt.djt")
    patterns_example = load_custom_template(template_dir, "example.yml")
    patterns_prompt = load_custom_template(
        template_dir,
        "prompt.djt",
        {
            "PATTERNS": patterns.model_dump_json(exclude_none=True),
            "SESSION_SUMMARIES": combined_session_summaries,
            "PATTERNS_ASSIGNMENT_EXAMPLE": patterns_example,
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    return PatternsPrompt(patterns_prompt=patterns_prompt, system_prompt=system_prompt)


def generate_session_group_patterns_combination_prompt(
    patterns_chunks: list[RawSessionGroupSummaryPatternsList],
    extra_summary_context: ExtraSummaryContext | None,
) -> PatternsPrompt:
    ...
    # Serialize all the pattern chunks to inject into the prompt
    patterns_chunks_yaml = []
    for i, chunk in enumerate(patterns_chunks):
        patterns_chunks_yaml.append(f"Patterns chunk #{i + 1}:\n\n{chunk.model_dump_json(exclude_none=True)}")
    combined_patterns_chunks = "\n\n---\n\n".join(patterns_chunks_yaml)

    template_dir = Path(__file__).parent / "templates" / "patterns_combining"
    system_prompt = load_custom_template(template_dir, "system-prompt.djt")
    patterns_example = load_custom_template(template_dir, "example.yml")
    patterns_prompt = load_custom_template(
        template_dir,
        "prompt.djt",
        {
            "PATTERNS_CHUNKS": combined_patterns_chunks,
            "PATTERNS_COMBINING_EXAMPLE": patterns_example,
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    return PatternsPrompt(patterns_prompt=patterns_prompt, system_prompt=system_prompt)
```

**Las ventajas concretas de sacar los prompts a `.djt`:**
- Se editan sin tocar Python ni redeployar lógica.
- Diff legible en PRs (un cambio de prompt no se pierde entre código).
- El motor de templates de Django ya resuelve escapado, condicionales, bucles.
- El `example.yml` es un fichero real y validable, no un string embebido.
- La forma `(system-prompt, prompt, example)` es idéntica en las tres etapas → trivial añadir una cuarta.

### 5.3 Anatomía de un prompt de reduce

`ee/hogai/session_summaries/session_group/templates/patterns_extraction/system-prompt.djt`:

```
You are an expert at analyzing user behavior patterns in web applications. Your specialty is identifying recurring pain points, failures, and friction across multiple user sessions.

Your analysis should:
1. Identify meaningful patterns that appear across multiple sessions
2. Focus on issues that impact user success and business goals
3. Provide actionable insights for product improvement
4. Distinguish between isolated incidents and systemic issues

When extracting patterns:
- Look for commonalities in user struggles, not just event sequences
- Consider the context and user intent behind the issues
- Prioritize patterns that block conversions or cause abandonment
- Ensure patterns are specific enough to guide solutions
```

`prompt.djt` (fragmentos clave). Primero **declara el formato de entrada**:

```
<session_summaries_input_format>
You'll receive a list of summaries of sessions of users visiting a site or an app... Each session summary is a JSON object with the following fields:

- session_id: The ID of the session
- segments: A list of segments in the session
- key_actions: A list of key actions in the session, including regular actions, failures, confusions, and abandonments.
- segment_outcomes: A list of outcomes for each segment
- session_outcome: The overall outcome of the session
</session_summaries_input_format>

<session_summaries_input>
```
{{ SESSION_SUMMARIES|safe }}
```
</session_summaries_input>
```

Luego un procedimiento numerado con checklists ✓/✗:

```
## Step 2: Extract Patterns

2.1. Find coherent patterns from analyzing similar issues across all provided sessions:
✓ Each pattern must be supported by evidence from at least 2 sessions
✓ Ensure patterns are specific enough to be actionable
✓ Use examples from the actual session data with clear, observable indicators
✓ Consider both technical and UX-related patterns
✓ Focus on patterns affecting conversions and critical flows

✗ DO NOT Create patterns based on single occurrences
✗ DO NOT Include overly generic patterns ("Users click buttons")
✗ DO NOT Invent patterns not supported by the sessions data
✗ DO NOT Focus on successful behaviors unless they reveal workarounds for issues
✗ DO NOT Create more than 10 patterns unless strongly justified by the data

2.2. Assign severity level to each pattern based on:
- **Critical**: Patterns that block conversions or cause session abandonment
- **High**: Patterns causing significant user frustration or workflow interruption
- **Medium**: Patterns creating minor friction but not preventing goal completion

IMPORTANT: If you want to assign "Low" severity (not listed) - better skip the pattern altogether.

Pattern severity level should be higher if it happens often (medium-level pattern that happens in >50% sessions should be high, but not critical), and lower if it happens rarely...

2.3. Ensure actionability of each pattern, as each pattern must pass the "So what?" test:
- Can specific UI/UX changes address this pattern?
- Is the pattern specific enough to guide priorities?
- Does it point to a clear problem owner (frontend, backend, UX, etc.)?
- Can success be measured after implementing fixes?

## Step 3: Consolidate Patterns

AGGRESSIVELY consolidate similar patterns.
```

Un paso de **autocrítica explícita antes de emitir**:

```
## Step 5: Quality Checks

Before finalizing patterns, verify:

5.1. Pattern Overlap Check:
- Are patterns distinct enough from each other?
- Have you aggressively consolidated similar patterns?

5.2. Session Coverage Check:
- Ensure patterns account for major issues in most sessions
- If many sessions have issues not captured by patterns, revisit analysis

5.3. Specificity Check:
- Is the pattern specific enough to guide improvements?
- Does it pass "So what?" check?
- Could a product manager create a specific ticket from this pattern?

5.4. Evidence Check:
- Is the pattern supported by multiple sessions?
- Are the indicators actually present in the data?
- Have you avoided inferring patterns not supported by evidence?

5.5. Business Impact Check:
- Does this pattern affect important user flows?
- Is it worth prioritizing for improvement?
- Does it impact conversions, engagement, or user satisfaction?

Revise your analysis if any inconsistencies are found.
```

Y una sección de formato con **workarounds anti-YAML-roto** aprendidos a golpes:

```
<output_format>
Provide your pattern analysis in YAML format using the provided example. Don't replicate the data, or comments, or logic of the example, or the number of example entries. Use it ONLY to understand the format.

IMPORTANT:
- Always use quotes around indicator strings that contain special characters
- Replace comparison operators with words:
  - Instead of ">3" use "more than 3"
  - Instead of "<1" use "less than 1"
  - Instead of ">=5" use "5 or more"
- Avoid using special YAML characters (>, <, :, &, *, ?, |, -, @, `) at the beginning of unquoted strings
- When in doubt, wrap the entire indicator string in single or double quotes
</output_format>

<output_example>
```
{{ PATTERNS_EXTRACTION_EXAMPLE|safe }}
```
</output_example>
```

Y "*Don't replicate the data... Use it ONLY to understand the format*" — mitigación explícita del sesgo de copiar el ejemplo.

### 5.4 Esquemas Pydantic de salida

`ee/hogai/session_summaries/session_group/patterns.py`:

```python
class RawSessionGroupSummaryPattern(BaseModel):
    """Schema for validating individual pattern from LLM output"""

    pattern_id: int = Field(..., description="Unique identifier for the pattern", ge=1)
    pattern_name: str = Field(..., description="Human-readable name for the pattern", min_length=1)
    pattern_description: str = Field(..., description="Detailed description of the pattern", min_length=1)
    severity: _SeverityLevel = Field(..., description="Severity level of the pattern")
    indicators: list[str] = Field(..., description="List of indicators that signal this pattern", min_length=1)


class RawSessionGroupSummaryPatternsList(BaseModel):
    """Schema for validating LLM output for patterns extraction"""
    patterns: list[RawSessionGroupSummaryPattern] = Field(..., description="List of patterns to validate", min_length=0)
```

Separación **raw vs enriched**: el LLM produce `Raw*`; el código añade estadísticas calculadas determinísticamente:

```python
class EnrichedSessionGroupSummaryPatternStats(BaseModel):
    """How many pattern occurrences, how pattern affected the success rate of segments, and similar"""
    occurences: int
    sessions_affected: int
    sessions_affected_ratio: float = Field(..., ge=0.0, le=1.0)
    segments_success_ratio: float = Field(..., ge=0.0, le=1.0)


class EnrichedSessionGroupSummaryPattern(RawSessionGroupSummaryPattern):
    """Enriched pattern with events context"""
    events: list[PatternAssignedEventSegmentContext] = Field(..., min_length=0)
    stats: EnrichedSessionGroupSummaryPatternStats
```

**El LLM nunca cuenta.** Aporta juicio cualitativo (nombre, severidad, indicadores); los números los calcula Python. Regla de oro.

Validador defensivo contra una alucinación de tipo concreta y recurrente:

```python
class RawSessionGroupPatternAssignment(BaseModel):
    pattern_id: int = Field(..., ge=1)
    event_ids: list[str] = Field(..., min_length=0)

    @field_validator("event_ids", mode="before")
    @classmethod
    def stringify_event_ids(cls, v: list[str | int]) -> list[str]:
        """If event ids are valid ints, LLM sometimes returns them as ints, so we need to convert them to strings"""
        try:
            return [str(item) for item in v]
        except Exception as err:
            msg = f"Error converting event ids to strings when validating pattern assignments ({v}): {err}"
            logger.exception(msg, signals_type="session-summaries")
            raise SummaryValidationError(msg) from err
```

### 5.5 Llamada, validación y retry

`ee/hogai/session_summaries/llm/call.py`:

```python
async def call_llm(
    input_prompt: str, *, session_id: str, model: str,
    assistant_start_text: str | None = None, system_prompt: str | None = None,
    trace_id: str | None = None, user_id: int,
    user_distinct_id: str | None = None, trigger_session_id: str | None = None,
) -> OpenAIResponse:
    """LLM call using the Responses API."""
    messages = _prepare_messages(input_prompt, session_id, assistant_start_text, system_prompt)
    user_param = _prepare_user_param(user_id)
    client = get_async_openai_client()
    posthog_props = _build_posthog_props(trigger_session_id)
    result = await client.responses.create(
        input=messages, model=model,
        reasoning={"effort": SESSION_SUMMARIES_REASONING_EFFORT},
        user=user_param,
        posthog_trace_id=trace_id, posthog_distinct_id=user_distinct_id, posthog_properties=posthog_props,
    )
    return result
```

Con el truco del *prefill*:

```python
    if assistant_start_text:
        # Force LLM to start with the assistant text
        messages.append({"role": "assistant", "content": assistant_start_text})
```

Poner un mensaje de assistant al final fuerza al modelo a continuar desde ahí (p.ej. `` ```yaml ``), eliminando el preámbulo conversacional.

`ee/hogai/session_summaries/llm/consume.py` — el patrón de retry, **idéntico en las tres etapas**:

```python
async def get_llm_session_group_patterns_extraction(
    prompt: PatternsPrompt, user_id: int, session_ids: list[str], model_to_use: str,
    trace_id: str | None = None, user_distinct_id: str | None = None, trigger_session_id: str | None = None,
) -> RawSessionGroupSummaryPatternsList:
    """Call LLM to extract patterns from multiple sessions."""
    sessions_identifier = generate_state_id_from_session_ids(session_ids)
    try:
        result = await call_llm(
            input_prompt=prompt.patterns_prompt,
            session_id=sessions_identifier,
            system_prompt=prompt.system_prompt,
            model=model_to_use,
            trace_id=trace_id, user_id=user_id,
            user_distinct_id=user_distinct_id, trigger_session_id=trigger_session_id,
        )
        raw_content = get_raw_content(result)
        if not raw_content:
            msg = f"No content consumed when calling LLM for session group patterns extraction, sessions {sessions_identifier}"
            logger.error(msg, signals_type="session-summaries")
            raise ValueError(msg)
        patterns = load_patterns_from_llm_content(raw_content, sessions_identifier)
        return patterns
    except (SummaryValidationError, ValueError) as err:
        # Hallucinations or parsing inconsistencies: retry as early as possible to reduce latency.
        logger.exception(
            f"Hallucinated data or inconsistencies in session group patterns extraction for sessions {sessions_identifier}: {err}",
            signals_type="session-summaries",
        )
        raise ExceptionToRetry() from err
    except (openai.APIError, openai.APITimeoutError, openai.RateLimitError) as err:
        logger.exception(
            f"Error calling LLM for session group patterns extraction, sessions {sessions_identifier} by user {user_id}: {err}",
            signals_type="session-summaries",
        )
        raise ExceptionToRetry() from err
```

**Dos clases de error se colapsan en una sola excepción `ExceptionToRetry`**: alucinación/parseo y error de red/rate-limit. El reintento no lo hace esta capa — lo hace Temporal, en la capa de workflow. Separación limpia: la capa LLM sólo *clasifica* el error.

### 5.6 Umbrales y chunking

`constants.py`:

```python
MAX_SESSIONS_TO_SUMMARIZE = 100  # Maximum number of sessions to summarize at once
HALLUCINATED_EVENTS_MIN_RATIO = 0.15  # If more than 15% of events in the summary hallucinated, fail the summarization
GROUP_SUMMARIES_MIN_SESSIONS = 5  # Minimum number of sessions to use group summary logic (find patterns)

# Fail-fast threshold for the summarization phase. Group patterns aren't meaningful from 1-2 sessions.
# Continue if `successes >= max(min(FLOOR, ceil(total/2)), total * RATIO)` (floor capped at majority of input).
GROUP_SUMMARY_MIN_SUCCESS_FLOOR = 3
GROUP_SUMMARY_MIN_SUCCESS_RATIO = 0.3

# Patterns
PATTERNS_ASSIGNMENT_CHUNK_SIZE = 10  # How many single-session-summaries to feed at once to assign events to patterns
# Maximum tokens allowed for pattern extraction (below o3 model limit and within expected quality range)
PATTERNS_EXTRACTION_MAX_TOKENS = 150000
SINGLE_ENTITY_MAX_TOKENS = 200000  # General limit to avoid hitting the o3 model limit
FAILED_PATTERNS_ENRICHMENT_MIN_RATIO = 0.75  # If less than 75% of patterns were enriched with the meta
```

El chunking es **doble**: por número de items (`PATTERNS_ASSIGNMENT_CHUNK_SIZE = 10`) y por presupuesto de tokens (`PATTERNS_EXTRACTION_MAX_TOKENS = 150000`, medido con `tiktoken` en `utils.py`). Y el límite de tokens está deliberadamente por debajo del límite del modelo: "*below o3 model limit and within expected quality range*" — el techo real no es técnico, es de calidad.

### 5.7 Un patrón hermano: clustering por embeddings

`ee/hogai/llm_traces_summaries/tools/clustering/clusterize_kmeans.py` resuelve el mismo problema (agrupar N cosas parecidas) sin LLM en la etapa de agrupación:

```python
# How many times max to re-group singles to increase group count
EMBEDDINGS_CLUSTERING_MAX_RECURSION: int = 3
# How many additional recursions allowed if the tail is too large (loose traces)
EMBEDDINGS_CLUSTERING_MAX_TAIL_RECURSION: int = 3
# If the tail is larger than that - try to cluster once more with more loose approach
EMBEDDINGS_CLUSTERING_MAX_TAIL_PERCENTAGE: float = 0.50
# Split embeddings into chunks to speed up clustering
EMBEDDINGS_CLUSTERING_CHUNK_SIZE: int = 1000  # Increasing from default 25
# Expected average similarity between embeddings to group them
EMBEDDINGS_COSINE_SIMILARITY: float = 0.72  # Lowering from the default 0.95
EMBEDDINGS_CLUSTERING_ITERATIONS: int = 5
EXPECTED_SUGGESTIONS_PER_EMBEDDINGS_GROUP: int = 25
MAX_SUGGESTIONS_PER_EMBEDDINGS_GROUP: int = 100
# How to decrease the similarity between embeddings to group them with each iteration,
# to increase the number of groups and improve the user experience
EMBEDDINGS_COSINE_SIMILARITY_DECREASE: float = 0.01
```

Clustering **iterativo con umbral decreciente**: si quedan demasiados elementos sueltos ("tail"), se relaja el umbral de similitud 0.01 y se reintenta, hasta 3 recursiones. El fichero incluso conserva los resultados de benchmarks en comentarios (`Groups count: 70 / Singles count: 506 / Avg cosine similarity: 0.74`). El pipeline es: `embed_summaries.py` → `clusterize_kmeans.py` → `explain_clusters.py` (aquí sí entra el LLM, sólo para *nombrar* los clusters ya formados). Misma filosofía que §5.4: **el LLM juzga, el código calcula**.

### ▶ MAPEO A CINEMATOGRAFÍAS

Este es el patrón que da coherencia global a una pieza larga:

| PostHog | Nuestro agente |
|---|---|
| MAP: sesión → resumen | **Escena → beats/shots**: cada escena del guion se descompone en paralelo en su lista de planos |
| EXTRACTION por chunks | **Extracción de la biblia visual**: de todas las escenas, extraer paleta, esquema de luz, lentes, wardrobe, look de cada personaje |
| COMBINING (reduce) | Consolidar las biblias parciales en **una sola biblia visual canónica** — clave para consistencia entre shots generados independientemente |
| ASSIGNMENT (chunk de 10) | Asignar a cada shot concreto qué entradas de la biblia le aplican (personaje X + paleta noche + 35mm) |
| terna `(system-prompt.djt, prompt.djt, example.yml)` | **Copiar la estructura entera.** Nuestras etapas: `beat_breakdown/`, `style_bible/`, `style_combining/`, `shot_prompt/`, `continuity_check/`, `shot_qa/` |
| `example.yml` inyectado + "use it ONLY to understand the format" | Ejemplo de shot list bien formada, sin que copie su contenido |
| Checklists ✓/✗ ("DO NOT create more than 10 patterns") | "NO más de N shots por escena", "NO shots sin movimiento de cámara especificado", "NO describir lo que no se ve" |
| "Quality Checks" antes de emitir | Auto-revisión de continuidad: ¿el eje de acción se respeta? ¿la ropa cambia entre planos? ¿la hora del día es coherente? |
| Reglas anti-YAML-roto | Idénticas si emitimos YAML; si emitimos JSON, usar §6 en su lugar |
| `Raw*` vs `Enriched*` | El LLM da `RawShot(prompt, lens, movement)`; el código calcula duración total, coste estimado, orden en timeline |
| "El LLM nunca cuenta" | Timings, duraciones, número de frames, presupuesto: todo en Python |
| `PATTERNS_ASSIGNMENT_CHUNK_SIZE = 10` | Nunca meter 200 shots en un prompt; trocear en lotes de ~10 |
| `MAX_TOKENS` por debajo del límite del modelo | El techo es de calidad, no técnico |
| `GROUP_SUMMARY_MIN_SUCCESS_RATIO` | Ratio mínimo de shots exitosos para continuar al ensamblado |
| `ExceptionToRetry` unificado + retry en la capa de workflow | La capa de generación clasifica; la capa de orquestación reintenta |
| Clustering por embeddings + LLM que sólo nombra | Agrupar shots visualmente similares para reusar seeds/referencias y ahorrar generaciones |

---

## 6. SCHEMA GENERATOR + QUERY PLANNER — JSON válido con reintentos

Ésta es la respuesta de PostHog a "cómo obligo al LLM a producir un objeto complejo y válido". La respuesta tiene **dos mitades**, y ésa es la lección principal.

### 6.1 La separación: planificar en prosa, generar en JSON

- **Query planner** (`ee/hogai/chat_agent/query_planner/`): agente ReAct que explora la taxonomía de datos y produce un **plan en lenguaje natural**. No genera JSON.
- **Schema generator** (`ee/hogai/chat_agent/schema_generator/`): recibe el plan y produce **sólo el JSON**, con structured output y bucle de reintentos.

El modelo nunca tiene que razonar sobre el problema *y* satisfacer un esquema de 300 campos a la vez.

### 6.2 Query planner: ReAct con herramientas obligatorias

`ee/hogai/chat_agent/query_planner/nodes.py`:

```python
    def _get_model(self, state: AssistantState):
        dynamic_retrieve_entity_properties, dynamic_retrieve_entity_property_values = self._get_dynamic_entity_tools()

        return MaxChatOpenAI(
            model="o4-mini",
            use_responses_api=True,
            streaming=False,
            reasoning={
                "summary": "auto",  # Without this, there's no reasoning summaries! Only works with reasoning models
            },
            include=["reasoning.encrypted_content"],
            team=self._team, user=self._user,
            # LangChain sometimes incorrectly handles reasoning items. They fixed it in the new output version.
            output_version="responses/v1",
            disable_streaming=True,
            billable=True,
        ).bind_tools(
            [
                retrieve_event_properties,
                retrieve_action_properties,
                dynamic_retrieve_entity_properties,
                retrieve_event_property_values,
                retrieve_action_property_values,
                dynamic_retrieve_entity_property_values,
                ask_user_for_help,
                final_answer,
            ],
            tool_choice="required",
            parallel_tool_calls=False,
        )
```

`tool_choice="required"` es la técnica central: **el modelo no puede responder con texto libre**, siempre debe llamar a una herramienta. La terminación es también una herramienta (`final_answer`), y pedir ayuda es otra (`ask_user_for_help`). Toda salida está tipada por construcción.

`parallel_tool_calls=False` aquí (a diferencia de §2.3): es un bucle de exploración secuencial, cada paso depende del anterior.

**Herramientas generadas dinámicamente** para que el enum de entidades sea el real del equipo:

```python
    def _get_dynamic_entity_tools(self):
        """Create dynamic Pydantic models with correct entity types for this team."""
        # Create Literal type with actual entity names
        DynamicEntityLiteral = Literal["person", "session", *self._team_group_types]  # type: ignore
        retrieve_entity_properties_dynamic = create_model(
            "retrieve_entity_properties",
            entity=(
                DynamicEntityLiteral,
                Field(..., description="The type of the entity that you want to retrieve properties for."),
            ),
            __doc__="""
            Use this tool to retrieve property names for a property group (entity)...
            - **Infer the property groups from the user's request.**
            - **Try other entities** if the tool doesn't return any properties.
            - **Prioritize properties that are directly related to the context or objective of the user's query.**
            - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
            """,
        )
```

`create_model` de Pydantic en runtime + `Literal[...]` con los valores reales. **El modelo no puede alucinar un nombre de entidad porque el esquema sólo admite los existentes.** Esto es prevención, no validación.

Los esquemas JSON completos se inyectan en el prompt, desreferenciados:

```python
                "trends_json_schema": dereference_schema(AssistantTrendsQuery.model_json_schema()),
                "funnel_json_schema": dereference_schema(AssistantFunnelsQuery.model_json_schema()),
                "retention_json_schema": dereference_schema(AssistantRetentionQuery.model_json_schema()),
```

`dereference_schema` resuelve los `$ref` — los LLM manejan mal las referencias JSON Schema.

Bucle de herramientas con límite y validación:

```python
class QueryPlannerToolsNode(AssistantNode, ABC):
    MAX_ITERATIONS = 16
    """
    Maximum number of iterations for the ReAct agent. After the limit is reached,
    the agent will terminate the conversation and return a message to the root node
    to request additional information.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = TaxonomyAgentToolkit(self._team, self._user)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]

        input = None
        output = ""

        try:
            input = TaxonomyAgentTool.model_validate({"name": action.tool, "arguments": action.tool_input})
        except ValidationError as e:
            output = str(
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
        else:
            # First check if we've reached the terminal stage.
            # The plan has been found. Move to the generation.
            if input.name == "final_answer":
                return PartialAssistantState(
                    plan=input.arguments.plan,
                    root_tool_insight_type=input.arguments.query_kind,
                    query_planner_previous_response_id=None,
                    intermediate_steps=None,
                    query_planner_intermediate_messages=None,
                )

            # The agent has requested help, so we return a message to the root node.
            if input.name == "ask_user_for_help":
                return self._get_reset_state(state, REACT_HELP_REQUEST_PROMPT.format(request=input.arguments))

        # If we're still here, the final prompt hasn't helped.
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(state, ITERATION_LIMIT_PROMPT)

        if input and not output:
            output = self._handle_tool(input, toolkit)

        return PartialAssistantState(
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
            query_planner_intermediate_messages=[
                *(state.query_planner_intermediate_messages or []),
                LangchainToolMessage(output, tool_call_id=action.log),
            ],
        )
```

Si la validación Pydantic de los argumentos falla, el error **se devuelve al modelo como el output de la herramienta** — el modelo se autocorrige en la siguiente iteración sin salir del bucle.

### 6.3 Schema generator: structured output + retry

`ee/hogai/chat_agent/schema_generator/utils.py` — el genérico:

```python
Q = TypeVar("Q", AssistantHogQLQuery, AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, DataVisualizationNode)

class SchemaGeneratorOutput(BaseModel, Generic[Q]):
    query: Q
```

`ee/hogai/chat_agent/schema_generator/parsers.py` (completo) — el parser que conserva el output crudo para poder devolvérselo al modelo:

```python
class PydanticOutputParserException(ValueError):
    llm_output: str
    """Serialized LLM output."""
    validation_message: str
    """Pydantic validation error message."""

    def __init__(self, llm_output: str, validation_message: str):
        super().__init__(f"{validation_message}, occurred at:\n```\n{llm_output}\n```")
        self.llm_output = llm_output
        self.validation_message = validation_message


T = TypeVar("T", bound=BaseModel)


def parse_pydantic_structured_output(model: type[T]) -> Callable[[dict], T]:
    def parser(output: dict) -> T:
        try:
            return model.model_validate(output)
        except ValidationError as e:
            raise PydanticOutputParserException(
                llm_output=json.dumps(output), validation_message=e.json(include_url=False)
            )

    return parser
```

`e.json(include_url=False)` — el error de Pydantic serializado a JSON, sin las URLs de documentación (ruido inútil que gasta tokens).

`ee/hogai/chat_agent/schema_generator/nodes.py`:

```python
RETRIES_ALLOWED = 2


class SchemaGenerationException(Exception):
    """An error occurred while generating a schema in the `SchemaGeneratorNode` node."""

    def __init__(self, llm_output: str, validation_message: str):
        super().__init__("Failed to generate schema")
        self.llm_output = llm_output
        self.validation_message = validation_message


class SchemaGeneratorNode(AssistantNode, Generic[Q]):
    INSIGHT_NAME: str
    """Name of the insight type used in the exception messages."""
    OUTPUT_MODEL: type[SchemaGeneratorOutput[Q]]
    """Pydantic model of the output to be generated by the LLM."""
    OUTPUT_SCHEMA: dict
    """JSON schema of OUTPUT_MODEL for LLM's use."""

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-5.2",
            temperature=0.3,
            disable_streaming=True,
            user=self._user, team=self._team,
            max_tokens=8192,
            billable=True,
            output_version="responses/v1",
            use_responses_api=True,
            reasoning={"effort": "none"},
            model_kwargs={"prompt_cache_key": f"team_{self._team.id}"},
        ).with_structured_output(
            self.OUTPUT_SCHEMA,
            method="json_schema",
            include_raw=False,
        )

    def _parse_output(self, output: dict) -> SchemaGeneratorOutput[Q]:
        """This can raise a PydanticOutputParserException if the output is not parsable (therefore unusable)."""
        return parse_pydantic_structured_output(self.OUTPUT_MODEL)(output)

    async def _quality_check_output(self, output: SchemaGeneratorOutput[Q]) -> None:
        """
        If implemented, this can raise a PydanticOutputParserException exception if something's off about the output
        (e.g. a non-existent table field is used).

        Raising here means that the LLM should iterate on the output, but also that it's still usable
        if we aren't able to resolve the issue in a couple attempts.
        """
        pass
```

Tres capas de defensa, cada una más débil que la anterior:
1. `method="json_schema"` — el proveedor **garantiza** JSON sintácticamente conforme.
2. `_parse_output` — Pydantic valida la semántica (rangos, uniones discriminadas, campos requeridos).
3. `_quality_check_output` — validación de dominio (¿existe esa tabla? ¿ese campo?), **best-effort**: si tras los reintentos sigue fallando, se acepta igualmente.

`reasoning={"effort": "none"}` — no hay que razonar aquí; el razonamiento ya lo hizo el planner. Y `prompt_cache_key` por equipo para cachear el prefijo (el esquema es enorme y constante).

**El bucle de reintentos (bloque literal):**

```python
    async def _run_with_prompt(
        self, state: AssistantState, prompt: ChatPromptTemplate, config: Optional[RunnableConfig] = None,
    ) -> PartialAssistantState:
        generated_plan = state.plan or ""
        intermediate_steps: Sequence[IntermediateStep] = state.intermediate_steps or []
        validation_error_message = intermediate_steps[-1][1] if intermediate_steps else None

        message_history = await self._construct_messages(state, validation_error_message=validation_error_message)
        generation_prompt = prompt + message_history
        merger = merge_message_runs()

        chain = generation_prompt | merger | self._model | self._parse_output

        try:
            result: SchemaGeneratorOutput[Q] = await chain.ainvoke(
                {
                    "project_datetime": self.project_now,
                    "project_timezone": self.project_timezone,
                    "project_name": self._team.name,
                },
                config,
            )
            # If quality check raises, we will still iterate if we've got any attempts left,
            # however if we don't have any more attempts, we're okay to use `result` (instead of throwing)
            await self._quality_check_output(cast(SchemaGeneratorOutput[Q], result))
        except (PydanticOutputParserException, OutputParserException) as e:
            # Try again with feedback a couple times
            if len(intermediate_steps) < RETRIES_ALLOWED:
                return PartialAssistantState(
                    intermediate_steps=[
                        *intermediate_steps,
                        (
                            AgentAction(
                                "handle_incorrect_response",
                                e.llm_output or "No input was provided.",
                                e.validation_message
                                if isinstance(e, PydanticOutputParserException)
                                else "The provided JSON was invalid.",
                            ),
                            None,
                        ),
                    ],
                    query_generation_retry_count=len(intermediate_steps) + 1,
                )

            if isinstance(e, PydanticOutputParserException):
                raise SchemaGenerationException(e.llm_output, e.validation_message)
            raise SchemaGenerationException(e.llm_output or "No input was provided.", str(e))

        # We've got a result that either passed the quality check or we've exhausted all attempts at iterating - return
        artifact = await self.context_manager.artifacts.acreate(
            content=VisualizationArtifactContent(
                query=result.query,
                name=state.visualization_title,
                description=state.visualization_description,
                plan=generated_plan,
            ),
            name=state.visualization_title or "Visualization",
        )
        artifact_message = self.context_manager.artifacts.create_message(
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
            content_type=ArtifactContentType.VISUALIZATION,
        )

        return PartialAssistantState(
            messages=[artifact_message],
            intermediate_steps=None,
            plan=None,
            rag_context=None,
            query_generation_retry_count=len(intermediate_steps),
        )

    def router(self, state: AssistantState):
        if state.intermediate_steps:
            return "tools"
        return "next"
```

**Lo más importante: el reintento NO es un bucle `for`.** El nodo *retorna* un estado parcial con el error acumulado en `intermediate_steps`, y el `router` reencamina el grafo de vuelta. Ventajas: cada intento es un nodo observable en LangGraph, el checkpointer lo persiste, y es interrumpible/reanudable. Un `for` en memoria no da nada de eso.

Construcción del historial, con el error **al final** de la conversación:

```python
    async def _construct_messages(self, state: AssistantState, validation_error_message: str | None = None) -> list[BaseMessage]:
        """Construct the prompt for schema generation with only the plan and a static generation instruction."""
        generated_plan = state.plan or ""

        group_mapping = await self._get_group_mapping_prompt()
        conversation: list[BaseMessage] = [
            HumanMessagePromptTemplate.from_template(GROUP_MAPPING_PROMPT, template_format="mustache").format(
                group_mapping=group_mapping
            )
        ]

        conversation.append(
            HumanMessagePromptTemplate.from_template(PLAN_PROMPT, template_format="mustache").format(plan=generated_plan)
        )

        # Retries must be added to the end of the conversation.
        if validation_error_message:
            conversation.append(
                HumanMessagePromptTemplate.from_template(FAILOVER_PROMPT, template_format="mustache").format(
                    validation_error_message=validation_error_message
                )
            )

        return conversation
```

Y el nodo de failover que formatea el par (output, excepción):

```python
class SchemaGeneratorToolsNode(AssistantNode):
    """Used for failover from generation errors."""

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        intermediate_steps = state.intermediate_steps or []
        if not intermediate_steps:
            return None

        action, _ = intermediate_steps[-1]
        prompt = (
            ChatPromptTemplate.from_template(FAILOVER_OUTPUT_PROMPT, template_format="mustache")
            .format_messages(output=action.tool_input, exception_message=action.log)[0]
            .content
        )

        return PartialAssistantState(intermediate_steps=[*intermediate_steps[:-1], (action, str(prompt))])
```

Los prompts (`ee/hogai/chat_agent/schema_generator/prompts.py`, completo) son minimalistas:

```python
GROUP_MAPPING_PROMPT = """
Here is the group mapping:
{{{group_mapping}}}
""".strip()

PLAN_PROMPT = """
Here is the plan:
{{{plan}}}

Generate a schema from this plan.
""".strip()

FAILOVER_OUTPUT_PROMPT = """
Generation output:
```
{{{output}}}
```

Exception message:
```
{{{exception_message}}}
```
""".strip()

FAILOVER_PROMPT = """
The result of the previous generation raised the Pydantic validation exception.

{{{validation_error_message}}}

Fix the error and return the correct response.
""".strip()
```

Reintentar es literalmente: *aquí está lo que produjiste, aquí está el error de validación, arréglalo*. Nada más.

### ▶ MAPEO A CINEMATOGRAFÍAS

| PostHog | Nuestro agente |
|---|---|
| Planner (prosa) → Generator (JSON) | **Separar**: un agente escribe el tratamiento del shot en prosa cinematográfica; otro lo convierte al JSON de la API de generación (aspect, seed, motion_bucket, cfg, camera_control) |
| `tool_choice="required"` + `final_answer` como tool | El agente de guion no puede "responder con texto": debe llamar a `add_shot`, `revise_shot` o `finalize_shotlist` |
| `create_model` + `Literal[...]` dinámico | Enum runtime con los **modelos/LoRAs/estilos realmente disponibles** en nuestra cuenta → imposible alucinar un modelo inexistente |
| `dereference_schema()` | Nuestro `ShotSpec` tiene uniones anidadas; desreferenciar antes de inyectarlo |
| `with_structured_output(schema, method="json_schema")` | Capa 1: JSON conforme garantizado |
| `parse_pydantic_structured_output` + `e.json(include_url=False)` | Capa 2: validar `ShotSpec` (duración en rango, aspect permitido, seed entero) |
| `_quality_check_output` (best-effort) | Capa 3: coherencia narrativa — ¿el personaje existe en la biblia? ¿el shot respeta el eje? Si falla tras 2 intentos, se acepta y se marca |
| `RETRIES_ALLOWED = 2` + retorno de estado, no `for` | Cada reintento es un nodo del grafo: observable, persistido, reanudable |
| `FAILOVER_PROMPT` | "Tu shot spec falló la validación: {error}. Corrígelo." |
| `reasoning={"effort":"none"}` en el generador | El razonamiento creativo ya se hizo; la traducción a JSON es mecánica y barata |
| `prompt_cache_key` por equipo | Cachear el prefijo (esquema + biblia visual) entre los N shots del mismo proyecto — **ahorro grande con fan-out** |
| `MAX_ITERATIONS = 16` + `ITERATION_LIMIT_PROMPT` | Tope duro en el bucle de refinamiento de shot list |
| Error de validación devuelto como output de tool | El agente se autocorrige sin salir del bucle |

---

## 7. `utils/types/base.py` — el modelo de estado compartido

Ruta: `ee/hogai/utils/types/base.py` (645 líneas). Es el fichero que hace que todo lo anterior componga.

### 7.1 Reductores: la pieza conceptual clave

En LangGraph, cuando dos ramas paralelas actualizan el mismo campo, un **reductor** decide cómo fusionar. PostHog define los suyos:

```python
def replace(_: Any | None, right: Any | None) -> Any | None:
    return right


def replace_if_not_none(left: Any | None, right: Any | None) -> Any | None:
    """Replace the left value with right only if right is not None."""
    return right if right is not None else left


def append(left: Sequence, right: Sequence) -> Sequence:
    """Appends the right value to the state field."""
    return [*left, *right]


def merge_retry_counts(left: int, right: int) -> int:
    """Merges two retry counts by taking the maximum value."""
    return max(left, right)
```

Se aplican con `Annotated`:

```python
class BaseStateWithTasks(BaseState):
    tasks: Annotated[Optional[list[TaskExecutionItem]], replace] = Field(default=None)
    """Deprecated."""
    task_results: Annotated[list[TaskResult], append] = Field(default=[])
    """Results of tasks executed by assistants."""
```

`task_results: Annotated[list[TaskResult], append]` es **exactamente el mecanismo de agregación del fan-out de §1**. N subtareas concurrentes escriben `task_results` y LangGraph concatena automáticamente. No hay código de merge manual en ningún sitio.

`merge_retry_counts` con `max` es sutil: si dos ramas reintentaron 1 y 2 veces, el estado fusionado debe decir 2, no 3 ni 1.

### 7.2 Merge de mensajes por ID

```python
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

Append-only por defecto, pero **update-in-place si el ID coincide**: así se actualiza un mensaje de progreso ("shot 3: generando… → shot 3: listo") sin duplicarlo en el chat.

Y la escotilla de escape, un tipo-marcador:

```python
class ReplaceMessages(Generic[T], list[T]):
    """Replaces the existing messages with the new messages."""

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
```

Una **subclase de `list` usada como señal semántica**: el reductor mira el *tipo* del valor entrante para decidir entre merge y reemplazo. Elegante — el modo de fusión viaja con el dato, no en un flag aparte.

### 7.3 Sentinel serializable para borrar

```python
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
    # CLEAR_SUPERMODE should only appear on the right side (incoming update)
    # If it's in left (current state), that's a bug - treat as None
    if result == CLEAR_SUPERMODE:
        return None
    return cast("AgentMode", result)
```

Problema clásico: `None` significa "sin cambio", entonces ¿cómo se borra un campo? Con un sentinel. Y debe ser **string**, porque el estado se serializa con msgpack al checkpointer.

### 7.4 Modelos de tarea y artefacto

```python
class TaskArtifact(BaseModel):
    """Base artifact created by a task."""
    id: str | int | None = None  # The id of the object referenced by the artifact
    task_id: str  # The id of the task that created the artifact
    content: str  # A string content attached to the artifact


class InsightArtifact(TaskArtifact):
    """An insight artifact created by a task."""
    query: Union[AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, AssistantHogQLQuery, DataVisualizationNode]


class TaskResult(BaseModel):
    """The result of an individual task."""
    model_config = ConfigDict(extra="ignore")

    id: str
    result: str
    artifacts: Sequence[TaskArtifact] = Field(default=[])
    status: TaskExecutionStatus
```

`TaskArtifact` es deliberadamente mínimo: `id` (referencia al objeto real), `task_id` (procedencia), `content` (descripción textual para el LLM). El artefacto pesado vive fuera del estado; el estado sólo lleva la referencia. `model_config = ConfigDict(extra="ignore")` da tolerancia a estados antiguos persistidos.

### 7.5 Reset y estado base

```python
class BaseState(BaseModel):
    """Base state class with reset functionality."""

    @classmethod
    def get_reset_state(cls) -> Self:
        """Returns a new instance with all fields reset to their default values."""
        return cls(**{k: v.default for k, v in cls.model_fields.items()})
```

Usado en §6.2 (`_get_reset_state`) para salir limpiamente de un subgrafo sin arrastrar estado intermedio.

Jerarquía: `BaseState` → `BaseStateWithMessages` / `BaseStateWithTasks` / `BaseStateWithIntermediateSteps` → `_SharedAssistantState` → `AssistantState` / `PartialAssistantState`.

La diferencia final entre estado completo y parcial es sólo el reductor:

```python
class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])


class PartialAssistantState(_SharedAssistantState):
    # This must be kept here, so we don't loose type annotation for the ReplaceMessages type.
    messages: ReplaceMessages[AssistantMessageUnion] | list[AssistantMessageUnion] = Field(default=[])
```

### 7.6 Campos con docstring

Todo campo lleva un docstring debajo:

```python
    plan: Optional[str] = Field(default=None)
    """
    The insight generation plan.
    """
    query_generation_retry_count: Annotated[int, merge_retry_counts] = Field(default=0)
    """
    Tracks the number of times the query generation has been retried.
    """
    specific_session_ids_to_summarize: Optional[list[str]] = Field(default=None)
    """
    List of specific session IDs (UUIDs) to summarize. Can be populated from:
    - Session IDs extracted from user's natural language query
    - Current session ID from context when user refers to "this session"
    - Multiple session IDs when user specifies several sessions
    """
```

Con ~40 campos en un estado compartido por 6 subgrafos, esto no es opcional.

### 7.7 Migración de esquema vía validador

```python
    @field_validator("messages", mode="after")
    @classmethod
    def convert_visualization_messages_to_artifacts(cls, messages):
        """
        Convert legacy VisualizationMessage to ArtifactRefMessage with State source.
        The original VisualizationMessage is kept in state for content lookup.
        """
        existing_artifact_ids = {msg.artifact_id for msg in messages if isinstance(msg, ArtifactRefMessage)}
        converted: list[AssistantMessageUnion] = []
        for message in messages:
            converted.append(message)
            if message.id and isinstance(message, VisualizationMessage):
                if message.id not in existing_artifact_ids:
                    converted.append(
                        ArtifactRefMessage(
                            id=str(uuid.uuid4()),  # TRICKY: Keep this ID unique, so we don't deduplicate artifacts and visualization messages.
                            content_type=ArtifactContentType.VISUALIZATION,
                            artifact_id=message.id,
                            source=ArtifactSource.STATE,
                        )
                    )
        if isinstance(messages, ReplaceMessages):
            return ReplaceMessages(converted)
        return converted
```

Migración **al vuelo, en la carga**, idempotente. Los estados viejos persistidos se actualizan sin script de migración. Ver también el comentario en el union:

```python
AIMessageUnion = Union[
    AssistantMessage,
    VisualizationMessage,  # IMPORTANT: Keep it here for backwards compatibility with old states, as they're persisted in the database
    ...
]
```

### 7.8 Tipado del stream de salida

```python
AssistantOutput = (
    tuple[Literal[AssistantEventType.CONVERSATION], Conversation]
    | tuple[Literal[AssistantEventType.MESSAGE], AssistantStreamedMessageUnion]
    | tuple[Literal[AssistantEventType.STATUS], AssistantGenerationStatusEvent]
    | tuple[Literal[AssistantEventType.UPDATE], AssistantUpdateEvent | SubagentUpdateEvent]
    | tuple[Literal[AssistantEventType.APPROVAL], ApprovalPayload]
)
```

Unión discriminada de tuplas → el consumidor del stream tiene exhaustividad garantizada por el type checker.

`ApprovalPayload` merece mención — es el **human-in-the-loop para operaciones peligrosas**:

```python
class ApprovalPayload(BaseModel):
    """Payload for dangerous operation approval requests."""
    proposal_id: str
    decision_status: str
    tool_name: str
    preview: str
    payload: dict
    original_tool_call_id: str | None
    message_id: str | None
```

Y `WithCommentary`, un mixin para que las tool calls se narren solas mientras hacen streaming:

```python
class WithCommentary(BaseModel):
    """
    Use this class as a mixin to your tool calls, so that the `Assistant` class can parse the commentary from the tool call chunks stream.
    """
    commentary: str = Field(
        description="A commentary on what you are doing, using the first person: 'I am doing this because...'"
    )
```

### ▶ MAPEO A CINEMATOGRAFÍAS

| PostHog | Nuestro agente |
|---|---|
| `task_results: Annotated[list[TaskResult], append]` | `shot_results: Annotated[list[ShotResult], append]` — **la agregación del fan-out sale gratis** |
| `add_and_merge_messages` (update por ID) | Actualizar la tarjeta de progreso de un shot in-place en vez de spamear el chat |
| `ReplaceMessages` como tipo-señal | Reemplazar la shot list entera tras una revisión del guion |
| `merge_retry_counts` con `max` | Contador de reintentos por shot correcto bajo concurrencia |
| `CLEAR_SUPERMODE` sentinel string | Distinguir "sin cambio" de "borrar" con un estado serializado a disco |
| `TaskArtifact(id, task_id, content)` | `ShotAsset(asset_url, shot_id, description)` — la referencia en el estado, el MP4 en S3 |
| `BaseState.get_reset_state()` | Salir de un subgrafo de shot sin contaminar el estado del proyecto |
| Docstring por campo | Obligatorio: nuestro estado tendrá guion, biblia visual, shot list, assets, timeline, presupuesto |
| `@field_validator` de migración | Los proyectos de cinematografía persisten semanas; el esquema evolucionará |
| `ApprovalPayload` | **Gate de aprobación antes de gastar créditos**: "voy a generar 12 shots ≈ $X. ¿Confirmas?" |
| `WithCommentary` | Cada shot narra su intención mientras se genera |
| `AssistantOutput` unión discriminada | Tipar el stream: `SHOT_STARTED / SHOT_PROGRESS / SHOT_DONE / SHOT_FAILED / ASSEMBLY_DONE` |

---

## 8. `api/serializers.py` e `insights_assistant.py`

`ee/hogai/api/serializers.py` (406 líneas) es la capa REST de conversaciones (`ConversationMinimalSerializer` se usa en el streaming del sandbox, §3.3). Menos relevante para nosotros salvo como ejemplo de separación entre serializador mínimo (para el evento inicial del SSE) y completo.

`ee/hogai/insights_assistant.py` sí tiene una lección de compatibilidad: el runner emite **dos representaciones del mismo artefacto** durante una migración de formato, para no romper consumidores antiguos:

```python
        async for stream_event in super().astream(...):
            path, message = stream_event
            if isinstance(message, ArtifactMessage) and (
                last_artifact_content := unwrap_visualization_artifact_content(message)
            ):
                # for backwards compatibility with the MCP
                legacy_visualization_message = VisualizationMessage(
                    id=message.id,
                    answer=last_artifact_content.query,
                    plan=last_artifact_content.description,
                )
                path = cast(Literal[AssistantEventType.MESSAGE], path)
                yield (path, legacy_visualization_message)
            if isinstance(message, AssistantMessage):
                last_ai_message = message
            yield stream_event
```

Y la definición de "nodos verbosos" — qué nodos del grafo se muestran al usuario y cuáles se ocultan:

```python
VERBOSE_NODES: set["MaxNodeName"] = {
    AssistantNodeName.QUERY_EXECUTOR,
    AssistantNodeName.FUNNEL_GENERATOR,
    ...
}
```

En `ee/hogai/research_agent/runner.py` se distingue además `STREAMING_NODES` (token a token) de `VERBOSE_NODES` (sólo mensajes completos):

```python
STREAMING_NODES: set["MaxNodeName"] = {
    AssistantNodeName.ROOT,
}

VERBOSE_NODES: set["MaxNodeName"] = STREAMING_NODES | {
    AssistantNodeName.ROOT, AssistantNodeName.ROOT_TOOLS,
    AssistantNodeName.TRENDS_GENERATOR, ...
}
```

**Mapeo**: sólo el agente director hace streaming de tokens; los 12 nodos de generación de shots reportan estado, no tokens. Sin esta distinción, un fan-out de 12 shots produce una avalancha ilegible en la UI.

---

## 9. SÍNTESIS — arquitectura propuesta

Combinando los siete subsistemas, el agente de cinematografías queda así:

```
FASE 1 — BRIEF (supermode PLAN, §2)
  Modelo barato. Toolkit con create_form + finalize_script.
  ≤4 preguntas, fundamentadas tras explorar referencias.
  → Guion aprobado por el usuario. Gate ApprovalPayload (§7.8).

FASE 2 — DESGLOSE (map-reduce, §5)
  MAP:       cada escena → beats (paralelo, §1)
  EXTRACT:   biblia visual parcial por chunk de escenas
  COMBINE:   → biblia visual canónica (reduce)
  ASSIGN:    a cada shot, qué entradas de la biblia aplican (chunks de 10)
  Templates: terna (system-prompt.djt, prompt.djt, example.yml) por etapa.

FASE 3 — PROMPTS (§6)
  Planner en prosa cinematográfica → Generator a ShotSpec JSON.
  with_structured_output + Pydantic + quality check de continuidad.
  RETRIES_ALLOWED=2, reintento como nodo del grafo, no como for.
  Enums dinámicos (create_model + Literal) con modelos/LoRAs reales.

FASE 4 — GENERACIÓN (§1 + §4)
  _aexecute_tasks() con Semaphore.
  Hijos devuelven `int | Exception`, nunca lanzan (§4.2).
  Yield en orden de finalización → el usuario ve shots según llegan.
  failed_shots_min_ratio + borrado de assets parciales.
  Estado: shot_results: Annotated[list[ShotResult], append] (§7.1).

FASE 5 — QA VISUAL (§4.3 + §2.4)
  Cada shot renderizado → Gemini understand_video con el prompt original.
  Vídeo acelerado 4-8× para abaratar (§4.3).
  ¿Cumple? → [APPROVED]. ¿No? → [NEEDS_RETAKE: motivo] → vuelve a FASE 4.
  Bucle draft-driven: termina cuando no quedan marcadores pendientes.

FASE 6 — ENSAMBLADO (§3)
  FFmpeg/Remotion en contenedor aislado, nunca in-process.
  Progreso vía Redis Stream → SSE, con start_id para reanudar sin replay.
  Duraciones reales con pymediainfo + math.ceil (§4.1).
```

### Las siete ideas que más valen

1. **`_aexecute_tasks` completo** (§1.4) — motor de fan-out con aislamiento de fallos, orden de finalización y limpieza. Copiar literal.
2. **Hijos que devuelven la excepción en vez de lanzarla** bajo `TaskGroup` (§4.2). Un detalle de tres líneas que separa "un shot falla" de "el batch entero se cancela".
3. **El bucle draft-driven con marcadores sintácticos** (§2.4). Convierte un bucle agéntico abierto en algo con condición de parada objetiva e inspeccionable.
4. **Terna de templates `.djt` por etapa** (§5.2). Prompts como datos, no como código.
5. **El LLM juzga, el código calcula** (§5.4). Raw vs Enriched. Ningún número lo produce el modelo.
6. **Reintento como nodo del grafo, no como `for`** (§6.3). Observable, persistido, reanudable.
7. **Reductores de estado con `Annotated`** (§7.1). `append` sobre `shot_results` hace que la agregación del fan-out no requiera una sola línea de código de merge.

### Y lo que hay que añadir (PostHog no lo tiene)

- `asyncio.Semaphore` para limitar concurrencia — las APIs de generación de vídeo tienen rate limits y coste por llamada.
- Presupuesto explícito en el estado y gate de aprobación antes de cada batch (`ApprovalPayload` existe, pero no se usa para coste).
- Caché de shots por hash del prompt + seed: no regenerar lo idéntico.
- Backoff exponencial en los reintentos de shot (PostHog delega esto a Temporal `RetryPolicy`; nosotros lo necesitamos explícito).
