"""
El worker: el dueño del job.

Reparto de responsabilidades que conviene tener claro antes de tocar esto. El grafo del
agente **no espera**. La tool de generación encola, devuelve un `AssetRef` en estado
`generating` y termina su turno. Desde ahí el job es de este worker, que corre en otro
proceso. Consecuencia buscada: si el usuario cierra el navegador a los diez segundos de
un render de cuatro minutos, el render sigue, el asset aterriza en la base de datos y al
reconectar el agente reanuda desde el checkpoint con el plano ya hecho.

Lo contrario — un grafo que espera al proveedor — significaría un turno de LangGraph
bloqueado minutos, un checkpoint gigante y trabajo pagado que se pierde al cerrar la
pestaña.

Ciclo de un job:

    claim → submit → poll hasta terminal → descarga → storage → assets → créditos → evento

El cobro va **después** de que el asset esté escrito, nunca antes. Si el proceso muere
entre medias, el job queda reservado y sin liquidar, que es un estado recuperable (lo
barre `sweep_stale`). Al revés — cobrar y luego morir antes de escribir el asset — deja
al usuario pagando por algo que no existe y que nadie va a reconstruir.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

import asyncpg
import httpx

from app.config import get_settings
from app.db import transaction
from app.jobs import credits
from app.providers.base import (
    AdapterRegistry,
    GenerationRequest,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.stream.bus import EventBus, get_bus
from app.tools.errors import ProviderError, ProviderRejectedError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
"""
Intentos ante fallo **transitorio** del proveedor. Tres, no más: cada intento cuesta la
latencia de un render, y un proveedor que falla tres veces seguidas no está teniendo un
mal segundo, está caído.
"""

BASE_BACKOFF_S = 2.0
MAX_BACKOFF_S = 60.0

STALE_AFTER_S = 3600
"""Un job sin latido durante una hora se da por muerto y se reembolsa."""


class AssetStorage(Protocol):
    """
    Destino de los binarios. Es un `Protocol` para que los tests no necesiten red ni
    bucket: se inyecta una implementación en memoria y el worker no se entera.
    """

    async def put(
        self, *, project_id: str, job_id: str, filename: str, data: bytes, content_type: str
    ) -> str: ...


class SupabaseStorage:
    """
    Subida al bucket de Supabase por REST.

    Se copia el binario a nuestro storage en vez de guardar la URL del proveedor porque
    esas URLs caducan — en varios proveedores en cuestión de horas. Un proyecto cuyos
    planos dejan de cargarse a los dos días no es un proyecto.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._base = settings.supabase_url.rstrip("/")
        self._bucket = settings.storage_bucket
        self._key = settings.supabase_service_key
        self._client = client or httpx.AsyncClient(timeout=120.0)

    async def put(
        self, *, project_id: str, job_id: str, filename: str, data: bytes, content_type: str
    ) -> str:
        path = f"{project_id}/{job_id}/{filename}"
        url = f"{self._base}/storage/v1/object/{self._bucket}/{path}"
        resp = await self._client.post(
            url,
            content=data,
            headers={
                "authorization": f"Bearer {self._key}",
                "content-type": content_type,
                "x-upsert": "true",  # reintento del worker sobre el mismo job = mismo path
            },
        )
        resp.raise_for_status()
        return f"{self._base}/storage/v1/object/public/{self._bucket}/{path}"


@dataclass(slots=True)
class ClaimedJob:
    """Un job tomado en exclusiva por este worker."""

    id: UUID
    project_id: UUID
    conversation_id: UUID | None
    shot_id: str | None
    provider: str
    model_id: str
    request: dict[str, Any]
    attempts: int
    credits_reserved: int


