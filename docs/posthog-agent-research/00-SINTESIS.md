# Síntesis: qué robarle al agente de PostHog (Max AI) para Xframe

Investigación sobre `PostHog/posthog @ ee/hogai` (562 ficheros analizados).
Informes detallados con código literal en `01`–`05` de este mismo directorio.

---

## 0. Punto de partida real

Xframe **no tiene agente**. `src/main.jsx` (6.279 líneas) es un prototipo de UI:
`generateAssets` (línea 4588) y las respuestas del chat (línea 4650) son mocks.
No hay backend, ni llamada a LLM, ni herramientas, ni persistencia más allá de
`src/lib/db.js`.

Esto es una ventaja: podemos adoptar la arquitectura de PostHog sin migrar nada.
Pero implica que el trabajo es **construir**, no "mejorar".

---

## 1. Los cinco hallazgos que más valen

### 1.1 La topología del grafo es trivial — la complejidad va en los executables

El agente de PostHog tiene **exactamente dos nodos**: `ROOT` (LLM) y `ROOT_TOOLS`,
con aristas condicionales entre ambos. El paralelismo se logra con
`Send(ROOT_TOOLS, state.model_copy(update={"root_tool_call_id": tc.id}))`,
un map-reduce sobre el estado.

**Consecuencia para nosotros:** no diseñar un grafo con nodos "guion → shotlist →
render → ensamblado". Eso se vuelve rígido en cuanto el usuario pide algo fuera de
secuencia ("cambia solo el plano 7"). Un loop de dos nodos + herramientas bien
descritas cubre ambos casos.

### 1.2 El frontend manda objetos, no ids — y el contexto va en el HumanMessage

`AssistantContextManager._format_ui_context` recibe los objetos completos que el
usuario tiene abiertos, ejecuta sus queries y adjunta **también los resultados**.
Se inyecta como `ContextMessage` insertado *antes* del mensaje humano, no en el
system prompt: así entra en la caché de prompt y sobrevive a la compactación.

Los insights de un dashboard se ordenan **por posición de layout (y, x)** para que
el LLM lea en el mismo orden visual que el usuario.

**Mapeo:** el timeline se serializa en **orden narrativo**, con cada plano llevando
su spec completo y su estado de render. Un plano ≡ un insight.

### 1.3 Taxonomy toolkit: el modelo no puede alucinar porque el enum es runtime

Generan las tools con `create_model` y tipos `Literal[...]` construidos desde las
entidades reales del equipo. El enum acaba en el JSON Schema. No es una instrucción
de prompt que el modelo pueda ignorar — es una restricción estructural.

Apilan tres mecanismos: (a) `Literal` runtime, (b) descubrimiento en dos niveles
(nombres → valores), (c) errores que enumeran las opciones válidas.

**Mapeo — probablemente lo más valioso de toda la investigación:**
modelos de vídeo, estilos visuales, lentes, ratios, personajes y assets ya
generados pasan a ser `Literal` con lo que el usuario **realmente tiene en el
proyecto y en su plan de suscripción**. Elimina de golpe la clase de bug más
frecuente en agentes creativos: inventar un personaje o un modelo que no existe.

### 1.4 Reinyección de estado operativo tras compactar

Al compactar, reinyectan condicionalmente la todo list y el modo activo si no son
evidentes en la nueva ventana.

**Para nosotros esto no es un detalle de eficiencia, es correctitud:** si la biblia
de estilo y las fichas de personaje no se reinyectan tras un resumen, **se rompe la
continuidad visual entre planos**. Es el fallo más caro que podemos tener, porque
además se paga en créditos de generación.

### 1.5 Las restricciones se imponen quitando herramientas, no pidiéndolo en el prompt

El research agent tiene dos supermodos: PLAN (con `create_form`/`finalize_plan`) y
RESEARCH (sin ellos). El modo `plan` no tiene herramientas de escritura.

**Mapeo:** modo **preproducción** sin herramientas de generación. Garantía
estructural de que no se queman créditos antes de que el usuario apruebe el plan.

---

## 2. Código directamente copiable

| Origen | Qué es | Adaptación |
|---|---|---|
| `ee/hogai/tool_errors.py` | Política de reintento en la clase de excepción (`never`/`once`/`adjusted`), `retry_hint` en lenguaje natural para el LLM, `to_summary(max_length=500)` | Copiar casi tal cual |
| `core/loop_graph/graph.py` | Loop de 2 nodos + `Send` para fan-out | Copiar la topología |
| `utils/types/base.py` | `AssistantState`/`PartialAssistantState`, reductores `Annotated`, upsert por ID, centinela `CLEAR_*` porque `None` significa "no cambies" | Copiar el patrón |
| `artifacts/manager.py` + handlers | Registro por decorador, refs rotas → `ErrorBlock` sin romper el documento | Copiar |
| `context/context.py` | Formateo de contexto de UI, dedup por contenido, `<system_reminder>` untrusted | Copiar la estructura |
| `parallel_task_execution/nodes.py` | `asyncio.wait(FIRST_COMPLETED)` en bucle → yield en orden de finalización | Copiar |
| `eval/scorers/` | Scorers graduados 0.0/0.5/1.0, `score=None` ≠ 0.0, LLM-as-judge ordinal | Adaptar métricas |
| `chat_agent/prompts/base.py` | System prompt como slots reutilizables, no como string | Copiar la técnica |

