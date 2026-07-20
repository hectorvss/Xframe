# Arquitectura del agente de Xframe

Diseño de producción para el agente de generación cinematográfica.
Basado en la investigación de `ee/hogai` (PostHog Max AI) — ver
`docs/posthog-agent-research/` — y en el informe de APIs de generación (`06`).

**Decisiones tomadas:** Python + LangGraph · APIs directas de proveedor ·
arquitectura completa de producción.

---

## 1. Principio rector

> El agente no genera vídeo. El agente **decide** y **encola**; los workers generan.

Todo lo demás se deriva de aquí. Ningún proveedor tier-1 es síncrono, un vídeo de
6 planos son minutos de tiempo de pared, y cada intento cuesta dinero real. Un
agente que "espera a que termine" es un agente que se cae con el navegador del
usuario y que no puede cobrarse bien.

---

## 2. Topología: dos nodos, no un pipeline

Copiamos literalmente el hallazgo de PostHog (`core/loop_graph/graph.py`): el grafo
tiene **`ROOT` (LLM) y `ROOT_TOOLS`**, con aristas condicionales. Nada más.

```
        ┌──────────────────────────────┐
        │                              ▼
   ┌────────┐   tool_calls?   ┌────────────────┐
   │  ROOT  │ ───────────────▶│   ROOT_TOOLS   │
   └────────┘                 └────────────────┘
        │                              │
        │ sin tool_calls               │ Send(...) por cada tool call
        ▼                              │  → fan-out paralelo
       END ◀────────────────────────────
```

**Por qué no un pipeline `guion → shotlist → render → montaje`:** se rompe el día
que el usuario dice *"cambia solo el plano 7"* o *"este personaje no me gusta,
regenera todo lo que salga con él"*. Con dos nodos, ambos flujos son la misma
máquina. La secuencia la impone el **modo** y el **estado del artefacto**, no la
topología.

Fan-out con el patrón de PostHog:

```python
Send(ROOT_TOOLS, state.model_copy(update={"root_tool_call_id": tc.id}))
```

**Límites dobles:** `MAX_TOOL_CALLS = 24` + `recursion_limit: 96`. Y, crítico para
nosotros, un tercer límite **por recurso**: `MAX_GENERATIONS_PER_TURN`. Al alcanzar
cualquiera, no lanzamos excepción — le quitamos las tools al modelo e inyectamos un
mensaje forzando el cierre (patrón de PostHog, degradación amable).

---

## 3. Estado

`XframeState` / `PartialXframeState` con reductores anotados, como
`utils/types/base.py`:

```python
class XframeState(BaseModel):
    messages: Annotated[list[AnyMessage], add_and_merge_messages]  # upsert por ID
    mode: Literal["preproduction", "production", "edit"] | None
    supermode: Literal["plan"] | None          # None = "no cambies"; CLEAR_SUPERMODE = borra
    project_id: UUID
    todos: list[Todo]
    job_results: Annotated[list[JobResult], append]   # agregación del fan-out gratis
    root_tool_call_id: str | None
    generations_this_turn: int
    credits_reserved: int
```

Dos detalles que PostHog aprendió por las malas y nosotros heredamos:

- **Centinela `CLEAR_*`**: `None` significa *"no cambies este campo"*, no *"bórralo"*.
  Sin centinela no puedes salir de un modo.
- **Nunca binarios en el checkpoint.** El estado guarda `AssetRefMessage` (id + tipo +
  estado); el cliente recibe `AssetMessage` enriquecido con URLs firmadas. Un
  checkpoint con vídeos dentro es un checkpoint que no se puede leer.

Checkpointing en el **Postgres de Supabase** que ya tenemos, con
`AsyncPostgresSaver` de LangGraph. Reanudación con el patrón
`_init_or_update_state()` → `Command(resume=...)` / `None` / estado inicial.

---

## 4. Taxonomía runtime — el corazón del sistema

Este es el patrón más valioso de PostHog y en nuestro caso es **doblemente**
importante, porque el informe de APIs reveló que:

