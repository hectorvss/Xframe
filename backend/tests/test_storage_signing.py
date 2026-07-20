"""
El circuito de URLs firmadas, con el bucket privado.

Estos tests protegen una propiedad que no se ve en ningún error: si la firma se hace en
el sitio equivocado, todo sigue "funcionando" durante días y luego los personajes dejan
de parecerse a sí mismos, o los proyectos amanecen con las imágenes rotas. No hay
excepción, no hay log, no hay test unitario convencional que lo note. Por eso lo que se
comprueba aquí no es que la firma exista, sino DÓNDE ocurre y DÓNDE no:

1. Se firma con el TTL que cubre la cola del proveedor, no con uno cualquiera.
2. No se persiste ninguna URL firmada: ni en `assets.url` ni en `generation_jobs.request`.
3. Un `ElementRef` llega al adaptador con una URL utilizable — que es la propiedad de
   producto: la continuidad de personaje.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("SUPABASE_URL", "https://proyecto.supabase.co")
os.environ.setdefault("STORAGE_BUCKET", "assets")

from app import storage  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.providers.base import (  # noqa: E402
    ElementRef,
    GenerationRequest,
    ProviderJobRef,
    ProviderJobStatus,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Firmador falso                                                               #
# --------------------------------------------------------------------------- #


class FakeSigner:
    """
    Registra cada firma con su TTL. No habla con Supabase.

    Devuelve una URL con un `token` distinto en cada llamada a propósito: es lo que hace
    detectable que alguien esté cacheando o persistiendo el resultado.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []
        self._n = 0

    async def sign(self, url_or_path: str, *, ttl_s: int | None = None) -> str:
        path = storage.object_path(url_or_path)  # rechaza lo que no es del bucket
        self.calls.append((path, ttl_s))
        self._n += 1
        return f"https://proyecto.supabase.co/storage/v1/object/sign/assets/{path}?token=t{self._n}"


@pytest.fixture
def signer() -> Any:
    fake = FakeSigner()
    storage.set_signer(fake)  # type: ignore[arg-type]
    yield fake
    storage.set_signer(None)


# --------------------------------------------------------------------------- #
# 1. Normalización a ruta                                                      #
# --------------------------------------------------------------------------- #


def test_object_path_acepta_las_dos_formas_que_conviven_durante_la_migracion() -> None:
    """
    Durante el despliegue habrá filas con URL pública y filas con ruta a la vez. Si
    `object_path` no aceptase las dos, el orden de despliegue tendría que ser atómico —y
    no existe forma de desplegar backend, frontend y migración en el mismo instante.
    """
    ruta = "proyecto-1/job-9/output.mp4"
    publica = f"https://proyecto.supabase.co/storage/v1/object/public/assets/{ruta}"
    privada = f"https://proyecto.supabase.co/storage/v1/object/assets/{ruta}"

    assert storage.object_path(ruta) == ruta
    assert storage.object_path(publica) == ruta
    assert storage.object_path(privada) == ruta


def test_una_url_ajena_no_se_confunde_con_una_ruta() -> None:
    """Tratar `https://otro.com/x.png` como ruta produciría una firma sobre un objeto
    inexistente, y el proveedor recibiría un 404 en vez de la imagen de referencia."""
    with pytest.raises(storage.StorageError):
        storage.object_path("https://otro.com/x.png")


def test_una_referencia_externa_pasa_intacta_en_vez_de_romperse(signer: FakeSigner) -> None:
    """
    Firmar es un intento, no un requisito. Una referencia que no vive en nuestro bucket se
    devuelve tal cual: puede que el proveedor la descargue perfectamente, y romperla sería
    perder un plano por celo.
    """
    externa = "https://otro.com/referencia.png"
    assert run(storage.sign_reference(externa)) == externa
    assert signer.calls == []


# --------------------------------------------------------------------------- #
# 2. El TTL es el que cubre la cola del proveedor                              #
# --------------------------------------------------------------------------- #


def test_el_ttl_del_proveedor_cubre_el_timeout_del_job_con_margen() -> None:
    """
    El fallo que este número evita: firmar con menos vida que `job_timeout_s` significa
    que un trabajo que espera en la cola del proveedor puede ver caducar su referencia
    antes de descargarla. Se paga el submit y sale un plano sin el personaje.
    """
    settings = get_settings()
    assert settings.provider_signed_url_ttl_s >= 4 * settings.job_timeout_s
    assert settings.provider_signed_url_ttl_s >= settings.signed_url_ttl_s


