"""
Entrypoint del worker: `python -m app.jobs`.

Existe porque `docker-compose.yml` declaraba `python -m app.jobs.worker` y ese módulo
nunca tuvo bloque `__main__`: el contenedor arrancaba y salía en el acto, así que los
jobs se quedaban en `queued` para siempre. Se pone en `app/jobs/__main__.py` en vez de
dentro de `worker.py` para que el módulo siga siendo importable sin efectos colaterales.

Arranca dos bucles: el worker propiamente dicho y el barrido de jobs obsoletos.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.config import get_settings
from app.db import close_pool, init_pool
from app.jobs.worker import JobWorker, sweep_stale
from app.providers.registry import get_registry
from app.runtime import configure_event_loop

# Antes de que nadie cree un bucle. Ver app/runtime.py.
configure_event_loop()

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_S = 300


async def _sweep_loop(stop: asyncio.Event) -> None:
    """
    Barrido periódico de jobs colgados.

    Corre aquí y no dentro del worker porque es idempotente y global: con varias réplicas
    da igual cuál lo ejecute, y `FOR UPDATE SKIP LOCKED` evita que dos se pisen.
    """
    while not stop.is_set():
        try:
            if swept := await sweep_stale():
                logger.info("stale_jobs_swept", extra={"count": swept})
        except Exception:
            logger.exception("sweep_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL_S)
        except TimeoutError:
            continue


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    await init_pool()

    worker = JobWorker(registry=get_registry())
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows no soporta add_signal_handler para SIGTERM. En desarrollo local
            # basta con Ctrl+C, que llega como KeyboardInterrupt.
            pass

    logger.info(
        "worker_started",
        extra={"max_concurrent": settings.max_concurrent_jobs_per_project},
    )

    sweeper = asyncio.create_task(_sweep_loop(stop))
    try:
        await worker.run_forever()
    finally:
        stop.set()
        sweeper.cancel()
        await asyncio.gather(sweeper, return_exceptions=True)
        await close_pool()
        logger.info("worker_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
