# Auditoría end-to-end del agente — 21 julio 2026

Esta auditoría describe el sistema que existe hoy, no la intención de producto ni la
auditoría histórica del 20 de julio. El criterio es estricto: una capacidad solo figura
como operativa si tiene contrato de datos, herramienta, persistencia, reflejo en UI y
algún gate que impida afirmar un resultado que no existe.

## Veredicto

El agente ya tiene una arquitectura de producción coherente para pasar de brief a
entrega sin sobrescribir fuentes y con referencias exactas. Puede construir y editar
brief, guion, canvas, assets, voces, cues, planos, transiciones, manifiestos y cortes.
El uso de `@` llega como identificadores validados, no como nombres ambiguos, y puede
quedar bloqueado para proyecto, escena, línea, plano o rango temporal.

No debe llamarse todavía «autónomo perfecto». La instalación auditada solo tiene
configurados OpenAI/Images; ElevenLabs, Sync y los demás proveedores de vídeo están sin
credenciales. Ya existe inspección técnica real, análisis objetivo de señal de audio y
revisión creativa multimodal sobre frames reales y referencias canónicas. Lipsync sigue
siendo la frontera honesta: se aceptan métricas del proveedor cuando existen y, si no,
queda en `needs_review`; nunca se convierte la ausencia de evidencia en un aprobado.

Valoración actual:

- Arquitectura y control de estado: **9,3/10**.
- Editabilidad desde UI/chat: **9/10**.
- Fiabilidad verificable sin proveedores externos: **9/10**.
- Operación audiovisual completa en este entorno: **5/10**, limitada por credenciales y
  por la ausencia de pruebas pagadas reales.

## Flujo real

1. El usuario crea o edita el project brief por bloques. Texto e imágenes sobreviven
   como filas estables; una imagen se convierte primero en asset del proyecto.
2. El guion se estructura en escenas y líneas con personaje, voz, interpretación,
   timing, estado y referencias.
3. El canvas separa nodos conceptuales/referencias de los nodos de tipo `shot`. Solo los
   `shot` entran en la secuencia narrativa que genera el agente.
4. Assets, Elements, voces, plantillas sonoras y transiciones pueden vincularse mediante
   `resource_bindings` con rol, instrucciones, bloqueo, prioridad y rango en milisegundos.
5. Audio coloca archivos existentes en una timeline determinista con pista, escena,
   línea/plano, entrada/salida, trim, ganancia, fades, paneo, loop, ducking y aprobación.
   El usuario puede editar en tiempo absoluto o relativo al inicio de la escena.
6. Antes de una escena multipano, el director crea un manifiesto versionado. Este congela
   guion, planos, recursos, voces, cues, continuidad y reglas de entrega.
7. Un manifiesto inválido no se puede aprobar. La aprobación requiere lenguaje explícito
   del usuario y almacena mensaje, usuario, referencias y huella SHA-256.
8. La generación encola jobs; los workers generan, aterrizan archivos en storage, cobran
   o reembolsan y notifican al hilo. Las derivaciones conservan `parent_id`, operación,
   inputs, modelo, prompt, parámetros, job y créditos.
9. Cada plano necesita output listo y QA dinámico antes de cerrar su manifiesto:
   técnico, render, prompt, identidad, continuidad, producto, texto, guion o lipsync
   según el contenido real del plano. Audio y transiciones tienen gates propios.
10. Al completar el manifiesto se congelan los UUID exactos de tomas, jobs, informes,
    cues, plan de audio y transiciones, junto a una huella SHA-256. El montaje consume
    exclusivamente ese snapshot; un asset nuevo no puede deslizarse en el corte.
11. La entrega final requiere inspección técnica, revisión humana de corte y, si hay
    audio, revisión humana de audio. Solo entonces se crea una aprobación de entrega.

## Control con `@`

El compositor ofrece assets, Elements, escenas, líneas, planos, nodos de canvas, voces,
cues, plantillas, transiciones, anotaciones, operaciones de edición, informes QA y
manifiestos. El frontend manda `{type,id}`; el backend vuelve a validar cada UUID contra
el mismo proyecto antes de mostrarlo al LLM. Los nombres duplicados reciben un sufijo
derivado del UUID, por lo que nunca se resuelven por coincidencia textual ambigua.

Hay dos niveles distintos y necesarios:

- **Referencia del turno**: «trabaja ahora con `@producto`». Orienta la operación actual.
- **Binding persistente**: «usar obligatoriamente `@producto` en escena 2, 4.2–6.8 s».
  Se conserva en base de datos y entra en el manifiesto. `locked=true` impide la
  sustitución silenciosa.