- Runway Gen-3 Turbo y Gen-4 Aleph se apagan el **30 de julio de 2026** (en 10 días).
- Sora 2 y la Videos API de OpenAI se apagan el **24 de septiembre de 2026**.
- Veo 3.0 ya está apagado desde el 30 de junio.
- Los presets de movimiento de Higgsfield se identifican por **UUID**, no por nombre.

**Conclusión: el catálogo de modelos y de controles cinematográficos es DATOS, no
código.** Un `Literal["Kling 3.0", "Sora 2", ...]` hardcodeado es deuda con fecha de
caducidad conocida.

Tablas nuevas:

```sql
create table gen_models (
  id text primary key,                    -- "kling-3.0-turbo"
  family text not null,                   -- "Kling"
  provider text not null,                 -- adaptador que lo sirve
  modality text not null check (modality in ('image','video','audio','lipsync')),
  max_duration_s numeric, resolutions text[], aspects text[],
  supports_i2v bool, supports_last_frame bool, supports_char_ref bool,
  cost_per_second numeric not null,       -- rango real: $0.05 → $1.50 (30×)
  min_plan text not null default 'free',
  status text not null default 'active'   -- active | deprecated | retired
    check (status in ('active','deprecated','retired')),
  sunset_at timestamptz,                  -- fecha de apagado conocida
  description_llm text not null           -- distinta de la descripción humana
);

create table camera_motions (
  id text primary key,                    -- "dolly-zoom"
  provider_ref jsonb not null,            -- {"higgsfield": "<uuid>", ...}
  label text not null,
  description_llm text not null,
  supports_strength bool default true,
  status text not null default 'active'
);

create table visual_styles (...);   -- paletas, iluminación, film stock, lentes
```

Y las tools se generan **en runtime** con `create_model` y `Literal[*ids]`
construidos desde estas tablas, filtradas por plan del usuario y por `status`:

```python
async def build_generate_video_tool(team_ctx: TeamContext) -> type[BaseModel]:
    models = await gen_models.active_for(team_ctx, modality="video")
    motions = await camera_motions.active()
    return create_model(
        "GenerateVideoArgs",
        model=(Literal[tuple(m.id for m in models)], Field(description=...)),
        camera_motion=(Literal[tuple(m.id for m in motions)] | None, None),
        element_refs=(list[Literal[tuple(e.id for e in team_ctx.elements)]], []),
        ...
    )
```

Tres consecuencias, todas buenas:

1. **El modelo no puede alucinar** un modelo, un movimiento de cámara o un personaje
   que no existe — el enum está en el JSON Schema, no en una instrucción del prompt.
2. **Apagar un proveedor es un `UPDATE`**, no un despliegue. El 30 de julio marcamos
   Runway como `retired` y el agente deja de ofrecerlo esa misma noche.
3. **Un recurso restringido por plan es indistinguible de uno inexistente** — el
   usuario free nunca ve que existe Seedance 2.0, así que el agente no lo propone y
   luego falla.

Añadimos el descubrimiento en dos niveles de PostHog: una tool
`list_available_models(modality, max_cost)` para cuando el agente necesita elegir con
criterio, y errores que **enumeran las opciones válidas** cuando algo no encaja.

---

## 5. Contexto del proyecto

Copiamos `context/context.py`. El frontend **no manda ids, manda los objetos**, y se
inyecta como `ContextMessage` **antes** del mensaje humano (entra en la caché de
prompt y sobrevive a la compactación).

`XframeUIContext` incluye:

| Campo | Contenido | Nota |
|---|---|---|
| `open_tab` | brief / canvas / assets / elements / preview | determina qué tools contextuales existen |
| `brief` | bloques en orden `position` | el guion/tratamiento |
| `timeline` | shots en **orden narrativo** | equivalente al orden (y,x) de layout de PostHog |
| `elements` | personajes/localizaciones/objetos con `role`, thumb y ficha | el sistema de continuidad |
| `selected_assets` | lo que el usuario tiene seleccionado ahora | |
| `gen_settings` | modelo, aspect, res, dur, estilo, cámara | de `profiles.settings` |
| `credits` | saldo actual | el agente debe saber si puede permitirse lo que propone |

