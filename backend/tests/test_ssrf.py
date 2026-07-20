"""
Tests de la política de descarga de salidas (`app/jobs/download.py`).

Qué se comprueba y por qué precisamente esto. La descarga de la salida es el único punto
del backend donde una URL elegida por un tercero se pide desde dentro de nuestra red y el
contenido acaba publicado. Los cuatro casos de abajo son las cuatro formas conocidas de
convertir eso en una fuga:

1. URL directa a una IP no pública (169.254.169.254 y compañía).
2. URL de host legítimo que **redirige** a una IP interna: el caso del open redirect en la
   CDN del proveedor, que es el realista, porque no exige comprometer al proveedor entero.
3. Salida enorme, que no filtra nada pero tumba el worker y con él los jobs de los demás.
4. Host fuera de los dominios declarados por los adaptadores.

Cada test es de mutación por construcción: quitar la comprobación correspondiente en
`download.py` lo pone en rojo, porque lo que se afirma es que la descarga **no ocurre**,
no que devuelva un error bonito.
"""

from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")

from app.jobs.download import (  # noqa: E402
    DownloadRejected,
    OutputDownloader,
    OutputTooLarge,
    allowed_hosts_from_registry,
    is_public_ip,
)

ALLOWED = frozenset({"cdn.test", "provider.test"})


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _downloader(handler: Any, **kwargs: Any) -> OutputDownloader:
    """Descargador con transporte falso y resolutor inyectado. Sin red y sin DNS."""
    kwargs.setdefault("allowed_hosts", ALLOWED)
    kwargs.setdefault("resolver", lambda host: ["93.184.216.34"])
    return OutputDownloader(_client(handler), **kwargs)


# --------------------------------------------------------------------------- #
# Clasificación de direcciones                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918
        "192.168.1.1",
        "172.16.4.4",
        "169.254.169.254",  # metadatos de AWS/GCP: el objetivo clásico
        "0.0.0.0",
        "::1",  # loopback IPv6
        "fd00::1",  # ULA IPv6
        "fe80::1",  # link-local IPv6
        "::ffff:169.254.169.254",  # IPv4 mapeada: "global" como IPv6, mortal en la práctica
    ],
)
def test_direcciones_internas_no_son_publicas(address: str) -> None:
    assert is_public_ip(address) is False


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1"])
def test_direcciones_publicas_pasan(address: str) -> None:
    assert is_public_ip(address) is True


# --------------------------------------------------------------------------- #
# 1. IP privada                                                                #
# --------------------------------------------------------------------------- #


def test_ip_privada_directa_se_rechaza_sin_conectar() -> None:
    """
    Una URL que apunta al servicio de metadatos no se pide siquiera.

    Se comprueba que el transporte **no se llama**: rechazar después de haber hecho la
    petición ya sería tarde para un endpoint con efectos secundarios.
    """
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"secreto")

    downloader = _downloader(handler, allowed_hosts=frozenset({"169.254.169.254"}))
    with pytest.raises(DownloadRejected):
        run(downloader.fetch("http://169.254.169.254/latest/meta-data/"))
    assert calls == []


def test_host_que_resuelve_a_ip_privada_se_rechaza() -> None:
    """El DNS del atacante apunta un dominio permitido a una IP interna."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"secreto")

    downloader = _downloader(handler, resolver=lambda host: ["10.1.2.3"])
    with pytest.raises(DownloadRejected):
        run(downloader.fetch("https://cdn.test/output.mp4"))
    assert calls == []


def test_una_sola_ip_privada_entre_varias_basta_para_rechazar() -> None:
    """
    Un nombre que resuelve a una pública y a una privada se rechaza.

    Comprobar solo la primera dirección deja el ataque abierto: cuál se usa al conectar
    depende del orden que devuelva el resolutor, que es del atacante.
    """
    downloader = _downloader(
        lambda r: httpx.Response(200), resolver=lambda host: ["93.184.216.34", "127.0.0.1"]
    )
    with pytest.raises(DownloadRejected):
        run(downloader.fetch("https://cdn.test/output.mp4"))


def test_esquema_no_http_se_rechaza() -> None:
    downloader = _downloader(lambda r: httpx.Response(200))
    with pytest.raises(DownloadRejected):
        run(downloader.fetch("file:///etc/passwd"))


# --------------------------------------------------------------------------- #
# 2. Redirección a IP interna                                                  #
# --------------------------------------------------------------------------- #


def test_redirect_a_ip_interna_se_rechaza() -> None:
    """
    El caso realista: el host de la salida es legítimo y devuelve un 302 al servicio de
    metadatos. Basta un open redirect en la CDN del proveedor, sin comprometerlo a él.

    Se afirma que la segunda petición nunca sale.
    """
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.host)
        if request.url.host == "cdn.test":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200, content=b"AKIA-credenciales")

    downloader = _downloader(handler)
    with pytest.raises(DownloadRejected):
        run(downloader.fetch("https://cdn.test/output.mp4"))
    assert visited == ["cdn.test"]


def test_redirect_a_host_no_permitido_se_rechaza() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.test":
            return httpx.Response(302, headers={"location": "https://evil.example/x"})
        return httpx.Response(200, content=b"x")

    with pytest.raises(DownloadRejected):
        run(_downloader(handler).fetch("https://cdn.test/output.mp4"))


def test_redirect_valido_entre_hosts_permitidos_si_funciona() -> None:
    """
    El contrapeso: la política no puede romper el flujo normal, que es API → CDN firmada.
    Sin este test, "rechazarlo todo" pasaría los demás.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "provider.test":
            return httpx.Response(302, headers={"location": "https://cdn.test/signed.mp4"})
        return httpx.Response(200, content=b"video", headers={"content-type": "video/mp4"})

    data, content_type = run(_downloader(handler).fetch("https://provider.test/out"))
    assert data == b"video"
    assert content_type == "video/mp4"