def test_el_worker_firma_con_ese_ttl_y_no_con_otro(signer: FakeSigner) -> None:
    """
    Comprueba el valor real que llega al firmador, no la constante. Que exista una
    constante correcta y que el worker use otra cosa es exactamente el tipo de desajuste
    que nadie ve hasta que un proveedor va lento.
    """
    req = GenerationRequest(
        modality="video",
        model_id="m",
        prompt="p",
        elements=[ElementRef(element_id="e1", name="Marta", role="character", image_url="p1/a.png")],
    )
    run(storage.sign_request_references(req, ttl_s=get_settings().provider_signed_url_ttl_s))

    assert signer.calls, "no se firmó ninguna referencia"
    assert {ttl for _, ttl in signer.calls} == {get_settings().provider_signed_url_ttl_s}


# --------------------------------------------------------------------------- #
# 3. Ninguna URL firmada se persiste                                           #
# --------------------------------------------------------------------------- #


def test_la_peticion_original_no_se_muta_al_firmar(signer: FakeSigner) -> None:
    """
    La propiedad de la que depende todo: `generation_jobs.request` guarda la petición
    original. Si `sign_request_references` mutase en vez de copiar, la ruta estable se
    convertiría en una URL con caducidad dentro de la fila, y el primer reintento de
    mañana saldría con una referencia muerta.

    Además, la clave de idempotencia se calcula sobre esta misma estructura: una URL
    firmada dentro haría que dos tool calls idénticas dejasen de colisionar y el usuario
    pagaría dos veces el mismo plano.
    """
    original = GenerationRequest(
        modality="video",
        model_id="m",
        prompt="p",
        init_image_url="p1/first.png",
        elements=[ElementRef(element_id="e1", name="Marta", role="character", image_url="p1/a.png")],
    )
    antes = asdict(original)

    firmada = run(storage.sign_request_references(original, ttl_s=3600))

    assert asdict(original) == antes, "sign_request_references mutó la petición original"
    assert firmada is not original
    assert "token=" in firmada.elements[0].image_url
    assert "token=" not in original.elements[0].image_url


def test_la_clave_de_idempotencia_no_cambia_entre_dos_firmas(signer: FakeSigner) -> None:
    """
    La misma petición encolada dos veces tiene que dar la misma clave. Es la única
    defensa contra cobrar dos veces al usuario que pulsa dos veces, y se pierde en el
    momento en que una URL con `token` variable entra en la petición persistida.
    """
    from app.jobs.queue import compute_idempotency_key

    def build() -> GenerationRequest:
        return GenerationRequest(
            modality="video",
            model_id="m",
            prompt="p",
            elements=[
                ElementRef(element_id="e1", name="Marta", role="character", image_url="p1/a.png")
            ],
        )

    project = str(uuid4())
    a, b = build(), build()
    run(storage.sign_request_references(a, ttl_s=3600))
    run(storage.sign_request_references(b, ttl_s=3600))

    assert compute_idempotency_key(a, provider="x", project_id=project) == compute_idempotency_key(
        b, provider="x", project_id=project
    )


def test_el_storage_del_worker_devuelve_una_ruta_no_una_url() -> None:
    """
    Lo que `put()` devuelve es lo que acaba escrito en `assets.url`. Si devolviera una
    URL firmada, la fila caducaría; si devolviera una pública, el bucket no podría
    cerrarse. Tiene que ser la ruta, y la ruta tiene que ser la que las políticas de
    storage esperan: `{project_id}/{job_id}/{fichero}`.
    """
    import httpx

    from app.jobs.worker import SupabaseStorage

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = run(
        SupabaseStorage(client).put(
            project_id="proj-1",
            job_id="job-2",
            filename="output.mp4",
            data=b"x",
            content_type="video/mp4",
        )
    )

    assert result == "proj-1/job-2/output.mp4"
    assert "://" not in result
    assert "token=" not in result


def test_la_taxonomia_entrega_rutas_y_no_urls() -> None:
    """
    `builder._reference_path` es el punto donde la URL pública de la base de datos se
    convierte en ruta. Firmar aquí sería firmar dentro de una caché con TTL
    (`PROJECT_TTL_S`), y la URL caducaría sin que nadie volviese a pedirla.
    """
    from app.taxonomy.builder import _reference_path

    publica = "https://proyecto.supabase.co/storage/v1/object/public/assets/p1/j2/out.png"
    assert _reference_path(publica) == "p1/j2/out.png"
    assert _reference_path("p1/j2/out.png") == "p1/j2/out.png"
    assert _reference_path(None) == ""


# --------------------------------------------------------------------------- #
# 4. El ElementRef llega utilizable al adaptador                               #
# --------------------------------------------------------------------------- #