**El orden narrativo del timeline no es cosmético**: es la señal que le dice al modelo
qué plano va antes de cuál, y por tanto qué continuidad debe respetar.

Cada shot se serializa con su **spec completa + estado de render**, igual que PostHog
adjunta la query *y sus resultados*:

```xml
<shot id="s3" position="3" status="ready" duration="8s">
  <prompt>Astronauta solitario en traje EVA flotando en gravedad cero…</prompt>
  <elements>@astronauta-marco @estacion-orbital</elements>
  <camera motion="dolly-zoom" strength="0.6" lens="35mm" aperture="f/2.0"/>
  <model>kling-3.0-turbo</model>
  <asset id="a91" kind="video" cost_credits="14"/>
</shot>
```

Todo el bloque va envuelto en `<attached_context>` + un `<system_reminder>` que lo
declara **untrusted data** — defensa anti prompt-injection, relevante en cuanto
aceptemos briefs pegados o assets de terceros.

**Escalera de degradación** ante presupuesto de tokens (3 peldaños, con telemetría de
cuál se usó): timeline completo → solo specs sin prompts largos → solo títulos y
estados. Y truncado autoconsciente: `"…y 24 planos más"`, nunca un corte en seco.

---

## 6. Memoria: la biblia de estilo

`CoreMemory` de PostHog es un blob de texto por equipo. El nuestro es por **proyecto**
y contiene lo que define la identidad visual:

- **Fichas de personaje**: descripción física canónica, vestuario, referencia de rostro.
- **Biblia de estilo**: paleta, iluminación, film stock, referencias cinematográficas.
- **Reglas de continuidad**: qué debe mantenerse constante entre planos.
- **Preferencias del director**: qué ha rechazado el usuario y por qué.

Se genera en un onboarding tipo `/init` (a partir del brief y de los primeros assets
aprobados) y se actualiza con un `MemoryCollectorNode` en paralelo, con tools
`memory_append` / `memory_replace`, más un `/remember` determinista sin LLM.

**Y aquí va el punto de correctitud más importante de todo el sistema:**

> Tras compactar el historial, la biblia de estilo y las fichas de personaje **deben**
> reinyectarse. Si no, se rompe la continuidad visual entre planos — y el fallo se
> paga en créditos de generación, no en tokens.

PostHog reinyecta la todo list y el modo activo. Nosotros reinyectamos eso **más** el
estado operativo de producción (qué planos están pendientes) **más** la biblia.

---

## 7. Herramientas

Contrato base copiado de `ee/hogai/tool.py`: registro por `__init_subclass__`,
`args_schema` Pydantic, `description` larga, `context_prompt_template`, control de
acceso, y separación `content` (texto barato al LLM) / `ui_payload` (estructura
completa al frontend).

### Lectura / preproducción (baratas, sin créditos)

| Tool | Qué hace |
|---|---|
| `read_project` | brief, timeline, elements, settings |
| `list_available_models` | catálogo filtrado por plan y coste |
| `search_assets` | búsqueda sobre los assets del proyecto |
| `write_brief` / `update_brief_block` | edita el tratamiento (bloques Notion) |
| `create_shot` / `update_shot` / `reorder_shots` / `delete_shot` | shot list en el canvas |
| `define_element` | crea/actualiza ficha de personaje, localización u objeto |
| `estimate_cost` | coste en créditos de un plan de generación **antes** de ejecutarlo |

### Generación (caras, consumen créditos)

| Tool | Notas |
|---|---|
| `generate_image` | referencia de personaje si el modelo la soporta |
| `generate_video` | t2v / i2v / first-last-frame; `camera_motion` de la taxonomía |
| `generate_shot_batch` | **fan-out**: N shots en paralelo, una tool call por shot |
| `generate_lipsync` / `generate_audio` | |
| `upscale_asset` | |
| `assemble_video` | montaje final de los clips |

### Meta

`switch_mode`, `finalize_plan`, `check_job_status`.

