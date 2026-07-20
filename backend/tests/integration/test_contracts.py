"""
Verificación de empalmes por introspección.

Este fichero existe por un motivo muy concreto. El 20/07/2026 el backend tenía 124 tests
unitarios en verde y no arrancaba: seis agentes habían escrito seis vocabularios distintos
para los mismos contratos (`ContextManager` vs `XframeContextManager`, `run_shots` vs
`run_fanout`, `concat_shots` vs `assemble_cut`, `job.id` vs `job.job_id`, `enqueue` con y
sin `adapter`). Cada módulo estaba probado contra fakes, y un fake por definición
implementa la firma que el llamante imagina, no la que el destino tiene escrita.

La lección: **la firma real de la función llamada es lo que hay que comprobar**, y se
puede comprobar gratis, sin base de datos, sin red y sin LLM. Eso es todo lo que hace
este fichero.

Tres capas, de la más automática a la más específica:

1. `test_todas_las_llamadas_cruzadas` — recorre `app/`, resuelve cada símbolo importado de
   `app.*` y comprueba con `inspect.signature` que los argumentos de cada llamada encajan.
   Es la red que cubre lo que a nadie se le ocurrió listar.
2. `test_empalme_critico` — la lista explícita de las juntas que, si se rompen, tumban el
   sistema. Redundante con la anterior por diseño: sobrevive a que la automática tenga que
   saltarse un módulo por una dependencia ausente.
3. Comprobaciones de forma de retorno (`job.id`, métodos del bus), que ninguna firma
   captura porque ocurren sobre el valor devuelto, no sobre la llamada.

No lleva marca `integration`: no necesita infraestructura y debe correr siempre.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import app

APP_ROOT = Path(app.__file__).resolve().parent


class _Sentinel:
    """Relleno para `Signature.bind`. Su tipo da igual: solo se comprueba la aridad."""

    def __repr__(self) -> str:
        return "<arg>"


ARG = _Sentinel()


class MissingDependency(Exception):
    """Falta un paquete de terceros, no un símbolo nuestro. Se salta, no se falla."""


# --------------------------------------------------------------------------- #
# Resolución de símbolos                                                       #
# --------------------------------------------------------------------------- #


def _import_module(dotted: str) -> Any:
    """
    Importa distinguiendo "falta una dependencia" de "nuestro código está roto".

    La distinción es la que hace que este test sirva de algo: un `ModuleNotFoundError`
    sobre `langgraph` en una máquina sin dependencias opcionales no dice nada del
    backend; uno sobre `app.assembly.concat_shots` dice exactamente lo que buscamos.
    """
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError as exc:
        missing = (exc.name or "").split(".")[0]
        if missing and missing != "app":
            raise MissingDependency(f"{dotted} necesita el paquete '{missing}'") from exc
        raise
    except ImportError as exc:
        # Un `from app.x import y` que no existe llega aquí y **sí** es un hallazgo.
        raise AssertionError(f"No se puede importar {dotted}: {exc}") from exc


def _resolve(target: str) -> tuple[Any, bool]:
    """
    `"app.jobs.queue:enqueue"` o `"app.stream.bus:EventBus.publish"` → (objeto, ¿pide self?).

    El segundo valor no se puede deducir del objeto una vez extraído: un `staticmethod`
    leído desde su clase es una función corriente con el `__qualname__` punteado de un
    método, indistinguible de un método normal. Hay que preguntárselo al descriptor
    original con `getattr_static`, y por eso se decide aquí, mientras aún tenemos el
    contenedor en la mano.
    """
    module_name, _, attr_path = target.partition(":")
    obj = _import_module(module_name)
    walked = module_name
    needs_self = False

    for part in attr_path.split("."):
        if not hasattr(obj, part):
            raise AssertionError(
                f"{walked} no define '{part}'.\n"
                f"  Buscado por: {target}\n"
                f"  Sí define:   {', '.join(sorted(n for n in dir(obj) if not n.startswith('_'))[:25])}"
            )
        static = inspect.getattr_static(obj, part, None)
        needs_self = inspect.isclass(obj) and inspect.isfunction(static)
        obj = getattr(obj, part)
        walked = f"{walked}.{part}"

    return obj, needs_self


def _bind(
    obj: Any, target: str, n_positional: int, keywords: tuple[str, ...], needs_self: bool = False
) -> None:
    """
    Comprueba que `obj(*n_positional, **keywords)` es una llamada válida.

    `bind` y no `bind_partial`: lo que hundió las cuatro tools de generación fue un
    argumento **obligatorio que faltaba** (`adapter=`), y `bind_partial` lo habría dado
    por bueno.
    """
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):  # builtins y objetos sin firma introspectable
        return

    args = [ARG] * n_positional
    if needs_self:
        args.insert(0, ARG)

    try:
        signature.bind(*args, **{k: ARG for k in keywords})
    except TypeError as exc:
        raise AssertionError(
            f"La llamada no encaja con la firma real.\n"
            f"  Destino:  {target}\n"
            f"  Firma:    {obj.__name__ if hasattr(obj, '__name__') else target}{signature}\n"
            f"  Llamada:  ({n_positional} posicional(es)"
            + (f", {', '.join(f'{k}=' for k in keywords)}" if keywords else "")
            + ")\n"
            f"  Motivo:   {exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# 1. Barrido automático de todo `app/`                                         #
# --------------------------------------------------------------------------- #


def _app_modules() -> list[str]:
    out = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        out.append(".".join(["app", *parts]) if parts else "app")
    return out


@dataclass(frozen=True)
class CrossCall:
    """Una llamada de un módulo a un símbolo importado de otro módulo de `app`."""

    caller: str
    line: int
    target: str
    n_positional: int
    keywords: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.caller}:{self.line} → {self.target}"


def _cross_calls(module_name: str, tree: ast.AST) -> Iterator[CrossCall]:
    """
    Extrae del AST las llamadas a símbolos importados de `app.*`.

    Se recorre el árbol entero, no solo el nivel de módulo: en este backend los imports
    que cruzan capas son casi todos **perezosos, dentro de la función** (`from
    app.jobs.fanout import run_shots`), justamente los que ninguna herramienta estática
    convencional mira y donde estaban escondidos los empalmes rotos.
    """
    symbols: dict[str, str] = {}   # nombre local → "modulo:atributo"
    modules: dict[str, str] = {}   # alias local → "modulo"

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
            for alias in node.names:
                symbols[alias.asname or alias.name] = f"{node.module}:{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app"):
                    modules[alias.asname or alias.name.split(".")[0]] = alias.name

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Desempaquetados (`f(*args)`, `f(**kw)`): la aridad no es decidible estáticamente.
        if any(isinstance(a, ast.Starred) for a in node.args):
            continue
        if any(k.arg is None for k in node.keywords):
            continue

        target: str | None = None
        if isinstance(node.func, ast.Name):
            target = symbols.get(node.func.id)
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if module := modules.get(node.func.value.id):
                target = f"{module}:{node.func.attr}"

        if target is None or not target.startswith("app"):
            continue

        yield CrossCall(
            caller=module_name,
            line=node.lineno,
            target=target,
            n_positional=len(node.args),
            keywords=tuple(k.arg for k in node.keywords if k.arg),
        )


def _all_cross_calls() -> list[CrossCall]:
    calls: list[CrossCall] = []
    for name in _app_modules():
        path = APP_ROOT / Path(*name.split(".")[1:])
        source = (path.with_suffix(".py") if path.suffix != ".py" else path)
        if not source.exists():
            source = path / "__init__.py"
        if not source.exists():
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        calls.extend(_cross_calls(name, tree))
    return calls


CROSS_CALLS = _all_cross_calls()


def test_hay_llamadas_que_analizar() -> None:
    """
    Guardia del propio analizador.

    Un extractor que deja de encontrar nada pasaría todos los tests sin comprobar
    absolutamente nada, y sería indistinguible de un backend sano. Esta es la única
    defensa contra ese modo de fallo.
    """
    assert len(CROSS_CALLS) > 50, (
        f"El analizador de AST solo encontró {len(CROSS_CALLS)} llamadas cruzadas. "
        f"Probablemente está roto: este backend tiene muchas más."
    )


@pytest.mark.parametrize("call", CROSS_CALLS, ids=str)
def test_todas_las_llamadas_cruzadas(call: CrossCall) -> None:
    """Cada símbolo importado de `app.*` existe y acepta los argumentos con los que se llama."""
    try:
        obj, needs_self = _resolve(call.target)
    except MissingDependency as exc:
        pytest.skip(str(exc))

    if not callable(obj):
        return
    _bind(obj, call.target, call.n_positional, call.keywords, needs_self)


# --------------------------------------------------------------------------- #
# 2. Lista explícita de empalmes críticos                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Seam:
    """
    Una junta entre dos capas, con el nombre de quien la cruza.

    La lista se mantiene a mano y a propósito. La capa automática puede quedar muda si un
    módulo no se puede importar en una máquina dada; esta no, porque nombra el destino
    directamente y falla con el mensaje de qué esperaba encontrar.
    """

    caller: str
    target: str
    n_positional: int = 0
    keywords: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.caller} → {self.target}"


SEAMS: tuple[Seam, ...] = (
    # -- executables → contexto ------------------------------------------- #
    Seam("agent.executables", "app.context.manager:XframeContextManager", 2),
    Seam(
        "agent.executables",
        "app.context.manager:XframeContextManager.get_context_messages",
        1,
        ("open_tab", "selected_asset_ids"),
    ),
    # -- executables → taxonomía ------------------------------------------- #
    Seam("agent.executables", "app.tools.base:ToolFactory.build_for_mode", 1),
    Seam("tools.base", "app.taxonomy.builder:build_tools_for_mode", 1),
    Seam("taxonomy.builder", "app.taxonomy.repo:load_snapshot", 2),
    # -- executables → créditos -------------------------------------------- #
    Seam("agent.executables", "app.jobs.credits:balance", 1),
    Seam("agent.executables", "app.tools.base:ToolContext", 0,
         ("project_id", "user_id", "conversation_id", "mode", "credits_available")),
    Seam("agent.executables", "app.agent.prompts.base:build_system_prompt", 0, ("mode",)),
    Seam("agent.executables", "app.agent.compaction:ConversationCompactor.compact", 1),
    Seam("agent.executables", "app.memory.collector:MemoryCollectorNode", 1),
    # -- runner → grafo y bus ---------------------------------------------- #
    Seam("agent.runner", "app.agent.graph:build_graph", 1),
    Seam("agent.runner", "app.stream.bus:EventBus.publish", 3),
    # -- tools/generation → cola, fan-out, montaje, registry ---------------- #
    Seam("tools.generation", "app.jobs.queue:enqueue", 1,
         ("project_id", "shot_id", "adapter")),
    Seam("tools.generation", "app.jobs.fanout:run_fanout", 2),
    Seam("tools.generation", "app.assembly:assemble_cut", 1),
    Seam("tools.generation", "app.jobs.fanout:ShotSpec", 0, ("shot_id", "payload")),
    Seam("tools.generation", "app.assembly:AssemblySpec", 0, ("clips", "output_path")),
    Seam("tools.generation", "app.assembly:TimelineClip", 0, ("asset_id", "src")),
    Seam("tools.generation", "app.providers.registry:get_registry"),
    Seam("tools.generation", "app.providers.registry:DbAdapterRegistry.resolve", 1),
    Seam("tools.generation", "app.providers.base:GenerationRequest", 0,
         ("modality", "model_id", "prompt")),
    # -- worker → proveedores, créditos, bus -------------------------------- #
    Seam("jobs.worker", "app.providers.registry:DbAdapterRegistry.get", 1),
    Seam("jobs.worker", "app.providers.base:GenerationAdapter.submit", 1),
    Seam("jobs.worker", "app.providers.base:GenerationAdapter.poll", 1),
    Seam("jobs.worker", "app.providers.base:GenerationAdapter.cancel", 1),
    Seam("jobs.worker", "app.providers.base:GenerationAdapter.estimate_cost", 2),
    Seam("jobs.worker", "app.providers.base:ProviderJobRef", 0, ("provider", "external_id")),
    Seam("jobs.worker", "app.jobs.credits:charge", 0, ("job_id", "final_credits", "note", "conn")),
    Seam("jobs.worker", "app.jobs.credits:refund", 0, ("job_id", "reason", "conn")),
    Seam("jobs.worker", "app.stream.bus:EventBus.publish", 3),
    Seam("jobs.worker", "app.stream.bus:get_bus"),
    # -- worker → reanudación → runner -------------------------------------- #
    # La junta que cierra el lazo: el worker avisa, `resume` decide, y el runner ejecuta
    # el turno. El import del runner es perezoso a propósito (`worker.py` no puede
    # arrastrar langgraph), y eso es justo lo que deja este empalme fuera del alcance de
    # cualquier análisis estático convencional.
    Seam("jobs.worker", "app.jobs.resume:on_job_settled", 1),
    Seam("tools.generation", "app.jobs.resume:mark_awaiting", 0,
         ("conversation_id", "project_id")),
    Seam("main", "app.jobs.resume:note_user_turn", 1),
    Seam("main", "app.jobs.resume:set_runner", 1),
    Seam("jobs.resume", "app.agent.runner:ConversationRunner", 2),
    Seam("jobs.resume", "app.agent.runner:make_checkpointer"),
    Seam("jobs.resume", "app.agent.runner:ConversationRunner.run", 0,
         ("conversation_id", "project_id", "user_id", "message", "system_event")),
    # -- worker y montaje → firma de URLs ----------------------------------- #
    # El bucket es privado: si estas juntas se rompen, nada falla en los tests y en
    # producción los personajes dejan de parecerse a sí mismos.
    Seam("jobs.worker", "app.storage:sign_request_references", 1, ("ttl_s",)),
    Seam("jobs.worker", "app.storage:sign_reference", 1),
    Seam("tools.generation", "app.storage:sign_reference", 1),
    Seam("taxonomy.builder", "app.storage:object_path", 1),
    # -- cola → créditos ---------------------------------------------------- #
    Seam("jobs.queue", "app.jobs.credits:lock_project_owner", 2),
    Seam("jobs.queue", "app.jobs.credits:reserve", 0, ("project_id", "amount", "job_id", "note", "conn")),
    Seam("jobs.queue", "app.jobs.credits:usd_to_credits", 1),
    Seam("jobs.queue", "app.jobs.credits:to_uuid", 1),
    # -- main → runner, bus, db --------------------------------------------- #
    Seam("main", "app.agent.runner:ConversationRunner", 2),
    Seam("main", "app.agent.runner:make_checkpointer"),
    Seam("main", "app.agent.runner:ConversationRunner.run", 0,
         ("conversation_id", "project_id", "user_id", "message", "ui_context", "resume_payload")),
    Seam("main", "app.stream.bus:EventBus"),
    Seam("main", "app.stream.bus:EventBus.seed", 1),
    Seam("main", "app.stream.bus:EventBus.subscribe", 1, ("last_event_id",)),
    Seam("main", "app.stream.bus:EventBus.close"),
    Seam("main", "app.db:init_pool"),
    Seam("main", "app.db:close_pool"),
    # -- entrypoint del worker ---------------------------------------------- #
    Seam("jobs.__main__", "app.jobs.worker:JobWorker", 0, ("registry",)),
    Seam("jobs.__main__", "app.jobs.worker:sweep_stale"),
)


@pytest.mark.parametrize("seam", SEAMS, ids=str)
def test_empalme_critico(seam: Seam) -> None:
    """Cada junta crítica del sistema existe y encaja con cómo la usa su llamante."""
    try:
        obj, needs_self = _resolve(seam.target)
    except MissingDependency as exc:
        pytest.skip(str(exc))

    assert callable(obj), f"{seam.target} existe pero no es invocable ({type(obj).__name__})"
    _bind(obj, seam.target, seam.n_positional, seam.keywords, needs_self)


# --------------------------------------------------------------------------- #
# 3. Contratos sobre el valor devuelto                                         #
# --------------------------------------------------------------------------- #


def _attributes_used_on(source: Path, variables: set[str]) -> dict[str, set[int]]:
    """Atributos leídos sobre unas variables concretas, con la línea de cada uso."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    out: dict[str, set[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in variables:
                out.setdefault(node.attr, set()).add(node.lineno)
    return out


