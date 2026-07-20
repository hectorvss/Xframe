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

    `False` en Windows por lo anterior. Lo consulta el montaje para decidir entre
    `asyncio.create_subprocess_exec` y un `subprocess.run` en un hilo.
    """
    return sys.platform != "win32"
