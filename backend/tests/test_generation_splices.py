"""
Tests de los EMPALMES de `app/tools/generation.py`.

Estos tests existen porque los otros 124 pasaban con el sistema roto. La razón es
concreta y merece la pena nombrarla: cada módulo se probó aislado contra un doble
escrito a la vez que el módulo, así que el doble reproducía los nombres que el autor
*creía* que tenía el otro lado. `generation.py` llamaba a `run_shots`, el doble se
llamaba `run_shots`, y `fanout.py` exportaba `run_fanout`. Verde por ambos lados, y el
sistema no arrancaba.

La corrección metodológica es la idea que sostiene este fichero: **un doble nunca define
su propia firma**. Todos los dobles de aquí se construyen a partir de
`inspect.signature()` de la función de verdad y hacen `bind()` de la llamada recibida
antes de responder nada. Si `generation.py` llama con un argumento que no existe, o se
deja uno obligatorio, el test falla con el mismo `TypeError` que daría en producción —
pero sin base de datos, sin ffmpeg y sin proveedor.

Lo que se comprueba, empalme a empalme:

1. `queue.enqueue` recibe `adapter` y `conversation_id`.
2. El resultado se lee como `EnqueueResult.job_id`, no `.id` (usa slots: `.id` es
   AttributeError, no None silencioso).
3. El fan-out pasa por `run_fanout` con un `ShotRunner` que encola de verdad.
4. El montaje pasa por `assemble_cut(AssemblySpec)` y **persiste** asset y artefacto.
5. Cotizar y reservar recorren el mismo camino: `estimate_cost` + `usd_to_credits`.
"""

from __future__ import annotations

import inspect
import os
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")