def _names_assigned_from(source: Path, callees: set[str]) -> set[str]:
    """Variables cuyo valor sale de llamar a una de `callees` (con o sin `await`)."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value.value if isinstance(node.value, ast.Await) else node.value
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if called in callees:
            names.add(target.id)
    return names


def test_resultado_de_enqueue_se_lee_por_sus_campos_reales() -> None:
    """
    `enqueue()` devuelve `EnqueueResult`, cuyo identificador se llama `job_id`.

    Las tools lo leían como `job.id`. Ninguna firma detecta esto —la llamada encaja
    perfectamente— y ningún test unitario con un fake tampoco, porque el fake devolvía
    un objeto con el atributo que el llamante esperaba. Solo se ve mirando el tipo real
    del valor devuelto, que es lo que hace esta comprobación.
    """
    from app.jobs.queue import EnqueueResult

    source = APP_ROOT / "tools" / "generation.py"
    fields = {f for f in EnqueueResult.__dataclass_fields__} | {
        name for name, _ in inspect.getmembers(EnqueueResult, lambda m: isinstance(m, property))
    }

    variables = _names_assigned_from(source, {"enqueue", "_enqueue"})
    assert variables, "No se encontró ninguna asignación desde enqueue() en tools/generation.py"

    problems = [
        f"{source.name}:{sorted(lines)} usa `.{attr}` sobre el resultado de enqueue()"
        for attr, lines in _attributes_used_on(source, variables).items()
        if attr not in fields
    ]
    assert not problems, (
        "El resultado de enqueue() se lee con atributos que EnqueueResult no tiene.\n"
        + "\n".join(f"  - {p}" for p in problems)
        + f"\n  Campos reales: {', '.join(sorted(fields))}"
    )


@pytest.mark.parametrize(
    ("module_file", "variables"),
    [("main.py", {"_bus", "bus"}), ("agent/runner.py", {"_bus", "bus"})],
)
def test_metodos_del_bus_existen(module_file: str, variables: set[str]) -> None:
    """
    Todo método invocado sobre el bus existe en `EventBus`.

    `main.py` llamaba a `bus.connect()`, que nunca existió —el cliente de Redis se crea
    en el constructor—, y el proceso no llegaba a levantar. Es el fallo más barato de
    detectar del informe y el que tuvo el efecto más caro.
    """
    from app.stream.bus import EventBus

    source = APP_ROOT / module_file
    # `self._bus` es un Attribute sobre un Attribute; se normaliza el AST buscando
    # también el patrón `self._bus.<metodo>`.
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    used: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        name = None
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name in variables:
            used[node.attr] = node.lineno

    missing = {a: line for a, line in used.items() if not hasattr(EventBus, a)}
    assert not missing, (
        f"{module_file} llama a métodos que EventBus no tiene: "
        + ", ".join(f"{a}() (línea {line})" for a, line in sorted(missing.items()))
        + "\n  EventBus expone: "
        + ", ".join(sorted(n for n in dir(EventBus) if not n.startswith("_")))
    )


def test_el_worker_se_puede_arrancar_como_modulo() -> None:
    """
    `docker-compose` lanza el worker con `python -m app.jobs`; ese módulo debe existir.

    La versión auditada apuntaba a `python -m app.jobs.worker`, que no tiene bloque
    `__main__`: el contenedor arrancaba, no hacía nada y salía, y los jobs se quedaban
    en `queued` para siempre sin un solo error en los logs.
    """
    try:
        entry = _import_module("app.jobs.__main__")
    except MissingDependency as exc:
        pytest.skip(str(exc))

    assert inspect.iscoroutinefunction(entry.main), (
        "app/jobs/__main__.py debe exponer una corrutina `main()` como entrypoint del worker"
    )


# --------------------------------------------------------------------------- #
# 4. Módulos huérfanos                                                         #
# --------------------------------------------------------------------------- #


def _importers_of(module: str) -> set[str]:
    """Módulos de `app` que importan `module`, por cualquiera de las dos sintaxis."""
    out: set[str] = set()
    for name in _app_modules():
        if name == module or name.startswith(f"{module}."):
            continue
        path = APP_ROOT / Path(*name.split(".")[1:])
        source = path.with_suffix(".py") if path.suffix != ".py" else path
        if not source.exists():
            source = path / "__init__.py"
        if not source.exists():
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(module):
                out.add(name)
            elif isinstance(node, ast.Import):
                if any(a.name.startswith(module) for a in node.names):
                    out.add(name)
    return out


ORPHAN_CANDIDATES = (
    "app.agent.compaction",
    "app.memory.collector",
    "app.memory.onboarding",
    "app.jobs.fanout",
    "app.jobs.webhooks",
    "app.artifacts.manager",
)


#: Huérfanos confirmados que **todavía** no tienen llamante, con el hallazgo anotado.
#: `xfail` no estricto a propósito: cuando el agente que está trabajando en esa capa lo
#: enganche, el test pasa a XPASS y se puede borrar la entrada sin que nadie se lleve un
#: rojo por haberlo arreglado.
STILL_ORPHANED: dict[str, str] = {
    "app.jobs.webhooks": (
        "HALLAZGO: `app/jobs/webhooks.py` define `WebhookReceiver` y `verify_signature` "
        "pero ninguna ruta lo monta — `main.py` no llama a `include_router` en ningún "
        "sitio y el módulo ni siquiera expone un `APIRouter`. Los webhooks de proveedor "
        "no tienen a dónde llegar, así que todo job depende del polling del worker."
    ),
}
# `app.memory.onboarding` estuvo aquí hasta que se enganchó en `MemoryCollectorNode`
# (`agent/executables.py`), que pregunta por `should_run()` en cada turno.


@pytest.mark.parametrize("module", ORPHAN_CANDIDATES)
def test_ningun_modulo_queda_sin_llamante(module: str) -> None:
    """
    Un módulo correcto que nadie invoca es código muerto que parece funcionalidad.

    La auditoría del 20/07/2026 encontró siete así, y ninguno daba un solo test en rojo:
    `compaction.py` con sus 515 líneas no compactaba nada, la biblia de estilo no se
    rellenaba nunca y el prompt le prometía al usuario una memoria que no existía. La
    firma no detecta esta clase de fallo —no hay llamada que comprobar—, así que hay que
    preguntar por lo contrario: quién importa a quién.
    """
    importers = _importers_of(module)

    # El orden importa. La versión anterior llamaba a `pytest.xfail()` ANTES de calcular
    # los importadores, y `pytest.xfail()` es imperativo: aborta el test en el acto. El
    # resultado era que una entrada de STILL_ORPHANED se quedaba en rojo-esperado para
    # siempre, incluso después de engancharla — lo contrario de lo que el comentario de
    # arriba promete. Comprobando primero, arreglar el huérfano pone el test en verde.
    if not importers and module in STILL_ORPHANED:
        pytest.xfail(STILL_ORPHANED[module])

    assert importers, (
        f"{module} no lo importa nadie en todo `app/`. O se engancha a quien deba usarlo, "
        f"o se borra: dejarlo ahí hace creer que la funcionalidad existe."
    )


def test_los_nodos_del_grafo_son_invocables_con_la_firma_del_grafo() -> None:
    """
    LangGraph invoca cada nodo como `node(state, config)`. Un nodo con otra aridad
    revienta en ejecución, no al construir el grafo, así que se comprueba aquí.
    """
    try:
        executables = _import_module("app.agent.executables")
    except MissingDependency as exc:
        pytest.skip(str(exc))

    for name in ("RootNode", "RootToolsNode", "MemoryCollectorNode"):
        node_cls = getattr(executables, name)
        signature = inspect.signature(node_cls.__call__)
        signature.bind(ARG, ARG, ARG)  # self, state, config
        assert inspect.iscoroutinefunction(node_cls.__call__), f"{name}.__call__ debe ser async"
