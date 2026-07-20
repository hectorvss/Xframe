# Auditoría completa del agente — 20 julio 2026

Seis auditorías independientes (empalmes, dinero, seguridad, concurrencia,
comportamiento, proveedores) sobre ~15.000 líneas de backend escritas por seis
agentes en paralelo.

**Veredicto: el sistema no arranca.** Los componentes hoja son código serio; la capa
que los compone no existe.

---

## Dos causas raíz

Casi todos los hallazgos son síntomas de estas dos. Atacarlas resuelve el grueso.

### Causa 1 — Fijé los contratos de datos, no los de función

Fijé `state.py`, `tools/base.py` y `providers/base.py`. Pero los nombres de las
funciones que cada módulo debía **exponer** se los di a cada agente en prosa, dentro de
su instrucción. Cada uno implementó el suyo:

| Se llama desde | Se llama así | Se llama de verdad |
|---|---|---|
| `executables.py:44` | `ContextManager(pid)` | `XframeContextManager(pid, uid)` |
| `main.py:40` | `bus.connect()` | (no existe; el constructor ya conecta) |
| `generation.py:471` | `run_shots(...)` | `run_fanout(shots, runner, ...)` |
| `generation.py:740` | `concat_shots(...)` | `assemble_cut(spec)` |
| `generation.py:118` | `enqueue(req, project_id=)` | exige además `adapter=` |
| `generation.py:166` | `job.id` | `job.job_id` |

Los 124 tests pasaban porque **cada módulo se probó aislado contra fakes**. Ninguno
ejecuta las dos mitades de un contrato juntas.

### Causa 2 — La capa de composición no se construyó

`RootNode` monta tools, contexto y prompt, y llama al modelo. Nada más. No compacta,
no recoge memoria, no interrumpe. `main.py` arranca el bus y el grafo, no el worker.

Huérfanos confirmados (código correcto, sin llamante):

- `compaction.py` — 515 líneas. **La reinyección de la biblia de estilo nunca corre.**
- `memory/collector.py` — la biblia nunca se rellena.
- `memory/onboarding.py`
- `jobs/fanout.py` — todo el diseño anti-cancelación está en el módulo muerto
- `jobs/worker.py` — `docker-compose` lanza `python -m app.jobs.worker`, que **no tiene `__main__`**
- `jobs/webhooks.py` — ninguna ruta lo monta
- Artefactos `script` / `timeline` / `cut` — sin productor
- `ui_context` — `main.py` lo envía, `runner.py` lo acepta y nunca lo usa

---

## P0 — Bloqueantes (sin esto no se ve un fotograma)

1. `main.py:40` — `bus.connect()` no existe. **El proceso no levanta.**
2. `executables.py:44` — `ContextManager`: nombre, aridad y método, los tres mal.
3. `generation.py:118,659` — `enqueue` sin `adapter`. Las 4 tools de generación fallan.
4. `generation.py:471` — `run_shots` no existe. El fan-out nunca ha funcionado.
5. `generation.py:740` — `concat_shots` no existe. El montaje nunca ha funcionado.
6. Nadie arranca el worker. Los jobs se quedan en `queued` para siempre.
7. `switch_mode` no persiste el modo → **el agente no sale nunca de preproducción**.

## P0-seguridad — No desplegar a URL pública sin esto

8. `main.py:79` — `x-user-id` sin verificar y **`project_id` nunca se contrasta contra
   `owner_id`**. Con un uuid ajeno se lee, se **borra** (`brief.py:74`) y se gasta
   contra el monedero de la víctima.
9. `/conversations/{id}/stream` — **sin autenticación alguna**. Con `Last-Event-ID: 0-0`
   se reproduce la transcripción completa.
10. `memory/store.py:252` — único bloque sin escapar, y el único con autoridad declarada
    en el prompt. Se puede fabricar un `<system_reminder>` falso desde la biblia.
11. Bucket `public = true`, rutas que no casan con las políticas, cero URLs firmadas.
    **Ojo: arreglar esto rompe la continuidad de personaje** (ver P1-15) — van juntos.

## P1 — Dinero

12. `webhooks.py:253` — el webhook de éxito repone `queued` sobre un job vivo → segundo
    claim → **segundo `submit` pagado**. ~$21/job en Seedance 4K.
13. `worker.py:269` — cancel con `external_id=""`. Timeout → reembolsamos al usuario,
    el proveedor cobra igual, el vídeo no se descarga. **Pérdida doble.**
14. `worker.py:165` — claim sin backpressure + `sweep_stale` → jobs reembolsados que
    luego se ejecutan y se pagan.
15. **Hailuo opera bajo break-even**: Minimax factura por clip, el seed lo modeló por
    segundo. `hailuo-2.3` a 6s = 0.96x. Y su `description_llm` le dice al modelo que es
    *"el modelo por defecto para un storyboard entero"*.
16. `credits_for` vs `estimate_cost` divergen hasta **4x**. Se anuncia un precio y se
    reserva otro. Siempre en contra del usuario.
17. `worker.py:420` — `charge` cobra siempre la reserva; el mecanismo de delta está
    construido y sin conectar.
