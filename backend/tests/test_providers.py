"""
Tests de la capa de proveedores.

Se prueba con `httpx.MockTransport` y no con respx porque lo que hay que verificar no
es "se llamó a esta URL", sino **la traducción en los dos sentidos**: que un
`GenerationRequest` nuestro sale en el dialecto correcto, y que una respuesta del
proveedor vuelve como el `ProviderJobStatus` correcto. Eso exige inspeccionar el cuerpo
enviado y construir respuestas realistas, que es justo lo que un transporte falso hace
cómodo y un mock de URLs no.

Las propiedades elegidas son las que cuestan dinero o corrompen datos si fallan:

1. **`nsfw` no es `failed`.** Son estados distintos porque uno se reembolsa y el otro
   no. Colapsarlos pierde créditos del usuario en silencio, y ningún test de "el submit
   funciona" lo detectaría.
2. **Los 4xx no se reintentan.** Reintentar un prompt moderado tres veces triplica el
   gasto sin cambiar el resultado.
3. **Los 5xx sí se reintentan.** El caso contrario: no hacerlo pierde jobs válidos.
4. **La `polling_url` del proveedor se usa literal.** BFL y Google devuelven URLs
   regionales; reconstruirlas a partir del id funciona en desarrollo y falla en la
   región del cliente.
5. **Todos los adaptadores cumplen el contrato.** Es lo que permite añadir el noveno
   proveedor sin releer los ocho anteriores.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import sys
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Igual que en test_jobs: la config se lee del entorno al importar. Las claves son
# ficticias pero deben existir, porque `_require` falla explícitamente si están vacías
# y ese camino se prueba aparte.
os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
for _var in (
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "KLING_ACCESS_KEY",
    "KLING_SECRET_KEY",
    "MINIMAX_API_KEY",
    "BYTEDANCE_API_KEY",
    "WAN_API_KEY",
    "HIGGSFIELD_KEY_ID",
    "HIGGSFIELD_KEY_SECRET",
    "BFL_API_KEY",
    "ELEVENLABS_API_KEY",
    "SYNC_API_KEY",
):
    os.environ.setdefault(_var, f"test-{_var.lower()}")

from app.providers import _http  # noqa: E402
from app.providers._http import RetryPolicy  # noqa: E402
from app.providers.base import (  # noqa: E402
    ElementRef,
    GenerationAdapter,
    GenerationRequest,
    ModelSpec,
    ProviderJobRef,
)
from app.providers.elevenlabs import ElevenLabsAdapter  # noqa: E402
from app.providers.flux import FluxAdapter  # noqa: E402
from app.providers.hailuo import HailuoAdapter  # noqa: E402
from app.providers.higgsfield import HiggsfieldAdapter  # noqa: E402
from app.providers.kling import KlingAdapter  # noqa: E402
from app.providers.openai_image import OpenAIImageAdapter  # noqa: E402
from app.providers.registry import DbAdapterRegistry, UnknownProviderError  # noqa: E402
from app.providers.seed import MODELS, MOTIONS, STYLES, credits_per_unit  # noqa: E402
from app.providers.seedance import SeedanceAdapter  # noqa: E402
from app.providers.sora import SoraAdapter  # noqa: E402
from app.providers.sync_labs import SyncLabsAdapter  # noqa: E402
from app.providers.veo import VeoAdapter  # noqa: E402
from app.providers.wan import WanAdapter  # noqa: E402
from app.tools.errors import (  # noqa: E402
    ProviderError,
    ProviderRejectedError,
    XframeToolFatalError,
)

ALL_ADAPTERS: tuple[type[GenerationAdapter], ...] = (
    VeoAdapter,
    SoraAdapter,
    KlingAdapter,
    HailuoAdapter,
    SeedanceAdapter,
    WanAdapter,
    HiggsfieldAdapter,
    FluxAdapter,
    OpenAIImageAdapter,
    ElevenLabsAdapter,
    SyncLabsAdapter,
)


def run(coro: Any) -> Any:
    """Mismo criterio que test_jobs: bucle explícito, sin plugin de asyncio."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Utilidades                                                                   #
# --------------------------------------------------------------------------- #


class Recorder:
    """
    Transporte falso que además guarda lo enviado.

    Guardar la petición es el punto: casi todos los bugs de esta capa son de traducción
    de salida (un campo con el nombre equivocado), y esos no se ven mirando la respuesta.
    """

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content or b"{}")


def client_for(recorder: Recorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(recorder))


def make_adapter(cls: type[Any], recorder: Recorder) -> Any:
    adapter = cls(client=client_for(recorder))
    # Los tests no deben pagar el ritmo real del proveedor; lo que se comprueba es que
    # el gate existe y ordena, no su constante.
    adapter.min_poll_interval_s = 0.02
    adapter.retry_policy = RetryPolicy(max_attempts=4, base_delay_s=0.001, max_delay_s=0.01)
    return adapter


def spec(model_id: str, **overrides: Any) -> ModelSpec:
    base: dict[str, Any] = {
        "id": model_id,
        "family": "test",
        "provider": "test",
        "modality": "video",
        "cost_per_second": Decimal("0.10"),
        "min_duration_s": 5.0,
        "max_duration_s": 10.0,
    }
    base.update(overrides)
    return ModelSpec(**base)


def video_request(**overrides: Any) -> GenerationRequest:
    base: dict[str, Any] = {
        "modality": "video",
        "model_id": "kling-3.0",
        "prompt": "un detective cruza un pasillo de neon",
        "duration_s": 5,
        "aspect": "16:9",
        "resolution": "1080p",
    }
    base.update(overrides)
    return GenerationRequest(**base)


def json_response(payload: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# --------------------------------------------------------------------------- #
# 1. Contrato: todos los adaptadores                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS, ids=lambda c: c.provider_id)
def test_adapter_implements_contract(adapter_cls: type[GenerationAdapter]) -> None:
    """
    Nada aquí es sofisticado, y por eso funciona: es la red que impide que el noveno
    adaptador se salte una pieza y falle solo en producción, con un job ya cobrado.
    """
    assert issubclass(adapter_cls, GenerationAdapter)

    adapter = adapter_cls()

    assert adapter.provider_id and isinstance(adapter.provider_id, str)
    assert adapter.supported_modalities, "declara al menos una modalidad"
    assert set(adapter.supported_modalities) <= {"image", "video", "audio", "lipsync"}

    for method in ("submit", "poll"):
        impl = getattr(adapter_cls, method)
        assert inspect.iscoroutinefunction(impl), f"{method} debe ser async"
        assert getattr(impl, "__isabstractmethod__", False) is False

    assert inspect.iscoroutinefunction(adapter_cls.cancel)
    assert not inspect.iscoroutinefunction(adapter_cls.estimate_cost)

    # El polling nunca puede ser más agresivo que el segundo: Runway throttlea a 5 s y
    # ningún proveedor del set premia ir por debajo de eso.
    assert adapter.min_poll_interval_s >= 1.0

    # `normalize_error` tiene que devolver algo que el ejecutor sepa clasificar, o la
    # política de reintento se pierde.
    from app.tools.errors import XframeToolError

    assert isinstance(adapter.normalize_error(RuntimeError("boom")), XframeToolError)


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS, ids=lambda c: c.provider_id)
def test_estimate_cost_is_positive_and_monotonic(adapter_cls: type[GenerationAdapter]) -> None:
    """Un clip más largo nunca puede salir más barato. Suena obvio hasta que alguien
    mete un redondeo por bloques mal calculado."""
    adapter = adapter_cls()
    modality = "image" if "image" in adapter.supported_modalities and "video" not in adapter.supported_modalities else "video"
    model_spec = spec("x", modality=modality, cost_per_second=Decimal("0.10"))

    short = adapter.estimate_cost(
        video_request(modality=modality, duration_s=5, init_image_url="https://x/a.png"),
        model_spec,
    )
    long = adapter.estimate_cost(
        video_request(modality=modality, duration_s=10, init_image_url="https://x/a.png"),
        model_spec,
    )
    assert short > 0
    assert long >= short


