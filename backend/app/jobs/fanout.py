"""
Fan-out de planos.

Ejecuta N generaciones en paralelo y emite cada resultado **en cuanto sale**, no cuando
termina el lote. Con doce planos y latencias de entre veinte segundos y cuatro minutos,
esperar al último para enseñar el primero convierte un render normal en una pantalla
congelada de cuatro minutos.

Hay tres detalles aquí que no son estilo, son la diferencia entre que esto funcione y que
pierda trabajo pagado. Los tres vienen de `ee/hogai/videos/` y de
`parallel_task_execution/nodes.py`:

1. **Los hijos DEVUELVEN el fallo, no lo lanzan.** Es *la* regla. `asyncio.TaskGroup`
   cancela a todas las hermanas en cuanto una hija lanza. Con doce planos lanzados y once
   ya renderizando, que el número siete falle cancelaría los otros once — que ya están
   pagados al proveedor y en muchos casos ya terminados. Por eso `_run_one` captura
   absolutamente todo y devuelve un `JobResult(ok=False)`. Un `JobResult` con `ok=False`
   es un valor de retorno normal, y `TaskGroup` no tiene nada que cancelar.

2. **`asyncio.wait(FIRST_COMPLETED)` en bucle, no `gather`.** `gather` devuelve en orden
   de envío y solo cuando han acabado todos. El bucle da orden de finalización, que es lo
   que hace que el usuario vea el plano rápido primero.

3. **Argumentos por defecto para capturar la variable del bucle.** `async def _wrap(shot=shot)`
   y no `async def _wrap()`. Sin esto las doce closures cierran sobre la *misma* variable
   y todas ven el último plano. Es el bug clásico de Python en fan-out, y en este contexto
   se manifiesta como doce renders idénticos cobrados doce veces.

Y una decisión de producto: si falla demasiada parte del lote, se aborta y se limpian los
assets parciales. Medio storyboard no le sirve a nadie, y dejar los planos sueltos en la
base de datos ensucia el canvas con material que el usuario no pidió así.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Sequence
from uuid import UUID

from app.agent.state import JobResult
from app.db import transaction
from app.tools.errors import XframeToolError

logger = logging.getLogger(__name__)

ShotRunner = Callable[["ShotSpec"], Awaitable[JobResult]]
"""
Lo que se ejecuta por plano. Recibe la especificación y devuelve un `JobResult`. Puede
lanzar: el motor lo captura. Esa es precisamente su función.
"""


@dataclass(slots=True)
class ShotSpec:
    """Un plano del lote. Deliberadamente opaco: el motor no interpreta el contenido."""

    shot_id: str
    payload: Any = None


@dataclass(slots=True)
class FanoutReport:
    """Balance del lote una vez terminado."""

    results: list[JobResult] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None

    @property
    def succeeded(self) -> list[JobResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[JobResult]:
        return [r for r in self.results if not r.ok]

    @property
    def credits_charged(self) -> int:
        return sum(r.credits_charged for r in self.results if r.ok)


async def _run_one(runner: ShotRunner, shot: ShotSpec) -> JobResult:
    """
    Envoltorio de aislamiento. **Nunca lanza.**

    El `except BaseException` es intencionado y no es pereza. Se excluye
    `asyncio.CancelledError`, que sí debe propagarse porque significa que alguien de
    arriba está apagando esto y tragárselo dejaría tareas zombis. Todo lo demás —
    incluido un `MemoryError` o un bug nuestro — se convierte en resultado, porque el
    coste de propagarlo es cancelar a las hermanas, y eso siempre es peor.
    """
    try:
        return await runner(shot)
    except asyncio.CancelledError:
        raise
    except XframeToolError as exc:
        logger.info("fanout_shot_failed", extra={"shot_id": shot.shot_id, "err": exc.to_summary()})
        return JobResult(job_id="", shot_id=shot.shot_id, ok=False, error=exc.to_summary())
    except BaseException as exc:  # noqa: BLE001
        logger.exception("fanout_shot_crashed", extra={"shot_id": shot.shot_id})
        return JobResult(
            job_id="",
            shot_id=shot.shot_id,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )


async def stream_fanout(
    shots: Sequence[ShotSpec],
    runner: ShotRunner,
    *,
    failed_shots_min_ratio: float = 0.5,
    cleanup_partials: bool = True,
) -> AsyncIterator[JobResult]:
    """
    Lanza todos los planos y emite cada `JobResult` en orden de finalización.

    `failed_shots_min_ratio` es la proporción **mínima de éxitos** que hace válido el lote
    (0.5 = al menos la mitad). Se evalúa al final y no sobre la marcha: cortar en cuanto se
    cruza el umbral cancelaría planos que ya están pagados y a punto de salir, que es
    justo lo que este módulo existe para evitar. El umbral decide si el lote *se acepta*,
    no si *se sigue ejecutando*.

    Al consumidor se le entregan igualmente todos los resultados antes del posible aborto:
    el agente necesita ver qué falló para poder contárselo al usuario o reintentar.
    """
    if not shots:
        return

    results: list[JobResult] = []

    async with asyncio.TaskGroup() as tg:
        pending: dict[asyncio.Task[JobResult], str] = {}
        for shot in shots:
            # Argumento por defecto: fija el valor de ESTA iteración. Sin él, las N
            # closures comparten la variable del bucle y todas ven el último plano.
            async def _wrap(_shot: ShotSpec = shot) -> JobResult:
                return await _run_one(runner, _shot)

            task = tg.create_task(_wrap())
            pending[task] = shot.shot_id

        try:
            while pending:
                done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    pending.pop(task, None)
                    # `_run_one` no lanza, así que `result()` es seguro. La red de
                    # seguridad cubre un fallo del propio TaskGroup, no del hijo.
                    try:
                        result = task.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("fanout_task_broken")
                        result = JobResult(job_id="", ok=False, error=str(exc))
                    results.append(result)
                    yield result
        finally:
            # Cubre el caso de que el consumidor abandone el generador (cierra la pestaña,
            # el SSE se corta). Sin esto, salir del `async with` esperaría a que terminen
            # los planos restantes y bloquearía el cierre indefinidamente.
            for task in pending:
                task.cancel()

    ok = [r for r in results if r.ok]
    if _below_threshold(len(ok), len(shots), failed_shots_min_ratio):
        reason = (
            f"solo {len(ok)} de {len(shots)} planos salieron bien, por debajo del mínimo "
            f"del {failed_shots_min_ratio:.0%}"
        )
        logger.warning("fanout_aborted", extra={"ok": len(ok), "total": len(shots)})
        if cleanup_partials:
            await cleanup_partial_assets([r.asset.asset_id for r in ok if r.asset])
        raise FanoutAborted(reason, results=results)


async def run_fanout(
    shots: Sequence[ShotSpec],
    runner: ShotRunner,
    *,
    failed_shots_min_ratio: float = 0.5,
    on_result: Callable[[JobResult], Awaitable[None]] | None = None,
    cleanup_partials: bool = True,
) -> FanoutReport:
    """
    Variante que recoge todo y devuelve un informe, para quien no quiere consumir un
    generador. `on_result` se llama según sale cada plano, así que el streaming al usuario
    se conserva.

    A diferencia de `stream_fanout`, el aborto por umbral se devuelve como
    `FanoutReport(aborted=True)` en vez de lanzarse: el llamante típico es un nodo del
    grafo, y una excepción ahí tumbaría el turno entero en lugar de dejar que el agente
    explique lo ocurrido.
    """
    report = FanoutReport()
    try:
        async for result in stream_fanout(
            shots,
            runner,
            failed_shots_min_ratio=failed_shots_min_ratio,
            cleanup_partials=cleanup_partials,
        ):
            report.results.append(result)
            if on_result is not None:
                await on_result(result)
    except FanoutAborted as exc:
        report.results = exc.results
        report.aborted = True
        report.abort_reason = str(exc)
    return report


class FanoutAborted(XframeToolError):
    """
    El lote no alcanzó el mínimo de planos válidos.

    Hereda de `XframeToolError` para que el ejecutor de herramientas la trate como el
    resto: mensaje al LLM y decisión de reintento tomada por la clase, no por el llamante.
    """

    def __init__(self, message: str, *, results: list[JobResult]) -> None:
        self.results = results
        super().__init__(
            f"{message}. Los planos válidos se han descartado para no dejar el timeline a "
            f"medias. Revisa los prompts de los que fallaron antes de volver a lanzar el lote."
        )


def _below_threshold(ok: int, total: int, ratio: float) -> bool:
    """
    Umbral por proporción, con `ceil` implícito vía comparación entera.

    Un lote de un solo plano con ratio 0.5 exige ese plano: `ceil(1 * 0.5) = 1`. Es lo
    correcto — "la mitad de uno" no puede ser cero planos válidos.
    """
    if total == 0 or ratio <= 0:
        return False
    required = -(-int(total * ratio * 1000) // 1000)  # ceil sin arrastrar float
    return ok < max(1, required)


async def cleanup_partial_assets(asset_ids: Sequence[str | UUID]) -> int:
    """
    Borra los assets de un lote abortado.

    Se borran las filas, no los binarios del storage: el bucket tiene política de
    caducidad y un objeto huérfano cuesta céntimos, mientras que un borrado de storage
    dentro de un camino de error es una fuente de fallos en cascada. Lo que no puede
    quedarse es la fila, porque es la que pinta una tarjeta en el canvas del usuario.

    No reembolsa: cada job se liquidó por su cuenta en el worker según su propio desenlace.
    Reembolsar aquí duplicaría —y `credits.refund` es idempotente, así que ni siquiera
    haría eso: fallaría en silencio y confundiría la auditoría.
    """
    ids = [credits_uuid(a) for a in asset_ids if a]
    if not ids:
        return 0
    async with transaction() as conn:
        deleted = await conn.fetch(
            "delete from public.assets where id = any($1::uuid[]) returning id", ids
        )
    logger.info("fanout_partials_cleaned", extra={"count": len(deleted)})
    return len(deleted)


def credits_uuid(value: str | UUID) -> UUID:
    from app.jobs.credits import to_uuid

    return to_uuid(value)