---

## 3. Patrones de arquitectura a adoptar

**Artefactos por referencia, no por copia.** Un notebook guarda `VisualizationRefBlock`.
Traducido: el timeline guarda `ShotRefBlock`, y regenerar un plano actualiza todo
lo que lo referencia. Corolario crítico: **nunca meter binarios en el checkpoint**
(`ArtifactRefMessage` en estado vs `ArtifactMessage` enriquecido al cliente).

**`content` vs `ui_payload`.** Texto barato al LLM, estructura completa al frontend.

**Límites dobles y degradación amable.** `MAX_TOOL_CALLS = 24` + `recursion_limit: 96`.
Al llegar al límite **no lanzan excepción: le quitan las tools al modelo** e inyectan
un mensaje forzando el cierre. Nosotros necesitamos además límites *por recurso*
(`MAX_RENDERS`), no solo por tokens.

**El reintento no es un `for`.** El nodo devuelve estado con el error y el router
reencamina. Observable y reanudable — importante cuando cada intento cuesta dinero.

**Terminación por condición sintáctica verificable.** El research agent escribe un
borrador con marcadores `[UNVERIFIED]` y termina cuando no quedan. Nuestro
equivalente: un guion donde cada plano queda marcado hasta tener asset asignado.

**Aprobación condicional al daño real.** `upsert_dashboard` solo pide confirmación
si el diff borra algo, y el usuario puede **editar los argumentos** antes de aprobar.

**Estático primero, dinámico al final** en el prompt, para que funcione el caching.

**Fan-out con hijos que devuelven `Exception` en vez de lanzarla** — si lanzan,
`TaskGroup` cancela a las hermanas y pierdes los planos que sí salieron.
Más umbral `failed_moments_min_ratio` y limpieza de assets parciales.

---

## 4. Lo que PostHog no tiene y nosotros necesitamos añadir

1. **Dimensión de coste separada de la de destructividad.** Generar un plano es caro
   aunque no borre nada. Su modelo de aprobación solo mira destructividad.
2. **Jobs largos con polling.** Sus tools responden en segundos; las nuestras en
   minutos. Hace falta `LoadingBlock` + tool de consulta de estado.
3. **`Semaphore` y gate de presupuesto.** No tienen control de concurrencia ni tope
   de gasto por conversación.
4. **Caché por hash de prompt de generación.** Reintento idéntico = no repagar.
5. **Backoff explícito** ante rate limits de los proveedores de generación.
6. **Continuidad como invariante evaluable.** Su equivalente más cercano es
   `SQLSemanticsCorrectness`; nosotros necesitamos un scorer de continuidad de
   personaje/estilo entre planos consecutivos.

---

## 5. Detalles prácticos sueltos que merecen la pena

- Aceleran el vídeo **8×** antes de pasarlo a Gemini para QA visual, porque el
  modelo muestrea a ~1 fps.
- El contexto adjunto se envuelve en `<system_reminder>` declarándolo *untrusted
  data* — defensa anti prompt-injection. Relevante si ingerimos briefs de terceros.
- Escalera de degradación de 3 peldaños ante presupuesto de tokens
  (completo → solo schema → truncado), **con telemetría de qué peldaño se usó**.
- Truncado autoconsciente: `"and 37 more distinct values"` en vez de cortar en seco.
- `description_llm` distinta de la descripción humana.
- Un recurso restringido es **indistinguible de uno inexistente** para el modelo.
- El registro de tools es por `__init_subclass__`: heredar registra.
- Slash commands como nodo interceptor que hace short-circuit a END **sin llamar al
  LLM** (`/remember` es totalmente determinista).
- Sin router central de modelos: cada tarea elige su modelo junto a su código.
  El fallback de proveedor vive en un gateway externo.

---

## 6. Orden de implementación sugerido

1. Backend mínimo + loop de 2 nodos + `AssistantState` con reductores.
2. `tool_errors.py` y el ejecutor de tools con sus 4 capas de captura.
3. Taxonomía runtime (`Literal` de estilos/modelos/personajes) — antes que las
   tools de generación, porque define sus firmas.
4. Contexto de UI desde el editor (timeline en orden narrativo).
5. Artefactos por referencia + streaming.
6. Modo preproducción (sin tools de generación) / producción.
7. Fan-out paralelo de planos + gate de coste + polling.
8. Core memory (biblia de estilo/personajes) + reinyección tras compactación.
9. Evals.