def test_every_seeded_provider_has_an_adapter_or_is_deprecated() -> None:
    """
    Un modelo activo apuntando a un proveedor sin adaptador es una bomba de relojería:
    el LLM lo ofrece, el usuario lo elige y el submit revienta. Runway está sembrado a
    propósito sin adaptador, y por eso la excepción es exactamente `deprecated`.
    """
    registry = DbAdapterRegistry()
    for model in MODELS:
        if model.status == "active":
            assert registry.get(model.provider) is not None
        else:
            with_adapter = True
            try:
                registry.get(model.provider)
            except UnknownProviderError:
                with_adapter = False
            assert with_adapter or model.sunset_at, (
                f"{model.id} no tiene adaptador y tampoco fecha de apagado que lo explique"
            )


# --------------------------------------------------------------------------- #
# 2. Higgsfield: el adaptador con más valor de producto                        #
# --------------------------------------------------------------------------- #


def test_higgsfield_dop_sends_motion_uuid_not_prompt_text() -> None:
    """
    La razón de ser de DoP es que la cámara es un parámetro del modelo. Si el motion
    acabara descrito en el prompt, estaríamos pagando Higgsfield para usarlo como un
    modelo genérico cualquiera.
    """
    motion_uuid = "8f14e45f-ceea-467a-9c17-1a2b3c4d5e6f"

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"id": "req-1", "status": "queued"})

    recorder = Recorder(handler)
    adapter = make_adapter(HiggsfieldAdapter, recorder)

    ref = run(
        adapter.submit(
            video_request(
                model_id="higgsfield-dop-turbo",
                camera_motion=motion_uuid,
                camera_motion_strength=0.8,
                init_image_url="https://cdn.test/frame.png",
            )
        )
    )

    body = recorder.body()["params"]
    assert body["motions"] == [{"id": motion_uuid}]
    assert body["motions_strength"] == 0.8
    assert "camera move" not in body["prompt"], "el motion no debe aplanarse en el prompt"
    assert body["input_images"] == [
        {"type": "image_url", "image_url": "https://cdn.test/frame.png"}
    ]
    assert ref.external_id == "req-1"
    assert ref.poll_url == "/v1/requests/req-1/status"

    # Auth literal del SDK: `Key ID:SECRET`, no Bearer.
    auth = recorder.last.headers["authorization"]
    assert auth.startswith("Key ") and ":" in auth


def test_higgsfield_dop_without_image_is_rejected_before_spending() -> None:
    """DoP es image-to-video. Detectarlo aquí ahorra un round-trip y un turno del agente,
    y el mensaje le dice al LLM exactamente cómo arreglarlo."""
    recorder = Recorder(lambda r: json_response({"id": "nope"}))
    adapter = make_adapter(HiggsfieldAdapter, recorder)

    with pytest.raises(ProviderRejectedError) as excinfo:
        run(adapter.submit(video_request(model_id="higgsfield-dop-turbo")))

    assert "image-to-video" in str(excinfo.value)
    assert not recorder.requests, "no debe haberse llamado al proveedor"


def test_higgsfield_nsfw_is_its_own_state_and_refunds() -> None:
    """Higgsfield reembolsa en `nsfw`. Si lo mapeáramos a `failed` el usuario pagaría
    igual, pero `should_refund` cubre ambos, así que lo que se comprueba es que el
    estado llega distinguible al orquestador."""
    recorder = Recorder(lambda r: json_response({"status": "nsfw", "id": "req-2"}))
    adapter = make_adapter(HiggsfieldAdapter, recorder)

    status = run(adapter.poll(ProviderJobRef("higgsfield", "req-2", "/v1/requests/req-2/status")))

    assert status.state == "nsfw"
    assert status.is_terminal
    assert status.should_refund
    assert not status.output_urls


def test_higgsfield_jobset_returns_every_output() -> None:
    """Un jobSet con batch QUAD produce cuatro imágenes. Devolver solo la primera
    perdería tres generaciones ya pagadas."""
    payload = {
        "status": "completed",
        "jobs": [
            {"results": {"raw": {"url": f"https://cdn.hf/{i}.png"}}} for i in range(4)
        ],
    }
    recorder = Recorder(lambda r: json_response(payload))
    adapter = make_adapter(HiggsfieldAdapter, recorder)

    status = run(adapter.poll(ProviderJobRef("higgsfield", "req-3")))

    assert status.state == "succeeded"
    assert len(status.output_urls) == 4


# --------------------------------------------------------------------------- #
# 3. Veo: long-running operations                                              #
# --------------------------------------------------------------------------- #


def test_veo_submit_returns_operation_name_as_poll_url() -> None:
    """Google devuelve el nombre de la operación, que ya *es* la ruta de polling.
    Persistirlo evita que un cambio de topología invalide los jobs en vuelo."""
    operation = "models/veo-3.1/operations/op-123"
    recorder = Recorder(lambda r: json_response({"name": operation}))
    adapter = make_adapter(VeoAdapter, recorder)

    ref = run(
        adapter.submit(
            video_request(model_id="veo-3.1", duration_s=8, audio=True, resolution="1080p")
        )
    )

    assert ref.external_id == operation
    assert ref.poll_url == f"/v1beta/{operation}"
    assert recorder.last.url.path.endswith(":predictLongRunning")
    assert recorder.last.headers["x-goog-api-key"]

    parameters = recorder.body()["parameters"]
    assert parameters["generateAudio"] is True
    assert parameters["durationSeconds"] == "8", "durationSeconds es string, no int"
    assert parameters["aspectRatio"] == "16:9"


def test_veo_poll_running_then_succeeded() -> None:
    responses = [
        {"name": "op", "done": False},
        {
            "name": "op",
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [{"video": {"uri": "https://files/v.mp4"}}]
                }
            },
        },
    ]
    recorder = Recorder(lambda r: json_response(responses[len(recorder.requests) - 1]))
    adapter = make_adapter(VeoAdapter, recorder)
    ref = ProviderJobRef("google", "op", "/v1beta/op")

    first = run(adapter.poll(ref))
    assert first.state == "running"
    assert not first.is_terminal

    second = run(adapter.poll(ref))
    assert second.state == "succeeded"
    assert second.output_urls == ["https://files/v.mp4"]
    assert second.progress == 1.0


def test_veo_safety_block_is_nsfw_not_failed() -> None:
    """Google devuelve la moderación como un error genérico. Sin leer el texto, un plano
    bloqueado se cobraría como un fallo cualquiera."""
    payload = {
        "done": True,
        "error": {"code": 400, "message": "Blocked by Responsible AI safety filters"},
    }
    recorder = Recorder(lambda r: json_response(payload))
    adapter = make_adapter(VeoAdapter, recorder)

    status = run(adapter.poll(ProviderJobRef("google", "op", "/v1beta/op")))

    assert status.state == "nsfw"
    assert status.should_refund


def test_veo_bills_full_eight_second_block() -> None:
    """Veo genera en bloques de ~8 s: pedir 5 no sale más barato. Estimar 5 s reales
    infravaloraría la reserva de créditos y el job se quedaría corto de saldo."""
    adapter = VeoAdapter()
    model = spec("veo-3.1", cost_per_second=Decimal("0.40"), min_duration_s=4.0)

    assert adapter.estimate_cost(video_request(duration_s=5), model) == Decimal("3.2000")
    assert adapter.estimate_cost(video_request(duration_s=8), model) == Decimal("3.2000")
    # 4K cuesta 1.5x.
    assert adapter.estimate_cost(
        video_request(duration_s=8, resolution="4K"), model
    ) == Decimal("4.8000")


# --------------------------------------------------------------------------- #
# 4. Flux: URL de polling regional                                             #
# --------------------------------------------------------------------------- #