Como en PostHog, `switch_mode` genera su descripción y su `Literal[*modes]` en runtime
instanciando las tools reales — **el catálogo nunca miente**.

---

## 8. Modos: la restricción es estructural, no un ruego al prompt

| Modo | Tools disponibles | Propósito |
|---|---|---|
| `preproduction` | lectura + brief + shots + elements + `estimate_cost` | **Sin ninguna tool de generación.** Guion, shot list y fichas. Cero créditos. |
| `production` | todo | Genera. Requiere plan aprobado. |
| `edit` | generación puntual + edición de timeline | Retoques sobre un montaje existente. |

Esto viene directo del research agent de PostHog (PLAN sin `create_form`, RESEARCH sin
`finalize_plan`): **la garantía de que no se queman créditos antes de aprobar es que
las herramientas no existen**, no que se lo hayamos pedido en el system prompt.

`plan` es un **supermodo ortogonal**: el plan es un artefacto visible y editable, y el
resultado del tool call `switch_mode` se reescribe con el catálogo completo de
capacidades de la fase siguiente.

---

## 9. Capa de proveedores

Contrato uniforme, un adaptador por proveedor:

```python
class GenerationAdapter(Protocol):
    provider_id: str
    async def submit(self, req: GenerationRequest) -> ProviderJobRef: ...
    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus: ...
    async def cancel(self, ref: ProviderJobRef) -> None: ...
    def normalize_error(self, exc: Exception) -> GenerationError: ...
    def estimate_cost(self, req: GenerationRequest) -> Decimal: ...
```

`GenerationRequest` es **nuestro** vocabulario (prompt, elements, motion, duración,
aspect, seed); cada adaptador lo traduce al dialecto de su proveedor. El agente nunca
ve un payload de proveedor.

Adaptadores iniciales: `veo`, `kling`, `sora`, `hailuo`, `seedance`, `wan`,
`higgsfield` (único camino legítimo a los presets DoP y a Soul ID — en ese eje es
proveedor, no competidor), `flux`/`nano-banana` para imagen.

Dos notas del informe de APIs:

- **Higgsfield es en sí mismo un agregador**: solo DoP y Soul ID son suyos; el resto lo
  compra. Que nosotros agreguemos no es un atajo, es la arquitectura correcta.
- Como los adaptadores comparten contrato, **un agregador entra como un adaptador más**
  el día que quieras cubrir la cola larga sin reescribir nada.

**Webhooks donde existan, polling donde no** — nunca más rápido que el rate limit del
proveedor (Runway throttlea por encima de 1 req/5 s).

---

## 10. Jobs, créditos e idempotencia

```sql
create table generation_jobs (
  id uuid primary key,
  project_id uuid not null references projects on delete cascade,
  asset_id uuid references assets,
  shot_id text,
  provider text not null, model text not null,
  request jsonb not null,
  idempotency_key text not null unique,   -- hash(provider,model,params,seed)
  status text not null check (status in
    ('queued','submitted','running','succeeded','failed','cancelled','nsfw')),
  provider_ref jsonb,
  credits_reserved int not null default 0,
  credits_charged int not null default 0,
  attempts int not null default 0,
  error jsonb,
  created_at timestamptz, updated_at timestamptz
);
```

**Créditos: reservar → confirmar → reembolsar.** Se reservan al encolar, se cobran al
`succeeded`, se devuelven en `failed`/`nsfw`/`cancelled`. El informe señala que
Higgsfield reembolsa en `failed` y `nsfw` pero **no todos los proveedores lo hacen**;
si no lo modelamos, perdemos dinero en silencio.

**Idempotencia:** `idempotency_key` sobre el hash de la petición. Un reintento idéntico
no vuelve a pagar — devuelve el asset cacheado. Esto es correctitud, no optimización:
los webhooks de fal reintentan hasta 10 veces en 2 h.

**Gate de coste** — dimensión que PostHog no tiene (su aprobación solo mira
destructividad). Antes de un fan-out:

