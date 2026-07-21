"""
Configuración común a toda la suite.

Solo hace una cosa, pero hay que hacerla aquí y no en un fixture: fijar la política de
bucle de asyncio **antes** de que pytest-asyncio cree el suyo.

En Windows, `psycopg` —el driver del checkpointer de LangGraph— no funciona sobre el
`ProactorEventLoop`, que es el bucle por defecto. Sin esto, cualquier test que toque el
checkpointer falla con `InterfaceError: Psycopg cannot use the 'ProactorEventLoop'`, y el
mensaje no menciona ni a pytest ni a la configuración, así que cuesta relacionarlo.

Un fixture llega tarde: cuando se ejecuta, el bucle ya existe y cambiar la política no
tiene ningún efecto. Por eso va a nivel de módulo, en el conftest raíz, que es lo primero
que pytest importa.

El razonamiento completo —y el precio que se paga en `ffmpeg`, que en Windows no puede
lanzarse como subproceso asíncrono con este bucle— está en `app/runtime.py`.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.runtime import configure_event_loop

configure_event_loop()


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Cada test empieza con su entorno, no con la configuración de otro módulo."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
