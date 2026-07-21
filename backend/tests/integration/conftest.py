"""
Infraestructura de la suite de integración: Postgres de verdad, Redis de mentira.

El porqué de cada decisión, que es lo que hay que entender antes de tocar esto:

**Postgres real y no un fake.** La auditoría del 20/07/2026 señaló que el módulo de jobs
se validó entero contra un doble en memoria. Un fake no tiene `FOR UPDATE SKIP LOCKED`,
no tiene niveles de aislamiento, no tiene restricciones `unique` y no tiene el cerrojo de
fila que serializa a dos peticiones que van a gastar del mismo saldo. Esas cuatro cosas
**son** el mecanismo de correctitud del dinero en este backend: probarlas contra un dict
de Python es probar el dict. Por eso aquí se levanta un Postgres o la suite se salta,
pero nunca se sustituye por algo que dé verde sin comprobar nada.

**Redis falso y sí sustituible.** El bus transporta *progreso*, no *estado*: la verdad de
un job vive en Postgres. `fakeredis` implementa Streams (`XADD`/`XREAD`/`XREVRANGE`), que
es todo lo que `EventBus` usa, así que el doble es fiel al contrato completo.

**Esquema aplicado desde `supabase/*.sql`, no desde un DDL de test.** Un esquema paralelo
mantenido a mano diverge del real, y la divergencia se descubre en producción. El precio
es un prólogo de compatibilidad (`_SUPABASE_COMPAT`) que finge las piezas que pone la
plataforma —`auth`, `storage`, los roles— y que no existen en un Postgres desnudo.

Cómo se elige la base de datos, en este orden:

1. `TEST_DATABASE_URL` en el entorno. Es lo que usa CI y lo que permite correr la suite
   contra el `postgres` del `docker-compose` local.
2. `testcontainers`, si está instalado y hay un Docker vivo.
3. Si no hay ninguna de las dos, `pytest.skip`. Nunca un fallback silencioso.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SUPABASE_DIR = BACKEND_ROOT.parent / "supabase"

# `schema.sql` already contains the browser-facing migrations through team chat.
# The agent schema and every production-studio migration must still be applied here:
# otherwise integration tests can pass against a database that cannot open Guion/Audio.
SCHEMA_FILES = (
    "schema.sql",
    "002_agent.sql",
    "004_conversation_resume.sql",
    "007_mcp_api.sql",
    "008_production_studio.sql",
    "009_audio_lipsync_models.sql",
    "010_oauth_mcp_grants.sql",
    "010_script_asset_links_sound_templates.sql",
    "011_project_types.sql",
    "012_audio_library_assets.sql",
    "013_resource_bindings.sql",
    "014_production_manifests_quality.sql",
    "015_persistent_visual_references.sql",
    "016_manifest_approval_evidence.sql",
    "017_stable_brief_blocks.sql",
    "018_audio_scene_scope.sql",
    "019_quality_review_evidence.sql",
    "020_delivery_approvals.sql",
    "021_scene_shots_and_timeline.sql",
    "022_manifest_execution_snapshot.sql",
)


# --------------------------------------------------------------------------- #
# Compatibilidad con la plataforma Supabase                                    #
# --------------------------------------------------------------------------- #

_SUPABASE_COMPAT = """
create extension if not exists pgcrypto;

-- Los roles existen en Supabase; el SQL les hace grant/revoke y sin ellos falla.
do $$ begin create role anon;           exception when duplicate_object then null; end $$;
do $$ begin create role authenticated;  exception when duplicate_object then null; end $$;
do $$ begin create role service_role;   exception when duplicate_object then null; end $$;

create schema if not exists auth;
create schema if not exists storage;

-- `profiles` referencia a auth.users y un trigger cuelga de su INSERT: sembrar un
-- usuario aquí es lo que crea el perfil, igual que en producción.
create table if not exists auth.users (
  id                 uuid primary key default gen_random_uuid(),
  email              text not null,
  raw_user_meta_data jsonb not null default '{}'::jsonb
);

