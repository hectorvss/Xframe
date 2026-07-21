# Xframe · backend

Agente de cinematografía generativa. FastAPI + LangGraph sobre Postgres, con workers
asíncronos para la generación y ffmpeg para el montaje final.

El diseño y el porqué de cada decisión están en `docs/ARQUITECTURA-AGENTE.md`. Este
fichero es solo cómo se levanta y cómo se comprueba.

## Requisitos

- Python 3.12
- Postgres 16 y Redis 7 (los trae el compose)
- ffmpeg y ffprobe en el PATH, o `FFMPEG_PATH` apuntando al binario

## Arranque

```bash
cp .env.example .env      # y rellenar ANTHROPIC_API_KEY como mínimo
docker compose up --build
```

Levanta `api` (puerto 8000), dos `worker`, `postgres` y `redis`. La imagen ya trae
ffmpeg instalado.

Sin Docker:

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload      # api
python -m app.jobs.worker          # worker, en otra terminal
```

## Base de datos

El esquema base (`profiles`, `projects`, `assets`, `canvas_nodes`, …) está en
`supabase/schema.sql`. Encima va el esquema del agente:

```bash
# contra el Postgres del compose
psql postgresql://xframe:xframe@localhost:5432/xframe -f ../supabase/schema.sql
for file in ../supabase/[0-9][0-9][0-9]_*.sql; do
  psql postgresql://xframe:xframe@localhost:5432/xframe -v ON_ERROR_STOP=1 -f "$file"
done

# contra Supabase
# aplica cada fichero numerado pendiente, en orden, contra "$DATABASE_URL"
python scripts/apply_migration.py ../supabase/022_manifest_execution_snapshot.sql
```

### API y MCP

El backend publica un servidor MCP remoto en `PUBLIC_BASE_URL/mcp`. Usa
Streamable HTTP y una cabecera `Authorization: Bearer xfr_...`; las credenciales
se crean, limitan por scopes y revocan desde `Ajustes > Servidor MCP`. No se
aceptan identificadores de usuario desde el cliente y una clave restringida a
proyectos concretos no puede escapar de esa lista.

La migración `007_mcp_api.sql` es obligatoria antes de crear credenciales MCP.
Las Edge Functions complementarias se despliegan así:

```bash
supabase functions deploy resolve-asset
supabase functions deploy extract-url
```

Los ficheros numerados 002–022 son migraciones incrementales. En una instalación
nueva se aplica primero `schema.sql`; en una ya existente se aplican solo las migraciones
pendientes y en orden (incluidos ambos ficheros `010_*`). No se vuelve a ejecutar el
esquema base para actualizar producción ni se reaplica a ciegas una migración ya registrada.

### Seeds de taxonomía

Las tablas `gen_models`, `camera_motions` y `visual_styles` son **datos, no código**:
de ellas salen los `Literal[...]` que ven las herramientas del agente en tiempo de
ejecución. Un backend con esas tablas vacías arranca, pero el agente no puede generar
nada porque no conoce ningún modelo.

```bash
psql "$DATABASE_URL" -f seeds/taxonomy.sql
```

`seeds/taxonomy.sql` está **generado**; no se edita a mano. La fuente de verdad es
`app/providers/seed.py`, y se regenera con:

```bash
python -m app.providers.seed --emit-sql > seeds/taxonomy.sql
```

Apagar un modelo retirado es un `UPDATE`, no un despliegue:

```sql
update gen_models set status = 'retired' where id = 'runway-gen4';
```

## Variables de entorno

Todas están en `.env.example`, comentadas. Las imprescindibles para arrancar:

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Postgres. El compose la inyecta. |
| `REDIS_URL` | Cola de jobs. El compose la inyecta. |
| `ANTHROPIC_API_KEY` | El agente. Sin esto no hay nada. |
| `SUPABASE_SERVICE_KEY` | Storage de assets. Salta RLS: nunca sale del servidor. |
| `PUBLIC_BASE_URL` | Webhooks de proveedor. Debe ser alcanzable desde internet; en local, un túnel. Si apunta a localhost, los jobs solo terminan por polling. |
| `*_API_KEY` de proveedor | Solo los de los modelos marcados `active` en `gen_models`. |

## Tests

```bash
pytest -m "not evals and not integration"   # suite unitaria: rápida, sin red, sin coste
pytest -m ffmpeg                            # las que necesitan el binario instalado
```

Las llamadas HTTP a proveedores se simulan con `respx`; ningún test unitario debe salir
a la red ni gastar un crédito.

## Tests de integración

Viven en `tests/integration/` y existen por una razón concreta: el 20/07/2026 el backend
tenía 124 tests unitarios en verde y **no arrancaba**. Cada módulo se había probado aislado
contra dobles, y un doble implementa siempre la firma que su autor imagina, no la que el
módulo de destino tiene escrita. Esta suite ejecuta las dos mitades de cada contrato a la
vez.

| Fichero | Qué cubre | Necesita infraestructura |
|---|---|---|
| `test_contracts.py` | Por introspección: cada símbolo importado de `app.*` existe y su firma acepta los argumentos con los que se le llama. Más una lista explícita de las juntas críticas. | **No.** Corre en la suite rápida. |
| `test_turn_e2e.py` | Un turno entero: mensaje → ROOT → tool call → fan-out → tool → cola → worker → asset → evento → SSE. | Sí |
| `test_money_e2e.py` | Doble cobro bajo concurrencia, reembolso, y la `unique` de idempotencia ante una carrera real. | Sí |

`test_contracts.py` no lleva marca y **debe correr siempre**: es el más barato de todos y
el que impide que vuelva a haber seis vocabularios para los mismos contratos.

### Cómo correrla

```bash
pip install -e ".[dev]"
pytest -m integration
```

Hace falta un Postgres. Se elige en este orden, y si no hay ninguno los tests se **saltan**
con un mensaje que dice qué falta — nunca degradan a un fake:

```bash
# 1. Una base que ya tengas levantada (es lo que usa CI y lo más rápido en local)
docker compose up -d postgres
TEST_DATABASE_URL=postgresql://xframe:xframe@localhost:5432/xframe pytest -m integration