def test_cadena_de_redirecciones_se_corta() -> None:
    """Un bucle de redirecciones no puede tener al worker dando vueltas."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://cdn.test/otra"})

    with pytest.raises(DownloadRejected):
        run(_downloader(handler).fetch("https://cdn.test/output.mp4"))


# --------------------------------------------------------------------------- #
# 3. Tope de tamaño                                                            #
# --------------------------------------------------------------------------- #


def test_exceso_de_tamano_aborta_la_descarga() -> None:
    """
    El cuerpo se corta en cuanto pasa del tope, sin acumularlo entero.

    El servidor de este test entrega en trozos y va contando: si el descargador leyera
    todo antes de mirar el tamaño, `served` acabaría siendo el fichero completo. Se
    afirma que se leyó poco, no solo que se lanzara la excepción — es la diferencia entre
    cortar la descarga y quedarse sin memoria educadamente.
    """
    served = {"chunks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        async def stream() -> Any:
            for _ in range(10_000):
                served["chunks"] += 1
                yield b"x" * 1024

        return httpx.Response(200, content=stream())

    downloader = _downloader(handler, max_bytes=4096)
    with pytest.raises(OutputTooLarge):
        run(downloader.fetch("https://cdn.test/enorme.mp4"))
    assert served["chunks"] < 100


def test_content_length_excesivo_se_rechaza_antes_de_leer() -> None:
    """Atajo barato: si el propio proveedor declara que se pasa, ni se empieza."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x" * 10, headers={"content-length": str(10 * 1024 * 1024)}
        )

    with pytest.raises(OutputTooLarge):
        run(_downloader(handler, max_bytes=4096).fetch("https://cdn.test/grande.mp4"))


def test_salida_normal_no_se_corta() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * 2048, headers={"content-type": "video/mp4"})

    data, _ = run(_downloader(handler, max_bytes=4096).fetch("https://cdn.test/ok.mp4"))
    assert len(data) == 2048


# --------------------------------------------------------------------------- #
# 4. Lista de hosts                                                            #
# --------------------------------------------------------------------------- #


def test_host_no_declarado_se_rechaza() -> None:
    with pytest.raises(DownloadRejected):
        run(_downloader(lambda r: httpx.Response(200)).fetch("https://cualquiera.test/x"))


def test_subdominio_de_host_permitido_pasa() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    data, _ = run(_downloader(handler).fetch("https://delivery-eu1.cdn.test/x"))
    assert data == b"ok"


def test_sufijo_pegado_no_cuela() -> None:
    """
    `evil-cdn.test` **no** es `cdn.test`. Es el registro que compraría un atacante si la
    coincidencia fuera por subcadena en vez de por etiqueta de dominio.
    """
    with pytest.raises(DownloadRejected):
        run(_downloader(lambda r: httpx.Response(200)).fetch("https://evilcdn.test/x"))


def test_la_lista_sale_de_los_adaptadores() -> None:
    """
    La lista no es una constante del worker: se deriva de los `output_domains` que declara
    cada adaptador. Si un adaptador deja de declararlos, sus jobs dejan de aterrizar, y
    ese acoplamiento es deliberado — es lo que evita la lista mágica desactualizada.
    """
    hosts = allowed_hosts_from_registry()
    assert "bfl.ai" in hosts
    assert "googleapis.com" in hosts
    assert "aliyuncs.com" in hosts


# --------------------------------------------------------------------------- #
# data: URIs (imágenes de OpenAI)                                              #
# --------------------------------------------------------------------------- #


def test_data_uri_sigue_funcionando() -> None:
    """
    La rama de `data:` es la que mantiene vivas las imágenes de OpenAI, que llegan en
    base64 y no por URL. Romperla mataría todo job de imagen después de haberse pagado.
    """
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    data, content_type = run(
        _downloader(lambda r: httpx.Response(200)).fetch(f"data:image/png;base64,{payload}")
    )
    assert data.startswith(b"\x89PNG")
    assert content_type == "image/png"


def test_data_uri_tambien_tiene_tope() -> None:
    """El tope se aplica antes de decodificar: decodificar ya duplicaría la memoria."""
    payload = base64.b64encode(b"z" * 8192).decode()
    with pytest.raises(OutputTooLarge):
        run(
            _downloader(lambda r: httpx.Response(200), max_bytes=1024).fetch(
                f"data:image/png;base64,{payload}"
            )
        )
