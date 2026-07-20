"""
Descarga de las salidas del proveedor, con el proveedor tratado como hostil.

Por qué existe este módulo. El worker recibe una URL **elegida por un tercero** y la
descarga desde dentro de la red del backend, sube el resultado a nuestro bucket y publica
la URL pública en el stream de la conversación. Eso es un SSRF con canal de exfiltración
completo: no solo se puede hacer que el worker toque un servicio interno, es que el
contenido de la respuesta acaba publicado y legible. Un proveedor comprometido —o
simplemente un open redirect en su CDN, que es un fallo mucho más común— convierte
`302 → http://169.254.169.254/latest/meta-data/iam/security-credentials/` en un fichero
descargable desde nuestro storage.

Cuatro defensas, en este orden, porque cada una tapa lo que la anterior no ve:

1. **Nada de seguir redirecciones a ciegas.** `follow_redirects=False` y un bucle propio
   que vuelve a validar **cada salto**. Delegar el seguimiento en httpx significa que la
   única URL que llegamos a validar es la primera, que es justo la que el atacante nos
   deja ver.

2. **Lista de hosts permitidos derivada de los adaptadores.** No es una constante de este
   módulo: cada adaptador declara sus `output_domains` (ver `providers/base.py`). Así dar
   de alta un proveedor no obliga a acordarse de tocar el worker, y cuando un proveedor
   cambia de CDN se arregla en el fichero que ya hay que abrir. `OUTPUT_HOST_ALLOWLIST`
   permite parchear en caliente si un proveedor rota su dominio un domingo.

3. **Rechazo de IPs no públicas.** Es la defensa que no depende de que la lista de arriba
   esté al día, y por eso es la principal. Se resuelve el nombre y se exige que **todas**
   las direcciones devueltas sean globales: fuera privadas (RFC1918), loopback,
   link-local (169.254.0.0/16, que es donde vive el servicio de metadatos de AWS/GCP),
   ULA IPv6 (fc00::/7), multicast y reservadas.

   El TOCTOU entre resolver y conectar es real —un DNS controlado por el atacante puede
   devolver una IP pública a nuestra comprobación y una privada a la conexión, con TTL
   0— y por eso la validación se repite **sobre el socket ya conectado**: se lee la
   dirección real del par y se vuelve a exigir que sea global, antes de leer un solo byte
   del cuerpo. Esa segunda comprobación es la que cierra el hueco; la primera solo evita
   abrir la conexión cuando ya se sabe que sobra.

4. **Tope de tamaño con lectura en streaming.** `resp.content` materializa la respuesta
   entera en memoria: un fichero de 10 GB —o un servidor que genera bytes sin fin— tumba
   el worker y con él todos los jobs que tenga en vuelo. Se lee por trozos y se aborta en
   cuanto se pasa del tope.

El fallo de cualquiera de las cuatro se propaga como excepción, el worker marca el job
`failed` y reembolsa. Se prefiere un reembolso a una descarga dudosa: el coste de un
falso positivo es un crédito devuelto, y el de un falso negativo son las credenciales de
la instancia publicadas en un bucket público.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import socket
from collections.abc import Callable, Iterable
from urllib.parse import unquote_to_bytes, urljoin, urlsplit

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 512 * 1024 * 1024
"""
Tope de una salida descargada: 512 MiB.

De dónde sale el número. El caso más pesado que este producto genera hoy es un plano de
vídeo 4K: a 12 s y ~60 Mbps (un H.264 4K generoso, muy por encima de lo que devuelven
Veo, Sora o Kling) son ~90 MB. 512 MiB deja un factor 5 de margen sobre eso, así que
ningún render legítimo lo roza, ni siquiera si un proveedor empieza a entregar ProRes o
duraciones largas.

