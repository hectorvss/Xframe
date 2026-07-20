# 06 — Ecosistema de APIs de generación de imagen y vídeo

**Fecha de investigación:** 20 de julio de 2026
**Método:** WebSearch + WebFetch sobre documentación oficial y fuentes secundarias.

## Cómo leer este documento

Cada afirmación lleva una etiqueta:

- **[V]** — Verificado en fuente primaria (docs oficiales del proveedor) fetcheada durante esta investigación.
- **[S]** — Fuente secundaria (blogs, agregadores, comparativas). Direccionalmente fiable, números a re-verificar antes de comprometer arquitectura.
- **[I]** — Inferencia mía, no verificada.

### Lo que NO he podido verificar (léelo antes que nada)

1. **La documentación oficial de la API de Higgsfield.** `cloud.higgsfield.ai` devuelve solo un "Redirecting..." al fetchearla, y `platform.higgsfield.ai` (la base URL real que usa el SDK) no expone docs públicas indexables. Todo lo que documento de la API de Higgsfield viene del **SDK oficial de Node en GitHub** (primaria pero indirecta) y de **revendedores** (Pixazo, Segmind, WaveSpeed, MindCloud) que la envuelven. Los precios de Higgsfield API son de revendedor, no oficiales.
2. **Precios oficiales de Kling, MiniMax/Hailuo, Luma, Pika y Wan.** Solo he podido leer tablas de terceros. Los números de Hailuo/Luma/Pika/Wan vienen de una única fuente agregadora y expresan "$X por N segundos de vídeo", una unidad rara — trátalos como orden de magnitud, no como precio.
3. **Higgsfield /pricing** no renderiza contenido a WebFetch (SPA). Los tiers que cito son de terceros.
4. **fal.ai /pricing** solo expuso una muestra de modelos (los destacados), no el catálogo completo.
5. **Latencias reales.** Casi ningún proveedor publica p50/p95 de generación. No he encontrado benchmarks fiables de julio 2026. Todo lo que digo de latencia está marcado [I].
6. **Rate limits** por proveedor, salvo OpenAI (que sí publica tabla por tier). Higgsfield "~10 concurrentes en free" es de un blog de terceros [S].
7. **Existencia de Sora 3.** La página de modelos de OpenAI no menciona sucesor pese a que Sora 2 tiene fecha de apagado. No lo he podido confirmar ni desmentir.

---

## 1. Higgsfield como producto

### 1.1 Arquitectura de producto (modelos propios)

Higgsfield no es un modelo, es **una capa de producto sobre un mix de modelos propios y de terceros**. Los propios son tres [S — kolbo.ai, higgsfield.ai/blog]:

| Módulo | Función |
|---|---|
| **Soul** | Generación de imagen de alta fidelidad, foco en fotorrealismo y textura de piel |
| **Soul ID** | Consistencia de personaje. Se entrena con ~20+ fotos de una persona y fija su geometría facial a través de poses, ropa, iluminación y estilo [S] |
| **DoP** ("Director of Photography") | Image-to-video. **Modelo entrenado específicamente sobre movimiento de cámara**, no un modelo genérico con prompt engineering encima [S] |
| **Popcorn** | Originalmente edición de imagen / face replace; en 2026 se posiciona como **motor de storyboard**: genera 8–10 imágenes narrativas consistentes que luego se "hornean" en secuencias animadas [S] |

El diferenciador declarado de DoP es que el control de cámara es **first-class en el modelo**, no un adjetivo en el prompt. Esta es la tesis de producto central de Higgsfield y la razón por la que un clon no puede replicarlo solo llamando a Veo/Kling con prompts descriptivos [I — pero es la inferencia arquitectónicamente más importante del documento; ver §6].

### 1.2 Módulos de producto (2026)

Verificado en la página de features de Higgsfield [V — geo.higgsfield.ai]:

- **Cinema Studio 3.5** — producción narrativa. Incluye una función "AI Director" que **descompone un concepto creativo en shots individuales**, y luego aplica controles de cámara por shot (dollies, trucks, pans, tilts). Flujo: concepto → desglose de planos → controles por plano → colaboración.
- **Marketing Studio** — sobre Seedance 2.0. Feature **URL-to-video**: pegas la URL de un producto y genera creatividades publicitarias en varios formatos.
- **Soul ID** — identidad persistente de personaje.
- **Multi Reference** — anclas visuales múltiples fijadas antes de generar.
- **Reference Extension (Chrome)** — Soul ID desde el navegador.
- **Visual Effects Library** — presets de VFX (explosiones, transformaciones, transiciones estilizadas).
- **Mixed Media** — 30+ looks de estilo (ilustrado, texturizado).
- **Edit Image / Edit Video** — inpainting con brocha, también sobre vídeo.
- **Utilidades**: upscaling, background removal, color grading, image expansion.
- **Apps Library (80+ herramientas)**: Face Swap, Video Face Swap, Lipsync Studio, AI Headshot, Skin Enhancer, Product Placement, Outfit Swap, Commercial Faces, Angles 2.0.
- **Higgsfield Originals** — sección de streaming de series generadas.

**Lipsync Studio** es explícitamente un **multiplexor de modelos de terceros** bajo una sola UI: Speak v2, lipsync-2, InfiniteTalk, Kling AI Avatar, Kling Lipsync y Veo 3 [S — higgsfield.ai/blog]. Soporta 20+ idiomas y tres flujos: avatar hablante desde foto, avatar persistente para contenido a volumen, y doblaje de metraje real.

Igualmente, el pipeline "completo" que promociona el propio Higgsfield combina **Popcorn + Seedream + Seedance + Veo 3.1 + Sora 2 + Recast** [S]. Es decir: **Higgsfield es principalmente un orquestador/agregador con dos o tres modelos propios de alto valor (DoP, Soul ID) y el resto comprado.** Esto es la observación de producto más importante para un clon [I].

### 1.3 Taxonomía de controles cinematográficos

Nombres concretos de presets de DoP verificados [S — kolbo.ai]:

**Movimientos de cámara:** Dolly Zoom · 360 Orbit · Truck Left · Truck Right · Push to Glass · Head Tracking · Crane Up · Crane Down · Pan Left · Pan Right · Tilt Up · Tilt Down · Zoom In (este último confirmado además en el SDK, ver abajo).

**Óptica / grado:** Anamorphic Flares · Film Stock · Depth of Field Control.

La biblioteca declarada es de **100+ presets**. No he encontrado un listado público completo y enumerable — el SDK expone `getMotions()` precisamente porque el catálogo es dinámico y se identifica por UUID, no por nombre estable.

**Implicación de diseño [I]:** la taxonomía correcta no es un enum hardcodeado. Es una tabla `motions` con `{id, nombre, categoría, thumbnail/preview_video, strength_default, modelos_compatibles}`, servida desde tu backend. Higgsfield lo hace así.

### 1.4 API pública de Higgsfield

**Sí existe.** Se llama Higgsfield Cloud API / platform API.

**Verificado desde el SDK oficial** [V — github.com/higgsfield-ai/higgsfield-js]:

- **Base URL:** `https://platform.higgsfield.ai`
- **Auth:** header `Authorization: Key KEY_ID:KEY_SECRET`. El SDK v2 acepta `credentials: 'KEY_ID:KEY_SECRET'`, o `apiKey`/`apiSecret` separados, o env `HF_CREDENTIALS` / `HF_API_KEY` + `HF_API_SECRET`.
- **Endpoints de generación** (paths tipo "model id", estilo fal):
  - `/v1/text2image/soul` — Soul
  - `/v1/image2video/dop` — DoP
  - `/v1/speak/higgsfield` — speech-to-video / lipsync
  - `flux-pro/kontext/max/text-to-image` — **revenden modelos de terceros bajo su propia API**
- **Polling:** `/requests/{request_id}/status`. El SDK poletea cada **2 s** con timeout por defecto de **5 minutos**.
- **Estados:** `queued` → `in_progress` → `completed` | `failed` | `nsfw`. **Los créditos se reembolsan en `failed` y `nsfw`.**
- **Motions:** `client.getMotions()` devuelve el catálogo; se aplica con `inputMotion()` buscando por nombre (ej. `'Zoom In'`).
- **Enums:** tamaños tipo `SQUARE_1536x1536`, `PORTRAIT_1536x2048`; calidad `SoulQuality.HD`; batch `SINGLE` | `QUAD`; DoP model `TURBO`.
- **Errores tipados:** `AuthenticationError`, `NotEnoughCreditsError`, `BadInputError`, `ValidationError`, `APIError`.
- El **cliente v2 bloquea el uso desde navegador** por seguridad (server-side only). El v1 lo permitía y está deprecado.