def test_flux_uses_provider_polling_url_verbatim() -> None:
    """La `polling_url` de BFL es regional. Reconstruirla contra api.bfl.ai funciona en
    la cuenta de desarrollo y falla en la del cliente: el bug más caro de diagnosticar
    de todo este fichero."""
    polling = "https://eu-central.bfl.ai/v1/get_result?id=abc"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return json_response({"id": "abc", "polling_url": polling})
        return json_response({"status": "Ready", "result": {"sample": "https://cdn/i.png"}})

    recorder = Recorder(handler)
    adapter = make_adapter(FluxAdapter, recorder)

    ref = run(
        adapter.submit(
            GenerationRequest(
                modality="image",
                model_id="flux-2-pro",
                prompt="retrato del detective",
                aspect="9:16",
                resolution="1080p",
            )
        )
    )
    assert ref.poll_url == polling

    status = run(adapter.poll(ref))
    assert status.state == "succeeded"
    assert status.output_urls == ["https://cdn/i.png"]
    assert str(recorder.last.url) == polling

    assert recorder.requests[0].headers["x-key"], "BFL autentica con x-key, no Authorization"
    submitted = recorder.body(0)
    assert (submitted["width"], submitted["height"]) == (1088, 1920)


def test_flux_moderation_is_nsfw() -> None:
    recorder = Recorder(lambda r: json_response({"status": "Request Moderated"}))
    adapter = make_adapter(FluxAdapter, recorder)

    status = run(adapter.poll(ProviderJobRef("bfl", "abc", "https://eu.bfl.ai/r")))

    assert status.state == "nsfw"
    assert status.should_refund


def test_flux_sends_every_element_as_a_numbered_input_image() -> None:
    """
    El fallo silencioso más caro del set.

    FLUX.2 no tiene ningún campo de lista para referencias: son ocho campos numerados
    (`input_image`, `input_image_2` … `input_image_8`). Los nombres que se mandaban antes
    (`image_prompt` + `reference_images`) no existen, y BFL **ignora lo que no conoce sin
    quejarse**: la llamada devolvía 200 y una imagen razonable, generada sin una sola
    referencia. Nada en la respuesta lo delata, así que este test es la única forma de
    detectarlo sin mirar el resultado a ojo.
    """
    recorder = Recorder(lambda r: json_response({"id": "x", "polling_url": "https://p/1"}))
    adapter = make_adapter(FluxAdapter, recorder)

    elements = [
        ElementRef(f"el-{i}", f"personaje {i}", "character", f"https://cdn/{i}.png")
        for i in range(3)
    ]
    run(
        adapter.submit(
            GenerationRequest(
                modality="image", model_id="flux-2-pro", prompt="los tres en el bar",
                elements=elements,
            )
        )
    )

    body = recorder.body()
    assert body["input_image"] == "https://cdn/0.png"
    assert body["input_image_2"] == "https://cdn/1.png"
    assert body["input_image_3"] == "https://cdn/2.png"

    # Los nombres viejos no deben reaparecer: si vuelven, vuelve el 200 sin referencias.
    assert "image_prompt" not in body
    assert "reference_images" not in body


def test_flux_numbers_references_from_the_init_image_and_caps_at_eight() -> None:
    """El índice del campo es el que el prompt puede citar ("image 2"), así que el orden
    es semántico y no cosmético: el frame inicial va primero."""
    recorder = Recorder(lambda r: json_response({"id": "x", "polling_url": "https://p/1"}))
    adapter = make_adapter(FluxAdapter, recorder)

    elements = [
        ElementRef(f"el-{i}", f"p{i}", "character", f"https://cdn/{i}.png") for i in range(12)
    ]
    run(
        adapter.submit(
            GenerationRequest(
                modality="image", model_id="flux-2-pro", prompt="multitud",
                init_image_url="https://cdn/init.png", elements=elements,
            )
        )
    )

    body = recorder.body()
    assert body["input_image"] == "https://cdn/init.png"
    assert body["input_image_2"] == "https://cdn/0.png"
    assert "input_image_8" in body
    assert "input_image_9" not in body, "el máximo son ocho campos"


def test_flux_drops_negative_prompt_and_disables_prompt_rewriting() -> None:
    """`negative_prompt` no existe en FLUX.2 pro: mandarlo daba la falsa impresión de que
    la negación se estaba aplicando. Y el upsampling de prompt, activo por defecto,
    reescribe cada viñeta de forma distinta y rompe la continuidad de la serie."""
    recorder = Recorder(lambda r: json_response({"id": "x", "polling_url": "https://p/1"}))
    adapter = make_adapter(FluxAdapter, recorder)

    run(
        adapter.submit(
            GenerationRequest(
                modality="image", model_id="flux-2-pro", prompt="el bar",
                negative_prompt="sin texto, sin logos",
            )
        )
    )

    body = recorder.body()
    assert "negative_prompt" not in body
    assert body["disable_pup"] is True


def test_flux_surfaces_the_real_cost_reported_by_the_submit() -> None:
    """BFL calcula el importe exacto en el propio submit. `estimate_cost` solo puede
    adivinar los megapíxeles de las referencias, así que la cifra buena es esta y tiene
    que llegar al cierre del job."""
    recorder = Recorder(
        lambda r: json_response(
            {"id": "x", "polling_url": "https://p/1", "cost": 0.062, "megapixels": 2.09}
        )
    )
    adapter = make_adapter(FluxAdapter, recorder)

    ref = run(
        adapter.submit(
            GenerationRequest(modality="image", model_id="flux-2-pro", prompt="el bar")
        )
    )

    assert ref.raw["actual_cost_usd"] == 0.062
    assert ref.raw["actual_megapixels"] == 2.09


# --------------------------------------------------------------------------- #
# 5. Kling: JWT y errores de negocio en HTTP 200                               #
# --------------------------------------------------------------------------- #


def test_kling_signs_a_jwt_and_caches_it() -> None:
    import base64

    recorder = Recorder(lambda r: json_response({"code": 0, "data": {"task_id": "t1"}}))
    adapter = make_adapter(KlingAdapter, recorder)

    run(adapter.submit(video_request(model_id="kling-3.0")))
    token = recorder.last.headers["authorization"].removeprefix("Bearer ")

    header_b64, payload_b64, signature = token.split(".")
    decode = lambda s: json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))  # noqa: E731
    assert decode(header_b64) == {"alg": "HS256", "typ": "JWT"}
    payload = decode(payload_b64)
    assert payload["iss"] == os.environ["KLING_ACCESS_KEY"]
    assert payload["exp"] > payload["nbf"]
    assert signature

    # Segundo submit: el token se reutiliza. Firmar en cada poll sería gasto puro.
    run(adapter.submit(video_request(model_id="kling-3.0")))
    assert recorder.last.headers["authorization"].removeprefix("Bearer ") == token


def test_kling_business_error_in_http_200_is_a_rejection() -> None:
    """Kling devuelve 200 con `code != 0`. Sin traducirlo, un rechazo se leería como un
    submit correcto y el job quedaría colgado esperando un task_id inexistente."""
    recorder = Recorder(
        lambda r: json_response({"code": 1303, "message": "risk control: sensitive content"})
    )
    adapter = make_adapter(KlingAdapter, recorder)

    with pytest.raises(ProviderRejectedError) as excinfo:
        run(adapter.submit(video_request(model_id="kling-3.0")))

    assert "1303" in str(excinfo.value)
    assert len(recorder.requests) == 1, "un rechazo de contenido no se reintenta"


def test_kling_routes_to_image2video_and_keeps_last_frame() -> None:
    """El endpoint depende de si hay imagen de partida, así que `poll_url` tiene que
    salir del submit: reconstruirlo por defecto acertaría solo en la mitad de los jobs."""
    recorder = Recorder(lambda r: json_response({"code": 0, "data": {"task_id": "t9"}}))
    adapter = make_adapter(KlingAdapter, recorder)

    ref = run(
        adapter.submit(
            video_request(
                model_id="kling-3.0",
                init_image_url="https://cdn/first.png",
                last_frame_url="https://cdn/last.png",
            )
        )
    )

    assert recorder.last.url.path == "/v1/videos/image2video"
    assert ref.poll_url == "/v1/videos/image2video/t9"
    body = recorder.body()
    assert body["image"] == "https://cdn/first.png"
    assert body["image_tail"] == "https://cdn/last.png"
    assert "aspect_ratio" not in body, "en i2v el aspect lo fija la imagen"
    assert body["mode"] == "pro", "1080p exige modo pro"


