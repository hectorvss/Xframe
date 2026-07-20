"""
Suite: brief → guion.

Es el eslabón más barato de evaluar y el que más arrastra: un guion que no responde al
brief produce una shot list correcta sobre la historia equivocada y, después, planos
renderizados y pagados sobre la historia equivocada. Se evalúa aquí para no descubrirlo
tres pasos y doscientos créditos más tarde.

    pytest evals/eval_script.py -m evals
    pytest evals/eval_script.py -m evals --eval thriller
"""

from __future__ import annotations

import pytest

from evals.base import run_eval
from evals.datasets import SCRIPT_CASES, SCRIPT_CRITERIA
from evals.scorers import ScriptCoherence

pytestmark = pytest.mark.evals


async def eval_script_coherence(script_task, case_filter) -> None:
    """
    Un único scorer, porque en esta etapa solo hay una dimensión que medir: si el guion
    responde al brief. Añadir un scorer de "calidad" aquí sería medir gusto, y el gusto
    no se regresiona.

    El umbral (0.75) coincide con `slightly_off` de la escala ordinal: se acepta que un
    guion tenga discrepancias menores con la referencia, no que se deje un beat fuera.
    """
    report = await run_eval(
        "script",
        data=SCRIPT_CASES,
        task=script_task,
        scores=[
            ScriptCoherence(evaluation_criteria=SCRIPT_CRITERIA, piece_kind="short piece"),
        ],
        case_filter=case_filter,
    )
    report.assert_min(script_coherence=0.75)