Ejemplo del SDK (v2, recomendado):

```typescript
const jobSet = await higgsfield.subscribe('flux-pro/kontext/max/text-to-image', {
  input: { prompt: 'A beautiful sunset', aspect_ratio: '9:16' },
  withPolling: true
});

if (jobSet.isCompleted) {
  for (const job of jobSet.jobs) {
    console.log('Image URL:', job.results?.raw.url);
  }
}
```

Nótese el modelo de datos: **un `jobSet` contiene N `jobs`**. Un solo request puede producir varias salidas (batch_size QUAD). Esto es relevante para tu esquema de BD [I].

**Parámetros de image-to-video DoP** [S — Pixazo, revendedor]:

| Campo | Tipo | Notas |
|---|---|---|
| `model` | string | `dop-lite` \| `dop-turbo` \| `dop-preview` |
| `prompt` | string | |
| `seed` | int 1–1.000.000 | reproducibilidad |
| `motions_id` | UUID | **el preset de cámara se identifica por UUID** |
| `motions_strength` | float 0.0–1.0 | intensidad del movimiento |
| `input_images` | string[] | URLs públicamente accesibles |
| `input_images_end` | string[] | **first/last frame interpolation** |
| `enhance_prompt` | bool | reescritura automática del prompt |
| `check_nsfw` | bool | |

Estados en el wrapper: `QUEUED → PROCESSING → COMPLETED | FAILED | ERROR`, polling en `GET /v2/requests/status/{request_id}`, con webhook opcional [S].

**Precios (revendedor Pixazo, por vídeo de 5 s)** [S — no oficiales]:

| Modelo | $/5 s | ≈ $/s |
|---|---|---|
| dop-lite | $0.135 | $0.027 |
| dop-preview | $0.573 | $0.115 |
| dop-turbo | $0.416 | $0.083 |

Otra fuente cita "$0.1 por segundo de vídeo generado" como tarifa directa de Higgsfield API [S]. Y Segmind cotiza Soul text-to-image $0.120–0.230/gen, image-to-video $0.160–0.700/gen, speech-to-video $0.863–4.22/gen [S].

**Planes web** [S, no verificados en la fuente]: Free $0, Basic $9, Pro $29, Ultimate $49, Creator $149, más Enterprise.

**Conclusión sobre la API de Higgsfield [I]:** existe y es usable, pero (a) la doc pública es pobre, (b) la mayor parte del tráfico de integración pasa por revendedores, y (c) su API es **el único camino legítimo a los presets de DoP y a Soul ID**. Si tu producto depende de esa taxonomía cinematográfica exacta, Higgsfield API es proveedor, no competidor.

---

## 2. APIs de generación de VÍDEO

### 2.1 Tabla comparativa

Precios en USD por segundo salvo indicación. **Todas las cifras de esta tabla salvo Veo, Sora y Runway son [S].**

