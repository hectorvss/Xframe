"""
Suite: guion → shot list, y shot list → parámetros de generación.

Dos suites en un fichero porque miden el mismo salto desde dos alturas: la cobertura
narrativa (¿hay un plano para cada beat?) y la traducción a parámetros concretos
(¿pidió el modelo, la duración y el movimiento correctos?).

Ambas son deterministas o casi, y ninguna renderiza nada. Es la línea que se puede
correr en cada commit sin pensar en el gasto.

    pytest evals/eval_shotlist.py -m evals
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from evals.base import run_eval
from evals.datasets import (
    PARAM_CASES,
    SHOT_SCHEMA,
    SHOTLIST_CASES,
    SHOTLIST_CRITERIA,
    format_shots,
)
from evals.scorers import ParamRelevance, ShotListCompleteness

pytestmark = pytest.mark.evals


async def eval_shotlist_completeness(shotlist_task, case_filter) -> None:
    """
    Cobertura del guion por la shot list.

    Las referencias del dataset son `ShotSpec` tipados, pero al juez se le pasan ya
    formateados: un juez que recibe JSON crudo empieza a puntuar detalles de
    serialización en vez de decisiones de cobertura.
    """
    cases = [replace(case, expected=format_shots(case.expected or [])) for case in SHOTLIST_CASES]

    report = await run_eval(
        "shotlist",
        data=cases,
        task=shotlist_task,
        scores=[
            ShotListCompleteness(
                evaluation_criteria=SHOTLIST_CRITERIA,
                shot_schema=SHOT_SCHEMA,
            ),
        ],
        case_filter=case_filter,
    )
    report.assert_min(shotlist_completeness=0.75)


async def eval_generation_params(shotlist_task, case_filter) -> None:
    """
    Elección de herramienta y parámetros.

    Umbral más alto (0.8) que el de los jueces, y a propósito: esto es determinista, así
    que no hay ruido de juez que absorber, y el caso de "no generar durante
    preproducción" es de todo o nada — un fallo ahí es dinero gastado sin permiso.
    """
    report = await run_eval(
        "generation_params",
        data=PARAM_CASES,
        task=shotlist_task,
        scores=[ParamRelevance(semantic_args={"prompt", "negative_prompt"})],
        case_filter=case_filter,
    )
    report.assert_min(param_relevance=0.8)