-- `my_sessions()` y `revoke_session()` de schema.sql leen de aquí. Supabase la provee
-- de serie; nuestro `auth` de mentira no, y sin ella el esquema entero fallaba al
-- aplicarse con `relation "auth.sessions" does not exist`, dejando los siete tests de
-- integración en error. Solo se declaran las columnas que esas dos funciones tocan.
create table if not exists auth.sessions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users on delete cascade,
  created_at   timestamptz not null default now(),
  refreshed_at timestamp,
  user_agent   text,
  ip           inet
);

-- El backend usa la conexión de servicio y salta RLS, así que `auth.uid()` nunca
-- resuelve a nadie. Devuelve NULL a propósito: si alguna consulta del backend
-- dependiera de ella para filtrar, aquí no devolvería filas y el test lo vería.
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

create table if not exists storage.buckets (
  id text primary key, name text, public boolean,
  file_size_limit bigint, allowed_mime_types text[]
);
create table if not exists storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text, name text, owner uuid
);
alter table storage.objects enable row level security;

create or replace function storage.foldername(name text) returns text[]
  language sql immutable as $$ select string_to_array(name, '/') $$;
"""


# --------------------------------------------------------------------------- #
# Base de datos                                                                #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """
    URL de un Postgres vivo y desechable.

    Fixture síncrona a propósito. Las fixtures asíncronas de ámbito de sesión obligan a
    fijar el ámbito del bucle de eventos, y ese acoplamiento entre pytest-asyncio y el
    contenedor es una fuente de fallos intermitentes que no aporta nada aquí: levantar
    el contenedor no necesita asyncio.
    """
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield _normalise(url)
        return

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip(
            "Sin base de datos de integración. Define TEST_DATABASE_URL "
            "(p. ej. postgresql://xframe:xframe@localhost:5432/xframe, con "
            "`docker compose up postgres`) o instala testcontainers."
        )

    try:
        # La misma imagen que el docker-compose: probar contra otra versión mayor de
        # Postgres que la de producción invalida justo lo que esta suite comprueba.
        with PostgresContainer("postgres:16-alpine") as container:
            yield _normalise(container.get_connection_url())
    except Exception as exc:
        pytest.skip(f"testcontainers está instalado pero no pudo arrancar Docker: {exc}")


def _normalise(url: str) -> str:
    """`postgresql+psycopg2://` (SQLAlchemy) → `postgresql://` (asyncpg)."""
    return url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgres+psycopg2://", "postgresql://"
    )


@pytest.fixture(scope="session")
def schema(postgres_url: str) -> str:
    """
    Aplica el esquema base, el agente y todas las migraciones de producción sobre una
    base limpia, una vez por sesión.

    Se ejecuta con `asyncio.run` en una fixture síncrona por el mismo motivo que arriba:
    aislar el ciclo de vida del esquema del ciclo de vida del bucle de los tests.
    """
    asyncpg = pytest.importorskip("asyncpg", reason="asyncpg es obligatorio para la integración")

    missing = [f for f in SCHEMA_FILES if not (SUPABASE_DIR / f).exists()]
    if missing:
        pytest.skip(f"No encuentro el esquema en {SUPABASE_DIR}: faltan {missing}")

    async def apply() -> None:
        conn = await asyncpg.connect(postgres_url)
        try:
            await conn.execute(_SUPABASE_COMPAT)
            for name in SCHEMA_FILES:
                sql = (SUPABASE_DIR / name).read_text(encoding="utf-8")
                await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(apply())
    return postgres_url


@pytest.fixture
async def db(schema: str) -> Any:
    """
    Pool de `app.db` apuntando al Postgres de test, con la base vacía.

    Se apunta el pool **de la aplicación**, no uno paralelo: `queue.enqueue`,
    `credits.reserve` y el worker usan `app.db.transaction()` internamente y no aceptan
    una conexión desde fuera. Si el test usara su propio pool, no estaría ejercitando el
    mismo camino que producción.

    El truncado va al principio y no al final: si un test se cae a mitad, la base queda
    tal cual para poder inspeccionarla, y el siguiente arranca limpio igualmente.
    """
    from app import db as app_db
    from app.config import get_settings

    os.environ["DATABASE_URL"] = schema
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-no-real-key")
    # Sin esto el worker duerme 5 s entre polls (el valor de producción, que es un dato
    # de Runway) y un e2e tarda medio minuto en algo que no está midiendo.
    os.environ["JOB_POLL_INTERVAL_S"] = "0.01"
    os.environ["JOB_TIMEOUT_S"] = "30"
    get_settings.cache_clear()

    await app_db.close_pool()  # por si un test anterior lo dejó abierto
    await app_db.init_pool()

    await app_db.execute(
        """
        truncate table auth.users, public.gen_models, public.camera_motions,
                       public.visual_styles restart identity cascade
        """
    )

    # Los checkpoints de LangGraph viven en sus propias tablas y **no** cuelgan de
    # `projects`, así que el `cascade` de arriba no los toca. Como el `conversation_id`
    # de la semilla es fijo, sin esto un test hereda el checkpoint del anterior: el
    # runner encuentra estado previo, deduce de él un modo o un turno a medias, y el
    # resultado es un test que pasa en aislamiento y falla dentro de la suite —o al
    # revés—, según el orden. Se hace con `to_regclass` porque las tablas solo existen
    # después del primer `checkpointer.setup()`.
    await app_db.execute(
        """
        do $$
        declare t text;
        begin
          foreach t in array array['checkpoints', 'checkpoint_blobs',
                                   'checkpoint_writes', 'checkpoint_migrations']
          loop
            if to_regclass('public.' || t) is not null then
              execute format('truncate table public.%I', t);
            end if;
          end loop;
        end $$;
        """
    )
    _reset_caches()

    try:
        yield app_db
    finally:
        await app_db.close_pool()
        _reset_caches()


def _reset_caches() -> None:
    """
    Las cachés con TTL de la taxonomía y del registry sobreviven entre tests.

    Sin este reset, un test que siembra dos modelos ve los cinco del test anterior
    durante los 60 s del TTL, y el fallo aparece o no según el orden de ejecución.
    """
    from app.taxonomy.repo import invalidate_cache

    invalidate_cache()

    from app.providers import registry as registry_mod

    if registry_mod._default is not None:
        registry_mod._default.invalidate()


# --------------------------------------------------------------------------- #
# Semilla                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Seed:
    """Ids fijos del proyecto sembrado. Fijos para que un fallo sea legible."""

    user_id: str
    project_id: str
    conversation_id: str
    element_id: str
    shot_id: str
    video_model: str
    image_model: str
    motion_id: str
    style_id: str
    credits: int


SEED = Seed(
    user_id="11111111-1111-4111-8111-111111111111",
    project_id="22222222-2222-4222-8222-222222222222",
    conversation_id="33333333-3333-4333-8333-333333333333",
    element_id="44444444-4444-4444-8444-444444444444",
    shot_id="55555555-5555-4555-8555-555555555555",
    video_model="test-video",
    image_model="test-image",
    motion_id="dolly-in",
    style_id="teal-orange",
    credits=10_000,
)


@pytest.fixture
async def seed(db: Any) -> Seed:
    """
    Taxonomía mínima + proyecto + perfil con saldo + un element usable.

    Mínima **pero completa**: dos modelos (vídeo e imagen), un movimiento de cámara y un
    estilo. Con la taxonomía vacía el builder no monta ninguna tool de generación —es su
    comportamiento correcto—, así que un e2e sobre una base sin sembrar daría verde sin
    haber ejercitado nada. El element existe porque la continuidad de personaje es el
    núcleo del producto y su cadena entera pasa por aquí.
    """
    await db.execute(
        "insert into auth.users (id, email) values ($1::uuid, $2)",
        SEED.user_id,
        "director@xframe.test",
    )
    # El trigger `on_auth_user_created` ya creó el perfil; aquí solo se le da plan y saldo.
    await db.execute(
        "update public.profiles set plan = 'pro', credits = $2 where id = $1::uuid",
        SEED.user_id,
        SEED.credits,
    )
    # Y el libro mayor, que es la fuente de verdad. `profiles.credits` es solo el espejo
    # que lee el frontend.
    #
    # Sembrarlo aquí no es adorno: en producción lo hizo la migración, y sin esta fila el
    # saldo arranca en 0 y el bootstrap perezoso salta **a mitad del primer `reserve`**.
    # El resultado era un test que leía 0 antes de encolar y 9904 después, y que por tanto
    # no comprobaba nada de lo que decía comprobar.
    await db.execute(
        """
        insert into public.credit_ledger (profile_id, kind, amount, balance_after, note)
        values ($1::uuid, 'grant', $2, $2, 'saldo inicial del fixture')
        """,
        SEED.user_id,
        SEED.credits,
    )
    await db.execute(
        """
        insert into public.projects (id, owner_id, title, prompt)
        values ($1::uuid, $2::uuid, 'Proyecto de integración', 'un corto de prueba')
        """,
        SEED.project_id,
        SEED.user_id,
    )
    await db.execute(
        """
        insert into public.conversations (id, project_id, owner_id, mode)
        values ($1::uuid, $2::uuid, $3::uuid, 'production')
        """,
        SEED.conversation_id,
        SEED.project_id,
        SEED.user_id,
    )

    await db.execute(
        """
        insert into public.gen_models
            (id, family, provider, modality, label, description_llm,
             min_duration_s, max_duration_s, resolutions, aspects,
             supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
             cost_per_second, cost_per_image, credits_per_unit, min_plan, status, sort)
        values
            ($1, 'Test', 'fake', 'video', 'Vídeo de prueba',
             'modelo de vídeo de prueba, 4-8s, sin coste real',
             4, 8, array['720p'], array['16:9','9:16'],
             true, false, true, false,
             0.1000, null, 10, 'free', 'active', 1),
            ($2, 'Test', 'fake', 'image', 'Imagen de prueba',
             'modelo de imagen de prueba, sin coste real',
             null, null, array['1024'], array['16:9','1:1'],
             false, false, true, false,
             0.0100, 0.0100, 2, 'free', 'active', 2)
        """,
        SEED.video_model,
        SEED.image_model,
    )
    await db.execute(
        """
        insert into public.camera_motions
            (id, label, description_llm, provider_ref, supports_strength, category, status, sort)
        values ($1, 'Dolly In', 'acercamiento sobre el eje; intimidad creciente',
                '{"fake": "motion-0001"}'::jsonb, true, 'push', 'active', 1)
        """,
        SEED.motion_id,
    )
    await db.execute(
        """
        insert into public.visual_styles
            (id, dimension, label, description_llm, prompt_fragment, status, sort)
        values ($1, 'palette', 'Teal & Orange', 'contraste cálido-frío de cine comercial',
                'teal and orange colour grading', 'active', 1)
        """,
        SEED.style_id,
    )

    # Element: un asset con `role`, que es lo que lo convierte en referencia de
    # continuidad. `status='ready'` y `url` no vacía porque sin las dos cosas
    # `Element.usable_as_reference` es falso y las tools lo rechazan, con razón.
    await db.execute(
        """
        insert into public.assets (id, project_id, name, type, meta, url, status, role)
        values ($1::uuid, $2::uuid, 'Marta', 'image', 'protagonista, 30 años',
                'https://storage.test/marta.png', 'ready', 'character')
        """,
        SEED.element_id,
        SEED.project_id,
    )
    await db.execute(
        """
        insert into public.canvas_nodes
               (id, project_id, node_key, type, title, text, position, spec)
        values ($1::uuid, $2::uuid, 'shot-seed-1', 'shot', 'Plano 1',
                'Marta entra en el bar', 1, '{"duration_s": 6}'::jsonb)
        """,
        SEED.shot_id,
        SEED.project_id,
    )

    _reset_caches()
    return SEED


# --------------------------------------------------------------------------- #
# Redis / bus                                                                  #
# --------------------------------------------------------------------------- #


@pytest.fixture
def redis_client() -> Any:
    """
    Cliente de Redis para el bus. `fakeredis` implementa Streams, que es lo único que
    `EventBus` usa; si no está, se salta en vez de degradar a un doble hecho a mano que
    no reproduciría ni el orden ni los ids `<ms>-<seq>` de los que depende la reconexión.
    """
    fakeredis = pytest.importorskip(
        "fakeredis", reason="pip install fakeredis para la suite de integración"
    )
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
async def bus(redis_client: Any) -> Any:
    """`EventBus` real sobre Redis falso: se ejercita el código del bus, no un doble."""
    from app.stream.bus import EventBus

    instance = EventBus(client=redis_client)
    try:
        yield instance
    finally:
        await instance.close()


# --------------------------------------------------------------------------- #
# Utilidades compartidas                                                       #
# --------------------------------------------------------------------------- #


def new_uuid() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Proveedor fingido                                                            #
# --------------------------------------------------------------------------- #


class FakeAdapter:
    """
    Adaptador de proveedor sin red.

    Es lo **único** que se finge del camino de generación, junto con el LLM. Implementa
    el contrato completo de `GenerationAdapter` (submit → poll → coste → normalización de
    errores) porque el worker lo usa entero: un doble que solo implementase `submit` daría
    verde sin haber ejercitado el polling, el cierre terminal ni el cobro.

    `min_poll_interval_s = 0` porque el intervalo real es un dato del proveedor y aquí no
    hay proveedor al que respetar.
    """

    provider_id = "fake"
    supported_modalities = ("image", "video", "lipsync")
    min_poll_interval_s = 0.0

    #: El proveedor fingido entrega en `provider.test`. Se declara igual que lo hace un
    #: adaptador real porque la política de descarga del worker se alimenta de este
    #: atributo: sin él, el e2e no descargaría nada y el fallo parecería del worker.
    output_domains = ("provider.test",)

    def __init__(
        self,
        *,
        outcome: str = "succeeded",
        output_url: str = "https://provider.test/output.mp4",
        error: str | None = None,
        cost_usd: str = "0.60",
    ) -> None:
        self.outcome = outcome
        self.output_url = output_url
        self.error = error
        self.cost_usd = cost_usd
        self.submits: list[Any] = []
        self.cancels: list[Any] = []

    async def submit(self, req: Any) -> Any:
        from app.providers.base import ProviderJobRef

        self.submits.append(req)
        return ProviderJobRef(provider=self.provider_id, external_id=f"ext-{len(self.submits)}")

    async def poll(self, ref: Any) -> Any:
        from app.providers.base import ProviderJobStatus

        return ProviderJobStatus(
            state=self.outcome,  # type: ignore[arg-type]
            progress=1.0,
            output_urls=[self.output_url] if self.outcome == "succeeded" else [],
            error=self.error,
        )

    async def cancel(self, ref: Any) -> None:
        self.cancels.append(ref)

    def download_headers(self, url: str) -> dict[str, str]:
        """
        Vacío, como el defecto del contrato.

        Está aquí porque el worker lo llama en cada descarga y un doble al que le falta un
        método del contrato no falla en el sitio donde está el hueco: falla dentro del
        worker, con un `AttributeError` que parece un bug del worker. Es exactamente la
        clase de fallo que `test_contracts.py` existe para cazar antes.
        """
        return {}

    def estimate_cost(self, req: Any, spec: Any) -> Any:
        from decimal import Decimal

        return Decimal(self.cost_usd)

    def normalize_error(self, exc: Exception) -> Exception:
        from app.tools.errors import ProviderError

        return ProviderError(self.provider_id, str(exc))


class FakeRegistry:
    """`AdapterRegistry` que siempre devuelve el mismo adaptador fingido."""

    def __init__(self, adapter: FakeAdapter) -> None:
        self.adapter = adapter

    def get(self, provider_id: str) -> FakeAdapter:
        return self.adapter

    def for_model(self, model_id: str) -> FakeAdapter:
        return self.adapter

    async def resolve(self, model_id: str) -> tuple[FakeAdapter, Any]:
        from app import db as app_db
        from app.jobs.queue import load_model_spec

        async with app_db.acquire() as conn:
            return self.adapter, await load_model_spec(conn, model_id)


class MemoryStorage:
    """Storage en memoria. El worker solo necesita que `put()` devuelva una URL."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(
        self, *, project_id: str, job_id: str, filename: str, data: bytes, content_type: str
    ) -> str:
        path = f"{project_id}/{job_id}/{filename}"
        self.objects[path] = data
        return f"https://storage.test/{path}"


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def registry(adapter: FakeAdapter, monkeypatch: pytest.MonkeyPatch) -> FakeRegistry:
    """
    Registro fingido, **también** dado de alta en la tabla real de fábricas.

    Las tools resuelven su adaptador por `get_registry()`, que es el singleton de
    producción: sin registrar aquí la fábrica del proveedor `fake`, la tool moriría con
    `UnknownProviderError` antes de llegar a la cola y el e2e no probaría nada.
    """
    from app.providers import registry as registry_mod

    fake = FakeRegistry(adapter)
    registry_mod._register_defaults()
    monkeypatch.setitem(registry_mod._FACTORIES, "fake", lambda: adapter)
    return fake