| Modelo | Proveedor | $/s | Dur. máx | Resolución | I2V | First/Last frame | Ref. personaje | Audio nativo |
|---|---|---|---|---|---|---|---|---|
| Veo 3.1 Standard | Google | **$0.40** (720p/1080p), $0.60 (4K) | ~8 s/gen, extensible | hasta 4K | Sí | Sí (last-frame control) | Ref. images | Sí, incluido |
| Veo 3.1 Fast | Google | **$0.10** (720p) – $0.30 (4K) | ídem | hasta 4K | Sí | Sí | Sí | Sí |
| Veo 3.1 Lite | Google | **$0.05** (720p) – $0.08 (1080p) | ídem | 1080p | Sí | Sí | Sí | Sí |
| Gemini Omni Flash | Google | ~**$0.10**/s @720p ($17.50/1M tok) | — | 720p | Sí | — | **Sí, es su punto fuerte** | Sí |
| Sora 2 | OpenAI | **$0.10** (720p) | 4 / 8 / 12 s | 720×1280, 1280×720 | Sí | — | `input_reference` | Sí |
| Sora 2 Pro | OpenAI | **$0.30** (720p), $0.50 (1024p), $0.70 (1080p) | 10 / 15 / 25 s | hasta 1080p | Sí | — | Sí | Sí |
| Kling 3.0 / O3 | Kuaishou | desde **$0.075** | **15 s** | 720p / 1080p | Sí | **Sí, start+end frame** | **Multi-image ref + multi-character coreference** | Sí (9–12 cr/s) |
| Kling 2.5 Turbo Pro | vía fal | **$0.07** | 10 s | 1080p | Sí | Sí | Sí | — |
| Gen-4 Turbo | Runway | 5 cr/s = **$0.05** | 10 s | 720p | Sí | — | Sí | — |
| Gen-4.5 | Runway | 12 cr/s = **$0.12** | 10 s | — | Sí | — | Sí | — |
| Seedance 2 (vía Runway) | ByteDance | 36–150 cr/s = **$0.36–1.50** | — | según res. | Sí | — | Sí | — |
| Hailuo 2.3 | MiniMax | ~$0.19–0.56 / vídeo | 6–10 s | 1080p | Sí | — | Sí (S2V) | — |
| Wan 2.5 | Alibaba | **$0.05** (480p) | — | 480p+ | Sí | Sí | — | Sí |
| Wan 2.2 A14B | Alibaba | **$0.10** | — | 720p | Sí | Sí | — | — |
| Wan 2.7 | Alibaba | ~$0.10 (de $6/60 s) | — | — | Sí | **Sí + 9-grid image input, prompts 5000 chars** | Sí | — |
| Luma Ray 3 | Luma | ~$0.21 (de $12.60/60 s) | — | 4K HDR | Sí | Sí (keyframes) | — | — |
| Pika 2.2 | Pika | ~$0.05 (de $3/60 s) | — | 1080p | Sí | Sí | — | — |
| DoP turbo | Higgsfield | ~$0.083 | 5 s típico | — | Sí | **Sí (`input_images_end`)** | Soul ID | — |

### 2.2 Deprecaciones críticas (esto condiciona arquitectura)

- **Veo 3.0** (`veo-3.0-generate-001`, `veo-3.0-fast-generate-001`) — **ya apagado, 30 de junio de 2026** [S]. Migrar a Veo 3.1.
- **Sora 2 y la Videos API de OpenAI — apagado anunciado para el 24 de septiembre de 2026** [S]. El snapshot `sora-2-2025-12-08` ya está deprecado [V — developers.openai.com]. Es decir: **si construyes sobre Sora 2 hoy, tienes ~2 meses de vida útil.** No he podido confirmar cuál es el sucesor.
- **Runway Gen-3 Alpha Turbo y Gen-4 Aleph — sunset el 30 de julio de 2026**, es decir **en 10 días** [S]. Ruta: Gen-3 Turbo → Gen-4.5 o Gen-4 Turbo; Aleph → Aleph 2.0.

Tres de los cuatro proveedores tier-1 tienen un apagado dentro de los próximos 60 días. **La rotación de modelos es el riesgo operativo dominante de este dominio, no el precio.** [I, pero fuertemente respaldado]

### 2.3 Modelo de job por proveedor

**Ninguno de los proveedores serios de vídeo es síncrono.** Todos son async. Las variantes:

| Proveedor | Patrón | Detalle |
|---|---|---|
| **Google / Gemini** | Long-running operation + polling | `generate_videos()` devuelve una operación; se poletea hasta `done`. Ficheros con retención limitada [S] |
| **OpenAI** | Job + poll + download | crear job → poll → descargar. Endpoint `v1/videos` [V] |
| **Runway** | Task + polling | `POST` a `api.dev.runwayml.com`, luego `GET /v1/tasks/{taskId}`. **No poletear más de 1 vez cada 5 s** o contribuyes al throttling [V — docs.dev.runwayml.com] |
| **fal.ai** | Cola + polling **o** webhook | ver §4 |
| **Replicate** | Predicción sync o async + webhook o polling | webhook recibe POST en created/updated/finished [V — replicate docs] |
| **Higgsfield** | jobSet + polling (2 s) o webhook | timeout SDK 5 min [V] |

### 2.4 Latencias

**No verificado.** Ningún proveedor publica SLOs de latencia de generación. Lo que sí es verificable y sirve de proxy: el SDK de Higgsfield tiene un **timeout por defecto de 5 minutos** [V], y Runway pide no poletear más rápido que cada 5 s [V]. Shotstack, para renderizado (no generación), declara ~20 s por minuto de vídeo [S].