Un binding puede usar tiempo absoluto. Un cue admite tiempo absoluto o relativo a la
escena: el frontend lo presenta en segundos de escena y el backend lo convierte usando
`script_scenes.timeline_start_ms`, conservando `scene_id`, `shot_id` y `script_line_id`.

## Capacidades por superficie

| Superficie | Estado | Control disponible |
|---|---|---|
| Project brief | Operativa | CRUD por bloque, orden, todos, texto, imágenes/asset, edición incremental del agente |
| Guion | Operativa | Escenas/líneas CRUD, orden, speaker, voz, performance, duración, aprobación, assets por escena/línea |
| Canvas | Operativa | Conceptos, referencias, planos, media, posiciones, conexiones y CRUD desde UI/chat sin cambiar UUIDs |
| Assets/Elements | Operativa | Upload/generación, roles libres, selección `@`, linaje, anotaciones por punto/región/tiempo |
| Edición de imagen | Operativa con proveedor compatible | Plan no destructivo, máscara rectangular/dibujo, preservación y output derivado |
| Edición de vídeo | Parcial por proveedor | Extend/remix/variation y frame boundary; edición arbitraria solo si un modelo declara capacidad real |
| Voces | UI y modelo de datos operativos | Catálogo, previews, perfiles, asignación a personajes/líneas, performance y consentimiento |
| Música/SFX/ambiente | Operativa con proveedor | Generar, guardar, editar/variar, convertir en plantilla, drag & drop y mezcla exacta |
| Lipsync | Estructura operativa | Audio/segmentos multi-speaker, face mapping, sync mode, output derivado y gate de calidad |
| Transiciones | Operativa | Cut/crossfade deterministas o puente generado entre frames frontera exactos, seed y firma |
| Manifiesto | Operativa | Versionado, validación, huella, aprobación humana y bloqueo de montaje |
| QA y entrega | Operativa | `ffprobe`, LUFS/true peak/silencio/clipping, visión sobre frames reales, evidencia/autor, gates dinámicos y aprobación final humana |

## Qué impide un output «serio» falso

- El asset fuente nunca se sobrescribe; cada resultado es una derivación trazable.
- Un modelo no aparece si la taxonomía o sus credenciales no lo habilitan.
- Los bindings bloqueados y Elements se resuelven por UUID.
- Las escenas multipano necesitan manifiesto y aprobación explícita.
- Un output `ready` no equivale a output aprobado.
- Un reintento multipano solo acepta jobs fallidos/cancelados/NSFW o outputs cuya
  revisión vigente haya fallado; bloquea tomas sanas, activas o pendientes de QA.
- Completar un manifiesto congela linaje y pruebas. Montar desde «latest asset» está
  estructuralmente prohibido.
- La tool de QA humana exige que el mensaje actual identifique el asset y exprese una
  decisión; el agente no puede autocertificar media que no ha inspeccionado.
- La entrega es una entidad auditable distinta del asset y referencia los informes que
  la justificaron.

## Faltantes reales

### P0 operativo: necesario para producir fuera de OpenAI

1. Configurar y hacer un smoke test pagado por proveedor. En este entorno: OpenAI y
   OpenAI Images están configurados; Google, Kling, MiniMax, ByteDance, Wan, Higgsfield,
   BFL, ElevenLabs y Sync no lo están.
2. Probar un ciclo real de cada proveedor habilitado: submit, poll/webhook, descarga,
   almacenamiento, cobro, visualización y regeneración. La suite usa dobles y no demuestra
   que un endpoint externo no haya cambiado.
3. Ejecutar los siete tests de integración Postgres/worker con Docker disponible. Ahora
   se saltan porque Docker no está arrancado.
4. Ejecutar los cuatro evals de comportamiento con una clave de juez real. Ahora se
   saltan por ausencia de `ANTHROPIC_API_KEY`.

### P1 de calidad externa

1. Conectar un evaluador temporal de lipsync independiente (SyncNet/equivalente) para
   medir offset AV, boca, identidad y asignación de hablante cuando el proveedor no
   entregue esas métricas. Hasta entonces ese caso exige revisión humana.
2. Ejecutar el E2E pagado con media real para calibrar los umbrales del QA multimodal y
   de loudness. La infraestructura mide outputs reales, pero los thresholds necesitan
   ejemplos representativos del producto y de sus formatos de entrega.
3. Convertir automáticamente cada informe fallido en una propuesta de retry con parámetros
   corregidos y estimación de coste. El backend ya impide reintentar tomas sanas y permite
   el subconjunto fallido; la decisión creativa del nuevo seed/prompt sigue en el agente.

### P2 de experiencia

