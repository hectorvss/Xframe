"""
URLs firmadas del bucket de assets.

Hoy el bucket es `public = true` y el backend guarda en la BD la URL pública cruda. Eso
significa que **cualquiera con el uuid de un asset ve el material del proyecto**, sin
sesión: los uuids se filtran en logs, en el `Referer` y en los payloads que mandamos a
los proveedores.

El bucket tiene que ser privado, pero volverlo privado a secas rompe el núcleo del
producto: la continuidad de personaje pasa `ElementRef.image_url` —la URL cruda del
asset— al proveedor, y el proveedor la descarga desde su infraestructura sin ninguna
credencial nuestra. Con el bucket privado, esa descarga devuelve 400 y el personaje
deja de parecerse a sí mismo.

La pieza que falta es ésta: firmar la URL en el momento de construir el payload del
proveedor, con un TTL que cubra el job entero. Se guarda en BD la **ruta del objeto**,
no una URL; la URL se deriva y caduca.

Sobre el TTL: `SIGNED_URL_TTL_S` por defecto es 4x `job_timeout_s`. El proveedor no
descarga en el instante en que recibe el payload — encola, y en hora punta un vídeo
puede tardar. Una URL que caduca a mitad de cola produce un fallo caro (se paga el
submit y no sale nada) e intermitente, que es la peor combinación para depurar.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """No se pudo firmar. Quien llama decide si degrada o aborta."""


def object_path(url_or_path: str) -> str:
    """
    Normaliza a ruta dentro del bucket.

    Acepta lo que hay escrito en BD hoy —URLs públicas completas— y también rutas
    limpias, para que la migración de los datos existentes no tenga que ser atómica.
    """
    value = (url_or_path or "").strip()
    if not value:
        raise StorageError("ruta vacía")
    bucket = get_settings().storage_bucket
    for marker in (f"/storage/v1/object/public/{bucket}/", f"/storage/v1/object/{bucket}/"):
        if marker in value:
            return value.split(marker, 1)[1]
    if "://" in value:
        raise StorageError("la URL no pertenece al bucket de assets")

    # Ruta absoluta del sitio (`/assets/scene-3.webp`): son los ficheros estáticos que
    # sirve Vite desde `public/`, no objetos del bucket. En la BD quedan filas así del
    # prototipo. Antes se les quitaba la barra y se firmaban como si fueran del bucket:
    # la firma "funcionaba", la descarga daba 404, y si la fila se usaba como referencia
    # de personaje el síntoma era un plano generado sin la cara correcta — un fallo que
    # no se diagnostica nunca. Las rutas reales del worker son `{project_id}/{job_id}/…`,
    # relativas y con dos segmentos, así que la barra inicial las distingue sin ambigüedad.
    if value.startswith("/"):
        raise StorageError(
            f"'{value}' es un fichero estático del frontend, no un objeto del bucket. "
            f"No se puede usar como referencia para un proveedor de generación."
        )

    return value


class SignedUrls:
    """
    Firma rutas del bucket con la clave de servicio.

    Una instancia por proceso: cada firma es una petición HTTP a Supabase y crear un
    cliente por llamada agotaría los descriptores en un fan-out de doce planos.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._base = settings.supabase_url.rstrip("/")
        self._bucket = settings.storage_bucket
        self._key = settings.supabase_service_key
        self._default_ttl = settings.signed_url_ttl_s
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def sign(self, url_or_path: str, *, ttl_s: int | None = None) -> str:
        path = object_path(url_or_path)
        ttl = ttl_s or self._default_ttl
        resp = await self._client.post(
            f"{self._base}/storage/v1/object/sign/{self._bucket}/{quote(path)}",
            json={"expiresIn": ttl},
            headers={"authorization": f"Bearer {self._key}"},
        )
        if resp.status_code >= 400:
            # Sin el cuerpo del error: puede llevar la ruta completa y ésta acaba en
            # mensajes que ve el usuario.
            logger.warning("sign_failed", extra={"status": resp.status_code, "path": path})
            raise StorageError("no se pudo firmar el asset")
        signed = resp.json().get("signedURL") or resp.json().get("signedUrl")
        if not signed:
            raise StorageError("respuesta de firma sin URL")
        return f"{self._base}/storage/v1{signed}" if signed.startswith("/") else signed

    async def sign_many(self, paths: list[str], *, ttl_s: int | None = None) -> dict[str, str]:
        """
        Firma en lote. Una ruta que falla se omite del resultado en vez de tumbar el
        lote entero: en un fan-out, once referencias buenas valen más que cero.
        """
        out: dict[str, str] = {}
        for p in paths:
            try:
                out[p] = await self.sign(p, ttl_s=ttl_s)
            except StorageError:
                continue
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