**Inferencia [I]:** el rango operativo para un clip de 5–10 s está entre **30 s y 3 minutos** según modelo y carga de cola; los tiers "fast/turbo/lite" existen precisamente para comprar latencia. Un producto tipo Higgsfield con 6 shots por vídeo tiene un tiempo de pared de varios minutos incluso paralelizando, lo que **obliga a un modelo de UX asíncrono con notificación, no un spinner.**

---

## 3. APIs de IMAGEN

| Modelo | Proveedor | Precio | Ref. personaje / consistencia | Edición / inpainting |
|---|---|---|---|---|
| **FLUX.2 [pro]** | Black Forest Labs | ~$0.03/MP salida; ~$0.03/MP entrada de refs | **Hasta 8 imágenes de referencia vía API (9 MP total de entrada); 10 en Playground** | Sí (edit) |
| **FLUX.2 [max]** | BFL | $0.03/MP entrada; $0.07 primer MP salida + $0.03/MP adicional | ídem | Sí |
| **FLUX.2 [dev]** | BFL (open weights) | self-host / $ por proveedor | 32B params, **hasta 10 refs simultáneas sin entrenamiento adicional** | Sí |
| **FLUX Kontext Pro** | BFL vía fal | $0.04/imagen | Sí | Sí, es su especialidad |
| **Nano Banana 2** (Gemini 3.1 Flash Image) | Google | ~$0.045 (0.5K), ~$0.067 (1K), ~$0.151 (4K) | Sí | Sí, edición conversacional |
| **Nano Banana Pro** (Gemini 3 Pro Image) | Google | ~$0.134 (1K/2K), ~$0.24 (4K) | Sí | Sí |
| **Imagen 4** | Google | Fast $0.02 / Std $0.04 / Ultra $0.06 | Limitada | — |
| **Seedream 4.0** | ByteDance | ~$0.03–0.035/imagen | **Multi-reference** | Sí |
| **Seedream 4.5** | ByteDance | ~$0.045/imagen | Multi-reference | Sí |
| **Ideogram 4.0** | Ideogram | Turbo $0.03 / Default $0.06 / Quality $0.10 | **Character Reference: +$0.05–0.11/imagen** (o $0.10–0.20 en 3.0) | Sí |
| **Qwen Image** | Alibaba vía fal | $0.02/megapixel | — | Sí |
| **Midjourney** | Midjourney | $10/$30/$60/$120 mes | Best-in-class estética | Sí en la web |

**Midjourney: no tiene API oficial pública** [S]. Las API keys están restringidas al dashboard Enterprise y hay que solicitar acceso de developer. Todo lo que se vende como "Midjourney API" (ApiFrame, ImaginePro, etc.) son **wrappers no oficiales sobre Discord/web**, con el riesgo de TOS y de rotura que eso implica. **Descartar Midjourney para un producto en producción** [I].

**Notas de consistencia:**
- FLUX.2 permite **combinar pose y personaje de imágenes distintas en una sola llamada** — referencia el personaje de una imagen y la pose de otra [S — Together AI, fal]. Es el equivalente más cercano y directo a Soul ID sin entrenar nada.
- Ideogram cobra la referencia de personaje como **add-on por imagen**, lo que hace su coste marginal impredecible respecto a FLUX.
- **Gemini Omni Flash** se posiciona explícitamente como mejor que Veo 3.1 en "coherencia, consistencia de personaje y refinamiento iterativo" [V — ai.google.dev]. Es el candidato más fuerte hoy para el eje "personaje consistente" en vídeo.

---

## 4. Patrones de integración

### 4.1 fal.ai — la referencia de unificación

fal es el mejor caso de estudio de cómo unificar proveedores heterogéneos, porque **impone una única forma de cola sobre modelos de origen dispar**. Verificado en su doc [V — fal.ai/docs/model-apis/model-endpoints/queue]:

**Endpoints (idénticos para todos los modelos, solo cambia `{model-id}`):**

```
POST https://queue.fal.run/{model-id}
GET  https://queue.fal.run/{model-id}/requests/{request_id}/status?logs=1
GET  https://queue.fal.run/{model-id}/requests/{request_id}/status/stream?logs=1
GET  https://queue.fal.run/{model-id}/requests/{request_id}
PUT  https://queue.fal.run/{model-id}/requests/{request_id}/cancel
```

**Submit:**

```bash
curl -X POST https://queue.fal.run/fal-ai/flux/schnell \
  -H "Authorization: Key $FAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a sunset over mountains"}'
```