@pytest.fixture
def provider_http() -> Any:
    """
    Cliente HTTP del worker: sirve el binario que el proveedor "produjo".

    Con `MockTransport` en vez de dejar salir la petición: un test que descargue de
    internet es un test que falla los lunes por la mañana en CI.
    """
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"\x00\x00\x00\x18ftypmp42fake-bytes", headers={"content-type": "video/mp4"}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
async def worker(db: Any, registry: FakeRegistry, bus: Any, provider_http: Any) -> Any:
    """`JobWorker` real contra la BD real; solo el proveedor y el storage son dobles."""
    from app.jobs.download import OutputDownloader
    from app.jobs.worker import JobWorker

    # El descargador es el de producción, con su lista de hosts y su tope de tamaño; lo
    # único que se sustituye es el resolutor de DNS, porque `provider.test` no existe en
    # ningún DNS y no tiene por qué. Devuelve una IP pública para que la política diga que
    # sí y el e2e ejercite el camino completo. Los rechazos (IP privada, redirección
    # interna, exceso de tamaño) se prueban con el resolutor real en `tests/test_ssrf.py`.
    downloader = OutputDownloader(
        provider_http,
        allowed_hosts=frozenset({"provider.test", "storage.test"}),
        resolver=lambda host: ["93.184.216.34"],
    )

    storage = MemoryStorage()
    instance = JobWorker(
        registry=registry,
        storage=storage,
        bus=bus,
        http=provider_http,
        downloader=downloader,
    )
    instance.storage = storage  # type: ignore[attr-defined]  — para inspección en el test
    try:
        yield instance
    finally:
        await instance.stop()
        await provider_http.aclose()


async def wait_for_job(db: Any, job_id: str, *, states: tuple[str, ...], timeout_s: float = 20.0) -> str:
    """
    Espera a que un job alcance uno de `states`.

    Sondeo sobre la BD y no un `sleep` fijo: el worker corre en otra tarea y cualquier
    espera por tiempo convierte el test en una carrera que falla de forma intermitente.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    last = ""
    while asyncio.get_running_loop().time() < deadline:
        last = await db.fetchval(
            "select status from public.generation_jobs where id = $1::uuid", job_id
        )
        if last in states:
            return last
        await asyncio.sleep(0.02)
    raise AssertionError(
        f"El job {job_id} no llegó a {states} en {timeout_s}s; se quedó en '{last}'. "
        f"Si está en 'queued', nadie lo reclamó: el worker no arrancó."
    )