async def sign_reference(url_or_path: str | None, *, ttl_s: int | None = None) -> str | None:
    """
    Firma una referencia visual **si es nuestra**, y la deja intacta si no lo es.

    Existe porque los campos que llevan referencias (`init_image_url`, `last_frame_url`,
    `ElementRef.image_url`) no siempre apuntan al bucket: el agente puede pasar una URL
    externa, y un adaptador puede recibir un `data:` URI. Firmar a ciegas rompería esos
    casos; no firmar ninguno rompería la continuidad de personaje. La discriminación la
    hace `object_path`, que lanza `StorageError` sobre cualquier cosa que no viva en
    nuestro bucket.

    Un fallo de firma tampoco aborta: se devuelve el valor original. Puede que el
    proveedor no llegue a descargarlo, pero eso es un plano peor, no un job perdido —y el
    adaptador ya traduce ese caso a un error legible en `fetch_image_inline`.
    """
    if not url_or_path:
        return url_or_path
    if url_or_path.startswith("data:"):
        return url_or_path
    try:
        return await get_signer().sign(url_or_path, ttl_s=ttl_s)
    except StorageError:
        return url_or_path


async def sign_request_references(request: Any, *, ttl_s: int | None = None) -> Any:
    """
    Devuelve una COPIA de la `GenerationRequest` con sus referencias firmadas.

    Copia y no mutación, y esto no es higiene: el original es lo que está escrito en
    `generation_jobs.request` y lo que se rehidrata en cada reintento. Si se mutara, una
    URL firmada acabaría propagándose a la columna en la siguiente escritura y el proyecto
    tendría imágenes rotas a los días — exactamente lo que este diseño evita.

    Se firma todo lo que un proveedor vaya a descargar: los elements (continuidad de
    personaje), el primer y el último frame, y el `audio_url` del lipsync, que viaja en
    `extra` porque no es vocabulario común.
    """
    from dataclasses import replace

    elements = [
        replace(e, image_url=await sign_reference(e.image_url, ttl_s=ttl_s) or "")
        for e in request.elements
    ]
    extra = dict(request.extra or {})
    if extra.get("audio_url"):
        extra["audio_url"] = await sign_reference(extra["audio_url"], ttl_s=ttl_s)
    if isinstance(extra.get("segments"), list):
        signed_segments: list[Any] = []
        for segment in extra["segments"]:
            if not isinstance(segment, dict):
                signed_segments.append(segment)
                continue
            signed_segment = dict(segment)
            if signed_segment.get("audio_url"):
                signed_segment["audio_url"] = await sign_reference(
                    signed_segment["audio_url"], ttl_s=ttl_s
                )
            signed_segments.append(signed_segment)
        extra["segments"] = signed_segments

    return replace(
        request,
        elements=elements,
        init_image_url=await sign_reference(request.init_image_url, ttl_s=ttl_s),
        last_frame_url=await sign_reference(request.last_frame_url, ttl_s=ttl_s),
        extra=extra,
    )


_signer: SignedUrls | None = None


def get_signer() -> SignedUrls:
    global _signer
    if _signer is None:
        _signer = SignedUrls()
    return _signer


def set_signer(signer: SignedUrls | None) -> None:
    """Inyección para los tests."""
    global _signer
    _signer = signer
