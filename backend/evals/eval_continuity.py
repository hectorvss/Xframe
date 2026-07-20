"""
Suite: render y montaje reales — continuidad, estilo, validez y coste.

Es la suite cara. Renderiza planos de verdad, los monta y juzga los frames con un
modelo visual. No corre en cada commit: corre antes de cambiar prompts de producción,
antes de cambiar de modelo por defecto, y cuando se toca la reinyección de la biblia de
estilo tras compactar el historial —que es donde la continuidad se rompe en silencio—.

Cuatro scorers ortogonales sobre **la misma ejecución**, que es la metodología de la
§6.4 del informe. Importa que sean cuatro y no un promedio: los cuatro fallos tienen
arreglos distintos y opuestos. Bajar de modelo arregla `cost_efficiency` y empeora
`character_continuity`; subir arregla la continuidad y dispara el coste. Un número
agregado escondería exactamente ese compromiso, que es la decisión de producto real.

    EVAL_ALLOW_RENDER=1 pytest evals/eval_continuity.py -m evals
"""

from __future__ import annotations

import pytest

from evals.base import run_eval
from evals.datasets import CONTINUITY_CASES
from evals.scorers import (
    CharacterContinuity,
    CostEfficiency,
    RenderValidity,
    StyleAdherence,
)

pytestmark = pytest.mark.evals


async def eval_continuity_and_style(continuity_task, case_filter) -> None:
    """
    Umbrales asimétricos, y cada uno tiene su razón:

    - `character_continuity` **0.9**: por encima de `minor_drift` (0.5). La deriva de
      identidad es la queja número uno de los usuarios de vídeo generativo y no se
      arregla en montaje, sólo regenerando y pagando otra vez.
    - `style_adherence` **0.5**: la escala son modos de fallo, no una rampa; 0.5 exige
      que la mitad de los casos den `on-brief` sin castigar el tramo intermedio.
    - `render_validity` **0.9**: pedirle a un proveedor algo que no soporta es un fallo
      de conocimiento del catálogo, y el catálogo lo servimos nosotros desde
      `gen_models`. Casi no tiene excusa.
    - `cost_efficiency` **0.7**: se tolera pasarse en algunos casos. Es el único scorer
      donde el óptimo no es 1.0: un agente que nunca se pasa de presupuesto está
      eligiendo el modelo barato incluso cuando el plano merecía el bueno.
    """
    report = await run_eval(
        "continuity",
        data=CONTINUITY_CASES,
        task=continuity_task,
        scores=[
            CharacterContinuity(),
            StyleAdherence(),
            RenderValidity(),
            CostEfficiency(),
        ],
        case_filter=case_filter,
        # Concurrencia baja: cada caso mantiene varios jobs de generación abiertos
        # contra el mismo proveedor, y el rate limit se aplica por cuenta, no por caso.
        concurrency=2,
    )
    report.assert_min(
        character_continuity=0.9,
        style_adherence=0.5,
        render_validity=0.9,
        cost_efficiency=0.7,
    )
