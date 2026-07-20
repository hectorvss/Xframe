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
):
    os.environ.setdefault(_var, f"test-{_var.lower()}")

from app.providers._http import RetryPolicy  # noqa: E402
from app.providers.base import (  # noqa: E402
    ElementRef,
    GenerationAdapter,
    GenerationRequest,
    ModelSpec,
    ProviderJobRef,
)
from app.providers.flux import FluxAdapter  # noqa: E402
from app.providers.hailuo import HailuoAdapter  # noqa: E402
from app.providers.higgsfield import HiggsfieldAdapter  # noqa: E402
from app.providers.kling import KlingAdapter  # noqa: E402
from app.providers.registry import DbAdapterRegistry, UnknownProviderError  # noqa: E402
from app.providers.seed import MODELS, MOTIONS, STYLES, credits_per_unit  # noqa: E402
from app.providers.seedance import SeedanceAdapter  # noqa: E402
from app.providers.sora import SoraAdapter  # noqa: E402
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
    assert parameters["durationSeconds"] == 8
    assert parameters["aspectRatio"] == "16:9"


def test_veo_poll_running_then_succeeded() -> None:
    responses = [
        {"name": "op", "done": False},
        {
            "name": "op",
            "done": True,
            "response": {"generatedVideos": [{"video": {"uri": "https://files/v.mp4"}}]},
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


def test_flux_sends_every_element_as_reference() -> None:
    """FLUX.2 admite hasta 8 referencias en una llamada, y es la vía barata a la
    continuidad de personaje. Mandar solo la primera desperdiciaría la capacidad."""
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
    assert body["image_prompt"] == "https://cdn/0.png"
    assert len(body["reference_images"]) == 3


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
    adapter = make_adapter(SeedanceAdapter, recorder)

    with pytest.raises(ProviderError) as excinfo:
        run(adapter.submit(video_request(model_id="seedance-2.0")))

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

    # `Retry-After` del proveedor manda sobre nuestro cálculo, pero no por encima del techo.
    assert policy.delay_for(0, retry_after_s=7.5) == 7.5
    assert policy.delay_for(0, retry_after_s=900) == 20.0


# --------------------------------------------------------------------------- #
# 7. Throttle de polling                                                       #
# --------------------------------------------------------------------------- #


def test_poll_gate_enforces_min_interval() -> None:
    """Runway documenta 1 req/5 s y el resto agradece el respiro. Se comprueba que el
    gate espera de verdad, con un intervalo reducido para no alargar la suite."""
    recorder = Recorder(lambda r: json_response({"name": "op", "done": False}))
    adapter = make_adapter(VeoAdapter, recorder)
    adapter.min_poll_interval_s = 0.25
    ref = ProviderJobRef("google", "op", "/v1beta/op")

    async def poll_twice() -> float:
        start = time.monotonic()
        await adapter.poll(ref)
        await adapter.poll(ref)
        return time.monotonic() - start

    elapsed = run(poll_twice())
    assert elapsed >= 0.25
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


def test_registry_cache_expires() -> None:
    """El TTL corto es la razón de que apagar un modelo sea un UPDATE. Un TTL infinito
    convertiría la ventaja de tener esto en datos en una desventaja operativa."""
    registry = DbAdapterRegistry(ttl_s=0.05)
    loads = {"n": 0}

    async def fake_load() -> dict[str, ModelSpec]:
        loads["n"] += 1
        return {"veo-3.1": spec("veo-3.1", provider="google")}

    registry._load = fake_load  # type: ignore[method-assign]

    async def scenario() -> None:
        await registry.models()
        await registry.models()
        assert loads["n"] == 1, "dentro del TTL no se recarga"
        await asyncio.sleep(0.06)
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
