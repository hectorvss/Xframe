"""
Un turno completo, de punta a punta.

Lo que se finge: **el LLM y los proveedores de generación**. Nada más. El grafo, el
estado, los reductores, el checkpointer de Postgres, la taxonomía, el contexto, las tools,
la cola, el worker y el bus son los de producción, corriendo contra una base de datos de
verdad.

Esa frontera no es una comodidad, es la tesis del fichero. Los 124 tests unitarios que
había el 20/07/2026 estaban en verde con el sistema sin arrancar, y estaban en verde
precisamente porque cada uno sustituía por un doble la mitad del contrato que no estaba
probando. Un doble implementa siempre la firma que su autor imagina. Lo único que se puede
fingir sin perder la propiedad que aquí se busca son las dos fronteras que cuestan dinero
de verdad: el modelo y los proveedores.

La traza que se comprueba, salto a salto:

    mensaje → ROOT → tool call → fan-out (`Send`) → ROOT_TOOLS → tool de generación
           → enqueue (reserva de créditos) → worker (claim → submit → poll → descarga)
           → asset en BD → evento en el bus → SSE

Y lo que se afirma al final es lo que le importa al usuario: **el asset está en la base de
datos y el evento ha llegado al bus**.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar

import pytest

from tests.integration.conftest import Seed, wait_for_job

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# LLM fingido                                                                  #
# --------------------------------------------------------------------------- #


class FakeChat:
    """
    Modelo guionizado.

    Se sustituye la clase `ChatAnthropic` completa, no la respuesta: `RootNode` la
    instancia él mismo con su propia configuración, y un doble que solo reemplazara el
    valor devuelto no ejercitaría ni el montaje del toolset ni el `bind_tools`, que es
    donde vive el esquema generado desde la taxonomía.

    El guion se consume por llamada. La primera respuesta pide una generación; la segunda
    cierra el turno sin tool calls, que es lo que enruta a MEMORY_COLLECTOR y de ahí a
    END. Cualquier modelo que no sea el root (el colector de memoria usa `model_fast`)
    recibe siempre un `[Done]`, para que la memoria no interfiera con lo que se mide.
    """

    def __init__(self, *, model: str = "", **_: Any) -> None:
        self.model = model
        self._tools: list[Any] = []

    #: Guion compartido por todas las instancias del root dentro de un test. De clase y
    #: no de instancia a propósito: `RootNode` construye un `ChatAnthropic` nuevo en cada
    #: paso por el nodo, así que un guion por instancia se reiniciaría en cada vuelta y el
    #: modelo pediría la misma generación una y otra vez.
    script: ClassVar[list[Any]] = []
    calls: ClassVar[list[list[Any]]] = []
    root_models: ClassVar[set[str]] = set()

    def bind_tools(self, tools: Any, **_: Any) -> FakeChat:
        self._tools = list(tools)
        return self

    async def ainvoke(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        from langchain_core.messages import AIMessage

        FakeChat.calls.append(list(messages))

        if self.model not in FakeChat.root_models:
            return AIMessage(content="[Done]")

        if FakeChat.script:
            return FakeChat.script.pop(0)
        return AIMessage(content="Listo. Te aviso cuando el plano esté renderizado.")

    @property
    def tool_names(self) -> list[str]:
        return [getattr(t, "name", "") for t in self._tools]


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch, seed: Seed) -> type[FakeChat]:
    """
    Enchufa `FakeChat` allí donde se importa `ChatAnthropic`.

    Dos sitios y los dos hacen falta: `executables` la importa a nivel de módulo (así que
    hay que parchear el atributo ya vinculado) y `compaction`/`memory.collector` la
    importan perezosamente dentro de la función (así que hay que parchear el paquete).
    """
    pytest.importorskip("langchain_anthropic", reason="el e2e del turno necesita el cliente del LLM")

    import langchain_anthropic

    from app.agent import executables
    from app.config import get_settings

    FakeChat.script = []
    FakeChat.calls = []
    FakeChat.root_models = {get_settings().model_root}

    monkeypatch.setattr(executables, "ChatAnthropic", FakeChat)
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChat)
    return FakeChat


# --------------------------------------------------------------------------- #
# El turno                                                                     #
# --------------------------------------------------------------------------- #


async def test_turno_completo_de_mensaje_a_asset(
    db: Any,
    seed: Seed,
    bus: Any,
    worker: Any,
    registry: Any,
    adapter: Any,
    fake_llm: type[FakeChat],
) -> None:
    """
    Un mensaje del usuario acaba en un asset listo en la BD y en un evento en el bus.

    Es el único test del repositorio que ejecuta las dos mitades de cada contrato a la
    vez. Si mañana alguien renombra `run_fanout`, cambia la aridad de
    `XframeContextManager` o deja de propagar el `conversation_id` a la cola, este test se
    pone rojo aunque todos los unitarios sigan verdes.
    """
    pytest.importorskip("langgraph", reason="el e2e del turno necesita el grafo")

    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from app.agent.runner import ConversationRunner
    from app.config import get_settings

    # El modelo pide un plano. El id de la tool call es lo que el router usa para abrir la
    # rama del fan-out (`Send`), así que tiene que estar y ser único.
    fake_llm.script = [
        AIMessage(
            content="Voy a renderizar el plano 1.",
            tool_calls=[
                {
                    "name": "generate_video",
                    "id": "call-plano-1",
                    "args": {
                        "prompt": "Marta entra en el bar a contraluz, plano medio",
                        "model_id": seed.video_model,
                        "duration_s": 6,
                        "shot_id": seed.shot_id,
                        "aspect": "16:9",
                        "camera_motion": seed.motion_id,
                        "styles": [seed.style_id],
                        "element_refs": ["Marta"],
                    },
                }
            ],
        )
    ]

    # El worker corre en paralelo al turno, como en producción: el grafo no espera al
    # render. Arrancarlo después de que el turno termine escondería justamente el bug de
    # que nadie lo arranca.
    trabajo = asyncio.create_task(worker.run_forever(poll_idle_s=0.01))

    eventos: list[dict[str, Any]] = []
    async with AsyncPostgresSaver.from_conn_string(get_settings().database_url) as checkpointer:
        await checkpointer.setup()
        runner = ConversationRunner(checkpointer, bus)

        async for evento in runner.run(
            conversation_id=seed.conversation_id,
            project_id=seed.project_id,
            user_id=seed.user_id,
            message="Renderiza el plano 1 con Marta.",
            ui_context={"open_tab": "timeline", "selected_asset_ids": []},
        ):
            eventos.append(evento)

        estado = await checkpointer.aget(
            {"configurable": {"thread_id": seed.conversation_id, "checkpoint_ns": ""}}
        )

    assert not any(e.get("type") == "error" for e in eventos), (
        f"El turno terminó con error: {[e for e in eventos if e.get('type') == 'error']}"
    )
    assert estado is not None, "El turno no dejó checkpoint: el grafo no llegó a ejecutarse."

    # -- salto 1: la tool call se convirtió en un job encolado ---------------- #
    job = await db.fetchrow(
        """
        select id, status, shot_id, conversation_id, credits_reserved, provider, model_id
          from public.generation_jobs where project_id = $1::uuid
        """,
        seed.project_id,
    )
    assert job is not None, (
        "No se encoló ningún job. El modelo pidió generate_video y la cadena "
        "ROOT → Send → ROOT_TOOLS → tool → enqueue se ha roto en algún punto."
    )
    assert job["shot_id"] == seed.shot_id
    assert job["credits_reserved"] > 0
    assert str(job["conversation_id"]) == seed.conversation_id, (
        "El job no lleva conversation_id. Con la columna a NULL, `worker._emit` sale por "
        "su return temprano y el usuario nunca ve aparecer el plano."
    )

    # -- salto 2: el worker lo reclama, lo ejecuta y aterriza el asset -------- #
    try:
        estado_final = await wait_for_job(db, str(job["id"]), states=("succeeded", "failed", "cancelled"))
    finally:
        await worker.stop()
        await asyncio.wait_for(trabajo, timeout=15)

    assert estado_final == "succeeded", f"El job acabó en '{estado_final}'"
    assert adapter.submits, "El worker nunca llamó a submit() del proveedor"

    asset = await db.fetchrow(
        """
        select id, type, status, url, shot_id, job_id, model_id, credits_spent
          from public.assets where job_id = $1
        """,
        job["id"],
    )
    assert asset is not None, "El job terminó bien pero no dejó asset en la base de datos"
    assert asset["status"] == "ready"
    assert asset["type"] == "video"
    assert asset["url"].startswith("https://storage.test/"), (
        "El asset apunta a la URL del proveedor. Esas URLs caducan en horas y el proyecto "
        "se quedaría sin planos a los dos días."
    )
    assert asset["shot_id"] == seed.shot_id
    assert asset["credits_spent"] > 0

    # El plano del canvas queda marcado como listo: es lo que pinta el timeline.
    assert (
        await db.fetchval(
            "select shot_status from public.canvas_nodes where id = $1::uuid", seed.shot_id
        )
        == "ready"
    )

    # -- salto 3: el evento llega al bus y se serializa a SSE ----------------- #
    recibidos = [
        evento
        async for evento in bus.subscribe(seed.conversation_id, last_event_id="0-0", idle_timeout_s=1.0)
    ]
    tipos = [e.type for e in recibidos]
    assert "asset_ready" in tipos, (
        f"El worker no publicó asset_ready en el stream de la conversación. Tipos vistos: {tipos}"
    )

    listo = next(e for e in recibidos if e.type == "asset_ready")
    assert listo.data["asset_id"] == str(asset["id"])
    assert listo.data["job_id"] == str(job["id"])

    sse = listo.to_sse()
    assert sse.startswith(f"id: {listo.id}\n"), "Sin `id:` el navegador no puede reanudar solo"
    assert "event: asset_ready\n" in sse
    cuerpo = json.loads(sse.split("data: ", 1)[1].strip())
    assert cuerpo["type"] == "asset_ready"
    assert cuerpo["data"]["asset_id"] == str(asset["id"])


async def test_el_toolset_del_modo_sale_de_la_taxonomia_real(db: Any, seed: Seed, registry: Any) -> None:
    """
    En preproducción no existe ninguna tool que gaste créditos; en producción sí.

    La restricción es estructural —las tools de generación no se instancian— y por eso
    hay que comprobarla sobre el builder real leyendo la taxonomía real: con la tabla
    `gen_models` vacía el builder no monta ninguna tool en ningún modo, y un test contra
    un snapshot fingido daría verde sin haber comprobado nada.
    """
    from app.tools.base import ToolContext, ToolFactory

    def contexto(mode: str) -> ToolContext:
        return ToolContext(
            project_id=seed.project_id,
            user_id=seed.user_id,
            conversation_id=seed.conversation_id,
            mode=mode,
            credits_available=seed.credits,
        )

    preproduccion = await ToolFactory.build_for_mode(contexto("preproduction"))
    produccion = await ToolFactory.build_for_mode(contexto("production"))

    assert preproduccion, "La taxonomía sembrada no monta ninguna tool en preproducción"
    assert not [t for t in preproduccion if getattr(t, "consumes_credits", False)], (
        "Hay tools que gastan créditos montadas en preproducción. La restricción es "
        "estructural: en ese modo simplemente no deben existir."
    )

    caras = {t.name for t in produccion if getattr(t, "consumes_credits", False)}
    assert "generate_video" in caras, f"En producción faltan tools de generación: {caras}"


async def test_el_contexto_del_proyecto_se_carga_de_la_base_real(db: Any, seed: Seed) -> None:
    """
    El contexto que ve el agente contiene el proyecto, su timeline y sus elements.

    Se comprueba aquí y no en el test del turno porque el contexto se deduplica contra el
    historial: en un turno con historial vacío se inyecta entero, pero el fallo que
    importa —que la carga desde BD devuelva sillas vacías porque una consulta usa un
    nombre de columna que ya no existe— se ve mejor mirando el objeto cargado.
    """
    from app.context.manager import XframeContextManager

    manager = XframeContextManager(seed.project_id, seed.user_id)
    contexto = await manager.load(open_tab="timeline")

    assert contexto.project_title == "Proyecto de integración"
    assert [e.name for e in contexto.elements] == ["Marta"]
    assert contexto.elements[0].usable_as_reference, (
        "El element sembrado no sirve como referencia visual, así que la cadena de "
        "continuidad de personaje no se estaría ejercitando."
    )
    assert [s.title for s in contexto.timeline] == ["Plano 1"]
    assert contexto.credits == seed.credits

    mensajes = await manager.get_context_messages([], open_tab="timeline")
    assert mensajes, "El contexto no produjo ningún mensaje para el modelo"
    texto = str(mensajes[0].content)
    assert "Marta" in texto and "Plano 1" in texto
