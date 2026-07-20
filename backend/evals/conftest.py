"""
Configuración compartida de las suites de evaluación.

Aquí viven las *tasks*: la función que ejecuta el pipeline una vez por caso. Los
scorers no saben nada de cómo se produjo la salida, y el pipeline no sabe nada de cómo
se le va a puntuar. Esa separación es la que permite añadir un scorer sin tocar el
agente, y cambiar el agente sin reescribir los evals.

Las tasks importan el agente **de forma perezosa** y hacen `skip` si todavía no existe.
Es deliberado: el andamiaje de evals se escribe antes que el grafo, y una suite que
revienta al importar es una suite que nadie arregla.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from evals.datasets import Brief, ContinuityInput, format_shots


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    `--eval <substr>` filtra casos por nombre.

    Es la opción de PostHog y se usa constantemente: cuando un caso concreto falla, se
    itera sobre ese caso solo en vez de pagar la suite entera en cada intento.
    """
    parser.addoption(
        "--eval",
        action="store",
        default=None,
        help="Ejecuta solo los casos cuyo nombre contenga esta subcadena.",
    )


@pytest.fixture
def case_filter(pytestconfig: pytest.Config) -> str | None:
    return pytestconfig.getoption("--eval")


@pytest.fixture(autouse=True)
def _require_api_key() -> None:
    """
    Sin clave no hay eval. Se salta con un mensaje claro en vez de fallar con un 401
    veinte casos más adelante, cuando ya se ha perdido el tiempo de todos.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — evals need a real model")


def _agent_or_skip() -> Any:
    """Importa el grafo del agente, o salta la suite si aún no está montado."""
    try:
        from app.agent.graph import build_graph  # type: ignore[import-not-found]
    except ImportError as exc:
        pytest.skip(f"agent graph not available yet ({exc})")
    return build_graph()


@pytest.fixture
def script_task() -> Callable[[Brief], Awaitable[str]]:
    """brief → guion. Solo preproducción: esta task no debe gastar un crédito."""
    graph = _agent_or_skip()

    async def _task(brief: Brief) -> str:
        from app.agent.state import AgentMode

        state = await graph.ainvoke(
            {
                "messages": [{"role": "user", "content": str(brief)}],
                "mode": AgentMode.PREPRODUCTION,
                "project_id": os.getenv("EVAL_PROJECT_ID", "eval"),
                "user_id": "eval",
            }
        )
        return _last_text(state)

    return _task


@pytest.fixture
def shotlist_task() -> Callable[[str], Awaitable[dict[str, Any]]]:
    """guion → shot list."""
    graph = _agent_or_skip()

    async def _task(script: str) -> dict[str, Any]:
        from app.agent.state import AgentMode

        prompt = f"Break this script into a shot list:\n\n{script}"
        state = await graph.ainvoke(
            {
                "messages": [{"role": "user", "content": prompt}],
                "mode": AgentMode.PREPRODUCTION,
                "project_id": os.getenv("EVAL_PROJECT_ID", "eval"),
                "user_id": "eval",
            }
        )
        return {"shots": _last_text(state), "raw": state}

    return _task


@pytest.fixture
def continuity_task() -> Callable[[ContinuityInput], Awaitable[dict[str, Any]]]:
    """
    shot list → render + montaje. Es la única task que gasta créditos de verdad, así
    que exige un opt-in explícito por entorno: nadie debe descubrir que ha gastado
    doscientos euros porque corrió `pytest` sin argumentos.
    """
    if os.getenv("EVAL_ALLOW_RENDER") != "1":
        pytest.skip("set EVAL_ALLOW_RENDER=1 to run evals that spend real credits")

    graph = _agent_or_skip()

    async def _task(case: ContinuityInput) -> dict[str, Any]:
        from app.agent.state import AgentMode

        prompt = (
            f"{case.project_brief}\n\nStyle bible:\n{case.style_bible}\n\n"
            f"Characters:\n{case.character_sheet}\n\n"
            f"Render and assemble this shot list:\n{format_shots(case.shots)}"
        )
        state = await graph.ainvoke(
            {
                "messages": [{"role": "user", "content": prompt}],
                "mode": AgentMode.PRODUCTION,
                "project_id": os.getenv("EVAL_PROJECT_ID", "eval"),
                "user_id": "eval",
            }
        )
        results = state.get("job_results") or []
        return {
            "video_path": state.get("cut_path"),
            "reference_frame": case.reference_frame,
            "character_sheet": case.character_sheet,
            "style_bible": case.style_bible,
            "job_status": "succeeded" if all(r.ok for r in results) else "failed",
            "credits_spent": sum(r.credits_charged for r in results),
            "retries": max(0, len(results) - len(case.shots)),
        }

    return _task


def _last_text(state: Any) -> str:
    messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", [])
    for message in reversed(messages or []):
        content = getattr(message, "content", None) or (
            message.get("content") if isinstance(message, dict) else None
        )
        if isinstance(content, str) and content.strip():
            return content
    return ""
