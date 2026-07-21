"""
Arranque de la API.

Existe porque `uvicorn app.main:app` **no funciona en Windows**, y el motivo no es
evidente: uvicorn instala su propio bucle de eventos al arrancar y en Windows elige
`ProactorEventLoop`, que es exactamente el que `psycopg` no soporta. Da igual que
`app/main.py` fije la política al importarse — uvicorn la pisa después, y el proceso
muere en el `lifespan` con `InterfaceError: Psycopg cannot use the 'ProactorEventLoop'`.

La salida es `loop="none"`: le dice a uvicorn que no toque la política y use el bucle que
ya hay, que es el que `configure_event_loop()` dejó puesto.

En Linux esto es equivalente a llamar a uvicorn directamente, así que el Dockerfile puede
usar cualquiera de las dos formas. Se deja este entrypoint como el camino único para que
no haya un comando que funciona en el contenedor y falla en la máquina de quien desarrolla.

    python run_api.py [--port 8000] [--reload]
"""

from __future__ import annotations

import argparse

from app.runtime import configure_event_loop

# Antes de importar uvicorn y antes de que nadie cree un bucle.
configure_event_loop()

import uvicorn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="API de Xframe")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        # La API sÃ³lo se publica tras Caddy. Confiar en sus cabeceras conserva
        # HTTPS en las redirecciones automÃ¡ticas de mounts como /mcp -> /mcp/.
        proxy_headers=True,
        forwarded_allow_ips="*",
        # Lo importante de todo este fichero. Sin esto, uvicorn instala Proactor en
        # Windows y el checkpointer no puede abrir una sola conexión.
        loop="none",
    )


if __name__ == "__main__":
    main()
