"""
Ajustes del entorno de ejecución que hay que hacer **antes** de crear el bucle de asyncio.

Existe por un choque real entre dos dependencias en Windows, que no se ve en Linux y que
por tanto no aparece en CI:

- `psycopg` (el driver del checkpointer de LangGraph) **no funciona** sobre
  `ProactorEventLoop`, que es el bucle por defecto de Windows. Falla con
  `InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode`.
- `SelectorEventLoop`, que es la alternativa, **no soporta subprocesos** en Windows. Y el
  montaje final lanza `ffmpeg` como subproceso.

Es decir: en Windows no hay un bucle que sirva para las dos cosas a la vez. La salida es
elegir Selector —sin él no hay agente, porque no hay checkpointer— y ejecutar `ffmpeg` de
forma bloqueante en un hilo aparte en vez de con `asyncio.create_subprocess_exec`. Ver
`app/assembly/ffmpeg.py`.

En Linux y macOS esta función no hace nada: allí el bucle por defecto sirve para ambas.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence


def configure_event_loop() -> None:
    """
    Fija la política de bucle antes de que nadie cree uno.

    Hay que llamarla en cada entrypoint (API, worker, scripts) y **a nivel de módulo**,
    no dentro de una corrutina: cuando el bucle ya existe, cambiar la política no tiene
    ningún efecto y el fallo reaparece sin explicación aparente.
    """
    if sys.platform != "win32":
        return

    policy = asyncio.get_event_loop_policy()
    if isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy):  # type: ignore[attr-defined]
        return

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


def supports_asyncio_subprocess() -> bool:
    """
    ¿Puede este bucle lanzar subprocesos?

    `False` en Windows por lo anterior. Lo consulta `run_process` para decidir entre
    `asyncio.create_subprocess_exec` y un `subprocess.run` en un hilo.
    """
    return sys.platform != "win32"


async def run_process(
    args: Sequence[str], *, timeout_s: float, capture_stdout: bool = False
) -> tuple[int, bytes, bytes]:
    """
    Ejecuta un binario externo y devuelve `(returncode, stdout, stderr)`.

    Existe porque en Windows el bucle que necesita `psycopg` —Selector— **no implementa
    subprocesos**: `create_subprocess_exec` lanza `NotImplementedError` a secas, sin
    mensaje, y el montaje muere sin decir por qué. Ahí se cae a `subprocess.run` dentro de
    un hilo, que bloquea ese hilo pero no el bucle.

    En Linux —producción, y el Docker de desarrollo— se usa el camino asíncrono normal,
    que es el bueno: no consume un hilo por render.

    El timeout mata el proceso en ambos caminos. Un `ffmpeg` colgado con el fichero de
    salida a medias es peor que un error: el asset existiría, corrupto.
    """
    if supports_asyncio_subprocess():
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE if capture_stdout else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return proc.returncode or 0, stdout or b"", stderr or b""

    def _blocking() -> tuple[int, bytes, bytes]:
        import subprocess

        completed = subprocess.run(  # noqa: S603
            list(args),
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
        return completed.returncode, completed.stdout or b"", completed.stderr or b""

    import subprocess as _sp

    try:
        return await asyncio.to_thread(_blocking)
    except _sp.TimeoutExpired as exc:
        # Se normaliza al mismo tipo que levanta el camino asíncrono para que los
        # llamantes tengan un solo `except` y no dos según la plataforma.
        raise TimeoutError(str(exc)) from exc