**Respuesta:**

```json
{
  "request_id": "764cabcf-b745-4b3e-ae38-1200304cf45b",
  "response_url": "https://queue.fal.run/fal-ai/flux/schnell/requests/764cabcf.../response",
  "status_url": "https://queue.fal.run/fal-ai/flux/schnell/requests/764cabcf.../status",
  "cancel_url": "https://queue.fal.run/fal-ai/flux/schnell/requests/764cabcf.../cancel",
  "queue_position": 0
}
```

Fíjate en el detalle de diseño: **la respuesta devuelve las URLs completas de status/response/cancel**, no solo el ID. El cliente no construye URLs. Esto es lo que hace que el cliente sea agnóstico al modelo.

**Estados:** `IN_QUEUE` → `IN_PROGRESS` → `COMPLETED`.

**Webhook** (query param, no body):

```bash
curl -X POST "https://queue.fal.run/fal-ai/flux/schnell?fal_webhook=https://your-server.com/webhook" \
  -H "Authorization: Key $FAL_KEY" \
  -d '{"prompt": "a sunset over mountains"}'
```

**Payload del webhook:**

```json
{
  "request_id": "abc123",
  "status": "OK",
  "payload": {
    "images": [{"url": "https://fal.media/files/...", "width": 1024, "height": 1024}]
  }
}
```

**Fiabilidad de webhooks:** timeout de **15 s** en la entrega inicial, **10 reintentos a lo largo de 2 horas**. La doc obliga explícitamente a que **tu handler sea idempotente** y tolere entregas repetidas del mismo `request_id` [V].

**Headers de control operativo** [V] — esto es lo que un agregador serio expone y casi nadie más:

| Header | Uso |
|---|---|
| `X-Fal-Request-Timeout` | deadline server-side en segundos |
| `X-Fal-No-Retry: 1` | desactiva reintentos automáticos |
| `X-Fal-Queue-Priority` | `low` \| `normal` |
| `X-Fal-Runner-Hint` | afinidad al mismo runner (útil para cachear modelo/LoRA cargado) |

**Cancelación:** `202 {"status":"CANCELLATION_REQUESTED"}` / `400 {"status":"ALREADY_COMPLETED"}` / `404 {"status":"NOT_FOUND"}`.

**Cómo unifica fal proveedores heterogéneos [I, inferido del diseño observado]:**
1. Un único plano de cola y un único esquema de estados, con el model-id como puro path segment.
2. Devolver URLs absolutas en lugar de IDs, para que el cliente no conozca la topología del proveedor.
3. Normalizar la salida a `{images:[{url,width,height}]}` / `{video:{url}}`.
4. Alojar los artefactos ellos mismos (`fal.media`), no pasar URLs del proveedor upstream — así la vida útil del artefacto es suya, no del upstream.
5. Un único esquema de auth (`Authorization: Key`).

**Higgsfield copia este patrón casi literalmente**: model-id como path (`flux-pro/kontext/max/text-to-image`), `Authorization: Key`, `subscribe(modelId, {input, withPolling})`, `/requests/{id}/status`. Es el patrón de facto del sector [I].

### 4.2 Replicate

Post-adquisición por **Cloudflare (diciembre 2025)** [S]. Dos modos: sync y async. Async devuelve un `prediction id`. Webhooks reciben POST en `created`, `updated` y `finished` [V].

**Dos modelos de facturación** [V]:
- **Hardware-per-second**: se cobra el uptime de GPU/CPU. Aplica a modelos de la comunidad y deployments propios.
- **Output-based**: se cobra por token, imagen o segundo de vídeo. Aplica a los **Official Models** (100+, incluye Veo y Kling).

Esto importa: en modelos comunitarios pagas el arranque en frío y la latencia; en oficiales no. **Para producción, usa solo Official Models o asume el riesgo de cold start en la factura** [I].

### 4.3 Rate limits

Solo OpenAI publica tabla clara [V — developers.openai.com]:

| Tier | Requests/min (Sora 2) |
|---|---|
| Tier 1 | 25 |
| Tier 2 | 50 |
| Tier 3 | 125 |
| Tier 4 | 200 |
| Tier 5 | 375 |

Runway no publica números pero **documenta el comportamiento**: no poletear por debajo de 5 s de intervalo, o contribuyes al throttling [V]. Higgsfield: ~10 generaciones concurrentes en free tier [S, sin verificar].

