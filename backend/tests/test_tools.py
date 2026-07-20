"""
Tests de la taxonomía runtime y las herramientas.

Estos tests no comprueban que el código "funcione": comprueban las cuatro propiedades
sobre las que se apoya el diseño entero, y que son justo las que se rompen en silencio
si alguien las toca sin querer.

1. Los `Literal` salen de la BD. Si algún día alguien hardcodea una lista de modelos
   "temporalmente", este test cae.
2. En preproducción las tools de generación **no existen**. No que estén prohibidas:
   que no se instancian. Es la única barrera real contra gastar créditos planificando.
3. Referenciar algo inexistente produce `UnknownEntityError` **con la lista de opciones
   válidas**. Sin esa lista el modelo no puede autocorregirse y repite el mismo nombre
   inventado turno tras turno.
4. Una referencia rota degrada a `ErrorBlock` sin romper el documento. Borrar un plano
   no puede costar un guion.

La BD se sustituye por un doble en memoria: estos tests son sobre la lógica de
construcción, no sobre SQL, y atarlos a Postgres los haría lentos y saltables.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.state import AgentMode
from app.artifacts.manager import ArtifactManager, EnrichmentContext, _resolve_blocks
from app.artifacts.types import (
    AssetRefBlock,
    ErrorBlock,
    PlanArtifactContent,
    ShotBlock,
    ShotRefBlock,
    TextBlock,
)
from app.taxonomy import repo
from app.taxonomy.builder import build_tools_for_mode
from app.taxonomy.repo import (
    CameraMotion,
    Element,
    GenModel,
    TaxonomySnapshot,
    VisualStyle,
)
from app.tools.base import ToolContext
from app.tools.errors import UnknownEntityError

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Dobles                                                                       #
# --------------------------------------------------------------------------- #


def make_model(model_id: str, modality: str, **kw: Any) -> GenModel:
    defaults = dict(
        family="Test",
        provider="test",
        label=model_id,
        description_llm=f"{modality} model",
        min_duration_s=2.0 if modality == "video" else None,
        max_duration_s=10.0 if modality == "video" else None,
        resolutions=("1080p",),
        aspects=("16:9", "9:16"),
        supports_i2v=True,
        supports_last_frame=False,
        supports_char_ref=True,
        supports_audio=False,
        cost_per_second=Decimal("0.10"),
        cost_per_image=Decimal("0.04"),
        credits_per_unit=16,
        min_plan="free",
        status="active",
        sunset_at=None,
    )
    defaults.update(kw)
    return GenModel(id=model_id, modality=modality, **defaults)  # type: ignore[arg-type]


def make_snapshot(
    *,
    plan: str = "pro",
    models: list[GenModel] | None = None,
    elements: list[Element] | None = None,
) -> TaxonomySnapshot:
    return TaxonomySnapshot(
        plan=plan,
        models=tuple(
            models
            if models is not None
            else [make_model("kling-3.0-turbo", "video"), make_model("flux-2-pro", "image")]
        ),
        motions=(
            CameraMotion(
                id="dolly-zoom",
                label="Dolly Zoom",
                description_llm="vertigo effect",
                provider_ref={"higgsfield": "uuid-1"},
                supports_strength=True,
                category="fx",
            ),
        ),
        styles=(
            VisualStyle(
                id="teal-orange",
                dimension="palette",
                label="Teal & Orange",
                description_llm="blockbuster palette",
                prompt_fragment="teal and orange grade",
            ),
        ),
        elements=tuple(
            elements
            if elements is not None
            else [
                Element(
                    id="11111111-1111-1111-1111-111111111111",
                    name="Marta",
                    role="Personaje",
                    url="https://example.test/marta.png",
                    meta="protagonista",
                    status="ready",
                )
            ]
        ),
    )


def enum_values(fragment: dict[str, Any]) -> list[str]:
    """
    Extrae los valores admitidos de un trozo de JSON Schema.

    Hace falta porque pydantic serializa `Literal["a","b"]` como `enum` pero
    `Literal["a"]` como `const`, y un catálogo con un solo elemento es un caso
    perfectamente normal aquí (una taxonomía recién sembrada).
    """
    if "enum" in fragment:
        return list(fragment["enum"])
    if "const" in fragment:
        return [fragment["const"]]
    for key in ("anyOf", "oneOf"):
        for option in fragment.get(key, []):
            values = enum_values(option)
            if values:
                return values
    if "items" in fragment:
        return enum_values(fragment["items"])
    return []


def make_ctx(mode: str = "production", credits: int = 5000) -> ToolContext:
    return ToolContext(
        project_id="22222222-2222-2222-2222-222222222222",
        user_id="33333333-3333-3333-3333-333333333333",
        conversation_id="44444444-4444-4444-4444-444444444444",
        mode=mode,
        credits_available=credits,
    )


class FakeDB:
    """
    Doble de `app.db`. Devuelve filas por prefijo de consulta.

    Es deliberadamente tonto: si un test necesita algo más listo, probablemente esté
    testeando SQL, y para eso hace falta Postgres de verdad, no un doble más elaborado.
    """

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _match(self, q: str) -> Any:
        normalized = " ".join(q.split())
        for needle, value in self.responses.items():
            if needle in normalized:
                return value
        return None

    async def fetch(self, q: str, *args: Any) -> list[Any]:
        self.calls.append((q, args))
        return self._match(q) or []

    async def fetchrow(self, q: str, *args: Any) -> Any:
        self.calls.append((q, args))
        value = self._match(q)
        if isinstance(value, list):
            return value[0] if value else None
        return value

    async def fetchval(self, q: str, *args: Any) -> Any:
        self.calls.append((q, args))
        return self._match(q)

    async def execute(self, q: str, *args: Any) -> str:
        self.calls.append((q, args))
        return "OK"

    @asynccontextmanager
    async def transaction(self):  # type: ignore[no-untyped-def]
        yield self


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch):
    """Instala el doble en todos los módulos que importaron `app.db`."""

    def install(responses: dict[str, Any] | None = None) -> FakeDB:
        double = FakeDB(responses)
        import app.artifacts.manager as manager_mod
        import app.taxonomy.repo as repo_mod
        import app.tools.brief as brief_mod
        import app.tools.elements as elements_mod
        import app.tools.generation as generation_mod
        import app.tools.meta as meta_mod
        import app.tools.project as project_mod
        import app.tools.shots as shots_mod

        for module in (
            repo_mod, project_mod, brief_mod, shots_mod, elements_mod,
            generation_mod, meta_mod, manager_mod,
        ):
            monkeypatch.setattr(module, "db", double, raising=False)
        return double

    return install


@pytest.fixture(autouse=True)
def clear_taxonomy_cache():
    """La caché es global y con TTL: sin esto, un test contaminaría al siguiente."""
    repo.invalidate_cache()
    yield
    repo.invalidate_cache()


# --------------------------------------------------------------------------- #
# 1. Los Literal se pueblan desde la BD                                        #
# --------------------------------------------------------------------------- #


async def test_literals_come_from_the_database(fake_db) -> None:
    """El enum del JSON Schema debe contener exactamente los ids que hay en la BD."""
    fake_db()
    snap = make_snapshot(
        models=[
            make_model("kling-3.0-turbo", "video"),
            make_model("seedance-2.0", "video"),
            make_model("flux-2-pro", "image"),
        ]
    )
    tools = await build_tools_for_mode(make_ctx("production"), snapshot=snap)
    by_name = {t.name: t for t in tools}

    schema = by_name["generate_video"].args_schema.model_json_schema()
    assert enum_values(schema["properties"]["model_id"]) == ["kling-3.0-turbo", "seedance-2.0"]
    assert "flux-2-pro" not in enum_values(schema["properties"]["model_id"])

    # Movimientos y elements salen del mismo snapshot, no de una constante.
    assert enum_values(schema["properties"]["camera_motion"]) == ["dolly-zoom"]
    assert enum_values(schema["properties"]["element_refs"]) == ["Marta"]

    # Y la descripción se reescribe con lo mismo que el esquema: no puede mentir.
    assert "kling-3.0-turbo" in by_name["generate_video"].description
    assert "flux-2-pro" not in by_name["generate_video"].description


async def test_literals_shrink_when_the_catalogue_shrinks(fake_db) -> None:
    """Apagar un modelo es un UPDATE: el toolset del turno siguiente ya no lo ofrece."""
    fake_db()
    before = await build_tools_for_mode(
        make_ctx("production"),
        snapshot=make_snapshot(
            models=[make_model("runway-gen4", "video"), make_model("kling-3.0-turbo", "video")]
        ),
    )
    after = await build_tools_for_mode(
        make_ctx("production"),
        snapshot=make_snapshot(models=[make_model("kling-3.0-turbo", "video")]),
    )

    def video_models(tools: list[Any]) -> list[str]:
        tool = next(t for t in tools if t.name == "generate_video")
        return enum_values(tool.args_schema.model_json_schema()["properties"]["model_id"])

    assert "runway-gen4" in video_models(before)
    assert "runway-gen4" not in video_models(after)


async def test_plan_restriction_is_indistinguishable_from_absence(fake_db, monkeypatch) -> None:
    """
    Un modelo fuera del plan no se marca como bloqueado: no se devuelve.

    Es la diferencia entre que el agente proponga algo que va a fallar y que ni se le
    ocurra proponerlo.
    """
    rows = [
        {
            "id": "seedance-2.0", "family": "Seedance", "provider": "bytedance",
            "modality": "video", "label": "Seedance 2.0", "description_llm": "premium",
            "min_duration_s": 2, "max_duration_s": 10, "resolutions": ["1080p"],
            "aspects": ["16:9"], "supports_i2v": True, "supports_last_frame": False,
            "supports_char_ref": True, "supports_audio": False, "cost_per_second": "0.5",
            "cost_per_image": None, "credits_per_unit": 80, "min_plan": "business",
            "status": "active", "sunset_at": None,
        },
        {
            "id": "kling-3.0-turbo", "family": "Kling", "provider": "kling",
            "modality": "video", "label": "Kling 3.0", "description_llm": "workhorse",
            "min_duration_s": 5, "max_duration_s": 10, "resolutions": ["1080p"],
            "aspects": ["16:9"], "supports_i2v": True, "supports_last_frame": False,
            "supports_char_ref": True, "supports_audio": False, "cost_per_second": "0.1",
            "cost_per_image": None, "credits_per_unit": 16, "min_plan": "free",
            "status": "active", "sunset_at": None,
        },
    ]
    fake_db({"from public.gen_models": rows})

    free_models = await repo.active_models("free", "video")
    business_models = await repo.active_models("business", "video")

    assert [m.id for m in free_models] == ["kling-3.0-turbo"]
    assert {m.id for m in business_models} == {"seedance-2.0", "kling-3.0-turbo"}
    # No hay ninguna señal de que exista algo bloqueado.
    assert all("seedance" not in m.summary_for_llm() for m in free_models)


async def test_retired_models_never_reach_the_catalogue(fake_db) -> None:
    """`status='retired'` se filtra en SQL; `deprecated` sobrevive pero etiquetado."""
    double = fake_db()
    await repo.active_models("pro", "video")
    issued = " ".join(" ".join(q.split()) for q, _ in double.calls)
    assert "status <> 'retired'" in issued, "el filtro debe ir en SQL, no en Python"

    deprecated = make_model("veo-2.5", "video", status="deprecated")
    assert "DEPRECATED" in deprecated.summary_for_llm()


# --------------------------------------------------------------------------- #
# 2. En preproducción no existen las tools de generación                       #
# --------------------------------------------------------------------------- #


async def test_preproduction_has_no_generation_tools(fake_db) -> None:
    """La restricción es estructural: no se instancian, así que no hay nada que invocar."""
    fake_db()
    snap = make_snapshot()
    tools = await build_tools_for_mode(make_ctx(AgentMode.PREPRODUCTION.value), snapshot=snap)
    names = {t.name for t in tools}

    for forbidden in (
        "generate_image", "generate_video", "generate_shot_batch",
        "generate_lipsync", "upscale_asset", "assemble_video",
    ):
        assert forbidden not in names, f"{forbidden} must not exist in preproduction"

    # Y no es que estén y no cobren: no hay ni una sola tool que consuma créditos.
    assert not any(t.consumes_credits for t in tools)

    # Lo que sí debe estar: planificar es todo lo que se puede hacer aquí.
    assert {"read_project", "create_shot", "define_element", "finalize_plan"} <= names


async def test_production_mounts_the_generation_tools(fake_db) -> None:
    fake_db()
    tools = await build_tools_for_mode(make_ctx(AgentMode.PRODUCTION.value), snapshot=make_snapshot())
    names = {t.name for t in tools}
    assert {"generate_image", "generate_video", "generate_shot_batch"} <= names
    assert any(t.consumes_credits for t in tools)
    # finalize_plan es de preproducción: el plan se cierra antes de rodar, no después.
    assert "finalize_plan" not in names


async def test_generation_tool_disappears_without_models(fake_db) -> None:
    """Sin un solo modelo de vídeo, la tool no se monta con un enum vacío: no se monta."""
    fake_db()
    snap = make_snapshot(models=[make_model("flux-2-pro", "image")])
    names = {t.name for t in await build_tools_for_mode(make_ctx("production"), snapshot=snap)}
    assert "generate_video" not in names
    assert "generate_shot_batch" not in names
    assert "generate_image" in names


async def test_switch_mode_catalogue_is_generated_not_hardcoded(fake_db) -> None:
    """`switch_mode` describe los otros modos construyendo sus tools de verdad."""
    fake_db()
    tools = await build_tools_for_mode(make_ctx("preproduction"), snapshot=make_snapshot())
    switch = next(t for t in tools if t.name == "switch_mode")

    modes = enum_values(switch.args_schema.model_json_schema()["properties"]["mode"])
    assert set(modes) == {"production", "edit"}
    assert "preproduction" not in modes  # no se ofrece el modo en el que ya se está

    # El catálogo que muestra coincide con lo que de verdad se monta allí.
    assert "generate_video" in switch.description
    production_names = {
        t.name for t in await build_tools_for_mode(make_ctx("production"), snapshot=make_snapshot())
    }
    listed = switch.description.split("- production:")[1].split("tools:")[1].split("\n")[0]
    for name in [n.strip() for n in listed.split(",")]:
        assert name in production_names


# --------------------------------------------------------------------------- #
# 3. Entidad inexistente → UnknownEntityError con las opciones válidas          #
# --------------------------------------------------------------------------- #


async def test_unknown_element_lists_the_valid_ones(fake_db) -> None:
    """Sin la lista de válidos el modelo no puede corregirse, y repite el nombre inventado."""
    fake_db()
    snap = make_snapshot(
        elements=[
            Element(id="a", name="Marta", role="Personaje", url="u", meta="", status="ready"),
            Element(id="b", name="El taller", role="Localización", url="u", meta="", status="ready"),
        ]
    )
    tool = next(
        t for t in await build_tools_for_mode(make_ctx("production"), snapshot=snap)
        if t.name == "generate_video"
    )

    with pytest.raises(UnknownEntityError) as excinfo:
        tool.resolve_elements(["Javier"])

    message = str(excinfo.value)
    assert "Javier" in message
    assert "Marta" in message and "El taller" in message
    assert excinfo.value.retry_strategy == "adjusted"


async def test_unknown_entity_error_is_returned_not_raised_to_the_caller(fake_db) -> None:
    """
    El ejecutor convierte el error en mensaje de herramienta con su `retry_hint`: el
    modelo lo lee y se autocorrige, en vez de que el turno se caiga.
    """
    fake_db()
    tool = next(
        t for t in await build_tools_for_mode(make_ctx("production"), snapshot=make_snapshot())
        if t.name == "generate_video"
    )
    content, artifact = await tool._arun(
        prompt="a shot", model_id="kling-3.0-turbo", duration_s=5, element_refs=["Nadie"]
    )
    assert "UnknownEntityError" in content
    assert "Marta" in content
    assert "retry with adjusted inputs" in content
    assert artifact is None


async def test_unknown_model_lists_models_of_the_right_modality(fake_db) -> None:
    fake_db()
    snap = make_snapshot(
        models=[make_model("kling-3.0-turbo", "video"), make_model("flux-2-pro", "image")]
    )
    tool = next(
        t for t in await build_tools_for_mode(make_ctx("production"), snapshot=snap)
        if t.name == "generate_video"
    )
    with pytest.raises(UnknownEntityError) as excinfo:
        tool.require_model("veo-3.0", "video")

    message = str(excinfo.value)
    assert "kling-3.0-turbo" in message
    assert "flux-2-pro" not in message  # no se sugiere un modelo de otra modalidad


# --------------------------------------------------------------------------- #
# 4. Las refs rotas degradan sin romper el documento                            #
# --------------------------------------------------------------------------- #


async def test_broken_shot_ref_degrades_to_error_block(fake_db) -> None:
    """Un plano borrado se convierte en `ErrorBlock`; el resto del documento sobrevive."""
    fake_db(
        {
            "from public.canvas_nodes n": [
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "position": 0,
                    "title": "Plano 1",
                    "text": "Marta entra",
                    "spec": {"framing": "wide"},
                    "shot_status": "ready",
                    "asset_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                    "asset_url": "https://example.test/shot1.mp4",
                }
            ]
        }
    )
    blocks = [
        TextBlock(text="Secuencia 1"),
        ShotRefBlock(shot_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ShotRefBlock(shot_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),  # borrado
    ]
    resolved = await _resolve_blocks(
        blocks, EnrichmentContext(project_id="22222222-2222-2222-2222-222222222222")
    )

    assert len(resolved) == 3, "el documento conserva todos sus bloques"
    assert isinstance(resolved[0], TextBlock)
    assert isinstance(resolved[1], ShotBlock) and resolved[1].title == "Plano 1"
    assert isinstance(resolved[2], ErrorBlock)
    assert resolved[2].ref_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert resolved[2].ref_kind == "shot"


async def test_broken_asset_ref_degrades_too(fake_db) -> None:
    fake_db({"from public.assets": []})
    resolved = await _resolve_blocks(
        [AssetRefBlock(asset_id="dddddddd-dddd-dddd-dddd-dddddddddddd", caption="toma 2")],
        EnrichmentContext(project_id="22222222-2222-2222-2222-222222222222"),
    )
    assert isinstance(resolved[0], ErrorBlock)
    assert resolved[0].ref_kind == "asset"


async def test_artifact_with_broken_refs_still_opens(fake_db) -> None:
    """Leer un artefacto nunca es un error de aplicación: como mucho llega degradado."""
    fake_db(
        {
            "from public.artifacts where id": {
                "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "kind": "plan",
                "version": 3,
                "created_by": "agent",
                "created_at": "2026-07-20",
                "content": PlanArtifactContent(
                    title="Plan",
                    estimated_credits=480,
                    blocks=[
                        TextBlock(text="Tres planos"),
                        ShotRefBlock(shot_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                    ],
                ).model_dump(mode="json"),
            },
            "from public.canvas_nodes n": [],
        }
    )
    doc = await ArtifactManager("22222222-2222-2222-2222-222222222222").aget(
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )

    assert doc["version"] == 3
    assert doc["estimated_credits"] == 480
    assert doc["broken_refs"] == 1
    assert [b["type"] for b in doc["blocks"]] == ["text", "error"]


async def test_unreadable_content_degrades_instead_of_raising(fake_db) -> None:
    """Un contenido que ya no valida (esquema evolucionado) no debe perder el documento."""
    fake_db(
        {
            "from public.artifacts where id": {
                "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "kind": "plan",
                "version": 1,
                "created_by": "agent",
                "created_at": "2026-07-20",
                "content": {"blocks": [{"type": "from_the_future", "payload": 1}]},
            }
        }
    )
    doc = await ArtifactManager("22222222-2222-2222-2222-222222222222").aget(
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )
    assert doc["content_type"] == "error"
    assert doc["blocks"][0]["type"] == "error"


# --------------------------------------------------------------------------- #
# Separación content / ui_payload                                              #
# --------------------------------------------------------------------------- #


async def test_tools_separate_content_from_ui_payload(fake_db) -> None:
    """
    El contrato de retorno no es decorativo: `content` es lo único que entra en el
    contexto del LLM. Si una tool devolviera el payload entero, cada llamada costaría
    un orden de magnitud más de tokens sin mejorar una sola decisión.
    """
    fake_db()
    tool = next(
        t for t in await build_tools_for_mode(make_ctx("production"), snapshot=make_snapshot())
        if t.name == "estimate_cost"
    )
    content, payload = await tool._arun_impl(
        items=[{"model_id": "kling-3.0-turbo", "count": 3, "duration_s": 5}]
    )

    assert isinstance(content, str)
    assert "240 credits" in content  # 5 s x 16 créditos x 3
    assert payload["total_credits"] == 240
    assert payload["items"][0]["model_id"] == "kling-3.0-turbo"
    assert len(content) < len(str(payload)) * 3


async def test_every_tool_description_says_when_not_to_use_it(fake_db) -> None:
    """
    Patrón PostHog: la descripción dice QUÉ hace, CUÁNDO usarla y CUÁNDO NO.

    El "cuándo no" es la mitad que más ahorra: sin ella el modelo llama a la tool cara
    en cuanto encuentra una excusa remotamente plausible.
    """
    fake_db()
    for mode in ("preproduction", "production", "edit"):
        for tool in await build_tools_for_mode(make_ctx(mode), snapshot=make_snapshot()):
            assert "USE THIS" in tool.description, f"{tool.name} lacks a 'when to use'"
            assert "DO NOT" in tool.description, f"{tool.name} lacks a 'when not to use'"
            assert len(tool.description) > 200, f"{tool.name} description is too vague"