# 2. Sin nada levantado: testcontainers arranca un postgres:16-alpine desechable.
#    Requiere un Docker en marcha.
pytest -m integration
```

El esquema se aplica desde `supabase/schema.sql` y las migraciones de producción hasta
`022_manifest_execution_snapshot.sql` sobre una base limpia, no desde un DDL paralelo: un
esquema de test mantenido a mano diverge del real y la divergencia se descubre en
producción. `conftest.py` añade un prólogo que finge lo que pone
la plataforma Supabase (los esquemas `auth` y `storage`, los roles `anon`/`authenticated`)
y que no existe en un Postgres desnudo.

Notas:

- **Ni claves de API ni gasto.** El LLM y los adaptadores de proveedor son los dos únicos
  dobles. Todo lo demás —grafo, estado, reductores, checkpointer, taxonomía, contexto,
  tools, cola, worker, bus— es el código de producción.
- **Redis se sustituye por `fakeredis`**, que implementa Streams y por tanto el contrato
  completo del bus. Postgres no se sustituye por nada: `FOR UPDATE SKIP LOCKED`, el cerrojo
  de fila sobre el perfil y la restricción `unique` de idempotencia **son** el mecanismo de
  correctitud del dinero, y contra un doble en memoria no se prueba ninguno de los tres.
- La base se trunca al principio de cada test, no al final: si uno se cae, queda tal cual
  para poder inspeccionarla.

## Evals

Framework en `evals/`, con el patrón de PostHog: pytest como runner, descubrimiento por
`eval_*.py` para que **no corran con la suite unitaria**, scorers graduados (0.0 / 0.5 /
1.0, nunca binarios) y `score=None` para "no aplica" — que no es lo mismo que 0.0 y no
entra en la media.

```bash
pytest evals -m evals                        # todo lo que no renderiza
pytest evals -m evals --eval thriller        # solo los casos que contengan "thriller"
pytest evals/eval_script.py -m evals         # una suite

EVAL_ALLOW_RENDER=1 pytest evals/eval_continuity.py -m evals   # gasta créditos de verdad
```

| Suite | Qué mide | Coste |
|---|---|---|
| `eval_script.py` | El guion responde al brief | llamadas al juez |
| `eval_shotlist.py` | Los planos cubren el guion; herramienta y parámetros correctos | juez + determinista |
| `eval_continuity.py` | Continuidad de personaje, estilo, validez de render y coste | **renderiza y paga** |

`eval_continuity.py` exige `EVAL_ALLOW_RENDER=1` a propósito: nadie debe descubrir que
ha gastado créditos porque corrió `pytest` sin argumentos.

Los scorers visuales (`CharacterContinuity`, `StyleAdherence`) **aceleran el vídeo 8x
antes de muestrear frames**, porque los modelos visuales muestrean a ~1 fps: sin
acelerar, el juez vería ocho instantes casi idénticos de un plano de ocho segundos y no
podría opinar sobre continuidad.

Los datasets están hardcodeados y tipados en `evals/datasets.py`. Cada bug de producción
debería acabar allí como un `EvalCase` permanente con su `regression_note`. Revisar
trazas y curar el dataset es lo que hace útil un eval; escribirlo una vez, no.

## Montaje final

`app/assembly/` produce el asset de tipo `cut` a partir del timeline en orden narrativo.

Lo que hay que saber para depurarlo: **los clips llegan heterogéneos** —720p, 1080p, 4K,
24/25/30 fps, con y sin audio— y ahí es donde falla el montaje. Por eso `probe.py` sondea
cada clip con ffprobe antes de tocar nada (nunca se asume lo que dijo el proveedor que
iba a generar) y `ffmpeg.py` normaliza todo a un formato de destino explícito: la
resolución menor del lote (nunca escalar hacia arriba) y el frame rate más frecuente
(menos clips remuestreados). La decisión se guarda en el artefacto, en `format.rationale`.

Si un montaje falla, el error trae el comando completo de ffmpeg y la cola de su stderr:
se reproduce a mano copiándolo y pegándolo.

## Estructura

```
app/
├── main.py          FastAPI: /chat (SSE), /jobs/webhook, /projects
├── config.py        Settings por entorno
├── db.py            Pool de asyncpg. Sin ORM: el esquema ya está en SQL con RLS.
├── agent/           Grafo, estado, nodos, modos, compactación, prompts
├── tools/           Herramientas del agente y su jerarquía de errores
├── taxonomy/        gen_models, camera_motions, styles → Literal en runtime
├── context/         Contexto de UI del proyecto
├── memory/          Biblia de estilo y fichas de personaje
├── artifacts/       Guion, timeline y cut por referencia
├── providers/       Un adaptador por proveedor de generación
├── jobs/            Cola, worker, polling, webhooks, créditos
└── assembly/        ffprobe + ffmpeg → el cut
evals/               Scorers, datasets y suites
```