class JobWorker:
    """
    Bucle de trabajo. Se instancian varios en paralelo sin coordinación entre ellos: el
    reparto lo hace Postgres con `FOR UPDATE SKIP LOCKED`, que es exactamente para esto y
    evita tener que montar un broker aparte.
    """

    def __init__(
        self,
        *,
        registry: AdapterRegistry,
        storage: AssetStorage | None = None,
        bus: EventBus | None = None,
        http: httpx.AsyncClient | None = None,
        max_provider_concurrency: int = 4,
    ) -> None:
        self._registry = registry
        self._storage = storage or SupabaseStorage()
        self._bus = bus or get_bus()
        self._http = http or httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        self._max_provider_concurrency = max_provider_concurrency

        # Los semáforos se crean bajo demanda y viven mientras viva el worker. Por
        # proyecto, para que un usuario con un fan-out de 40 planos no monopolice la cola;
        # por proveedor, porque los rate limits son por cuenta y el nuestro es uno solo,
        # compartido por todos los proyectos.
        self._project_sem: dict[UUID, asyncio.Semaphore] = {}
        self._provider_sem: dict[str, asyncio.Semaphore] = {}
        self._running: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()

    # -- bucle ------------------------------------------------------------- #

    async def run_forever(self, *, poll_idle_s: float = 1.0) -> None:
        """
        Toma jobs `queued` y los procesa concurrentemente hasta que se pida parar.

        No se hace `await` sobre el procesado dentro del bucle: eso serializaría el worker
        a un job cada vez y convertiría un fan-out de doce planos en doce renders en fila.
        """
        while not self._stop.is_set():
            job = await self._claim()
            if job is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=poll_idle_s)
                except TimeoutError:
                    pass
                continue

            task = asyncio.create_task(self._guarded(job))
            self._running.add(task)
            task.add_done_callback(self._running.discard)

        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)

    async def stop(self) -> None:
        self._stop.set()

    async def _guarded(self, job: ClaimedJob) -> None:
        """
        Procesa bajo los dos semáforos y garantiza que el job **nunca** queda en un estado
        no terminal si la tarea se muere. Un job colgado en `running` es una reserva de
        créditos que el usuario no puede recuperar.
        """
        try:
            async with self._sem_for_project(job.project_id), self._sem_for_provider(job.provider):
                await self._process(job)
        except asyncio.CancelledError:
            await self._finalize(job, "cancelled", error="worker detenido")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_crashed", extra={"job_id": str(job.id)})
            await self._finalize(job, "failed", error=f"error interno del worker: {exc}")

    def _sem_for_project(self, project_id: UUID) -> asyncio.Semaphore:
        if project_id not in self._project_sem:
            self._project_sem[project_id] = asyncio.Semaphore(
                get_settings().max_concurrent_jobs_per_project
            )
        return self._project_sem[project_id]

    def _sem_for_provider(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._provider_sem:
            self._provider_sem[provider] = asyncio.Semaphore(self._max_provider_concurrency)
        return self._provider_sem[provider]

    # -- toma de trabajo --------------------------------------------------- #

    async def _claim(self) -> ClaimedJob | None:
        """
        Toma un job en exclusiva.

        `FOR UPDATE SKIP LOCKED` sobre el subselect: varios workers pueden competir por la
        misma fila y todos menos uno la saltan en vez de bloquearse. Es el patrón estándar
        de cola sobre Postgres y nos ahorra un componente de infraestructura entero.
        """
        async with transaction() as conn:
            row = await conn.fetchrow(
                """
                update public.generation_jobs
                   set status = 'submitted', started_at = coalesce(started_at, now()),
                       updated_at = now()
                 where id = (
                     select id from public.generation_jobs
                      where status = 'queued'
                      order by created_at
                      for update skip locked
                      limit 1
                 )
                returning id, project_id, conversation_id, shot_id, provider, model_id,
                          request, attempts, credits_reserved
                """
            )
        if row is None:
            return None
        return ClaimedJob(
            id=row["id"],
            project_id=row["project_id"],
            conversation_id=row["conversation_id"],
            shot_id=row["shot_id"],
            provider=row["provider"],
            model_id=row["model_id"],
            request=row["request"],
            attempts=row["attempts"],
            credits_reserved=row["credits_reserved"],
        )

    # -- procesado --------------------------------------------------------- #

    async def _process(self, job: ClaimedJob) -> None:
        adapter = self._registry.get(job.provider)
        request = _deserialize(job.request)

        await self._emit(job, "job_status", {"status": "submitted"})

        try:
            async with asyncio.timeout(get_settings().job_timeout_s):
                ref = await self._submit_with_backoff(job, adapter, request)
                status = await self._poll_until_terminal(job, adapter, ref)
        except TimeoutError:
            # El timeout cubre submit y polling juntos, que es lo que le importa al
            # usuario: cuánto lleva esperando su plano, no en qué fase se atascó.
            logger.warning("job_timeout", extra={"job_id": str(job.id)})
            await adapter.cancel(ProviderJobRef(provider=job.provider, external_id=""))
            await self._finalize(job, "cancelled", error="el proveedor superó el tiempo máximo")
            return
        except ProviderRejectedError as exc:
            # Rechazo por contenido o parámetros. No se reintenta: reintentar lo mismo da
            # el mismo rechazo, y el LLM puede corregir la entrada con este mensaje.
            await self._finalize(job, "failed", error=exc.to_summary())
            return
        except ProviderError as exc:
            await self._finalize(job, "failed", error=exc.to_summary())
            return

        if status.state == "succeeded" and status.output_urls:
            await self._land_output(job, status)
        else:
            await self._finalize(
                job,
                status.state if status.state != "succeeded" else "failed",
                error=status.error or "el proveedor terminó sin producir salida",
            )

    async def _submit_with_backoff(
        self, job: ClaimedJob, adapter: Any, request: GenerationRequest
    ) -> ProviderJobRef:
        """
        Envía con backoff exponencial y jitter ante fallo transitorio.

        El jitter no es cosmético: en un fan-out de doce planos contra el mismo proveedor,
        un rate limit los golpea a todos a la vez y sin jitter los doce reintentarían
        sincronizados, reproduciendo exactamente el pico que provocó el límite.

        Solo se reintenta `ProviderError` (la clase transitoria de la jerarquía). Un
        `ProviderRejectedError` sube tal cual: la política de reintento vive en la clase de
        excepción, no aquí.
        """
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._bump_attempts(job.id, attempt)
            try:
                ref = await adapter.submit(request)
                await self._store_ref(job.id, ref)
                return ref
            except ProviderRejectedError:
                raise
            except Exception as exc:  # noqa: BLE001
                normalized = adapter.normalize_error(exc) if not isinstance(exc, ProviderError) else exc
                if isinstance(normalized, ProviderRejectedError):
                    raise normalized
                if not isinstance(normalized, ProviderError):
                    raise normalized
                last = normalized
                if attempt == MAX_ATTEMPTS:
                    break
                delay = getattr(normalized, "retry_after_s", None) or min(
                    MAX_BACKOFF_S, BASE_BACKOFF_S * (2 ** (attempt - 1))
                )
                delay += random.uniform(0, delay * 0.25)
                logger.info(
                    "job_submit_retry",
                    extra={"job_id": str(job.id), "attempt": attempt, "delay_s": round(delay, 2)},
                )
                await asyncio.sleep(delay)

        assert last is not None
        raise last

    async def _poll_until_terminal(
        self, job: ClaimedJob, adapter: Any, ref: ProviderJobRef
    ) -> ProviderJobStatus:
        """
        Poll hasta estado terminal, respetando el intervalo del adaptador.

        `min_poll_interval_s` es un dato del proveedor, no una preferencia nuestra: Runway
        throttlea por encima de 1 req/5 s, y pollear más rápido convierte un render normal
        en un rate limit autoinfligido. Se toma el máximo con el ajuste global para que
        subir el intervalo por configuración funcione, pero bajarlo por debajo del mínimo
        del proveedor no.

        Un fallo puntual del poll no mata el job: la petición se reintenta en el siguiente
        ciclo. El corte definitivo lo pone el `asyncio.timeout` de fuera.
        """
        interval = max(adapter.min_poll_interval_s, get_settings().job_poll_interval_s)
        last_progress: float | None = None
        consecutive_errors = 0

        while True:
            await asyncio.sleep(interval)
            try:
                status = await adapter.poll(ref)
                consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001
                consecutive_errors += 1
                if consecutive_errors >= MAX_ATTEMPTS:
                    raise adapter.normalize_error(exc)
                logger.info(
                    "job_poll_error", extra={"job_id": str(job.id), "n": consecutive_errors}
                )
                continue

            if status.state == "running" and status.progress != last_progress:
                last_progress = status.progress
                await self._set_progress(job.id, status.progress)
                await self._emit(
                    job, "tool_progress", {"shot_id": job.shot_id, "progress": status.progress}
                )

            if status.is_terminal:
                return status

    # -- aterrizaje del resultado ------------------------------------------ #

    async def _land_output(self, job: ClaimedJob, status: ProviderJobStatus) -> None:
        """
        Descarga, sube al storage, escribe el asset y cobra. En ese orden.

        Si la descarga falla se reembolsa: el proveedor puede haber cobrado, pero al
        usuario no le ha llegado nada, y comernos ese coste es preferible a cobrarle por
        un fichero que no podemos entregarle.
        """
        url = status.output_urls[0]
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
            data = resp.content
            content_type = resp.headers.get("content-type", "application/octet-stream")
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_download_failed", extra={"job_id": str(job.id)})
            await self._finalize(job, "failed", error=f"no se pudo descargar la salida: {exc}")
            return

        filename = f"output{_extension(content_type)}"
        public_url = await self._storage.put(
            project_id=str(job.project_id),
            job_id=str(job.id),
            filename=filename,
            data=data,
            content_type=content_type,
        )

        async with transaction() as conn:
            asset_id = await self._upsert_asset(conn, job, public_url, content_type)
            await conn.execute(
                """
                update public.generation_jobs
                   set status = 'succeeded', asset_id = $2, progress = 1,
                       updated_at = now(), finished_at = now(), error = null
                 where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                """,
                job.id,
                asset_id,
            )
            await credits.charge(
                job_id=job.id,
                final_credits=job.credits_reserved,
                note=f"generación {job.model_id}",
                conn=conn,
            )
            await conn.execute(
                "update public.assets set credits_spent = $2 where id = $1",
                asset_id,
                job.credits_reserved,
            )
            if job.shot_id:
                await conn.execute(
                    """
                    update public.canvas_nodes set shot_status = 'ready'
                     where id = $1 and project_id = $2
                    """,
                    job.shot_id,
                    job.project_id,
                )

        await self._emit(
            job,
            "asset_ready",
            {
                "asset_id": str(asset_id),
                "shot_id": job.shot_id,
                "url": public_url,
                "credits_charged": job.credits_reserved,
            },
        )
        logger.info("job_succeeded", extra={"job_id": str(job.id), "asset_id": str(asset_id)})

    async def _upsert_asset(
        self, conn: asyncpg.Connection, job: ClaimedJob, url: str, content_type: str
    ) -> UUID:
        """
        Crea o actualiza la fila del asset.

        Upsert y no insert: la tool de generación pudo dejar ya un asset en `generating`
        para que el frontend pinte el placeholder. Insertar otro dejaría dos tarjetas en el
        canvas para el mismo plano, una de ellas eternamente cargando.
        """
        existing = await conn.fetchval(
            "select asset_id from public.generation_jobs where id = $1", job.id
        )
        kind = "video" if content_type.startswith("video") else (
            "audio" if content_type.startswith("audio") else "image"
        )
        prompt = job.request.get("prompt", "")

        if existing is not None:
            await conn.execute(
                """
                update public.assets
                   set url = $2, status = 'ready', type = $3, job_id = $4,
                       model_id = $5, prompt = $6, shot_id = coalesce($7, shot_id)
                 where id = $1
                """,
                existing,
                url,
                kind,
                job.id,
                job.model_id,
                prompt,
                job.shot_id,
            )
            return existing

        return await conn.fetchval(
            """
            insert into public.assets
                (project_id, name, type, url, status, shot_id, job_id, model_id, prompt, params)
            values ($1, $2, $3, $4, 'ready', $5, $6, $7, $8, $9)
            returning id
            """,
            job.project_id,
            (job.shot_id or job.model_id)[:80],
            kind,
            url,
            job.shot_id,
            job.id,
            job.model_id,
            prompt,
            job.request,
        )

    async def _finalize(self, job: ClaimedJob, state: str, *, error: str | None) -> None:
        """
        Cierre no exitoso: marca el job y devuelve los créditos.

        El `where status not in (...)` es la misma guarda que usan los webhooks. Un poll
        lento y un webhook pueden llegar a la vez con veredictos distintos; el primero en
        alcanzar un estado terminal manda, y el segundo no lo revierte. `refund()` es
        idempotente, así que la carrera tampoco duplica el reembolso.
        """
        should_refund = state in ("failed", "nsfw", "cancelled")
        async with transaction() as conn:
            updated = await conn.fetchval(
                """
                update public.generation_jobs
                   set status = $2, error = $3, updated_at = now(), finished_at = now()
                 where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                returning id
                """,
                job.id,
                state,
                {"message": error} if error else None,
            )
            if updated is None:
                logger.info("job_already_terminal", extra={"job_id": str(job.id)})
                return

            if should_refund:
                await credits.refund(job_id=job.id, reason=f"{state}: {error}", conn=conn)

            await conn.execute(
                "update public.assets set status = 'failed' where job_id = $1 and status = 'generating'",
                job.id,
            )
            if job.shot_id:
                await conn.execute(
                    "update public.canvas_nodes set shot_status = 'failed' where id = $1 and project_id = $2",
                    job.shot_id,
                    job.project_id,
                )

        await self._emit(
            job,
            "error" if state == "failed" else "job_status",
            {"status": state, "shot_id": job.shot_id, "message": error, "refunded": should_refund},
        )
        logger.info("job_finalized", extra={"job_id": str(job.id), "state": state})

    # -- utilidades -------------------------------------------------------- #

    async def _emit(self, job: ClaimedJob, event_type: Any, data: dict[str, Any]) -> None:
        """Publica en el stream de la conversación, si el job pertenece a alguna."""
        if job.conversation_id is None:
            return
        await self._bus.publish(
            job.conversation_id, event_type, {"job_id": str(job.id), **data}
        )

    async def _bump_attempts(self, job_id: UUID, attempt: int) -> None:
        async with transaction() as conn:
            await conn.execute(
                "update public.generation_jobs set attempts = $2, updated_at = now() where id = $1",
                job_id,
                attempt,
            )

    async def _store_ref(self, job_id: UUID, ref: ProviderJobRef) -> None:
        """
        Persiste la referencia del proveedor en cuanto existe.

        Es lo que permite que un webhook encuentre su job, y que tras reiniciar el worker
        se pueda retomar el polling de algo que ya está corriendo y pagado al proveedor.
        """
        async with transaction() as conn:
            await conn.execute(
                """
                update public.generation_jobs
                   set provider_ref = $2, status = 'running', updated_at = now()
                 where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                """,
                job_id,
                {"provider": ref.provider, "external_id": ref.external_id, "poll_url": ref.poll_url},
            )

    async def _set_progress(self, job_id: UUID, progress: float | None) -> None:
        async with transaction() as conn:
            await conn.execute(
                "update public.generation_jobs set progress = $2, updated_at = now() where id = $1",
                job_id,
                progress,
            )


async def sweep_stale(*, older_than_s: int = STALE_AFTER_S) -> int:
    """
    Recoge jobs que llevan una hora sin latido y devuelve sus créditos.

    Hace falta porque el worker puede morir de formas que no dejan escribir nada: OOM,
    despliegue, corte de red. Sin este barrido, esos jobs se quedan en `running` para
    siempre y sus reservas nunca vuelven al usuario, que ve saldo descontado por planos
    que jamás llegaron.
    """
    swept = 0
    async with transaction() as conn:
        rows = await conn.fetch(
            """
            select id from public.generation_jobs
             where status in ('queued','submitted','running')
               and updated_at < now() - ($1 || ' seconds')::interval
             for update skip locked
            """,
            str(older_than_s),
        )
        for row in rows:
            await conn.execute(
                """
                update public.generation_jobs
                   set status = 'cancelled', updated_at = now(), finished_at = now(),
                       error = '{"message": "job sin latido; recogido por el barrido"}'::jsonb
                 where id = $1
                """,
                row["id"],
            )
            await credits.refund(job_id=row["id"], reason="job huérfano", conn=conn)
            swept += 1
    if swept:
        logger.warning("jobs_swept", extra={"count": swept})
    return swept


def _deserialize(raw: dict[str, Any]) -> GenerationRequest:
    """
    jsonb → `GenerationRequest`. Se filtran las claves desconocidas: un job encolado por
    una versión anterior del backend debe poder ejecutarse tras un despliegue que haya
    quitado un campo, no reventar el worker con un `TypeError`.
    """
    from app.providers.base import ElementRef

    fields = set(GenerationRequest.__dataclass_fields__)
    data = {k: v for k, v in (raw or {}).items() if k in fields}
    data["elements"] = [
        ElementRef(**{k: v for k, v in e.items() if k in ElementRef.__dataclass_fields__})
        for e in (raw.get("elements") or [])
    ]
    return GenerationRequest(**data)


def _extension(content_type: str) -> str:
    return {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
    }.get(content_type.split(";")[0].strip(), ".bin")


def _now() -> datetime:
    return datetime.now(timezone.utc)