1. `estimate_cost` suma el coste de todos los shots.
2. Si supera el umbral del proyecto **o** el saldo, `interrupt()` de LangGraph pide
   aprobación — y el usuario puede **editar los argumentos** antes de aprobar (patrón
   `upsert_dashboard`): bajar de Seedance 2.0 a Veo 3.1 Lite es un factor 30× en la
   factura.

**`Semaphore`** por proyecto y por proveedor, más backoff exponencial ante rate limits.

---

## 11. Fan-out de planos

`generate_shot_batch` emite N tool calls y cada una se convierte en tarea. Motor con
el patrón de `parallel_task_execution/nodes.py`:

```python
async with asyncio.TaskGroup() as tg:
    tasks = [tg.create_task(run_shot(s)) for s in shots]
# los hijos DEVUELVEN la excepción, no la lanzan
```

**El detalle que hay que respetar sí o sí** (de `ee/hogai/videos/`): los hijos
**devuelven** `Asset | Exception` en lugar de lanzar. Si lanzan, `TaskGroup` cancela a
las hermanas y pierdes —y pagas— los planos que sí habían salido.

Más: `asyncio.wait(FIRST_COMPLETED)` en bucle para hacer yield **en orden de
finalización** (el usuario ve cada plano según sale), umbral
`failed_shots_min_ratio` para abortar el lote si va mal, y limpieza de assets
parciales.

**Terminación por condición sintáctica verificable**, no por contador: el timeline
está listo cuando no queda ningún shot en estado `pending`. Es el equivalente a los
marcadores `[UNVERIFIED]` del research agent.

---

## 12. Streaming y jobs largos

Tres capas, como PostHog, con **Redis Streams como buffer** → la reconexión sale gratis:

```
worker ──▶ Redis Stream (por conversación) ──▶ SSE ──▶ EditorChat
```

Eventos: `message_delta`, `tool_start`, `tool_progress`, `asset_ready`,
`job_status`, `interrupt_request`, `error`.

**El grafo no bloquea durante minutos.** La tool de generación encola y devuelve un
`AssetRefMessage` en estado `generating`; el frontend pinta un placeholder (el
`LoadingBlock` que PostHog no necesita y nosotros sí). El worker es el dueño del job.
Si el usuario cierra el navegador, el worker sigue, los assets aterrizan en la BD, y al
reconectar el agente reanuda desde el checkpoint.

Timeouts del patrón sandbox de PostHog: **infinito en arranque frío, 60 s de
inactividad tras el primer dato**.

---

## 13. Montaje final

`assemble_video` con **ffmpeg** como motor por defecto: los clips ya vienen
renderizados de los proveedores, así que el montaje es concatenación + transiciones +
audio + subtítulos. No necesitamos un motor de composición completo.

Entrada: el timeline en orden narrativo con los assets `ready`. Salida: un asset de
tipo `cut` que es un artefacto más — versionado, referenciable y regenerable.

Remotion queda como opción futura si aparecen necesidades de composición programática
(títulos animados, lower thirds, motion graphics).

---

## 14. Artefactos por referencia

Copiamos `artifacts/manager.py`: registro por decorador, y **refs rotas degradan a
`ErrorBlock` sin romper el documento**.

- El guion guarda `ShotRefBlock`, no copias.
- El timeline guarda `ShotRefBlock`.
- Un `cut` guarda referencias a assets.

Consecuencia: **regenerar un plano actualiza automáticamente todo lo que lo
referencia** — guion, timeline y montajes. Sin esto, cada regeneración obliga a
propagar cambios a mano y las inconsistencias son inevitables.

---

## 15. Prompts

- **System prompt como slots reutilizables**, no como string (`chat_agent/prompts/base.py`).
  Secciones activables por feature flag → A/B testing trivial.
- **Estático primero, dinámico al final**, para que funcione el prompt caching.
- Secciones XML no anidadas, templating Mustache.
- **"Nunca adivines"**: ningún nombre de personaje, elemento, modelo o estilo que no
  esté en la taxonomía o en los elements del proyecto. Verificar con tools.