**Ausencia notable:** para el resto (Kling, MiniMax, Luma, Wan) no he encontrado rate limits publicados.

### 4.4 Patrón de reintentos recomendado

Consolidando lo verificado:

- **Backoff exponencial en 429** — recomendado explícitamente en la doc de Higgsfield [S].
- **Idempotencia obligatoria en el handler de webhook** — requisito de fal, con 10 reintentos en 2 h [V].
- **Distinguir fallos reembolsables de fallos facturables.** Higgsfield reembolsa créditos en `failed` y `nsfw` [V]. No todos los proveedores lo hacen. Tu contabilidad interna de créditos debe modelar esto o perderás dinero silenciosamente [I].
- **Poll no más rápido de 5 s** (Runway [V]); 2 s es el default de Higgsfield [V]. Un intervalo de 3–5 s con jitter es seguro transversalmente [I].
- **Timeout duro** — 5 min es el default del SDK de Higgsfield [V], razonable como techo por clip.

---

## 5. Ensamblado final

| Opción | Modelo | Coste | Trade-off |
|---|---|---|---|
| **ffmpeg** | Binario CLI, self-host | Gratis (pagas infra) | Máximo control y cero coste de licencia. Pero tú gestionas concurrencia, colas, workers, almacenamiento y fallos. Sin capa de composición declarativa: todo es filtergraphs. Sigue siendo el motor bajo casi todo lo demás [S] |
| **Remotion** | Componentes React → frames | Individuos gratis; **empresas desde $25/asiento/mes (Creator) o $0.01/render con mínimo $100/mes (Automators)** | Control por frame, animación real, tipografía y layout con CSS. **Pero: te da solo el motor de render, no el pipeline.** Tú eliges y configuras el cloud rendering, la concurrencia y el control de coste. Y **si tu stack no es React, adoptar Remotion es adoptar React** [S] |
| **Shotstack** | JSON declarativo + editor UI | Por minuto renderizado | El más completo: API + editor SDK + generación AI + Probe API. **Pero rinde ~20 s por minuto de vídeo** y, crítico, **necesitas conocer de antemano la duración de cada clip** — o sacas las duraciones con ffmpeg/Probe API antes de construir el JSON [S] |
| **Creatomate** | Plantillas + REST API | Hasta ~40% más barato que Shotstack a escala [S] | La mayoría de vídeos renderizan **en menos de 15 s**. Buen equilibrio para plantillas con datos variables. Menos flexible que Remotion para composiciones arbitrarias [S] |

**Lectura para un producto tipo Higgsfield [I]:** el ensamblado aquí es *concatenación de clips generados + audio + quizá texto*, no motion graphics complejos. Esto cae en el punto dulce de ffmpeg puro: concat demuxer, crossfades con `xfade`, mezcla de audio con `amix`. Remotion se justifica solo si vas a añadir capas gráficas animadas (titulares, lower-thirds, UI de marca). Shotstack/Creatomate se justifican si quieres saltarte por completo la operación de infra de render — pero heredas su latencia y su gotcha de duraciones precalculadas.

Nota práctica sobre el gotcha de Shotstack: en este dominio **tú ya conoces la duración de cada clip**, porque tú pediste "5 s" al generador. Ese problema te afecta menos que a un caso genérico [I].

---

## 6. Lo que más condiciona la arquitectura

1. **El vídeo generativo es async, sin excepción.** Ningún proveedor tier-1 es síncrono. Todo el producto —BD, API, UX— se organiza alrededor de jobs de larga duración.
2. **La rotación de modelos es brutal y es el riesgo #1.** Veo 3.0 apagado (30 jun 2026), Runway Gen-3/Aleph apagados en 10 días (30 jul 2026), Sora 2 y toda la Videos API de OpenAI apagados el 24 sep 2026. Cualquier acoplamiento directo a un modelo concreto es deuda con fecha de caducidad conocida.
3. **La taxonomía cinematográfica es datos, no código.** Higgsfield identifica presets por **UUID** y los sirve vía `getMotions()`, no por enum. Su ventaja competitiva (DoP entrenado sobre movimiento de cámara) no se replica con prompts.
4. **Precios con 30× de rango**: Veo 3.1 Lite $0.05/s vs Seedance 2 hasta $1.50/s. La elección de modelo *es* la decisión de unit economics.
5. **Higgsfield mismo es un agregador**, con solo 2–3 modelos propios de valor. Compra Seedream, Seedance, Veo 3.1, Sora 2, Kling. Confirma que agregar es la arquitectura correcta, no un atajo.
6. **Idempotencia y contabilidad de créditos**: fal reintenta webhooks 10 veces en 2 h; Higgsfield reembolsa en `failed`/`nsfw`. Ambos son requisitos de corrección, no optimizaciones.