def test_kling_succeed_and_moderation_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "t-ok" in str(request.url):
            return json_response(
                {
                    "code": 0,
                    "data": {
                        "task_status": "succeed",
                        "task_result": {"videos": [{"url": "https://cdn/k.mp4"}]},
                    },
                }
            )
        return json_response(
            {
                "code": 0,
                "data": {"task_status": "failed", "task_status_msg": "risk control triggered"},
            }
        )

    recorder = Recorder(handler)
    adapter = make_adapter(KlingAdapter, recorder)

    ok = run(adapter.poll(ProviderJobRef("kling", "t-ok", "/v1/videos/text2video/t-ok")))
    assert ok.state == "succeeded"
    assert ok.output_urls == ["https://cdn/k.mp4"]

    bad = run(adapter.poll(ProviderJobRef("kling", "t-bad", "/v1/videos/text2video/t-bad")))
    assert bad.state == "nsfw", "la moderación de Kling llega como un failed cualquiera"


# --------------------------------------------------------------------------- #
# 6. Política de reintentos                                                    #
# --------------------------------------------------------------------------- #


def test_transient_5xx_is_retried_until_it_succeeds() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, text="upstream unavailable")
        return json_response({"id": "ok", "polling_url": "https://p/1"})

    recorder = Recorder(handler)
    adapter = make_adapter(FluxAdapter, recorder)

    ref = run(
        adapter.submit(
            GenerationRequest(modality="image", model_id="flux-2-pro", prompt="x")
        )
    )
    assert ref.external_id == "ok"
    assert attempts["n"] == 3


def test_client_4xx_is_not_retried() -> None:
    """Reintentar un 400 gasta cuota sin cambiar nada, y el error debe llegar como
    ajustable para que el LLM corrija la entrada en el siguiente turno."""
    recorder = Recorder(lambda r: httpx.Response(422, text="duration out of range"))
    adapter = make_adapter(WanAdapter, recorder)

    with pytest.raises(ProviderRejectedError) as excinfo:
        run(adapter.submit(video_request(model_id="wan-2.5")))

    assert len(recorder.requests) == 1
    assert excinfo.value.retry_strategy == "adjusted"


def test_bad_credentials_are_fatal_and_not_retried() -> None:
    recorder = Recorder(lambda r: httpx.Response(401, text="invalid key"))
    adapter = make_adapter(SoraAdapter, recorder)

    with pytest.raises(XframeToolFatalError) as excinfo:
        run(adapter.submit(video_request(model_id="sora-2")))

    assert len(recorder.requests) == 1
    assert excinfo.value.retry_strategy == "never"


def test_exhausted_retries_surface_as_transient() -> None:
    """Agotar los reintentos no convierte el fallo en fatal: el ejecutor debe poder
    reencolar el job más tarde."""
    recorder = Recorder(lambda r: httpx.Response(500, text="boom"))
    adapter = make_adapter(WanAdapter, recorder)

    with pytest.raises(ProviderError) as excinfo:
        run(adapter.submit(video_request(model_id="wan-2.5")))

    assert len(recorder.requests) == 4
    assert excinfo.value.retry_strategy == "once"


def test_missing_credentials_fail_before_any_network_call() -> None:
    """Un despliegue sin la clave de un proveedor debe seguir sirviendo los otros siete,
    y el fallo debe ser fatal y explícito, no un 401 disfrazado de transitorio."""
    from app.config import get_settings

    settings = get_settings()
    original = settings.minimax_api_key
    settings.minimax_api_key = ""
    try:
        recorder = Recorder(lambda r: json_response({"task_id": "x"}))
        adapter = make_adapter(HailuoAdapter, recorder)
        with pytest.raises(XframeToolFatalError) as excinfo:
            run(adapter.submit(video_request(model_id="hailuo-2.3")))
        assert "MINIMAX_API_KEY" in str(excinfo.value)
        assert not recorder.requests
    finally:
        settings.minimax_api_key = original


def test_retry_delay_has_jitter_and_respects_retry_after() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=20.0)

    delays = {policy.delay_for(2) for _ in range(30)}
    assert len(delays) > 1, "sin jitter, un lote de reintentos reconstruye el pico"
    assert all(2.0 <= d <= 4.0 for d in delays), "jitter completo sobre 2^2 * 1.0"

    # `Retry-After` del proveedor manda sobre nuestro cálculo y se respeta **íntegro**.
    # Recortarlo a `max_delay_s` era reintentar cuando el proveedor había dicho que no:
    # así se convierte un rate limit de cinco minutos en un baneo de la cuenta.
    assert policy.delay_for(0, retry_after_s=7.5) == 7.5
    assert policy.delay_for(0, retry_after_s=300) == 300, "un 429 con 5 min se espera entero"

    # El único techo es la red de seguridad contra una cabecera absurda, y es altísimo.
    assert policy.delay_for(0, retry_after_s=99_999) == policy.max_retry_after_s
    assert policy.max_retry_after_s >= 300


# --------------------------------------------------------------------------- #
# 7. Throttle de polling                                                       #
# --------------------------------------------------------------------------- #


class _GateClock:
    """Reloj monótono y `sleep` controlados para probar el gate sin tiempo de pared.

    Los dos tests del gate medían segundos reales (`elapsed >= 0.25`). Esa medición es
    no determinista en cuanto la máquina va cargada —CI, o esta misma suite mientras
    corría el servidor de dev y dos agentes en paralelo—, y por eso el test parpadeaba
    en el orden completo aun pasando aislado. Aquí movemos el reloj nosotros: cuando el
    gate pide dormir X, lo anotamos y avanzamos el reloj X **sin esperar de verdad**. Se
    comprueba la lógica exacta del gate (cuánto decide esperar y que serializa a los
    pollers concurrentes), no una constante de reloj sujeta a la carga del CI.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds > 0:
            self.now += seconds
        # Ceder el turno como haría el sleep real: así los pollers concurrentes se
        # ordenan por el cerrojo del gate en vez de avanzar todos en bloque.
        await asyncio.sleep(0)


class _AsyncioProxy:
    """`asyncio` real salvo `sleep`. Rebindea solo el nombre dentro de `_http`, sin
    tocar el módulo global (que el event loop necesita intacto)."""

    def __init__(self, real: Any, sleep: Any) -> None:
        self._real = real
        self.sleep = sleep

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _TimeProxy:
    """`time` real salvo `monotonic`. Igual que `_AsyncioProxy`: nombre local, módulo
    global intacto."""

    def __init__(self, real: Any, monotonic: Any) -> None:
        self._real = real
        self.monotonic = monotonic

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _install_gate_clock(monkeypatch: pytest.MonkeyPatch) -> _GateClock:
    clock = _GateClock()
    monkeypatch.setattr(_http, "time", _TimeProxy(time, clock.monotonic))
    monkeypatch.setattr(_http, "asyncio", _AsyncioProxy(asyncio, clock.sleep))
    return clock


def test_poll_gate_enforces_min_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runway documenta 1 req/5 s y el resto agradece el respiro. Se comprueba que el
    gate espera un intervalo completo entre dos polls seguidos, con un reloj controlado
    en vez de medir tiempo real (que hacía el test no determinista bajo carga)."""
    clock = _install_gate_clock(monkeypatch)
    recorder = Recorder(lambda r: json_response({"name": "op", "done": False}))
    adapter = make_adapter(VeoAdapter, recorder)
    adapter.min_poll_interval_s = 0.25
    ref = ProviderJobRef("google", "op", "/v1beta/op")

    async def poll_twice() -> None:
        await adapter.poll(ref)
        await adapter.poll(ref)

    run(poll_twice())
    # El primer poll no espera (no hay marca previa); el segundo espera el intervalo.
    assert clock.sleeps == [0.25]
    assert clock.now >= 0.25
    assert len(recorder.requests) == 2