1. Vista de diff entre versiones de manifiesto y aprobación/rechazo por cada warning.
2. Overlay de waveform y playhead animado en Audio. La reproducción multipista ya funciona
   en el navegador con trim, gain, pan, fades, loop y ducking.
3. Grupos, frames, alineación y selección múltiple en Canvas. El CRUD y las conexiones
   funcionan, pero no es todavía un editor visual del nivel de Figma.
4. Historial de operaciones/QA visible en cada asset con comparación lado a lado entre
   padre y variante.

## Fallos encontrados y corregidos en la reauditoría

1. **Relación escena–plano rota desde UI.** `scene_shots` usa clave compuesta, pero el
   frontend intentaba borrar por una columna `id` inexistente. Mover o quitar un plano
   podía fallar en Supabase. Ahora elimina mediante `project_id + scene_id + shot_id`.
2. **Migraciones ausentes disfrazadas de estado vacío.** `getProduction()` convertía
   cualquier fallo de una tabla central en `[]`. Ahora Guion/Audio muestran un error
   accionable con la tabla que falta; solo las secciones auxiliares degradan a vacío.
3. **Contexto de audio contradictorio.** UI y tools permitían combinar una línea, un
   plano y una escena que no se correspondían. Ahora la escena canónica se deriva de la
   línea/plano y se rechaza cualquier contradicción tanto en chat como en UI.
4. **Cambio de escena sin recolocar el cue.** El selector podía dejar un tiempo global
   anterior al inicio de la nueva escena. Ahora escena, duración, tiempo, línea y plano
   se actualizan como una sola operación coherente.
5. **Preview fuera de rango.** WebAudio podía lanzar una excepción opaca si
   `source_in_ms` estaba fuera del archivo. Ahora se valida y la reproducción no excede
   la duración decodificada.
6. **Cobertura de esquema falsa en integración.** La fixture solo aplicaba el esquema
   antiguo del agente. Ahora incluye las migraciones de producción 008–022, de modo que
   una base sin Guion/Audio no puede aprobar los E2E cuando Docker esté disponible.
7. **Referencias `@` incompletas.** Operaciones e informes QA no eran seleccionables.
   Ya se resuelven por UUID y proyecto, y los límites de token/prompt no sustituyen esa
   validación.
8. **Tipos de asset dependientes del idioma.** Los uploads de la UI se guardaban como
   `Audio`, `Vídeos` o `Imágenes`, mientras varias tools exigían `audio/video/image`
   exactos. Los uploads nuevos usan tipos canónicos y el backend conserva compatibilidad
   con los existentes; los MP4 con pista sonora también pueden entrar en un plan de audio.
9. **Evento de render interpretado con el identificador equivocado.** El worker emite
   `asset_id`, pero la UI buscaba `id` e intentaba insertar otra fila. Ahora el worker es
   el único propietario de la fila y la UI relee la fuente de verdad tras `asset_ready`.
10. **Regeneración destructiva.** El botón ponía el asset fuente en `generating` y
    borraba su URL antes de pedir la variante. Ahora conserva el original, envía su
    referencia `@` validada y exige un output derivado con linaje.
11. **Controles de sonido decorativos.** La intensidad del compositor ya viaja como
    `prompt_influence` validado entre 0 y 1, y la voz escogida se asigna a la línea del
    guion antes de generar. Sin proveedor configurado la edición sigue disponible, pero
    generar permanece deshabilitado con un estado honesto.

## Verificación ejecutada

- `python -m compileall -q app`: correcto.
- Suite backend final: **1.038 passed, 11 skipped**.
- `python -m ruff check .`: correcto con target real de Python 3.11.
- `npm run build`: correcto; solo queda el aviso de chunk principal grande.
- `git diff --check`: sin errores de whitespace.
- Migraciones 013–022 aplicadas al Postgres configurado.
- Consulta directa al Postgres configurado: presentes `script_scenes`, `script_lines`,
  `scene_shots`, `voice_profiles`, `audio_cues.scene_id`, `audio_templates`,
  `resource_bindings`, `production_manifests` y `quality_reports`.
- Navegador: landing y autenticación cargan sin errores de consola. La prueba de las
  pantallas privadas no pudo completarse en el navegador aislado porque no comparte la
  sesión autenticada del usuario; no se falsea como verificada.

## Criterio de «completamente funcional»

No basta con que compile. Se considerará completo cuando exista una prueba grabada y
repetible que haga: brief → guion → planos → `@bindings` → voces/audio → render →
lipsync → QA → montaje → entrega, con al menos un personaje persistente, un producto
bloqueado, un cue temporal, una edición enmascarada y una regeneración por fallo. Debe
demostrar persistencia tras recarga, importes del ledger, identidad de UUIDs, evidencia de
aprobación y reproducción del archivo final almacenado.