El techo por arriba lo pone la memoria, no la generosidad: `AssetStorage.put()` recibe
`bytes`, así que la salida vive entera en RAM hasta que se sube. Con el `max_inflight`
por defecto (4 jobs), 512 MiB por job son 2 GiB en el peor caso, que es lo máximo que
admite un contenedor de worker normal. Subir esta constante sin bajar la concurrencia —o
sin pasar el storage a subida en streaming— es cambiar un fallo de descarga por un OOM,
que además se lleva por delante los jobs de los demás.
"""

MAX_REDIRECTS = 3
"""
Saltos permitidos. Los CDN legítimos usan uno (API → almacenamiento firmado); tres da
margen sin convertir el bucle en una herramienta de sondeo de red para el proveedor.
"""

CHUNK_BYTES = 64 * 1024

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


class DownloadRejected(Exception):
    """
    La descarga no se hace, y no por un fallo de red: la URL o el destino violan la
    política. Sube al `_land_output`, que cierra el job como `failed` y reembolsa.
    """


class OutputTooLarge(DownloadRejected):
    """La salida supera `MAX_OUTPUT_BYTES`. Se aborta a mitad, sin acumularla entera."""


Resolver = Callable[[str], list[str]]


def _system_resolver(host: str) -> list[str]:
    """Resolución real. Aislada en una función para poder inyectar otra en los tests."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def is_public_ip(raw: str) -> bool:
    """
    ¿Es una dirección a la que un proveedor externo puede legítimamente pedirnos que
    vayamos?

    Se apoya en `ipaddress.is_global`, que ya cubre de una vez privadas, loopback,
    link-local, ULA IPv6, multicast y los rangos reservados; enumerar redes a mano
    garantiza olvidarse de alguna (el clásico: acordarse de 127.0.0.0/8 y no de
    ::ffff:127.0.0.1).

    Los dos casos que `is_global` no resuelve solo se añaden explícitamente:
    IPv4 mapeada en IPv6 (`::ffff:169.254.169.254` sí es "global" como IPv6 pero
    conecta contra el servicio de metadatos) y las direcciones 6to4/Teredo, que
    embeben una IPv4 que hay que juzgar por separado.
    """
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False

    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or ip.teredo
        if embedded is not None:
            candidate = embedded[1] if isinstance(embedded, tuple) else embedded
            return bool(candidate.is_global)

    return bool(ip.is_global)


def allowed_hosts_from_registry(factories: Iterable[Callable[[], object]] | None = None) -> frozenset[str]:
    """
    Dominios de salida de los proveedores dados de alta, más los de `OUTPUT_HOST_ALLOWLIST`.

    Se leen de las fábricas del registry y no de una lista propia para que el conjunto no
    se pueda quedar atrás: dar de alta un adaptador ya lo mete aquí. Un adaptador cuya
    fábrica reviente (le falta una dependencia, típicamente) se salta en vez de impedir
    que arranque el worker, que es el mismo criterio que usa `_register_defaults`.
    """
    if factories is None:
        from app.providers import registry as registry_mod

        if not registry_mod._FACTORIES:
            registry_mod._register_defaults()
        factories = list(registry_mod._FACTORIES.values())

    hosts: set[str] = set()
    for factory in factories:
        try:
            domains = getattr(factory, "output_domains", None)
            if domains is None:
                domains = getattr(factory(), "output_domains", ())
        except Exception:
            logger.warning("output_domains_unavailable", extra={"factory": repr(factory)})
            continue
        hosts.update(d.lower().lstrip(".") for d in domains or () if d)

    extra = get_settings().output_host_allowlist
    hosts.update(part.strip().lower().lstrip(".") for part in extra.split(",") if part.strip())
    return frozenset(hosts)


def _host_of(url: str) -> str:
    """Host en minúsculas, sin puerto. Vacío si la URL no es parseable."""
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