# --------------------------------------------------------------------------- #
# 8. Registro                                                                  #
# --------------------------------------------------------------------------- #


def test_registry_reuses_adapter_instances() -> None:
    """El adaptador guarda estado que vale dinero conservar: el JWT de Kling y el
    catálogo de motions de Higgsfield. Instanciar por job los tiraría cada vez."""
    registry = DbAdapterRegistry()
    assert registry.get("kling") is registry.get("kling")
    assert registry.get("kling").provider_id == "kling"


def test_registry_rejects_unknown_provider_loudly() -> None:
    registry = DbAdapterRegistry()
    with pytest.raises(UnknownProviderError):
        registry.get("midjourney")


def test_registry_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    """El TTL corto es la razón de que apagar un modelo sea un UPDATE. Un TTL infinito
    convertiría la ventaja de tener esto en datos en una desventaja operativa."""
    registry = DbAdapterRegistry(ttl_s=0.05)
    loads = {"n": 0}
    now = 0.0

    def monotonic() -> float:
        return now

    monkeypatch.setattr("app.providers.registry.time.monotonic", monotonic)

    async def fake_load() -> dict[str, ModelSpec]:
        loads["n"] += 1
        return {"veo-3.1": spec("veo-3.1", provider="google")}

    registry._load = fake_load  # type: ignore[method-assign]

    async def scenario() -> None:
        await registry.models()
        await registry.models()
        assert loads["n"] == 1, "dentro del TTL no se recarga"
        nonlocal now
        now += 0.06
        await registry.models()
        assert loads["n"] == 2

        adapter, model_spec = await registry.resolve("veo-3.1")
        assert adapter.provider_id == "google"
        assert model_spec.id == "veo-3.1"

    run(scenario())


def test_registry_unknown_model_lists_the_valid_ones() -> None:
    """El patrón del taxonomy toolkit: enumerar las opciones es lo que permite al
    modelo autocorregirse en el turno siguiente en vez de insistir."""
    from app.tools.errors import UnknownEntityError

    registry = DbAdapterRegistry(ttl_s=60)

    async def fake_load() -> dict[str, ModelSpec]:
        return {"veo-3.1": spec("veo-3.1", provider="google")}

    registry._load = fake_load  # type: ignore[method-assign]

    async def scenario() -> None:
        with pytest.raises(UnknownEntityError) as excinfo:
            await registry.resolve("veo-3.0")
        assert "veo-3.1" in str(excinfo.value)

    run(scenario())


# --------------------------------------------------------------------------- #
# 9. Semilla                                                                   #
# --------------------------------------------------------------------------- #


def test_credits_round_up_so_the_margin_is_never_negative() -> None:
    """Redondear a la baja convierte el margen en pérdida justo en los modelos baratos,
    que son los más usados."""
    assert credits_per_unit(Decimal("0.40"), credits_per_usd=100, credit_margin=1.6) == 64
    assert credits_per_unit(Decimal("0.019"), credits_per_usd=100, credit_margin=1.6) == 4
    assert credits_per_unit(Decimal("0.0001"), credits_per_usd=100, credit_margin=1.6) == 1


def test_seed_ids_are_unique_and_sunsets_are_marked() -> None:
    ids = [m.id for m in MODELS]
    assert len(ids) == len(set(ids))
    assert len({m.id for m in MOTIONS}) == len(MOTIONS)
    assert len({s.id for s in STYLES}) == len(STYLES)

    by_id = {m.id: m for m in MODELS}
    # Los tres apagados conocidos del informe 06. Si alguien reactiva uno sin querer,
    # el agente empezaría a ofrecer un modelo que va a fallar.
    assert by_id["sora-2"].sunset_at == "2026-09-24"
    assert by_id["sora-2-pro"].sunset_at == "2026-09-24"
    assert by_id["runway-gen-4-turbo"].sunset_at == "2026-07-30"
    for model_id in ("sora-2", "sora-2-pro", "runway-gen-4-turbo", "runway-gen-4"):
        assert by_id[model_id].status == "deprecated"


def test_descriptions_explain_when_to_choose_not_what_the_specs_are() -> None:
    """
    `description_llm` compite por contexto con todo lo demás. Repetir resolución y
    duración es gastarlo en información que el modelo ya ve estructurada en el schema.
    """
    for model in MODELS:
        text = model.description_llm
        assert len(text) > 120, f"{model.id}: demasiado corta para orientar una decisión"
        assert "720p" not in text and "1080p" not in text, (
            f"{model.id}: la resolución ya está en el schema"
        )
    for motion in MOTIONS:
        assert len(motion.description_llm) > 60, f"{motion.id}: sin criterio narrativo"


def test_emitted_sql_is_idempotent_and_carries_price_confidence() -> None:
    """La semilla se aplica en cada despliegue: sin `on conflict` el segundo reventaría.
    Y la confianza del precio viaja al SQL porque un [S] equivocado no da error, solo
    margen negativo."""
    from app.providers.seed import emit_sql

    sql = emit_sql()
    assert sql.count("insert into public.gen_models") == len(MODELS)
    assert sql.count("on conflict (id) do update set") == len(MODELS) + len(MOTIONS) + len(STYLES)
    assert "[S] fuente secundaria" in sql
    assert "[I] INFERIDO" in sql
    # Los modelos que desaparecen de la semilla se retiran, no se borran: el historial
    # de generation_jobs los referencia.
    assert "set status = 'retired'" in sql
    assert "delete from public.gen_models" not in sql


# --------------------------------------------------------------------------- #
# 11. Correcciones contra documentación oficial (auditoría 2026-07-20)          #
# --------------------------------------------------------------------------- #
#
# Todo lo de esta sección es un fallo que la suite anterior no veía porque **el
# proveedor no protesta**: devuelve 200 y algo plausible. Un test que solo comprueba
# "el submit funciona" los aprueba todos. Por eso aquí se inspecciona el cuerpo enviado
# campo a campo, y se afirma también lo que *no* debe ir.

_FAKE_PNG = b"\x89PNG\r\n\x1a\nfake"


def image_response() -> httpx.Response:
    return httpx.Response(200, content=_FAKE_PNG, headers={"content-type": "image/png"})


def test_veo_reads_the_output_uri_from_the_real_response_path() -> None:
    """
    El fallo más caro del set: `_extract_urls` buscaba `generatedVideos` y `predictions`,
    que no existen en esta API. Ninguna clave casaba nunca, así que **toda** generación
    correcta se leía como "completada sin salida" y se marcaba `failed`. Se pagaba el
    vídeo íntegro y se tiraba el resultado, sin ningún error visible en el camino.
    """
    body = {
        "name": "op",
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [
                    {"video": {"uri": "https://files/a.mp4"}},
                    {"video": {"uri": "https://files/b.mp4"}},
                ]
            }
        },
    }
    recorder = Recorder(lambda r: json_response(body))
    adapter = make_adapter(VeoAdapter, recorder)

    status = run(adapter.poll(ProviderJobRef("google", "op", "/v1beta/op")))

    assert status.state == "succeeded", "una generación correcta no puede leerse como fallo"
    assert status.output_urls == ["https://files/a.mp4", "https://files/b.mp4"]
    assert not status.should_refund