- Sub-prompts especializados: director de guion, director de fotografía (traduce
  intención narrativa a parámetros de cámara), *prompt engineer* (spec de plano →
  prompt del modelo concreto, que **varía por proveedor**).
- Few-shot con contraste `<good_example>` / `<bad_example>`, donde el malo es
  plausible.

---

## 16. Evals

Braintrust + pytest (`python_files = eval_*.py`), scorers graduados 0.0/0.5/1.0 y
`score=None` ≠ 0.0.

| Scorer | Origen PostHog | Qué mide |
|---|---|---|
| `ScriptCoherence` | `PlanCorrectness` | el guion responde al brief |
| `ShotListCompleteness` | `QueryAndPlanAlignment` | los planos cubren el guion |
| `CharacterContinuity` | `SQLSemanticsCorrectness` | el personaje es el mismo entre planos |
| `StyleAdherence` | `StyleChecker` | modos de fallo nombrados, no escala |
| `ParamRelevance` | `ToolRelevance` | modelo y movimiento adecuados a la intención |
| `RenderValidity` | `SQLSyntaxCorrectness` | la petición es válida para ese proveedor |
| `CostEfficiency` | — (nuevo) | ¿el resultado justificaba el modelo elegido? |

`CharacterContinuity` y `StyleAdherence` corren con un modelo visual sobre los frames
generados. Truco del informe: **acelerar el vídeo 8× antes de pasarlo al juez**, porque
muestrea a ~1 fps.

---

## 17. Estructura de código

```
backend/
├── app/
│   ├── main.py                 # FastAPI: /chat (SSE), /jobs/webhook, /projects
│   ├── agent/
│   │   ├── graph.py            # ROOT + ROOT_TOOLS
│   │   ├── state.py            # XframeState, reductores, centinelas
│   │   ├── executables.py      # nodos
│   │   ├── modes/              # preproduction | production | edit
│   │   ├── compaction.py       # + reinyección de biblia de estilo
│   │   └── prompts/            # slots componibles
│   ├── tools/
│   │   ├── base.py             # MaxTool → XframeTool
│   │   ├── errors.py           # ← copiar tool_errors.py casi literal
│   │   ├── registry.py         # __init_subclass__ + build dinámico
│   │   ├── brief.py  shots.py  elements.py
│   │   └── generation.py       # generate_image/video/batch, assemble
│   ├── taxonomy/               # gen_models, camera_motions, styles → Literal runtime
│   ├── context/                # XframeUIContext, serialización, escalera
│   ├── memory/                 # biblia de estilo, fichas de personaje
│   ├── artifacts/              # ShotRefBlock, handlers, manager
│   ├── providers/
│   │   ├── base.py             # GenerationAdapter (Protocol)
│   │   └── {veo,kling,sora,hailuo,seedance,wan,higgsfield,flux}.py
│   ├── jobs/                   # cola, worker, polling, webhooks, créditos
│   └── assembly/               # ffmpeg
└── evals/
```

Frontend: `src/main.jsx` se rompe en módulos y `EditorChat` pasa a consumir SSE real.

---

## 18. Riesgos

| Riesgo | Mitigación |
|---|---|
| **Rotación de modelos** — Runway 30 jul, Sora 24 sep, Veo 3.0 ya apagado | Taxonomía en BD con `status` y `sunset_at`; apagar es un `UPDATE`. Alerta automática 14 días antes. |
| Coste descontrolado (rango 30× entre modelos) | `estimate_cost` + gate con aprobación editable + reserva de créditos |
| Continuidad rota tras compactar | Reinyección obligatoria de biblia y fichas; scorer `CharacterContinuity` en CI |
| Pérdida de trabajo pagado en fan-out | Hijos devuelven `Exception`, no la lanzan |
| Doble cobro por reintento | `idempotency_key` único |
| N integraciones directas | Contrato `GenerationAdapter`; un agregador cabe como adaptador más |
| Datos no verificados del informe de APIs | Precios y latencias de Kling/Hailuo/Luma/Pika/Wan **sin confirmar** — validar antes de fijar unit economics |
```