---

## Fuentes

**Primarias (fetcheadas):**
- [Higgsfield JS SDK — GitHub](https://github.com/higgsfield-ai/higgsfield-js)
- [fal — Asynchronous Inference / Queue](https://fal.ai/docs/model-apis/model-endpoints/queue)
- [fal — Webhooks](https://docs.fal.ai/model-apis/model-endpoints/webhooks)
- [fal — Pricing](https://fal.ai/pricing)
- [Gemini API — Video generation](https://ai.google.dev/gemini-api/docs/video)
- [Gemini API — Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [OpenAI — Sora 2 model](https://developers.openai.com/api/docs/models/sora-2)
- [Runway — API Pricing & Costs](https://docs.dev.runwayml.com/guides/pricing/)
- [Replicate — Predictions / Webhooks / HTTP API](https://replicate.com/docs/topics/predictions)
- [Higgsfield — Features 2026](https://geo.higgsfield.ai/higgsfield-ai-features-full-guide-2026)
- [Higgsfield Cloud API](https://cloud.higgsfield.ai/) *(solo redirect, sin contenido)*

**Secundarias:**
- [Kolbo.AI — Higgsfield Suite: 100+ Camera Presets](https://kolbo.ai/blog/higgsfield-suite-100-camera-presets)
- [Higgsfield — Soul ID / Character Consistency](https://higgsfield.ai/blog/Soul-ID-AI-Character-Consistency)
- [Higgsfield — Lipsync Studio](https://higgsfield.ai/blog/Lipsync-Studio-Turn-Any-Script-Into-Performance)
- [Higgsfield — Popcorn / face replace](https://higgsfield.ai/blog/AI-Tool-That-Allows-You-to-Replace-Faces-in-a-Movie-Scene)
- [Pixazo — Higgsfield API](https://www.pixazo.ai/models/higgsfield)
- [Apidog — How to Use Higgsfield API](https://apidog.com/blog/higgsfield-api/)
- [WaveSpeedAI — Higgsfield DoP I2V](https://wavespeed.ai/docs/docs-api/higgsfield/higgsfield-dop-image-to-video)
- [Segmind — Higgsfield Image2Video API](https://www.segmind.com/models/higgsfield-image2video/api)
- [BuildMVPFast — AI Video API Costs, July 2026](https://www.buildmvpfast.com/api-costs/ai-video)
- [Kling — Dev Pricing](https://kling.ai/dev/pricing)
- [KlingAI Open Platform docs](https://app.klingai.com/global/dev/document-api/quickStart/productIntroduction/overview)
- [invideo — Kling 3.0 guide](https://invideo.io/blog/kling-3-0-complete-guide/)
- [BFL — FLUX Pricing](https://bfl.ai/pricing)
- [BFL — FLUX.2 Overview](https://docs.bfl.ai/flux_2/flux2_overview)
- [Together AI — FLUX.2 multi-reference](https://www.together.ai/blog/flux-2-multi-reference-image-generation-now-available-on-together-ai)
- [fal — Flux 2 Developer Guide](https://fal.ai/learn/devs/flux-2-developer-guide)
- [Ideogram — API docs](https://developer.ideogram.ai/ideogram-api/api-overview) · [API pricing](https://about.ideogram.ai/api-pricing)
- [ApiFrame — Best Midjourney APIs 2026](https://apiframe.ai/blog/best-midjourney-apis)
- [MiniMax pricing](https://felloai.com/minimax-pricing/) · [PiAPI Hailuo](https://piapi.ai/hailuo)
- [Shotstack — Remotion alternatives](https://shotstack.io/vs/remotion-alternatives/)
- [Creatomate — Best Video Generation APIs](https://creatomate.com/blog/the-best-video-generation-apis)
- [Rendi — Best Video Generation APIs](https://www.rendi.dev/blog/best-video-generation-apis)
- [Replicate pricing 2026](https://checkthat.ai/brands/replicate/pricing)