def test_veo_sends_reference_images_inline_not_as_gcs_uri() -> None:
    """
    `gcsUri` es de Vertex AI. En `generativelanguage` se ignora en silencio: el modelo
    generaba sin la referencia y devolvía 200, que es exactamente el mismo tipo de fallo
    invisible que el de Flux. La Gemini API exige la imagen en base64 inline.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return image_response()
        return json_response({"name": "models/veo/operations/op-1"})

    recorder = Recorder(handler)
    adapter = make_adapter(VeoAdapter, recorder)

    run(
        adapter.submit(
            video_request(
                model_id="veo-3.1-generate-preview",
                init_image_url="https://cdn/first.png",
            )
        )
    )

    instance = recorder.body()["instances"][0]
    inline = instance["image"]["inlineData"]
    assert inline["mimeType"] == "image/png", "el mime sale del content-type real"
    assert base64.b64decode(inline["data"]) == _FAKE_PNG
    assert "gcsUri" not in json.dumps(instance), "gcsUri es de Vertex, aquí no vale"


def test_veo_forces_the_three_reference_constraints_together() -> None:
    """Con `referenceImages` la API impone 16:9, exactamente 8 s y como mucho tres
    referencias. Se fuerzan antes de enviar: un 400 cuesta un turno del agente, y salir
    en 9:16 sin avisar sería peor todavía."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return image_response()
        return json_response({"name": "models/veo/operations/op-2"})

    recorder = Recorder(handler)
    adapter = make_adapter(VeoAdapter, recorder)

    elements = [
        ElementRef(f"el-{i}", f"p{i}", "character", f"https://cdn/{i}.png") for i in range(5)
    ]
    run(
        adapter.submit(
            video_request(
                model_id="veo-3.1-generate-preview",
                aspect="9:16",
                duration_s=4,
                elements=elements,
            )
        )
    )

    body = recorder.body()
    assert len(body["instances"][0]["referenceImages"]) == 3, "el máximo son tres"
    assert body["parameters"]["aspectRatio"] == "16:9"
    assert body["parameters"]["durationSeconds"] == "8"


def test_veo_refuses_to_mix_references_with_frames() -> None:
    """`referenceImages` es mutuamente excluyente con `image`/`lastFrame`. Se rechaza
    aquí porque el 400 de Google no dice cuál de los dos caminos abandonar, y el agente
    necesita saberlo para reintentar con sentido."""
    recorder = Recorder(lambda r: json_response({"name": "op"}))
    adapter = make_adapter(VeoAdapter, recorder)

    with pytest.raises(ProviderRejectedError) as excinfo:
        run(
            adapter.submit(
                video_request(
                    model_id="veo-3.1-generate-preview",
                    init_image_url="https://cdn/first.png",
                    elements=[ElementRef("el", "p", "character", "https://cdn/p.png")],
                )
            )
        )

    assert "mutually exclusive" in str(excinfo.value)
    assert not recorder.requests, "no se gasta una llamada para que la rechacen"


def test_veo_duration_is_a_string_from_a_closed_set() -> None:
    recorder = Recorder(lambda r: json_response({"name": "op"}))
    adapter = make_adapter(VeoAdapter, recorder)

    for wanted, expected in ((4, "4"), (5, "6"), (8, "8"), (12, "8")):
        run(
            adapter.submit(
                video_request(
                    model_id="veo-3.1-generate-preview", duration_s=wanted, resolution="720p"
                )
            )
        )
        value = recorder.body()["parameters"]["durationSeconds"]
        assert value == expected
        assert isinstance(value, str)


def test_veo_high_resolution_forces_the_eight_second_clip() -> None:
    """1080p y 4K solo existen en clips de 8 s: pedirlos con 4 es un 400. Se sube la
    duración y no se baja la resolución, porque la resolución es lo que el usuario pidió
    y Veo factura el bloque de 8 s igualmente."""
    recorder = Recorder(lambda r: json_response({"name": "op"}))
    adapter = make_adapter(VeoAdapter, recorder)

    run(
        adapter.submit(
            video_request(model_id="veo-3.1-generate-preview", duration_s=4, resolution="1080p")
        )
    )
    parameters = recorder.body()["parameters"]
    assert parameters["durationSeconds"] == "8"
    assert parameters["resolution"] == "1080p"


def test_veo_4k_multiplier_depends_on_the_variant() -> None:
    """Una tabla plana aplicaba el salto de 4K de Standard (1.5x) a Fast, cuyo salto real
    es el doble, y ofrecía 4K en Lite, que no lo tiene. Los dos errores se pagan."""
    adapter = VeoAdapter()
    model = spec("x", cost_per_second=Decimal("0.10"), min_duration_s=4.0)

    def cost(model_id: str, resolution: str) -> Decimal:
        return adapter.estimate_cost(
            video_request(model_id=model_id, duration_s=8, resolution=resolution), model
        )

    base = cost("veo-3.1-generate-preview", "1080p")
    assert cost("veo-3.1-generate-preview", "4K") == base * 3 / 2
    assert cost("veo-3.1-fast-generate-preview", "4K") == base * 3
    # Lite no tiene 4K: se estima con su tramo más caro, nunca por debajo.
    assert cost("veo-3.1-lite-generate-preview", "4K") >= base


def test_higgsfield_sends_custom_reference_id_not_soul_id() -> None:
    """Una línea, y es el mecanismo de continuidad de mayor valor del catálogo: con el
    nombre equivocado la API ignoraba la identidad entrenada y devolvía una cara nueva en
    cada plano. Se pagaba el Soul ID y no se usaba."""
    recorder = Recorder(lambda r: json_response({"id": "req-1"}))
    adapter = make_adapter(HiggsfieldAdapter, recorder)

    run(
        adapter.submit(
            GenerationRequest(
                modality="image",
                model_id="higgsfield-soul",
                prompt="el detective",
                elements=[ElementRef("soul-abc", "detective", "character", "https://cdn/d.png")],
            )
        )
    )

    params = recorder.body()["params"]
    assert params["custom_reference_id"] == "soul-abc"
    assert "soul_id" not in params


def test_sora_sends_input_reference_as_an_object_and_no_seed() -> None:
    """Como string suelto era un 400, y OpenAI rechaza los parámetros que no conoce en vez
    de ignorarlos: mandar `seed` convertía en error toda petición reproducible."""
    recorder = Recorder(lambda r: json_response({"id": "vid-1"}))
    adapter = make_adapter(SoraAdapter, recorder)

    run(
        adapter.submit(
            video_request(
                model_id="sora-2",
                init_image_url="https://cdn/ref.png",
                seed=42,
                duration_s=8,
            )
        )
    )

    body = recorder.body()
    assert body["input_reference"] == {"image_url": "https://cdn/ref.png"}
    assert "seed" not in body
    assert body["seconds"] == "8"
    assert body["size"] in ("1280x720", "720x1280", "1024x1792", "1792x1024")


def test_sora_pro_uses_the_same_closed_duration_set() -> None:
    """La tabla anterior daba (10, 15, 25) a Pro: valores que no existen, así que toda
    petición a sora-2-pro salía con un `seconds` inválido."""
    recorder = Recorder(lambda r: json_response({"id": "vid-2"}))
    adapter = make_adapter(SoraAdapter, recorder)

    run(adapter.submit(video_request(model_id="sora-2-pro", duration_s=10)))
    assert recorder.body()["seconds"] == "12"


def test_kling_refuses_elements_instead_of_dropping_them_silently() -> None:
    """`image_list` es primer/último fotograma, no multi-referencia de personaje. Mandar
    ahí los elements producía un vídeo válido y facturado **sin ninguna referencia
    aplicada**, sin forma de detectarlo salvo mirándolo."""
    recorder = Recorder(lambda r: json_response({"code": 0, "data": {"task_id": "t"}}))
    adapter = make_adapter(KlingAdapter, recorder)

    with pytest.raises(ProviderRejectedError) as excinfo:
        run(
            adapter.submit(
                video_request(
                    model_id="kling-3.0",
                    elements=[ElementRef("el", "p", "character", "https://cdn/p.png")],
                )
            )
        )

    message = str(excinfo.value)
    assert "kling_elements" in message
    assert "Veo" in message or "Flux" in message, "el error propone una alternativa"
    assert not recorder.requests, "no se genera un plano que no sirve"


def test_kling_pro_mode_costs_one_third_more_not_double() -> None:
    """Con 2.0 se reservaba un 50% de más en cada plano en 1080p, que son casi todos.
    Esa reserva sale del saldo del usuario aunque después se devuelva."""
    adapter = KlingAdapter()
    model = spec("kling-3.0", cost_per_second=Decimal("0.10"), min_duration_s=5.0)

    std = adapter.estimate_cost(video_request(resolution="720p", duration_s=5), model)
    pro = adapter.estimate_cost(video_request(resolution="1080p", duration_s=5), model)

    assert pro == (std * Decimal("1.33")).quantize(Decimal("0.0001"))


