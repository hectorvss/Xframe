"""
El grafo.

Dos nodos: ROOT (el LLM) y ROOT_TOOLS (ejecución). Es la topología de PostHog
(`core/loop_graph/graph.py`) y la razón de copiarla es concreta: un grafo lineal
`guion → shotlist → render → montaje` se rompe el primer día que el usuario dice
"cambia solo el plano 7". Con dos nodos, generar la película entera y retocar un plano
suelto son el mismo camino.

Toda la complejidad vive en los executables, no en la topología.
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import StateGraph
from langgraph.types import Send

from app.agent.executables import MemoryCollectorNode, RootNode, RootToolsNode
from app.agent.state import NodeName, XframeState

logger = logging.getLogger(__name__)


def route_after_root(state: XframeState) -> str | list[Send]:
    """
    ¿Hay tool calls? Entonces fan-out: una rama por llamada.

    `Send` con una copia del estado marcada con `root_tool_call_id` es el map-reduce de
    PostHog. Cada rama ejecuta su tool en paralelo y el reductor `append` de
    `job_results` junta los resultados sin código de merge.
    """
    if not state.messages:
        return NodeName.MEMORY_COLLECTOR

    last = state.messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        # Fin del turno: antes de cerrar, destilar lo aprendido a la biblia de estilo.
        return NodeName.MEMORY_COLLECTOR

    return [
        Send(NodeName.ROOT_TOOLS, state.model_copy_for_branch(tc["id"]))
        for tc in tool_calls
    ]


def route_after_tools(state: XframeState) -> str:
    """Tras ejecutar, siempre se vuelve al root para que interprete los resultados."""
    return NodeName.ROOT


def build_graph(checkpointer: AsyncPostgresSaver | None = None):
    graph = StateGraph(XframeState)

    graph.add_node(NodeName.ROOT, RootNode())
    graph.add_node(NodeName.ROOT_TOOLS, RootToolsNode())
    graph.add_node(NodeName.MEMORY_COLLECTOR, MemoryCollectorNode())

    graph.add_edge(NodeName.START, NodeName.ROOT)
    graph.add_conditional_edges(NodeName.ROOT, route_after_root)
    graph.add_conditional_edges(
        NodeName.ROOT_TOOLS,
        route_after_tools,
        path_map={NodeName.ROOT: NodeName.ROOT},
    )
    graph.add_edge(NodeName.MEMORY_COLLECTOR, NodeName.END)

    return graph.compile(checkpointer=checkpointer)