class OutputDownloader:
    """
    Descargador con política. Se le inyecta el cliente HTTP para que los tests monten un
    `MockTransport`, y el resolutor para que no dependan del DNS de la máquina.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        allowed_hosts: frozenset[str] | None = None,
        max_bytes: int = MAX_OUTPUT_BYTES,
        max_redirects: int = MAX_REDIRECTS,
        resolver: Resolver | None = None,
    ) -> None:
        self._client = client
        self._allowed = allowed_hosts if allowed_hosts is not None else allowed_hosts_from_registry()
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._resolver = resolver or _system_resolver

    # -- API ---------------------------------------------------------------- #

    async def fetch(self, url: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
        """
        `(bytes, content_type)` o excepción. Nunca devuelve una descarga a medias.

        `headers` es para los proveedores cuya salida vive **dentro de su propia API** y
        exige autenticación: Sora entrega `GET /v1/videos/{id}/content`, que sin la clave
        responde 401. La regla general sigue siendo no mandar credenciales al descargar
        —la mayoría entrega en un CDN ajeno y mandárselas sería filtrarlas—, así que esto
        es una excepción que el adaptador declara explícitamente y que **solo vale para el
        primer salto**: ver el bucle de redirecciones.
        """
        if url.startswith("data:"):
            return self._from_data_uri(url)
        return await self._from_http(url, headers or {})

    # -- data: -------------------------------------------------------------- #

    def _from_data_uri(self, uri: str) -> tuple[bytes, str]:
        """
        `data:<mime>[;base64],<carga>` → `(bytes, mime)`.

        No toca la red, así que no hay SSRF que cerrar aquí, pero **sí** tiene el mismo
        problema de tamaño: la carga ya está en memoria dentro del `ProviderJobStatus` y
        decodificarla la duplica. El tope se aplica antes de decodificar, sobre el tamaño
        que tendrá el resultado (base64 infla 4/3), y no después.

        Se valida el prefijo en vez de confiar en el adaptador: un `data:` mal formado
        significaría escribir basura en el bucket y darle al usuario un asset roto por el
        que ya ha pagado. Mejor fallar y reembolsar.
        """
        if not uri.startswith("data:"):
            raise DownloadRejected("no es un data: URI")

        header, _, payload = uri[len("data:") :].partition(",")
        if not payload:
            raise DownloadRejected("data: URI sin carga")

        is_base64 = header.endswith(";base64")
        content_type = (
            header[: -len(";base64")] if is_base64 else header
        ) or "application/octet-stream"

        estimated = (len(payload) * 3) // 4 if is_base64 else len(payload)
        if estimated > self._max_bytes:
            raise OutputTooLarge(
                f"la salida en data: URI ocupa ~{estimated} bytes, por encima del tope "
                f"de {self._max_bytes}"
            )

        try:
            data = base64.b64decode(payload, validate=True) if is_base64 else unquote_to_bytes(payload)
        except Exception as exc:
            raise DownloadRejected(f"data: URI ilegible: {exc}") from exc

        if len(data) > self._max_bytes:
            raise OutputTooLarge(f"la salida ocupa {len(data)} bytes")
        return data, content_type

    # -- http --------------------------------------------------------------- #

    async def _from_http(self, url: str, headers: dict[str, str]) -> tuple[bytes, str]:
        current = url
        origin = _host_of(url)
        for _ in range(self._max_redirects + 1):
            await self._assert_url_allowed(current)

            # Las credenciales viajan **solo** mientras no se cambie de host. Un proveedor
            # comprometido —o un simple open redirect en su CDN— podría responder con un
            # 302 hacia un servidor suyo y quedarse nuestra clave de API si las cabeceras
            # siguieran al salto. Es el mismo motivo por el que los navegadores sueltan la
            # cabecera `Authorization` en una redirección cross-origin.
            send = headers if _host_of(current) == origin else {}

            # `follow_redirects=False` explícito y no solo en el constructor del cliente:
            # el cliente lo inyecta quien nos construye, y esta política no puede depender
            # de que se acuerde. El bucle de abajo es quien sigue los saltos, validando.
            async with self._client.stream(
                "GET", current, follow_redirects=False, headers=send or None
            ) as response:
                self._assert_peer_allowed(response, current)

                if response.status_code in _REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadRejected(
                            f"redirección {response.status_code} sin cabecera Location"
                        )
                    current = urljoin(current, location)
                    logger.info("output_redirect", extra={"to": current})
                    continue

                if response.status_code >= 400:
                    raise DownloadRejected(
                        f"el proveedor devolvió HTTP {response.status_code} al descargar la salida"
                    )

                return await self._read_capped(response)

        raise DownloadRejected(f"más de {self._max_redirects} redirecciones descargando la salida")

    async def _read_capped(self, response: httpx.Response) -> tuple[bytes, str]:
        """
        Lee el cuerpo por trozos, abortando en cuanto se pasa del tope.

        `Content-Length` se mira primero solo como atajo para no empezar una descarga que
        ya se sabe que sobra. No se confía en él: es una cabecera del atacante y puede
        mentir o faltar, así que el tope real lo pone el contador de bytes leídos.
        """
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_bytes:
            raise OutputTooLarge(
                f"el proveedor declara {declared} bytes, por encima del tope de {self._max_bytes}"
            )

        buffer = bytearray()
        async for chunk in response.aiter_bytes(CHUNK_BYTES):
            buffer.extend(chunk)
            if len(buffer) > self._max_bytes:
                raise OutputTooLarge(
                    f"la salida supera el tope de {self._max_bytes} bytes; descarga abortada"
                )

        content_type = response.headers.get("content-type", "application/octet-stream")
        return bytes(buffer), content_type

    # -- política ------------------------------------------------------------ #

    async def _assert_url_allowed(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise DownloadRejected(f"esquema no permitido en la salida: '{parts.scheme}'")

        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise DownloadRejected("URL de salida sin host")

        if not self._host_allowed(host):
            raise DownloadRejected(
                f"'{host}' no está entre los dominios de salida declarados por los "
                f"adaptadores; si el proveedor ha cambiado de CDN, decláralo en su "
                f"`output_domains` o añádelo a OUTPUT_HOST_ALLOWLIST"
            )

        # Una IP literal en la URL no pasa por el DNS: se valida tal cual.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not is_public_ip(host):
                raise DownloadRejected(f"la salida apunta a una IP no pública: {host}")
            return

        addresses = await self._resolve(host)
        if not addresses:
            raise DownloadRejected(f"'{host}' no resuelve a ninguna dirección")
        for address in addresses:
            if not is_public_ip(address):
                raise DownloadRejected(
                    f"'{host}' resuelve a {address}, que no es una dirección pública"
                )

    def _host_allowed(self, host: str) -> bool:
        """Coincidencia por sufijo de dominio, nunca por subcadena.

        `endswith('.' + dominio)` y no `endswith(dominio)`: lo segundo aceptaría
        `evil-bfl.ai` como si fuera de BFL, que es el registro que compraría un atacante.
        """
        return any(host == d or host.endswith("." + d) for d in self._allowed)

    async def _resolve(self, host: str) -> list[str]:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, self._resolver, host)
        except Exception as exc:
            raise DownloadRejected(f"no se pudo resolver '{host}': {exc}") from exc

    def _assert_peer_allowed(self, response: httpx.Response, url: str) -> None:
        """
        Cierre del TOCTOU: se comprueba la dirección **con la que se ha conectado de
        verdad**, no la que dijo el DNS hace un instante.

        Sin esto, un dominio con TTL 0 que alterna entre una IP pública y 169.254.169.254
        pasa la validación previa y conecta contra el servicio de metadatos: es el ataque
        de rebinding, y es la razón por la que validar solo antes de conectar no vale.

        Si el transporte no expone el socket (`MockTransport` en los tests, o un proxy)
        no se puede comprobar y se sigue: en ese caso la garantía la da la validación
        previa. Es una degradación consciente y acotada, no un `except: pass`.
        """
        stream = response.extensions.get("network_stream")
        if stream is None:
            return
        try:
            peer = stream.get_extra_info("server_addr")
            if peer is None:
                sock = stream.get_extra_info("socket")
                peer = sock.getpeername() if sock is not None else None
        except Exception:
            return
        if not peer:
            return

        address = peer[0] if isinstance(peer, (tuple, list)) else str(peer)
        if not is_public_ip(str(address)):
            raise DownloadRejected(
                f"la conexión a {url} terminó en {address}, que no es una dirección "
                f"pública (posible DNS rebinding)"
            )