def test_kling_base_url_is_configurable() -> None:
    """La doc de Kling responde 446 y las dos bases candidatas no son intercambiables:
    acertar por defecto y fallar en la cuenta del cliente da un 401, que clasificamos
    como fatal y mata el job sin reintento."""
    from app.providers import kling

    assert kling.KlingAdapter.base_url in kling._KLING_BASE_URL_OPTIONS
    assert len(kling._KLING_BASE_URL_OPTIONS) == 2
    assert "KLING_BASE_URL" in inspect.getsource(kling)


def test_wan_image_to_video_uses_its_own_path_and_ratio() -> None:
    """i2v y t2v no comparten endpoint, y el de texto rechaza `img_url`: la generación
    imagen→vídeo nunca llegó a funcionar. Además `parameters["audio"]` no existe."""
    recorder = Recorder(lambda r: json_response({"output": {"task_id": "task-1"}}))
    adapter = make_adapter(WanAdapter, recorder)

    run(
        adapter.submit(
            video_request(
                model_id="wan-2.7",
                init_image_url="https://cdn/first.png",
                aspect="9:16",
                resolution="1080p",
                audio=True,
            )
        )
    )

    assert recorder.last.url.path.endswith("/image2video/video-synthesis")
    body = recorder.body()
    assert body["model"] == "wan2.7-i2v"
    assert body["input"]["img_url"] == "https://cdn/first.png"
    assert body["parameters"]["ratio"] == "9:16", "wan2.7 usa ratio, no size en píxeles"
    assert "size" not in body["parameters"]
    assert "audio" not in body["parameters"], "no existe; el audio es input.audio_url"


def test_wan_text_to_video_keeps_the_legacy_size_field() -> None:
    """Las versiones anteriores a 2.7 siguen con `size` en píxeles. Mandar el par
    equivocado no da error: se ignora y el vídeo sale con el encuadre por defecto."""
    recorder = Recorder(lambda r: json_response({"output": {"task_id": "task-2"}}))
    adapter = make_adapter(WanAdapter, recorder)

    run(adapter.submit(video_request(model_id="wan-2.5", aspect="16:9", resolution="720p")))

    assert recorder.last.url.path.endswith("/video-generation/video-synthesis")
    body = recorder.body()
    assert body["model"] == "wan2.5-t2v-preview"
    assert body["parameters"]["size"] == "1280*720"
    assert "ratio" not in body["parameters"]


def test_seedance_fails_loudly_instead_of_calling_an_unverified_api() -> None:
    """Es el modelo más caro del catálogo (~$21/job en 4K). Con el esquema sin verificar,
    el fallo probable no es un 400 limpio: es una llamada aceptada, facturada y distinta
    de lo que se pidió."""
    recorder = Recorder(lambda r: json_response({"id": "t"}))
    adapter = make_adapter(SeedanceAdapter, recorder)

    with pytest.raises(XframeToolFatalError) as excinfo:
        run(adapter.submit(video_request(model_id="seedance-2.0")))

    assert "Do not retry" in str(excinfo.value)
    assert not recorder.requests, "no se toca la API"


def test_seedance_corrected_payload_is_ready_for_reactivation() -> None:
    """La traducción corregida se mantiene probada aunque no se envíe: el trabajo caro no
    es escribirla, es averiguar qué campos son."""
    adapter = SeedanceAdapter()
    payload = adapter.build_payload(
        video_request(model_id="seedance-2.0", duration_s=5, resolution="1080p", audio=True)
    )

    assert payload["model"] == "dreamina-seedance-2-0-260128"
    # Campos JSON de primer nivel, no flags `--clave valor` pegados al prompt (eso es 1.x).
    assert payload["ratio"] == "16:9"
    assert payload["resolution"] == "1080p"
    assert payload["duration"] == 5
    assert payload["generate_audio"] is True
    assert "--resolution" not in payload["content"][0]["text"]


def test_seedance_is_seeded_as_deprecated_so_the_agent_never_offers_it() -> None:
    seedance = [m for m in MODELS if m.provider == "bytedance"]
    assert seedance
    assert all(m.status == "deprecated" for m in seedance)


def test_seedance_base_url_is_the_byteplus_international_host() -> None:
    from app.providers import seedance

    assert seedance._ARK_BASE == "https://ark.ap-southeast.bytepluses.com"


# --------------------------------------------------------------------------- #
# 12. OpenAI Images: API síncrona dentro del contrato submit → poll            #
# --------------------------------------------------------------------------- #
#
# Es el único adaptador de imagen que funciona con la clave que el usuario ya tiene, así
# que es la puerta de entrada real al producto. Lo que se prueba aquí, por orden de lo que
# cuesta si falla:
#
#   1. El camino de REFERENCIA DE PERSONAJE (endpoint de edits). Es el que da continuidad
#      y el que justifica el adaptador entero.
#   2. Que `poll()` no vuelve a llamar a la API. Volver a llamar no es un fallo de
#      corrección: es facturar una imagen nueva en cada ciclo de polling.
#   3. Que el precio depende de la calidad. Entre `low` y `high` hay un factor de 35.

_B64_PIXEL = base64.b64encode(_FAKE_PNG).decode()


def openai_image_response(**extra: Any) -> httpx.Response:
    payload: dict[str, Any] = {
        "created": 1770000000,
        "data": [{"b64_json": _B64_PIXEL}],
        "output_format": "png",
        "size": "1024x1024",
        "quality": "medium",
        "usage": {"input_tokens": 20, "output_tokens": 1056, "total_tokens": 1076},
    }
    payload.update(extra)
    return json_response(payload)


def image_request(**overrides: Any) -> GenerationRequest:
    base: dict[str, Any] = {
        "modality": "image",
        "model_id": "gpt-image-2",
        "prompt": "retrato del detective en el bar de neon",
    }
    base.update(overrides)
    return GenerationRequest(**base)


def test_openai_image_submit_is_synchronous_and_poll_never_calls_again() -> None:
    """
    El contrato es submit → poll, pero la Images API devuelve la imagen en la misma
    respuesta. `submit()` guarda el resultado y `poll()` lo devuelve terminal **sin tocar
    la red**: si volviera a llamar, cada ciclo de polling generaría y facturaría una imagen
    distinta, y nos quedaríamos con la última. Es un fallo que ningún test de "el submit
    funciona" detecta, y que solo se ve en la factura.
    """
    recorder = Recorder(lambda r: openai_image_response())
    adapter = make_adapter(OpenAIImageAdapter, recorder)

    ref = run(adapter.submit(image_request()))
    assert len(recorder.requests) == 1
    assert recorder.last.url.path == "/v1/images/generations"

    status = run(adapter.poll(ref))
    assert status.state == "succeeded"
    assert status.is_terminal
    assert status.progress == 1.0
    assert len(recorder.requests) == 1, "poll() no puede volver a generar (y facturar)"

    # La salida es base64, no una URL: los GPT Image nunca devuelven `url`.
    assert status.output_urls[0].startswith("data:image/png;base64,")
    assert base64.b64decode(status.raw["images_b64"][0]) == _FAKE_PNG

    # Un segundo poll sigue siendo terminal e idéntico: el contrato exige idempotencia.
    assert run(adapter.poll(ref)).output_urls == status.output_urls
    assert len(recorder.requests) == 1