18. **No existe camino de recarga**, y `_mirror_profile_credits` **destruye** cualquier
    recarga externa. Bloqueante para integrar pagos.
19. `state.py:185` — `generations_this_turn` con reductor "gana el último": 12 renders
    paralelos cuentan como 1. El límite por recurso es inoperante justo donde importa.

## P1 — Concurrencia

20. `executables.py:122-138` — dos `await` desprotegidos antes de la tool. Una rama que
    falle **cancela las hermanas**. El requisito "los hijos devuelven, no lanzan" solo
    se cumple en `fanout.py`, que está muerto.
21. Reintentos anidados 4×3 = **144 submits** en un fan-out de 12 contra proveedor caído.
22. `_http.py:93` — `Retry-After` recortado a 20s. Convierte un rate limit en un baneo.
23. `repo.py:249` — escritura obsoleta tras invalidar: `define_element` + generar en el
    mismo superstep → el personaje es invisible 10s.
24. `db.py:59` — pool sin timeout de adquisición + convoy en el cerrojo del perfil.
25. `_http.py:242` — throttle de polling por job, no por proveedor.
26. `main.py:92` — la desconexión **sí** aborta el turno (mi comentario dice lo contrario).

## P1 — Comportamiento

27. `MAX_TOOL_CALLS = 24` cuenta sobre **toda la conversación**, no por turno. A partir
    de la llamada 24 el agente pierde las herramientas **para siempre**.
28. El agente **nunca se entera de que un job terminó**. `conversation_id` no se propaga
    (queda NULL → `_emit` sale por el return temprano), y aunque llegara al bus, el
    evento no reentra en el grafo. Solo lo sabe si el humano pregunta.
29. Slash commands, interrupts/HITL, supermodo `plan` y `todos`: diseñados, no construidos.

## P1 — Proveedores (antes de la primera llamada real)

30. `veo.py:139` — `_extract_urls` busca claves que no existen. **Pagas la generación y
    la tiras.** La ruta real es `.response.generateVideoResponse.generatedSamples[0].video.uri`.
31. `veo.py:66` — imágenes por `gcsUri` (eso es Vertex). La Gemini API exige base64 inline.
32. `flux.py:95` — el campo de referencias **no existe**. Son `input_image`,
    `input_image_2`..`_8`. Hoy Flux genera **sin ninguna referencia y devuelve 200**:
    el fallo más engañoso del set.
33. `seedance.py` — host, model ids y esquema de parámetros equivocados a la vez.
34. `seed.py` — ids de Veo (`veo-3.1` → `veo-3.1-generate-preview`) y de Wan inexistentes.
    `veo-3-fast` apunta a Veo 3.0, **apagado el 30 jun 2026**.
35. `higgsfield.py:163` — `soul_id` → **`custom_reference_id`**. Una línea, y es el
    mecanismo de continuidad de mayor valor del catálogo.
36. `kling.py:134` — `image_list` es primer/último fotograma, no multi-referencia. La
    continuidad real es `kling_elements`. **Base URL sin confirmar** (doc devuelve 446).
37. `sora.py:86` — `input_reference` debe ser objeto `{"image_url": ...}`, no string.

---

## Lo que está bien y no hay que tocar

- **Contabilidad de créditos**: ledger append-only, cerrojo **antes** de decidir, cierre
  único idempotente. La parte más sólida del backend.
- **Idempotencia del encolado**: `project_id` en la clave, orden lock→consulta correcto.
  Dos peticiones idénticas simultáneas se cobran una vez.
- **Aislamiento por `project_id`**: ~100 consultas revisadas, **ni una sin filtro**.
  Cero inyección SQL. Cero secretos filtrados.
- **Escapado XML del contexto**: se intentó construir un brief que se escapara y no se pudo.
- **La cadena de continuidad de personaje**: bien construida de punta a punta, del
  contexto al payload del proveedor. El núcleo del producto es lo mejor resuelto.
- **Webhooks duplicados/desordenados**: triple defensa correcta.
- **No se retienen conexiones de BD** durante las esperas al proveedor.
- **Captura de variables de bucle**: los 4 sitios, correctos.
- `assemble_video` se niega a montar con planos pendientes, y lo explica bien.
- Taxonomía vacía → las tools no se montan, en vez de fallar de forma críptica.

---

## Primera prueba real: con qué empezar

**1º MiniMax / Hailuo 2.3 Fast.** Único adaptador con **cada campo verificado contra
doc oficial**, incluida la estructura literal de `subject_reference`. ~$0.11-0.19 por
clip de 6s. Valida de una vez el patrón de tres saltos, `_http.py` y la continuidad
de personaje.

**2º Higgsfield DoP Lite.** ~$0.135/clip. Estratégicamente irreemplazable: los
movimientos de cámara por UUID y Soul ID no se compran en otro sitio. Requiere el fix
de una línea de `custom_reference_id`.

**Presupuesto de la primera tanda: menos de $1** para ~4 generaciones.

**Con qué NO empezar:** Seedance (tres cosas mal a la vez, y es el más caro), Veo
(pagas y tiras el resultado), Flux (devuelve 200 sin aplicar la referencia — sacarías
conclusiones falsas sobre la calidad de la continuidad).