def test_el_adaptador_recibe_el_element_con_una_url_descargable(signer: FakeSigner) -> None:
    """
    El test de producto: la continuidad de personaje.

    Recorre el camino entero —lo que la taxonomía pone en el `ElementRef`, lo que la cola
    persiste, lo que el worker firma— y comprueba lo único que le importa al usuario: que
    lo que el adaptador va a meter en el payload del proveedor es descargable. Si esto
    falla, el síntoma en producción es "sale con otra cara", que es indiagnosticable.
    """
    from app.jobs.worker import _deserialize
    from app.taxonomy.builder import _reference_path

    # 1. Taxonomía: la fila de `assets` (aún con URL pública, pre-migración).
    fila = "https://proyecto.supabase.co/storage/v1/object/public/assets/p1/j2/marta.png"
    ref = ElementRef(
        element_id="e1", name="Marta", role="character", image_url=_reference_path(fila)
    )
    req = GenerationRequest(modality="video", model_id="m", prompt="p", elements=[ref])

    # 2. Cola: se serializa a jsonb y se rehidrata en otro proceso.
    persistido = asdict(req)
    assert "token=" not in str(persistido), "se persistió una URL firmada"
    rehidratado = _deserialize(persistido)

    # 3. Worker: firma justo antes del submit.
    enviado = run(
        storage.sign_request_references(
            rehidratado, ttl_s=get_settings().provider_signed_url_ttl_s
        )
    )

    # 4. Lo que ve el adaptador.
    url = enviado.elements[0].image_url
    assert url.startswith("https://")
    assert "/object/sign/assets/p1/j2/marta.png" in url
    assert "token=" in url


def test_todas_las_referencias_del_payload_se_firman_no_solo_los_elements(
    signer: FakeSigner,
) -> None:
    """
    Los adaptadores descargan más cosas que los elements: `init_image_url` (i2v),
    `last_frame_url` (interpolación) y el `audio_url` del lipsync, que viaja en `extra`
    porque no es vocabulario común. Olvidar cualquiera de los tres rompe una modalidad
    entera y solo esa, que es un fallo que tarda semanas en aparecer.
    """
    req = GenerationRequest(
        modality="video",
        model_id="m",
        prompt="p",
        init_image_url="p1/first.png",
        last_frame_url="p1/last.png",
        elements=[ElementRef(element_id="e1", name="M", role="character", image_url="p1/a.png")],
        extra={"audio_url": "p1/voz.mp3", "source_asset_id": "no-es-una-ruta"},
    )
    firmada = run(storage.sign_request_references(req, ttl_s=3600))

    assert {p for p, _ in signer.calls} == {"p1/first.png", "p1/last.png", "p1/a.png", "p1/voz.mp3"}
    assert "token=" in firmada.extra["audio_url"]
    # Un campo de `extra` que no es una referencia no se toca.
    assert firmada.extra["source_asset_id"] == "no-es-una-ruta"


def test_un_data_uri_no_se_intenta_firmar(signer: FakeSigner) -> None:
    """Algunos adaptadores entregan la referencia inline. Firmar un `data:` daría un
    error de storage y perdería el job por una referencia que ya era utilizable."""
    uri = "data:image/png;base64,AAAA"
    assert run(storage.sign_reference(uri)) == uri
    assert signer.calls == []


def test_si_la_firma_falla_el_job_no_se_pierde() -> None:
    """
    Degradación, no aborto. Una referencia sin firmar puede dar un plano peor; un job
    abortado da un plano que no existe y un usuario esperando. El adaptador ya traduce la
    descarga fallida a un error legible (`fetch_image_inline`).
    """

    class Roto:
        async def sign(self, url_or_path: str, *, ttl_s: int | None = None) -> str:
            raise storage.StorageError("caído")

    storage.set_signer(Roto())  # type: ignore[arg-type]
    try:
        req = GenerationRequest(
            modality="video",
            model_id="m",
            prompt="p",
            elements=[ElementRef(element_id="e", name="M", role="character", image_url="p1/a.png")],
        )
        firmada = run(storage.sign_request_references(req, ttl_s=3600))
        assert firmada.elements[0].image_url == "p1/a.png"
    finally:
        storage.set_signer(None)


# --------------------------------------------------------------------------- #
# 5. El evento no contamina la base de datos                                   #
# --------------------------------------------------------------------------- #


def test_el_evento_asset_ready_separa_ruta_de_url() -> None:
    """
    El evento lleva las dos: `path` para persistir y `url` firmada para pintar ya. La
    separación tiene que ser explícita, porque el frontend guarda lo que recibe y un
    único campo ambiguo acabaría con una URL caducable dentro de `assets.url`.
    """
    import inspect

    from app.jobs import worker

    fuente = inspect.getsource(worker.JobWorker._land_output)
    assert '"path": object_path' in fuente
    assert '"url": await sign_reference(object_path)' in fuente