def test_openai_image_uses_the_edits_endpoint_for_character_reference() -> None:
    """
    EL CAMINO QUE IMPORTA. Un element (personaje, localización, objeto) es una imagen de
    referencia, y la continuidad depende de que llegue al proveedor de verdad.

    `/v1/images/generations` **no acepta imágenes**: mandar ahí una referencia la descarta
    y devuelve 200 con una cara nueva, que es el fallo silencioso clásico de esta capa. La
    referencia solo se aplica por `/v1/images/edits`, en multipart y con los bytes subidos,
    porque ese endpoint tampoco acepta URLs.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return image_response()  # descarga de la referencia desde el bucket
        return openai_image_response()

    recorder = Recorder(handler)
    adapter = make_adapter(OpenAIImageAdapter, recorder)

    elements = [
        ElementRef("el-1", "detective", "character", "https://cdn/detective.png"),
        ElementRef("el-2", "el bar", "location", "https://cdn/bar.png"),
    ]
    run(adapter.submit(image_request(prompt="el detective entra en el bar", elements=elements)))

    # Las dos referencias se descargaron y la generación fue al endpoint de edición.
    gets = [r for r in recorder.requests if r.method == "GET"]
    assert len(gets) == 2, "cada element se descarga para poder subirlo"
    assert recorder.last.url.path == "/v1/images/edits"

    body = recorder.last.content
    content_type = recorder.last.headers["content-type"]
    assert content_type.startswith("multipart/form-data"), (
        "edits es multipart; con application/json el servidor no ve ninguna imagen"
    )
    # `image[]` y no `image`: en singular solo viajaría la primera referencia, y la
    # segunda se perdería sin ningún error.
    assert body.count(b'name="image[]"') == 2
    assert _FAKE_PNG in body, "los bytes reales de la referencia tienen que ir en el cuerpo"

    # La clave de OpenAI no puede viajar al bucket de donde sale la referencia.
    assert "authorization" not in {k.lower() for k in gets[0].headers}


def test_openai_image_does_not_send_parameters_the_api_rejects() -> None:
    """
    `response_format` solo existe en dall-e-*, y `seed`/`negative_prompt` no existen en
    esta API. OpenAI **rechaza los parámetros que no conoce** en vez de ignorarlos (la
    misma lección que dejó `seed` en el adaptador de Sora), así que mandarlos convertiría
    en 400 justo las peticiones más elaboradas.
    """
    recorder = Recorder(lambda r: openai_image_response())
    adapter = make_adapter(OpenAIImageAdapter, recorder)

    run(adapter.submit(image_request(seed=42, negative_prompt="sin texto, sin logos", aspect="16:9")))

    body = recorder.body()
    assert "response_format" not in body
    assert "seed" not in body
    assert "negative_prompt" not in body
    # La negación no se pierde: sin campo propio, la única forma honesta es el prompt.
    assert "sin texto" in body["prompt"]
    assert body["size"] == "1536x1024", "16:9 es 1536x1024 en esta API"
    assert body["output_format"] == "png"
    assert body["n"] == 1


def test_openai_image_price_tracks_quality_not_a_flat_rate() -> None:
    """Entre `low` y `high` hay un factor de ~35. Una tarifa plana se equivocaría en un
    sentido u otro por ese factor: o se espanta al usuario o se genera bajo coste."""
    adapter = OpenAIImageAdapter()
    model = spec("gpt-image-2", modality="image", cost_per_second=Decimal("0.001"))

    low = adapter.estimate_cost(image_request(extra={"quality": "low"}), model)
    medium = adapter.estimate_cost(image_request(extra={"quality": "medium"}), model)
    high = adapter.estimate_cost(image_request(extra={"quality": "high"}), model)

    assert low < medium < high
    assert high > low * 10

    # Un tamaño no cuadrado consume más tokens de salida y cuesta más.
    wide = adapter.estimate_cost(
        image_request(aspect="16:9", extra={"quality": "medium"}), model
    )
    assert wide > medium

    # Las referencias no son gratis: se facturan como tokens de imagen de entrada.
    with_refs = adapter.estimate_cost(
        image_request(
            extra={"quality": "medium"},
            elements=[ElementRef("e", "p", "character", "https://cdn/p.png")],
        ),
        model,
    )
    assert with_refs > medium


def test_openai_image_empty_data_is_a_rejection_not_a_live_job() -> None:
    """Un 200 sin imagen no puede devolver un ref "vivo": el worker poletearía para siempre
    un trabajo que no existe, consumiendo su ventana de créditos hasta el barrido."""
    recorder = Recorder(lambda r: json_response({"created": 1, "data": []}))
    adapter = make_adapter(OpenAIImageAdapter, recorder)

    with pytest.raises(ProviderRejectedError) as excinfo:
        run(adapter.submit(image_request()))

    assert "b64_json" in str(excinfo.value)


def test_openai_image_does_not_collide_with_sora_in_the_registry() -> None:
    """
    El registry indexa por `provider_id`. Si el adaptador de imagen se hubiera llamado
    `openai` como Sora, la última clase registrada machacaría a la otra y **todos** los
    jobs de vídeo acabarían en el adaptador de imagen, o al revés. Comparten la clave de
    API, no la identidad.
    """
    registry = DbAdapterRegistry()

    assert OpenAIImageAdapter.provider_id != SoraAdapter.provider_id
    assert registry.get("openai").provider_id == "openai"
    assert registry.get("openai_image").provider_id == "openai_image"
    assert "video" in registry.get("openai").supported_modalities
    assert registry.get("openai_image").supported_modalities == ("image",)

    # Los modelos de imagen de OpenAI están sembrados contra el adaptador correcto.
    seeded = [m for m in MODELS if m.family == "OpenAI GPT Image"]
    assert seeded, "el catálogo tiene que ofrecer al menos un modelo de imagen de OpenAI"
    assert all(m.provider == "openai_image" for m in seeded)
    assert all(m.modality == "image" for m in seeded)
    assert all(m.cost_per_image is not None for m in seeded), (
        "sin cost_per_image el registry facturaría una imagen como si durase un segundo"
    )
    assert any(m.status == "active" for m in seeded)


def test_openai_image_poll_without_the_result_fails_instead_of_hanging() -> None:
    """
    El precio conocido de la decisión síncrona: el resultado vive en `ref.raw`, y
    `JobWorker._store_ref` no persiste `raw`. Un ref reconstruido desde base de datos no
    lo tiene. Tiene que fallar de forma terminal y explícita —la imagen ya está pagada—, no
    quedarse poleteando algo que nadie va a devolver.
    """
    adapter = OpenAIImageAdapter()

    status = run(adapter.poll(ProviderJobRef("openai_image", "img-1")))

    assert status.state == "failed"
    assert status.is_terminal
    assert status.should_refund, "si no entregamos la imagen, el usuario no la paga"
    assert "relanzar" in status.error


def test_poll_gate_is_per_provider_not_per_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    El gate contaba por `external_id`, así que doce planos concurrentes poleteaban doce
    veces el ritmo permitido — justo el escenario que dispara el 429 que el gate existe
    para evitar. El límite es del proveedor, no del job. Con reloj controlado se
    comprueba que tres jobs concurrentes se serializan a un intervalo cada uno, sin
    depender del tiempo de pared.
    """
    clock = _install_gate_clock(monkeypatch)
    recorder = Recorder(lambda r: json_response({"name": "op", "done": False}))
    adapter = make_adapter(VeoAdapter, recorder)
    adapter.min_poll_interval_s = 0.1

    async def poll_three_different_jobs() -> None:
        await asyncio.gather(
            *(
                adapter.poll(ProviderJobRef("google", f"op-{i}", f"/v1beta/op-{i}"))
                for i in range(3)
            )
        )

    run(poll_three_different_jobs())

    assert len(recorder.requests) == 3
    # El primero no espera; los otros dos, un intervalo cada uno. Comparten el ritmo del
    # proveedor aunque sean jobs distintos.
    assert clock.sleeps == [0.1, 0.1]
    assert clock.now >= 0.2


def test_poll_gate_does_not_grow_with_the_number_of_jobs() -> None:
    """El dict anterior nunca se purgaba: en un proceso de larga vida era una fuga
    proporcional a los jobs atendidos."""
    recorder = Recorder(lambda r: json_response({"name": "op", "done": False}))
    adapter = make_adapter(VeoAdapter, recorder)
    adapter.min_poll_interval_s = 0.0

    async def poll_many() -> None:
        for i in range(50):
            await adapter.poll(ProviderJobRef("google", f"op-{i}", f"/v1beta/op-{i}"))

    run(poll_many())

    assert isinstance(adapter._last_poll_at, float), "un instante, no un dict por job"
