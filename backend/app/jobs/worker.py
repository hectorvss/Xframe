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
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from uuid import UUID

import asyncpg
import httpx

from app.config import get_settings
from app.db import transaction
from app.jobs import credits, resume
from app.jobs.download import OutputDownloader
from app.providers.base import (
    AdapterRegistry,
    GenerationRequest,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.storage import sign_reference, sign_request_references
from app.stream.bus import EventBus, get_bus
from app.tools.errors import ProviderError, ProviderRejectedError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
"""
Intentos ante fallo **transitorio** del proveedor durante el **polling**. Tres, no más:
un proveedor que falla tres polls seguidos no está teniendo un mal segundo, está caído.
"""

SUBMIT_ATTEMPTS = 1
"""
Intentos de `submit()` **en esta capa**. Uno, es decir: ninguno adicional.

Por qué uno y no tres. La política de reintento ya vive en la capa HTTP
(`providers/_http.py`), que reintenta cada petición ante fallo transitorio con su propio
backoff. Reintentar otra vez aquí multiplica: 4 intentos HTTP x 3 intentos de worker = 12
submits por job, y un fan-out de doce planos son 144 peticiones contra un proveedor que
ya está caído. Eso no es tolerancia a fallos, es un ataque de denegación de servicio
contra nuestro propio proveedor, y cada submit que sí llega a cursar se factura.

Una sola política, y vive abajo, donde se ve el código de estado y la cabecera
`Retry-After`. Aquí arriba no hay información que la capa HTTP no tuviera ya.

Si alguna vez hay que reintentar de verdad en esta capa, hay que bajar antes los
intentos de `_http.py`: el producto de las dos capas es lo que importa, no cada factor.
"""

BASE_BACKOFF_S = 2.0
MAX_BACKOFF_S = 60.0

JITTER_RATIO = 1.0
"""
Jitter como fracción del retardo base: el retardo final es `delay * uniform(1, 1+ratio)`.

Al 100 % y no al 25 % porque el jitter existe para **romper la sincronía** de un fan-out
al que un rate limit golpeó a la vez. Con un 25 % los doce planos reintentan dentro de
una ventana del 25 % del retardo: siguen llegando en ráfaga y vuelven a provocar el
límite. El mismo valor que usa la capa HTTP, a propósito: dos capas con jitter distinto
producen un patrón de reintento que nadie ha razonado.
"""

SHUTDOWN_GRACE_S = 10.0
"""
Margen para que los jobs en vuelo terminen al apagar antes de cancelarlos.

Diez segundos: lo justo para que un job que ya está escribiendo en la base de datos cierre
su transacción, y no tanto como para que un despliegue se quede esperando a uno colgado.
"""

STALE_AFTER_S = 3600
"""Un job sin latido durante una hora se da por muerto y se reembolsa."""

TERMINAL_STATES: tuple[str, ...] = ("succeeded", "failed", "cancelled", "nsfw")
"""
Estados de los que no se sale. Toda escritura de estado del worker lleva esta guarda.

Está aquí arriba y no repetido en cada consulta porque el bug que arreglamos en
`sweep_stale` fue exactamente ese: la guarda estaba en `_finalize` y en los webhooks,
pero no en el barrido, y el barrido reembolsaba jobs ya entregados.
"""

MAX_SEM_ENTRIES = 512
"""
Tope de semáforos cacheados por dimensión.

`_project_sem` se indexa por `project_id`: sin evicción, un worker de larga vida acumula
una entrada por proyecto que haya pasado por él y no la suelta jamás. No es una fuga
rápida, pero es monótona, y un proceso que se reinicia solo cuando se queda sin memoria
reinicia siempre en el peor momento. Se descartan los semáforos **libres**, que por
definición no tienen a nadie esperando.
"""


class AssetStorage(Protocol):
    """
    Destino de los binarios. Es un `Protocol` para que los tests no necesiten red ni
    bucket: se inyecta una implementación en memoria y el worker no se entera.
    """

    async def put(
        self, *, project_id: str, job_id: str, filename: str, data: bytes, content_type: str
    ) -> str:
        """Sube el binario y devuelve la **ruta del objeto**, nunca una URL."""
        ...


class SupabaseStorage:
    """
    Subida al bucket de Supabase por REST.

    Se copia el binario a nuestro storage en vez de guardar la URL del proveedor porque
    esas URLs caducan — en varios proveedores en cuestión de horas. Un proyecto cuyos
    planos dejan de cargarse a los dos días no es un proyecto.

    Y por el mismo motivo esto devuelve una ruta y no una URL. El bucket es privado, así
    que la única URL que serviría sería una firmada, y una URL firmada guardada en
    `assets.url` caduca igual que la del proveedor: el proyecto volvería a romperse a los
    días, solo que por nuestra culpa. La ruta no caduca; la URL se deriva de ella en el
    momento de usarla y muere con su TTL.
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
        return path


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
        downloader: OutputDownloader | None = None,
        max_provider_concurrency: int = 4,
        max_inflight: int | None = None,
    ) -> None:
        self._registry = registry
        self._storage = storage or SupabaseStorage()
        self._bus = bus or get_bus()

        # `follow_redirects=False`, y no es un detalle. Este cliente descarga URLs que
        # elige el proveedor: seguir sus redirecciones automáticamente significa que la
        # única URL que llegamos a mirar es la primera, y un open redirect en su CDN
        # bastaría para llevarnos a 169.254.169.254. Quien sigue los saltos —validando
        # cada uno— es `OutputDownloader`.
        self._http = http or httpx.AsyncClient(timeout=120.0, follow_redirects=False)

        # Toda descarga de salida pasa por aquí: lista de hosts derivada de los
        # `output_domains` de los adaptadores, rechazo de IPs no públicas y tope de
        # tamaño. Ver `app/jobs/download.py` para el porqué de cada capa.
        self._downloader = downloader or OutputDownloader(self._http)

        self._max_provider_concurrency = max_provider_concurrency

        # Capacidad real de ejecución simultánea de este worker. Es el tope de jobs
        # reclamados a la vez, no solo de jobs corriendo: ver `_has_capacity`.
        self._max_inflight = max_inflight if max_inflight is not None else max_provider_concurrency

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

        Pero tampoco se reclama sin freno. Reclamar es un acto **contable**, no solo de
        planificación: el `_claim` pone el job en `submitted` y congela su `updated_at`.
        Sin el freno de `_has_capacity`, un worker con doscientos jobs en cola los reclama
        todos en segundos, los doscientos se quedan esperando el semáforo con la marca de
        tiempo parada, `sweep_stale` los da por muertos y los reembolsa, y **después** el
        semáforo se libera y los ejecuta igual. Resultado: el usuario tiene su vídeo, el
        proveedor nos ha cobrado y nosotros hemos devuelto el dinero. Se reclama solo lo
        que se puede empezar ahora.
        """
        while not self._stop.is_set():
            if not self._has_capacity():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=poll_idle_s)
                except TimeoutError:
                    pass
                continue

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

        await self._drain(timeout_s=SHUTDOWN_GRACE_S)

    async def _drain(self, *, timeout_s: float) -> None:
        """
        Espera a los jobs en vuelo al apagar, pero no para siempre.

        `gather` a secas es lo que había, y cuelga el proceso indefinidamente si una tarea
        se queda atascada —esperando un semáforo que nadie libera, o un poll que no
        vuelve—. En producción eso convierte un SIGTERM en un `kill -9` a los treinta
        segundos, y el job muere en `running` en vez de quedar liquidado.

        Se les da margen para terminar; a los que no lleguen se les cancela, y `_guarded`
        —que captura `CancelledError` bajo `shield`— los deja en un estado terminal antes
        de morir. Salir sucio deprisa es peor que salir limpio con un tope.
        """
        if not self._running:
            return
        pending = set(self._running)
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout=timeout_s
            )
        except TimeoutError:
            stuck = [t for t in pending if not t.done()]
            logger.warning("worker_shutdown_forced", extra={"stuck_jobs": len(stuck)})
            for task in stuck:
                task.cancel()
            await asyncio.gather(*stuck, return_exceptions=True)

    async def stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> bool:
        """
        Reclama y procesa **un** job, esperando a que termine. Devuelve si había alguno.

        No es una variante de `run_forever` para producción: allí lo correcto es no
        esperar, porque hacerlo serializa el fan-out. Existe para los guiones de prueba y
        los tests, donde lo que se quiere es exactamente lo contrario — procesar un
        trabajo concreto de principio a fin y poder afirmar algo sobre el resultado.

        Vive aquí y no en el guion para que la prueba de humo no tenga que llamar a
        `_claim` y `_guarded`: un script que usa métodos privados deja de compilar en
        silencio en cuanto alguien los renombra, que es justo el fallo que este proyecto
        ya ha pagado una vez.
        """
        job = await self._claim()
        if job is None:
            return False
        await self._guarded(job)
        return True

    async def _guarded(self, job: ClaimedJob) -> None:
        """
        Procesa bajo los dos semáforos y garantiza que el job **nunca** queda en un estado
        no terminal si la tarea se muere. Un job colgado en `running` es una reserva de
        créditos que el usuario no puede recuperar.

        El `shield` del cierre por cancelación no es decorativo. `_finalize` hace cuatro
        sentencias dentro de una transacción, y una de ellas es el reembolso. Sin escudo,
        el apagado que provocó la cancelación vuelve a cancelar el propio cierre en el
        primer `await` de la transacción: el job queda marcado `cancelled` pero **sin
        reembolsar**, o ni siquiera marcado. El usuario paga un plano que nadie generó, y
        el estado que queda en base de datos ya no le dice a nadie que falta devolverlo.
        Con escudo, el cierre corre entero o no empieza.
        """
        try:
            async with self._sem_for_project(job.project_id), self._sem_for_provider(job.provider):
                await self._process(job)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._finalize(job, "cancelled", error="worker detenido")
            )
            raise
        except Exception as exc:
            logger.exception("job_crashed", extra={"job_id": str(job.id)})
            await self._finalize(job, "failed", error=f"error interno del worker: {exc}")

    def _has_capacity(self) -> bool:
        """
        ¿Puede este worker **empezar** otro job ahora mismo?

        El tope se mide sobre los jobs ya reclamados y no terminados, porque desde el
        instante del claim el job ya está consumiendo su ventana de `STALE_AFTER_S`,
        esté ejecutándose o esperando un semáforo. Contar solo los que corren de verdad
        volvería a permitir la cola invisible detrás del semáforo.
        """
        return len(self._running) < self._max_inflight

    def _sem_for_project(self, project_id: UUID) -> asyncio.Semaphore:
        sem = self._project_sem.get(project_id)
        if sem is None:
            sem = asyncio.Semaphore(get_settings().max_concurrent_jobs_per_project)
            self._project_sem[project_id] = sem
            self._evict_idle(self._project_sem)
        return sem

    def _sem_for_provider(self, provider: str) -> asyncio.Semaphore:
        sem = self._provider_sem.get(provider)
        if sem is None:
            sem = asyncio.Semaphore(self._max_provider_concurrency)
            self._provider_sem[provider] = sem
            self._evict_idle(self._provider_sem)
        return sem

    @staticmethod
    def _evict_idle(cache: dict[Any, asyncio.Semaphore]) -> None:
        """
        Descarta semáforos ociosos cuando la caché pasa del tope.

        Solo se descarta lo que está **sin tomar y sin nadie esperando**: soltar un
        semáforo en uso rompería su exclusión mutua, que es precisamente lo que impide
        que un proyecto monopolice la cola o que nos pasemos del rate limit del
        proveedor. Recrear uno ocioso más tarde no cuesta nada y es equivalente, porque
        un semáforo libre no tiene estado que conservar.

        Se recorre en orden de inserción (los `dict` de Python lo conservan), así que se
        cae primero lo más antiguo, que es lo que más probablemente ya no vuelve.
        """
        excess = len(cache) - MAX_SEM_ENTRIES
        if excess <= 0:
            return
        for key in list(cache):
            if excess <= 0:
                break
            sem = cache[key]
            if not sem.locked() and not getattr(sem, "_waiters", None):
                del cache[key]
                excess -= 1

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

        # Se declara fuera del `try` para que el manejador del timeout tenga la
        # referencia real. Ver el porqué en el bloque de `TimeoutError`.
        ref: ProviderJobRef | None = None

        try:
            async with asyncio.timeout(get_settings().job_timeout_s):
                # La firma de las referencias ocurre AQUÍ y no antes, y el sitio exacto es
                # la decisión de diseño de todo este circuito. Tres razones, en orden de
                # gravedad:
                #
                # 1. `queue.enqueue` persiste la petición entera en
                #    `generation_jobs.request`. Firmar en `tools/generation.py` metería una
                #    URL con caducidad dentro de una columna que se rehidrata en cada
                #    reintento y tras cada reinicio del worker: un job reabierto mañana
                #    saldría con una URL muerta.
                # 2. La clave de idempotencia se calcula sobre esa misma petición. Una URL
                #    firmada cambia en cada llamada, así que dos tool calls idénticas
                #    dejarían de colisionar y el usuario pagaría dos veces el mismo plano.
                # 3. Entre encolar y ejecutar puede pasar cualquier cosa — cola propia,
                #    semáforo de proyecto, despliegue. Firmando aquí el TTL empieza a
                #    contar cuando de verdad falta poco: solo el submit y la cola del
                #    proveedor, que es lo que `provider_signed_url_ttl_s` dimensiona.
                #
                # Aquí y no en cada adaptador porque son ocho: uno que se olvide produce
                # el fallo silencioso (personaje con otra cara) que este cambio evita.
                signed = await sign_request_references(
                    request, ttl_s=get_settings().provider_signed_url_ttl_s
                )
                ref = await self._submit_with_backoff(job, adapter, signed)
                status = await self._poll_until_terminal(job, adapter, ref)
        except TimeoutError:
            # El timeout cubre submit y polling juntos, que es lo que le importa al
            # usuario: cuánto lleva esperando su plano, no en qué fase se atascó.
            #
            # La cancelación tiene que llevar el identificador REAL del trabajo en el
            # proveedor. Con `external_id=""` el adaptador cancela un trabajo que no
            # existe: el proveedor sigue renderizando y nos factura el render completo,
            # mientras nosotros ya hemos reembolsado al usuario en `_finalize`. Se paga
            # dos veces por un vídeo que además nadie llega a descargar.
            #
            # `ref` está en memoria si el submit llegó a devolver. Si el timeout cayó
            # entre el submit y su retorno, la referencia puede estar ya persistida por
            # `_store_ref`, así que se rescata de base de datos antes de rendirse.
            logger.warning("job_timeout", extra={"job_id": str(job.id)})
            cancel_ref = ref or await self._load_ref(job)
            if cancel_ref is not None:
                try:
                    await adapter.cancel(cancel_ref)
                except Exception:
                    # Que la cancelación falle no cambia lo que le debemos al usuario.
                    logger.warning("job_cancel_failed", extra={"job_id": str(job.id)})
            else:
                # Sin referencia no hay nada que cancelar, y tampoco hay nada que el
                # proveedor pueda estar cobrándonos: no llegó a aceptar el trabajo.
                logger.info("job_timeout_without_ref", extra={"job_id": str(job.id)})
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
            await self._land_output(job, status, adapter)
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
        Envía el trabajo al proveedor.

        Con `SUBMIT_ATTEMPTS = 1` este bucle da **una** vuelta: el reintento de red vive
        en la capa HTTP y no se duplica aquí (ver la nota de `SUBMIT_ATTEMPTS`). El bucle
        se conserva entero, con su backoff, porque la política es un número: si mañana se
        bajan los intentos de `_http.py`, subir esta constante vuelve a activar el
        reintento sin reescribir nada. Lo que no puede volver es que las dos capas
        reintenten a la vez.

        El jitter no es cosmético: en un fan-out de doce planos contra el mismo proveedor,
        un rate limit los golpea a todos a la vez y sin jitter los doce reintentarían
        sincronizados, reproduciendo exactamente el pico que provocó el límite.

        Solo se reintenta `ProviderError` (la clase transitoria de la jerarquía). Un
        `ProviderRejectedError` sube tal cual: la política de reintento vive en la clase de
        excepción, no aquí.
        """
        last: Exception | None = None
        for attempt in range(1, SUBMIT_ATTEMPTS + 1):
            await self._bump_attempts(job.id)
            try:
                ref = await adapter.submit(request)
                await self._store_ref(job.id, ref)
                return ref
            except ProviderRejectedError:
                raise
            except Exception as exc:
                normalized = adapter.normalize_error(exc) if not isinstance(exc, ProviderError) else exc
                if isinstance(normalized, ProviderRejectedError):
                    raise normalized
                if not isinstance(normalized, ProviderError):
                    raise normalized
                last = normalized
                if attempt == SUBMIT_ATTEMPTS:
                    break
                delay = getattr(normalized, "retry_after_s", None) or min(
                    MAX_BACKOFF_S, BASE_BACKOFF_S * (2 ** (attempt - 1))
                )
                delay += random.uniform(0, delay * JITTER_RATIO)
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
            except Exception as exc:
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

    async def _land_output(
        self, job: ClaimedJob, status: ProviderJobStatus, adapter: Any
    ) -> None:
        """
        Descarga, sube al storage, escribe el asset y cobra. En ese orden.

        Si la descarga falla se reembolsa: el proveedor puede haber cobrado, pero al
        usuario no le ha llegado nada, y comernos ese coste es preferible a cobrarle por
        un fichero que no podemos entregarle.

        La descarga no se hace aquí a mano. La URL la elige el proveedor y este proceso
        corre dentro de nuestra red, así que bajarla sin más es un SSRF con el resultado
        publicado en un bucket público. `OutputDownloader` es quien valida el host contra
        los `output_domains` de los adaptadores, rechaza las IPs no públicas en cada salto
        de redirección y corta la lectura al llegar al tope de tamaño. Su rama de `data:`
        cubre las imágenes de OpenAI, que llegan en base64 y no por URL.
        """
        url = status.output_urls[0]
        try:
            data, content_type = await self._downloader.fetch(url, adapter.download_headers(url))
        except Exception as exc:
            logger.exception("job_download_failed", extra={"job_id": str(job.id)})
            await self._finalize(job, "failed", error=f"no se pudo descargar la salida: {exc}")
            return

        filename = f"output{_extension(content_type)}"
        object_path = await self._storage.put(
            project_id=str(job.project_id),
            job_id=str(job.id),
            filename=filename,
            data=data,
            content_type=content_type,
        )

        final_credits = self._final_credits(job, status)

        async with transaction() as conn:
            asset_id = await self._upsert_asset(conn, job, object_path, content_type)
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
                final_credits=final_credits,
                note=f"generación {job.model_id}",
                conn=conn,
            )
            await conn.execute(
                "update public.assets set credits_spent = $2 where id = $1",
                asset_id,
                final_credits,
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

        # El evento lleva la ruta **y** una URL firmada de cortesía. La ruta es el dato
        # duradero; la URL solo existe para que la tarjeta del canvas se pinte al instante
        # sin una ida y vuelta más. No se persiste en ningún sitio: un evento SSE se
        # consume en segundos y muere, que es justo la vida útil de una URL firmada. El
        # frontend que recargue más tarde vuelve a firmar por su cuenta desde la ruta.
        await self._emit(
            job,
            "asset_ready",
            {
                "asset_id": str(asset_id),
                "shot_id": job.shot_id,
                "path": object_path,
                "url": await sign_reference(object_path),
                "credits_charged": final_credits,
            },
        )
        logger.info("job_succeeded", extra={"job_id": str(job.id), "asset_id": str(asset_id)})
        await self._maybe_resume(job)

    def _final_credits(self, job: ClaimedJob, status: ProviderJobStatus) -> int:
        """
        Créditos a cobrar de verdad por este job, que no siempre son los reservados.

        Contexto de por qué esto existía sin conectar. `credits.charge()` escribe el
        delta `reservado - final` y devuelve la diferencia al usuario. Como aquí se le
        pasaba siempre `job.credits_reserved`, el delta era 0 por construcción, la rama
        de ajuste era código muerto y un plano de 6 s se cobraba a precio de 10 s siempre
        que el proveedor facturase por duración real. La reserva es un techo, no un
        precio.

        Por qué no se puede resolver del todo hoy, dicho explícitamente para que el
        siguiente que pase no lo dé por hecho: **`ProviderJobStatus` no tiene campo de
        coste ni de duración real**. Solo tiene `state`, `progress`, `output_urls`,
        `error` y `raw`. `raw` es el cuerpo sin procesar del proveedor, y ahí unos pocos
        (los que facturan por uso medido) sí devuelven el coste. Eso es lo que se
        aprovecha aquí, con nombres de clave conocidos.

        Lo que falta para cerrarlo bien —y es trabajo de la capa de proveedores, no de
        aquí— es un campo declarado en `ProviderJobStatus` (`cost_usd`, `duration_s`) que
        cada adaptador rellene desde su propio dialecto. Mientras ese campo no exista,
        leer `raw` a ciegas es lo máximo correcto: adivinar una duración a partir del
        vídeo descargado sería inventarnos la base de facturación del proveedor.

        Regla de seguridad en los dos sentidos: nunca por encima de lo reservado (la
        reserva es el contrato con el usuario y `charge()` lo recorta igualmente), y
        nunca por debajo de 1 (un job cobrado a 0 es una generación gratis repetible
        contra una API que sí nos cobra).
        """
        cost_usd = _reported_cost_usd(status.raw)
        if cost_usd is None:
            # Camino normal hoy: el proveedor no dice lo que ha costado. Se cobra la
            # reserva, que es exactamente lo que el usuario aprobó al encolar.
            return job.credits_reserved

        real = credits.usd_to_credits(cost_usd)
        final = max(1, min(real, job.credits_reserved))
        if final != job.credits_reserved:
            logger.info(
                "job_charged_below_reserve",
                extra={
                    "job_id": str(job.id),
                    "reserved": job.credits_reserved,
                    "final": final,
                    "cost_usd": str(cost_usd),
                },
            )
        return final

    async def _upsert_asset(
        self, conn: asyncpg.Connection, job: ClaimedJob, url: str, content_type: str
    ) -> UUID:
        """
        Crea o actualiza la fila del asset.

        Upsert y no insert: la tool de generación pudo dejar ya un asset en `generating`
        para que el frontend pinte el placeholder. Insertar otro dejaría dos tarjetas en el
        canvas para el mismo plano, una de ellas eternamente cargando.

        `url` es la **ruta** del objeto dentro del bucket, pese al nombre heredado de la
        columna. Aquí no se escribe jamás una URL firmada: caducaría dentro de la fila y
        el proyecto se rompería solo. Quien necesite una URL la firma al usarla.
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
        await self._maybe_resume(job)

    # -- utilidades -------------------------------------------------------- #

    async def _maybe_resume(self, job: ClaimedJob) -> None:
        """
        Le cuenta al agente que este job ha terminado, si con él se acabó la espera.

        Va **después** de que el asset esté escrito, cobrado y publicado, y por el mismo
        motivo por el que el cobro va después de escribir el asset: cuando el turno
        reanudado arranque, tiene que leer un estado ya consistente. Si se disparase
        antes del commit, el agente leería el proyecto y no vería el plano que le acaban
        de anunciar.

        Se llama en los dos cierres —éxito y fallo— porque un lote de seis planos en el
        que uno falla también deja de tener jobs pendientes, y el agente tiene que
        enterarse igual: con cinco planos y un fallo hay trabajo que hacer, y ese fallo
        es justamente lo que el usuario no puede ver por sí mismo hasta que alguien se lo
        cuente.

        `resume.on_job_settled` decide y no lanza nunca; aquí solo se corta el caso del
        apagado. Arrancar un turno de LLM mientras el worker se está muriendo es gastar
        dinero en algo que se va a cancelar a la primera espera.
        """
        if self._stop.is_set():
            logger.info("resume_skipped_shutdown", extra={"job_id": str(job.id)})
            return
        await resume.on_job_settled(job.conversation_id)

    async def _emit(self, job: ClaimedJob, event_type: Any, data: dict[str, Any]) -> None:
        """Publica en el stream de la conversación, si el job pertenece a alguna."""
        if job.conversation_id is None:
            return
        await self._bus.publish(
            job.conversation_id, event_type, {"job_id": str(job.id), **data}
        )

    async def _bump_attempts(self, job_id: UUID) -> None:
        """
        Suma un intento. **Acumula**, no sobrescribe.

        Antes se escribía `attempts = <contador del bucle actual>`, y eso machacaba el
        histórico: un job reintentado por el worker, caído, retomado por otro worker y
        reintentado otra vez acababa con `attempts = 1`. La columna dejaba de servir para
        lo único que sirve, que es distinguir el job que falló una vez del que lleva ocho
        y está quemando dinero en un proveedor roto. Con `+ 1` el número es el total real
        de envíos que hemos pagado.
        """
        async with transaction() as conn:
            await conn.execute(
                """
                update public.generation_jobs
                   set attempts = coalesce(attempts, 0) + 1, updated_at = now()
                 where id = $1
                """,
                job_id,
            )

    async def _load_ref(self, job: ClaimedJob) -> ProviderJobRef | None:
        """
        Rescata de base de datos la referencia del proveedor.

        La escribe `_store_ref` en cuanto el submit devuelve, así que está disponible
        aunque este worker haya perdido la variable en memoria (timeout a mitad, o un
        worker distinto retomando el job). Es lo que permite cancelar de verdad en vez de
        reembolsar y dejar al proveedor renderizando a nuestra costa.
        """
        async with transaction() as conn:
            raw = await conn.fetchval(
                "select provider_ref from public.generation_jobs where id = $1", job.id
            )
        if not raw:
            return None
        if isinstance(raw, str):
            import json

            try:
                raw = json.loads(raw)
            except ValueError:
                return None
        external_id = (raw or {}).get("external_id") or ""
        if not external_id:
            return None
        return ProviderJobRef(
            provider=raw.get("provider") or job.provider,
            external_id=external_id,
            poll_url=raw.get("poll_url"),
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

    La guarda `status not in (terminales)` del UPDATE es la misma que llevan `_finalize`
    y los webhooks, y aquí faltaba. El hueco era una carrera con dinero dentro: entre el
    `select` que elige las filas y el `update` que las cierra, el worker legítimo puede
    terminar el job, escribir el asset y cobrarlo. Sin guarda, el barrido pisaba ese
    `succeeded` con un `cancelled` y encima reembolsaba. Resultado: el usuario se queda
    con el vídeo entregado **y** con el dinero, y a nosotros nos lo ha cobrado el
    proveedor. Con la guarda, el UPDATE no toca nada, no devuelve fila, y el reembolso
    —que es la parte cara— ni se intenta.

    Por eso el reembolso está condicionado a que el UPDATE **haya afectado a la fila**, y
    no a que el `select` la hubiera elegido: quien manda es quien llega primero a un
    estado terminal.
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
            closed = await conn.fetchval(
                """
                update public.generation_jobs
                   set status = 'cancelled', updated_at = now(), finished_at = now(),
                       error = '{"message": "job sin latido; recogido por el barrido"}'::jsonb
                 where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                returning id
                """,
                row["id"],
            )
            if closed is None:
                # Alcanzó un estado terminal mientras lo barríamos. No es un error: es
                # justamente la carrera que la guarda existe para perder.
                logger.info("sweep_skipped_terminal", extra={"job_id": str(row["id"])})
                continue
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


_COST_KEYS: tuple[str, ...] = (
    "cost_usd",
    "total_cost_usd",
    "cost",
    "total_cost",
    "billed_cost",
)
"""
Nombres bajo los que un proveedor publica lo que nos ha cobrado por este trabajo.

Es una lista de nombres conocidos y no un contrato porque no hay contrato: `raw` es el
cuerpo tal cual lo devolvió el proveedor. Un proveedor que use otro nombre simplemente no
se detecta y se cobra la reserva, que es el comportamiento seguro.
"""


def _reported_cost_usd(raw: dict[str, Any] | None) -> Decimal | None:
    """
    Coste en USD que el proveedor declara, si lo declara.

    Busca en el nivel superior y en los envoltorios habituales (`data`, `usage`,
    `billing`, `meta`). Devuelve `None` ante cualquier duda: un valor mal interpretado
    aquí se convierte en un cobro incorrecto, y equivocarse cobrando de menos por leer
    mal una clave ajena es peor que no leerla.
    """
    if not isinstance(raw, dict):
        return None

    for container in (raw, *(raw.get(k) for k in ("data", "usage", "billing", "meta"))):
        if not isinstance(container, dict):
            continue
        for key in _COST_KEYS:
            value = container.get(key)
            if isinstance(value, bool) or value is None:
                continue
            if not isinstance(value, (int, float, str, Decimal)):
                continue
            try:
                cost = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            # Un coste negativo o absurdo es un campo que no significa lo que creemos.
            if cost < 0:
                continue
            return cost
    return None


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