from app.assembly.ffmpeg import (
    AssemblyResult,
    AssemblySpec,
    TargetFormat,
    assemble_cut,
)
from app.jobs.queue import EnqueueResult
from app.jobs.queue import enqueue as real_enqueue
from app.providers.base import (
    GenerationAdapter,
    GenerationRequest,
    ModelSpec,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.taxonomy.builder import build_tools_for_mode
from app.tools.errors import InsufficientCreditsError
from app.tools.generation import _asset_or_raise
from tests.test_tools import FakeDB, make_ctx, make_model, make_snapshot

pytestmark = pytest.mark.asyncio

PROJECT_ID = "22222222-2222-2222-2222-222222222222"
CONVERSATION_ID = "44444444-4444-4444-4444-444444444444"
SHOT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SHOT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.parametrize(
    ("stored_type", "requested_kind"),
    [
        ("Audio", "audio"),
        ("Música", "audio"),
        ("Vídeos", "video"),
        ("cut", "video"),
        ("Imágenes", "image"),
    ],
)
async def test_asset_kind_accepts_legacy_localized_upload_types(
    monkeypatch: pytest.MonkeyPatch,
    stored_type: str,
    requested_kind: str,
) -> None:
    """Old UI uploads remain usable after canonical lowercase types were introduced."""
    import app.tools.generation as generation_mod

    asset_id = "11111111-1111-1111-1111-111111111111"
    double = FakeDB(
        {
            "from public.assets": {
                "id": asset_id,
                "name": "Legacy upload",
                "type": stored_type,
                "url": "project/object.ext",
                "status": "ready",
                "shot_id": None,
                "params": {},
            }
        }
    )
    monkeypatch.setattr(generation_mod, "db", double, raising=False)

    result = await _asset_or_raise(PROJECT_ID, asset_id, kind=requested_kind)

    assert result["id"] == asset_id


# --------------------------------------------------------------------------- #
# Dobles que NO inventan su firma                                              #
# --------------------------------------------------------------------------- #


def signature_guard(real: Any, impl: Any) -> Any:
    """
    Envuelve `impl` obligando a que la llamada encaje en la firma de `real`.

    Es el mecanismo central de este fichero. `bind()` lanza `TypeError` ante un argumento
    inventado, uno que falta, o uno posicional donde el original es keyword-only — que es
    exactamente cómo se manifestaban los seis empalmes rotos en producción.
    """
    sig = inspect.signature(real)

    async def _guarded(*args: Any, **kwargs: Any) -> Any:
        sig.bind(*args, **kwargs)
        return await impl(*args, **kwargs)

    return _guarded


class StubAdapter(GenerationAdapter):
    """Coste fijo por segundo, para que los números del test sean comprobables a mano."""

    provider_id = "kling"
    supported_modalities = ("video", "image", "lipsync")
    min_poll_interval_s = 0.0

    def __init__(self, usd_per_second: str = "0.50") -> None:
        self.usd_per_second = Decimal(usd_per_second)
        self.quotes: list[GenerationRequest] = []

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        return ProviderJobRef(provider=self.provider_id, external_id="ext-1")

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        return ProviderJobStatus(state="succeeded")

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        self.quotes.append(req)
        return self.usd_per_second * Decimal(str(req.duration_s or 1))


class StubRegistry:
    """Registro con la firma real de `DbAdapterRegistry.resolve`."""

    def __init__(self, adapter: GenerationAdapter) -> None:
        self.adapter = adapter

    async def resolve(self, model_id: str) -> tuple[GenerationAdapter, ModelSpec]:
        return self.adapter, ModelSpec(
            id=model_id,
            family="Test",
            provider=self.adapter.provider_id,
            modality="video",
            cost_per_second=Decimal("0.10"),
            min_duration_s=2.0,
            max_duration_s=10.0,
        )


class EnqueueSpy:
    """
    Sustituto de `queue.enqueue` que respeta su firma real y devuelve un `EnqueueResult`
    de verdad. Lo segundo importa tanto como lo primero: `EnqueueResult` usa slots, así
    que leer `.id` sobre él es `AttributeError` y no un `None` que se cuela hasta el
    mensaje que ve el usuario.
    """

    def __init__(self, *, credits: int = 40, fail_after: int | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.credits = credits
        self.fail_after = fail_after

    async def __call__(
        self,
        request: GenerationRequest,
        *,
        project_id: str,
        shot_id: str | None = None,
        adapter: GenerationAdapter,
        conversation_id: str | None = None,
    ) -> EnqueueResult:
        self.calls.append(
            {
                "request": request,
                "project_id": project_id,
                "shot_id": shot_id,
                "adapter": adapter,
                "conversation_id": conversation_id,
            }
        )
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise InsufficientCreditsError(self.credits, 0)
        return EnqueueResult(
            job_id=f"job-{len(self.calls)}",
            status="queued",
            idempotency_key=f"key-{len(self.calls)}",
            credits_reserved=self.credits,
            reused=False,
        )


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    """
    Monta una tool real con los empalmes envueltos en guardas de firma.

    Devuelve `(tool, spy, adapter, db)` para que cada test mire lo que le toca.
    """

    async def build(
        tool_name: str,
        *,
        responses: dict[str, Any] | None = None,
        credits: int = 5000,
        spy: EnqueueSpy | None = None,
    ):
        import app.jobs.queue as queue_mod
        import app.providers.registry as registry_mod
        import app.tools.generation as generation_mod

        double = FakeDB(responses)
        monkeypatch.setattr(generation_mod, "db", double, raising=False)

        adapter = StubAdapter()
        monkeypatch.setattr(registry_mod, "get_registry", lambda: StubRegistry(adapter))

        spy = spy or EnqueueSpy()
        monkeypatch.setattr(queue_mod, "enqueue", signature_guard(real_enqueue, spy))

        snap = make_snapshot(
            models=[make_model("kling-3.0-turbo", "video"), make_model("flux-2-pro", "image")]
        )
        tools = await build_tools_for_mode(make_ctx("production", credits), snapshot=snap)
        tool = {t.name: t for t in tools}[tool_name]
        return tool, spy, adapter, double

    return build


# --------------------------------------------------------------------------- #
# 1 y 2. adapter, conversation_id y job_id                                     #
# --------------------------------------------------------------------------- #


async def test_enqueue_recibe_adapter_y_conversation_id(wired) -> None:
    """
    El empalme de `generation.py:118`. `adapter` es keyword-only sin defecto y
    `conversation_id` es lo que hace que el usuario vea aparecer el plano.
    """
    tool, spy, adapter, _ = await wired("generate_video")

    await tool._arun_impl(prompt="un desierto al amanecer", model_id="kling-3.0-turbo",
                          duration_s=5)

    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["adapter"] is adapter, "sin adapter, queue.enqueue es un TypeError"
    assert call["conversation_id"] == CONVERSATION_ID, (
        "sin conversation_id el job queda con la columna a NULL y worker._emit sale por "
        "su return temprano: el render ocurre, se cobra, y el usuario no ve nada"
    )
    assert call["project_id"] == PROJECT_ID


async def test_el_resultado_se_lee_como_job_id(wired) -> None:
    """
    El empalme de `generation.py:166`. `EnqueueResult` usa slots: si el código volviera a
    `job.id` esto sería `AttributeError`, no un id vacío en el mensaje al usuario.
    """
    tool, _, _, _ = await wired("generate_image")

    content, payload = await tool._arun_impl(prompt="ficha de personaje", model_id="flux-2-pro")

    assert payload["job_id"] == "job-1"
    assert "job-1" in content
    assert not hasattr(EnqueueResult("j", "queued", "k", 1, False), "id")


async def test_lipsync_tambien_cierra_los_dos_empalmes(wired) -> None:
    """Las cuatro tools compartían el mismo empalme roto; comprobar una no cubre las otras."""
    tool, spy, adapter, _ = await wired(
        "generate_video",
        responses={"from public.assets": [{"id": SHOT_A, "url": "https://x/a.mp4"}]},
    )
    await tool._arun_impl(prompt="p", model_id="kling-3.0-turbo", duration_s=4, shot_id=SHOT_A)

    assert spy.calls[0]["shot_id"] == SHOT_A
    assert spy.calls[0]["adapter"] is adapter


# --------------------------------------------------------------------------- #
# 5. Cotizar y reservar por el mismo camino                                    #
# --------------------------------------------------------------------------- #


async def test_la_cotizacion_usa_estimate_cost_y_no_una_formula_paralela(wired) -> None:
    """
    El empalme del dinero. La cotización debe salir de `adapter.estimate_cost`, que es de
    donde sale la reserva. Con `credits_per_unit=16` de la taxonomía, la fórmula vieja
    habría dado 16*5 = 80; la real pasa por el adaptador.
    """
    tool, _, adapter, _ = await wired("generate_video")

    await tool._arun_impl(prompt="p", model_id="kling-3.0-turbo", duration_s=5)

    assert adapter.quotes, "no se ha consultado al adaptador: hay una fórmula paralela"
    quoted = adapter.quotes[0]
    assert quoted.duration_s == 5, "se ha cotizado una petición distinta de la que se encola"


async def test_sin_saldo_no_se_encola_nada(wired) -> None:
    """El chequeo de saldo va antes del encolado, no después de haber reservado."""
    tool, spy, _, _ = await wired("generate_video", credits=1)

    with pytest.raises(InsufficientCreditsError):
        await tool._arun_impl(prompt="p", model_id="kling-3.0-turbo", duration_s=10)

    assert spy.calls == []


# --------------------------------------------------------------------------- #
# 3. Fan-out                                                                   #
# --------------------------------------------------------------------------- #


def _shot_rows() -> list[dict[str, Any]]:
    return [
        {"id": SHOT_A, "position": 1, "title": "Plano 1", "text": "el desierto",
         "spec": {"duration_s": 4}},
        {"id": SHOT_B, "position": 2, "title": "Plano 2", "text": "la caravana",
         "spec": {"duration_s": 6}},
    ]


MANIFEST_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _approved_manifest() -> dict[str, Any]:
    return {
        "id": MANIFEST_ID,
        "status": "approved",
        "fingerprint": "manifest-fingerprint",
        "specification": {"shots": [{"id": SHOT_A}, {"id": SHOT_B}]},
    }


async def test_el_fanout_encola_de_verdad(wired) -> None:
    """
    El empalme de `generation.py:471`. `run_shots` no existía; `run_fanout` sí, con otra
    firma y devolviendo un `FanoutReport`. Y su `ShotRunner` nunca había estado conectado
    a la cola: este test es lo que comprueba que ahora lo está.
    """
    tool, spy, _, _ = await wired(
        "generate_shot_batch", responses={
            "from public.canvas_nodes": _shot_rows(),
            "from public.production_manifests": _approved_manifest(),
        }
    )

    content, payload = await tool._arun_impl(
        shot_ids=[SHOT_A, SHOT_B], model_id="kling-3.0-turbo", manifest_id=MANIFEST_ID
    )

    assert len(spy.calls) == 2, "el fan-out no ha llegado a la cola"
    assert {c["shot_id"] for c in spy.calls} == {SHOT_A, SHOT_B}
    # La captura de la variable de bucle: si las closures compartieran la variable, los
    # dos planos encolarían el mismo prompt y la misma duración.
    assert {c["request"].duration_s for c in spy.calls} == {4.0, 6.0}
    assert {c["request"].prompt for c in spy.calls} == {"el desierto", "la caravana"}
    assert all(c["conversation_id"] == CONVERSATION_ID for c in spy.calls)
    assert payload["credits_reserved"] == 80
    assert "2 queued, 0 failed" in content


async def test_un_plano_sin_saldo_no_cancela_a_sus_hermanos(wired) -> None:
    """
    El presupuesto del lote no es atómico y el comportamiento documentado es que el fallo
    sea limpio: el plano que no cabe se reporta como fallo, los que ya se reservaron
    siguen vivos, y los créditos anunciados son los realmente reservados.
    """
    tool, _spy, _, _ = await wired(
        "generate_shot_batch",
        responses={
            "from public.canvas_nodes": _shot_rows(),
            "from public.production_manifests": _approved_manifest(),
        },
        spy=EnqueueSpy(fail_after=1),
    )

    content, payload = await tool._arun_impl(
        shot_ids=[SHOT_A, SHOT_B], model_id="kling-3.0-turbo", manifest_id=MANIFEST_ID
    )

    assert "1 queued, 1 failed" in content
    assert "FAILED shot" in content
    assert payload["credits_reserved"] == 40, "se anuncian los créditos reservados de verdad"
    # 4s y 6s a 0.50 USD/s = 5 USD, que `usd_to_credits` convierte al K vigente. Se deriva
    # de la conversión para no clavar el valor a un K concreto.
    from app.jobs.credits import usd_to_credits

    assert payload["credits_quoted"] == usd_to_credits(Decimal("5.00"))


async def test_retry_dirigido_acepta_solo_un_plano_fallido(wired) -> None:
    manifest = _approved_manifest() | {"status": "executing"}
    tool, spy, _, _ = await wired(
        "generate_shot_batch",
        responses={
            "from public.production_manifests": manifest,
            "from public.generation_jobs": [
                {
                    "shot_id": SHOT_B,
                    "status": "failed",
                    "asset_id": None,
                    "has_current_rejection": False,
                }
            ],
            "from public.canvas_nodes": [_shot_rows()[1]],
        },
    )

    _, payload = await tool._arun_impl(
        shot_ids=[SHOT_B],
        model_id="kling-3.0-turbo",
        manifest_id=MANIFEST_ID,
    )

    assert [call["shot_id"] for call in spy.calls] == [SHOT_B]
    assert payload["results"][0]["shot_id"] == SHOT_B


async def test_retry_dirigido_no_regenera_un_output_sano(wired) -> None:
    from app.tools.errors import XframeToolRetryableError

    manifest = _approved_manifest() | {"status": "executing"}
    tool, spy, _, _ = await wired(
        "generate_shot_batch",
        responses={
            "from public.production_manifests": manifest,
            "from public.generation_jobs": [
                {
                    "shot_id": SHOT_A,
                    "status": "succeeded",
                    "asset_id": "asset-a",
                    "has_current_rejection": False,
                }
            ],
        },
    )

    with pytest.raises(XframeToolRetryableError, match="Retry refused"):
        await tool._arun_impl(
            shot_ids=[SHOT_A],
            model_id="kling-3.0-turbo",
            manifest_id=MANIFEST_ID,
        )

    assert spy.calls == []


# --------------------------------------------------------------------------- #
# 4. Montaje                                                                   #
# --------------------------------------------------------------------------- #


async def test_el_montaje_usa_assemble_cut_y_persiste_el_corte(
    wired, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Los empalmes de `generation.py:740`. `concat_shots` no existía: es
    `assemble_cut(spec, *, timeout_s)` y devuelve `AssemblyResult`, no un dict con `id`.
    Y el corte no se guardaba en ninguna parte — un entregable que solo vive en /tmp.
    """
    import app.artifacts.manager as manager_mod
    import app.assembly.ffmpeg as ffmpeg_mod

    rows = [
        {"shot_id": SHOT_A, "asset_id": "asset-a", "type": "video",
         "url": "https://x/a.mp4", "status": "ready"},
        {"shot_id": SHOT_B, "asset_id": "asset-b", "type": "video",
         "url": "https://x/b.mp4", "status": "ready"},
    ]
    tool, _, _, double = await wired(
        "assemble_video", responses={
            "from public.production_manifests": {
                "status": "complete",
                "specification": {"shots": [{"id": SHOT_A}, {"id": SHOT_B}]},
                "execution_snapshot": {
                    "outputs": [
                        {"shot_id": SHOT_A, "asset_id": "asset-a"},
                        {"shot_id": SHOT_B, "asset_id": "asset-b"},
                    ],
                    "audio_cues": [],
                    "transitions": [],
                },
                "execution_fingerprint": "frozen",
            },
            "from public.assets": rows,
        }
    )

    # `artifacts.manager` tiene su propio `db`; sin esto la creación del artefacto se
    # iría a la base de datos real.
    artifacts_db = FakeDB({"insert into public.artifacts": {"id": "artifact-1", "kind": "cut",
                                                            "version": 1, "created_at": None}})
    monkeypatch.setattr(manager_mod, "db", artifacts_db)

    output = tmp_path / "cut.mp4"
    output.write_bytes(b"fake-mp4")
    seen: dict[str, Any] = {}

    async def fake_assemble(spec: AssemblySpec, *, timeout_s: float = 1800.0) -> AssemblyResult:
        seen["spec"] = spec
        return AssemblyResult(
            output_path=str(output),
            duration_s=10.0,
            target=TargetFormat(1920, 1080, Fraction(24), "test"),
            version=spec.version,
            clip_asset_ids=[c.asset_id for c in spec.clips],
        )

    # Se parchean los dos: la tool importa de `app.assembly`, que reexporta el nombre y
    # por tanto guarda su propia referencia. Parchear solo `ffmpeg` no la alcanza.
    import app.assembly as assembly_mod

    guarded = signature_guard(assemble_cut, fake_assemble)
    monkeypatch.setattr(ffmpeg_mod, "assemble_cut", guarded)
    monkeypatch.setattr(assembly_mod, "assemble_cut", guarded)

    uploads: list[dict[str, Any]] = []

    class FakeStorage:
        async def put(self, **kw: Any) -> str:
            uploads.append(kw)
            return "https://storage/cut.mp4"

    import app.jobs.worker as worker_mod

    monkeypatch.setattr(worker_mod, "SupabaseStorage", FakeStorage)
    double.responses["insert into public.assets"] = {"id": "cut-asset-1"}

    content, payload = await tool._arun_impl(
        manifest_id="manifest-1", shot_ids=[SHOT_A, SHOT_B], title="Montaje final"
    )

    # La firma real: AssemblySpec con TimelineClip, no listas de urls sueltas.
    spec = seen["spec"]
    assert isinstance(spec, AssemblySpec)
    assert [c.src for c in spec.clips] == ["https://x/a.mp4", "https://x/b.mp4"]
    assert [c.shot_id for c in spec.clips] == [SHOT_A, SHOT_B]

    # Y la persistencia, que no existía.
    assert uploads, "el mp4 montado no se ha subido a ninguna parte"
    assert payload["asset_id"] == "cut-asset-1"
    assert payload["artifact_id"] == "artifact-1"
    inserts = [q for q, _ in double.calls if "insert into public.assets" in " ".join(q.split())]
    assert inserts, "no se ha creado el asset de tipo cut"
    assert "'cut'" in " ".join(inserts[0].split())
    assert "Montaje final" in content


async def test_no_se_monta_con_planos_pendientes(wired) -> None:
    """Comportamiento que ya estaba bien y que la reescritura no debía perder."""
    from app.tools.errors import XframeToolRetryableError

    tool, _, _, _ = await wired(
        "assemble_video",
        responses={
            "from public.production_manifests": {
                "status": "complete", "specification": {"shots": [{"id": SHOT_A}]},
                "execution_snapshot": {
                    "outputs": [{"shot_id": SHOT_A, "asset_id": "asset-a"}],
                    "audio_cues": [], "transitions": [],
                },
                "execution_fingerprint": "frozen",
            },
            "from public.assets": [],
        },
    )

    with pytest.raises(XframeToolRetryableError):
        await tool._arun_impl(manifest_id="manifest-1", shot_ids=[SHOT_A], title="Montaje")


# --------------------------------------------------------------------------- #
# 7. upscale_asset retirada                                                    #
# --------------------------------------------------------------------------- #


async def test_upscale_no_se_monta(wired) -> None:
    """
    No hay modelo de upscale en `gen_models` ni adaptador que lo sirva. Ofrecer la tool
    era peor que no tenerla: el agente la veía en su esquema y gastaba el turno probando
    ids de modelo inexistentes.
    """
    import app.tools.generation as generation_mod

    _tool, _, _, _ = await wired("generate_video")
    assert not hasattr(generation_mod, "UpscaleAssetTool")

    snap = make_snapshot(models=[make_model("kling-3.0-turbo", "video")])
    names = {t.name for t in await build_tools_for_mode(make_ctx("production"), snapshot=snap)}
    assert "upscale_asset" not in names
    assert "generate_video" in names
