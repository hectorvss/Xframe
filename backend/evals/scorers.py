"""
Scorers de Xframe.

Siete dimensiones ortogonales, ninguna agregada en un "score global". El mapeo con los
scorers de PostHog de los que sale cada uno está en la §16 de la arquitectura:

| Scorer                  | Origen PostHog           | Tipo                     |
|-------------------------|--------------------------|--------------------------|
| `ScriptCoherence`       | `PlanCorrectness`        | juez, escala ordinal     |
| `ShotListCompleteness`  | `QueryAndPlanAlignment`  | juez, escala ordinal     |
| `CharacterContinuity`   | `SQLSemanticsCorrectness`| juez visual, graduado    |
| `StyleAdherence`        | `StyleChecker`           | juez visual, modos fallo |
| `ParamRelevance`        | `ToolRelevance`          | determinista + similitud |
| `RenderValidity`        | `SQLSyntaxCorrectness`   | determinista graduado    |
| `CostEfficiency`        | — (nuevo)                | determinista graduado    |

Dos reglas atraviesan el fichero entero y no se negocian:

- **Ninguno es binario.** Siempre hay un tramo intermedio que distingue "se equivocó de
  planteamiento" de "acertó el planteamiento y falló un detalle". Sin ese tramo, el
  scorer dice que algo va mal pero no por dónde empezar.
- **`score=None` cuando el caso no aplica**, y nunca 0.0. Un plano sin personajes no
  puntúa cero en continuidad de personaje: se abstiene.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from evals.base import (
    ORDINAL_SCALE,
    LLMClassifier,
    Score,
    Scorer,
    sample_frames_for_judge,
)


def _as_dict(value: Any) -> dict[str, Any]:
    """Acepta dict, dataclass o modelo Pydantic. Los datasets usan los tres."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(getattr(value, "__dict__", {}))


# --------------------------------------------------------------------------- #
# 1. ScriptCoherence                                                           #
# --------------------------------------------------------------------------- #


class ScriptCoherence(LLMClassifier):
    """
    ¿El guion generado responde al brief?

    Calco de `PlanCorrectness`. Lo que se hereda y por qué:

    - **Criterios inyectables**: un spot de 30 s, un tráiler y un explainer no se juzgan
      igual. El criterio es un parámetro, no una constante escondida en el prompt.
    - **Asimetría deliberada** entre fallo por omisión y fallo por exceso, más
      admisión explícita de equivalencias legítimas. En un dominio creativo, dos
      guiones distintos pueden ser igual de válidos: un scorer que castigue toda
      divergencia respecto a la referencia enseña al agente a ser previsible, que es
      justo lo contrario de lo que se le pide.
    - **"Do not apply general knowledge"**: sin esa frase el juez se pone a evaluar
      calidad cinematográfica según su propio criterio en vez de comparar con la
      referencia, y la métrica deja de ser reproducible.
    """

    def __init__(self, *, evaluation_criteria: str, piece_kind: str = "short film", **kwargs: Any):
        super().__init__(
            name="script_coherence",
            choice_scores=dict(ORDINAL_SCALE),
            prompt_template="""
You are auditing the script an AI filmmaking agent produced from a client brief for a {{piece_kind}}.
You will be given the brief, a reference script written by a human, and the generated script.

Compare them to determine whether the generated script delivers what the brief asks for.
Do not apply general knowledge about {{piece_kind}} scripts: judge against the reference.

<evaluation_criteria>
{{evaluation_criteria}}
</evaluation_criteria>

<input_vs_output>
Client brief:
<brief>
{{input}}
</brief>

Reference script:
<expected_script>
{{expected}}
</expected_script>

Generated script:
<output_script>
{{output}}
</output_script>
</input_vs_output>

How would you rate the coherence of the generated script? Choose one:
- perfect: Covers every beat the brief requires, in a workable order, with nothing extraneous.
- near_perfect: Covers the brief with at most one immaterial detail missed.
- slightly_off: Covers the brief with minor discrepancies that do not change the message.
- somewhat_misaligned: Has correct elements but misses a beat the brief explicitly required, or adds a substantial beat nobody asked for.
- strongly_misaligned: Does not deliver the brief's message, or contradicts a stated constraint (duration, audience, tone).
- useless: Incomprehensible, or not a script at all.
""".strip(),
            **kwargs,
        )
        self.evaluation_criteria = evaluation_criteria
        self.piece_kind = piece_kind

    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        if not output:
            # Gating: no se paga una llamada al juez si no hay nada que juzgar.
            return self._fail("the agent produced no script")
        if not expected:
            return self._skip("no reference script in the eval case")

        return await self.classify(
            {
                "input": input,
                "expected": expected,
                "output": output,
                "evaluation_criteria": self.evaluation_criteria,
                "piece_kind": self.piece_kind,
            }
        )


# --------------------------------------------------------------------------- #
# 2. ShotListCompleteness                                                      #
# --------------------------------------------------------------------------- #


class ShotListCompleteness(LLMClassifier):
    """
    ¿Los planos cubren el guion?

    Es el análogo de `QueryAndPlanAlignment`: juzga el paso guion → artefacto, no el
    guion en sí. Se separa a propósito de `ScriptCoherence`, porque son fallos con
    arreglos distintos: un guion malo se arregla en el prompt del director de guion, y
    una shot list incompleta se arregla en el del director de fotografía.

    Se le inyecta el esquema de un plano (igual que PostHog inyecta el JSON Schema del
    insight) para que el juez sepa qué significa cada campo, con la misma guarda de
    tamaño: un esquema que crece sin control se convierte en un juez caro y distraído.
    """

    #: Igual que la guarda de PostHog. Se puede subir, pero conscientemente.
    MAX_SCHEMA_CHARS = 20_000

    def __init__(self, *, evaluation_criteria: str, shot_schema: str = "", **kwargs: Any):
        if len(shot_schema) > self.MAX_SCHEMA_CHARS:
            raise ValueError(
                f"The shot schema is {len(shot_schema)} chars — are you sure you want to put this "
                f"into an LLM on every case? Raise MAX_SCHEMA_CHARS deliberately if so."
            )
        super().__init__(
            name="shotlist_completeness",
            choice_scores=dict(ORDINAL_SCALE),
            prompt_template="""
Evaluate whether the generated shot list implements the script it was derived from.

Use the shot schema below to understand what each field means:
<shot_schema>
{{shot_schema}}
</shot_schema>

<evaluation_criteria>
{{evaluation_criteria}}

Note: shot count need not match the reference exactly. Two shot lists that cover the same
beats with different coverage decisions are both acceptable.
</evaluation_criteria>

<input_vs_output>
Script the shot list must cover:
<script>
{{input}}
</script>

Reference shot list:
<expected_shots>
{{expected}}
</expected_shots>

Generated shot list:
<output_shots>
{{output}}
</output_shots>
</input_vs_output>

How would you rate the coverage of the generated shot list? Choose one:
- perfect: Every beat of the script is covered by at least one shot, and every shot serves a beat.
- near_perfect: Full coverage with at most one immaterial detail missed.
- slightly_off: Full coverage, but a shot choice or two is questionable for the beat it serves.
- somewhat_misaligned: A beat of the script has no shot covering it, or several shots serve no beat.
- strongly_misaligned: Multiple beats uncovered, or the shot list describes a different piece.
- useless: Incomprehensible, or not a shot list at all.
""".strip(),
            **kwargs,
        )
        self.evaluation_criteria = evaluation_criteria
        self.shot_schema = shot_schema

    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        shots = output.get("shots") if isinstance(output, dict) else output
        if not shots:
            return self._fail("the agent produced no shot list")
        if not expected:
            return self._skip("no reference shot list in the eval case")

        return await self.classify(
            {
                "input": input,
                "expected": expected,
                "output": shots,
                "evaluation_criteria": self.evaluation_criteria,
                "shot_schema": self.shot_schema,
            }
        )


# --------------------------------------------------------------------------- #
# 3. CharacterContinuity                                                       #
# --------------------------------------------------------------------------- #


class CharacterContinuity(LLMClassifier):
    """
    ¿El personaje es el mismo entre planos?

    Corre sobre frames reales con un modelo visual. Es el scorer más caro del conjunto
    y el más necesario: la deriva de identidad es el fallo característico del vídeo
    generativo, no se detecta leyendo prompts, y se paga en créditos porque obliga a
    regenerar planos ya renderizados.

    **El vídeo se acelera 8x antes de muestrear** (`sample_frames_for_judge`): los
    modelos visuales muestrean a ~1 fps, así que sin acelerar el juez vería ocho
    instantes casi idénticos de un plano de ocho segundos y no podría opinar sobre
    continuidad. Acelerando, los mismos frames cubren toda la secuencia.

    La escala es graduada y no Pass/Fail: "deriva leve" es una decisión de producción
    distinta de "es otra persona". La primera se tolera en un plano de fondo; la segunda
    obliga a regenerar. Un scorer binario borraría esa diferencia.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="character_continuity",
            choice_scores={
                "same_character": 1.0,
                "minor_drift": 0.5,
                "different_character": 0.0,
                # No hay personaje visible: no aplica. Nunca 0.0.
                "no_character_visible": None,
            },
            prompt_template="""
You are auditing character continuity across shots of a generated film sequence.

The first image is the reference portrait of the character. The images that follow are frames
sampled from the generated sequence, in narrative order. The sequence was sped up before
sampling, so consecutive frames are several seconds apart in real time.

Character reference sheet:
<character_sheet>
{{character_sheet}}
</character_sheet>

Judge ONLY whether the person in the sampled frames is the same individual as the reference.
Ignore differences in lighting, camera angle, framing, expression, motion blur and background:
those are cinematography, not continuity errors. Judge identity: face geometry, hair, skin tone,
age, build, and wardrobe where the sheet specifies it.

Choose one:
- same_character: Recognisably the same individual throughout, wardrobe consistent with the sheet.
- minor_drift: The same individual, but with visible inconsistency across frames (hair, wardrobe detail, apparent age) that a viewer might notice.
- different_character: At least one frame shows a person a viewer would read as someone else.
- no_character_visible: No person is visible in the frames, so continuity cannot be judged.
""".strip(),
            **kwargs,
        )

    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        data = _as_dict(output)
        video = data.get("video_path") or data.get("cut_path")
        reference = data.get("reference_frame") or kwargs.get("reference_frame")
        sheet = data.get("character_sheet") or kwargs.get("character_sheet") or ""

        if not video:
            return self._skip("the case produced no rendered video")
        if not reference:
            return self._skip("no character reference frame available")

        frames = await sample_frames_for_judge(video)
        if not frames:
            return self._fail("the rendered video yielded no sampleable frames", video=video)

        images = [_read_bytes(reference), *frames]
        score = await self.classify({"character_sheet": sheet}, images=images)
        score.metadata["frames_sampled"] = len(frames)
        return score


# --------------------------------------------------------------------------- #
# 4. StyleAdherence                                                            #
# --------------------------------------------------------------------------- #


class StyleAdherence(LLMClassifier):
    """
    ¿La secuencia respeta la biblia de estilo del proyecto?

    Copia el diseño de `StyleChecker`: **las etiquetas son modos de fallo con nombre**,
    no una escala de calidad. La razón es práctica: "un 0.4 de estilo" no le dice a
    nadie qué arreglar, mientras que `generic-stock-footage-look` apunta directamente a
    que el prompt no está inyectando el fragmento de estilo. El nombre del fallo *es* el
    diagnóstico.

    Se conserva un tramo intermedio (0.5) frente al `StyleChecker` original, que manda
    todos los fallos a 0.0: en calidad creativa, "va por el camino pero flojea" es un
    estado real y frecuente, y colapsarlo con "no se parece en nada" haría el scorer
    insensible justo en el rango donde se trabaja.

    Como `CharacterContinuity`, muestrea el vídeo acelerado 8x.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="style_adherence",
            choice_scores={
                "on-brief": 1.0,
                "slightly-off-brief": 0.5,
                "generic-stock-footage-look": 0.0,
                "over-stylised": 0.0,
                "incoherent-across-shots": 0.0,
                "empty": None,
            },
            prompt_template="""
You are evaluating whether a generated sequence matches its project's style bible.

The frames below are sampled from the sequence in narrative order. The sequence was sped up
before sampling, so consecutive frames are several seconds apart in real time.

<style_bible>
{{style_bible}}
</style_bible>

Judge the visual treatment only: palette, lighting, contrast, texture, lens character, and
whether all shots look like they belong to the same piece. Ignore story, acting and framing.

Choose one:
- on-brief: The palette, lighting and texture match the style bible, and all shots look like one piece.
- slightly-off-brief: Recognisably the intended style, but one dimension (usually palette or contrast) drifts from the bible.
- generic-stock-footage-look: Competent but anonymous — flat lighting, default colour, none of the specified treatment applied.
- over-stylised: The treatment is applied so heavily it fights the content: crushed blacks, blown highlights, effects for their own sake.
- incoherent-across-shots: Individual shots may be fine, but they do not look like the same piece.
- empty: No frames to judge.
""".strip(),
            **kwargs,
        )

    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        data = _as_dict(output)
        video = data.get("video_path") or data.get("cut_path")
        bible = data.get("style_bible") or kwargs.get("style_bible") or expected or ""

        if not video:
            return self._skip("the case produced no rendered video")
        if not bible:
            return self._skip("no style bible to judge against")

        frames = await sample_frames_for_judge(video)
        if not frames:
            return self._fail("the rendered video yielded no sampleable frames", video=video)

        score = await self.classify({"style_bible": bible}, images=frames)
        score.metadata["frames_sampled"] = len(frames)
        return score


# --------------------------------------------------------------------------- #
# 5. ParamRelevance                                                            #
# --------------------------------------------------------------------------- #


class ParamRelevance(Scorer):
    """
    ¿Llamó a la herramienta de generación adecuada, con los parámetros adecuados?

    Puerto de `ToolRelevance`, que es el scorer que mejor encaja en este dominio: medio
    punto por acertar la herramienta y medio repartido entre los argumentos esperados.

    El reparto no es cosmético. Elegir `generate_video` en vez de `generate_image` es un
    error de categoría; poner 6 segundos donde tocaban 5 es un error de detalle. Un
    scorer que los puntúe igual no permite distinguir un agente que no entiende la tarea
    de uno que la entiende y calibra mal.

    `semantic_args` son los argumentos que se comparan por parecido y no por igualdad:
    dos prompts que describen el mismo plano con palabras distintas son ambos correctos.
    La similitud es léxica (Jaccard sobre tokens de contenido) y no por embeddings a
    propósito: no queremos que la suite dependa de un servicio de embeddings ni de su
    versión, porque eso hace que el mismo commit puntúe distinto en dos días distintos.
    Para lo que se usa —detectar que el prompt habla del mismo plano— basta y sobra.
    """

    name = "param_relevance"

    #: Palabras vacías del dominio: aparecen en casi todos los prompts de vídeo y sólo
    #: sirven para inflar el parecido entre dos prompts que no se parecen en nada.
    _STOPWORDS = frozenset(
        """a an the of in on at to with and or for from shot scene video film cinematic
        camera high quality detailed 4k realistic""".split()
    )

    def __init__(self, *, semantic_args: set[str] | None = None, similarity_floor: float = 0.35):
        self.semantic_args = semantic_args or {"prompt", "negative_prompt"}
        self.similarity_floor = similarity_floor

    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        expected_call = _as_dict(expected)
        if not expected_call:
            # Sin llamada esperada, el acierto es **no** llamar a nada: es el caso de
            # "el usuario aún está en preproducción y el agente no debe gastar créditos".
            calls = _tool_calls(output)
            return Score(
                name=self.name,
                score=1.0 if not calls else 0.0,
                metadata={"reason": "no tool call expected", "actual_calls": [c.get("name") for c in calls]},
            )

        calls = _tool_calls(output)
        if not calls:
            return self._fail("expected a generation tool call but the agent made none")

        best = 0.0
        best_detail: dict[str, Any] = {}
        for call in calls:
            score, detail = self._score_call(call, expected_call)
            if score > best:
                best, best_detail = score, detail

        return Score(name=self.name, score=best, metadata=best_detail)

    def _score_call(self, call: dict[str, Any], expected: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        detail: dict[str, Any] = {"tool": call.get("name"), "expected_tool": expected.get("name")}
        if call.get("name") != expected.get("name"):
            return 0.0, detail

        score = 0.5
        expected_args = expected.get("args") or {}
        actual_args = call.get("args") or {}

        if not expected_args:
            # No se esperaban argumentos: puntúa la ausencia de argumentos.
            return (1.0 if not actual_args else 0.5), detail

        per_arg = 0.5 / len(expected_args)
        arg_scores: dict[str, float] = {}
        for arg, expected_value in expected_args.items():
            actual_value = actual_args.get(arg)
            if arg in self.semantic_args:
                similarity = self._similarity(str(actual_value or ""), str(expected_value or ""))
                got = similarity if similarity >= self.similarity_floor else 0.0
            elif isinstance(expected_value, (int, float)) and isinstance(actual_value, (int, float)):
                # Tolerancia numérica: los proveedores cuantizan la duración a frames,
                # así que 5.0 y 5.04 son la misma decisión editorial.
                got = 1.0 if abs(float(actual_value) - float(expected_value)) <= 0.25 else 0.0
            else:
                got = 1.0 if actual_value == expected_value else 0.0

            arg_scores[arg] = round(got, 3)
            score += got * per_arg

        detail["arg_scores"] = arg_scores
        return round(min(score, 1.0), 4), detail

    def _similarity(self, actual: str, expected: str) -> float:
        a, b = self._tokens(actual), self._tokens(expected)
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _tokens(self, text: str) -> set[str]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        return {w for w in words if w not in self._STOPWORDS and len(w) > 2}


def _tool_calls(output: Any) -> list[dict[str, Any]]:
    """Extrae las tool calls de un mensaje del agente, de un dict o de una lista."""
    if output is None:
        return []
    if isinstance(output, list):
        return [_as_dict(c) for c in output]
    calls = getattr(output, "tool_calls", None)
    if calls is None and isinstance(output, dict):
        calls = output.get("tool_calls")
    if calls is None:
        return []
    return [_as_dict(c) for c in calls]


# --------------------------------------------------------------------------- #
# 6. RenderValidity                                                            #
# --------------------------------------------------------------------------- #


class RenderValidity(Scorer):
    """
    ¿La petición de generación era válida para ese proveedor?

    Copia la **graduación por tipo de fallo** de `SQLSyntaxCorrectness`, que es el
    detalle fino de ese scorer:

    - **0.0 — rechazo local o del proveedor.** Duración fuera del rango del modelo,
      aspect no soportado, i2v sobre un modelo que no lo hace. El agente pidió algo
      imposible: no entendió las capacidades del modelo.
    - **0.5 — aceptado y luego fallido.** La petición era formalmente válida (el
      proveedor la encoló) pero el render no terminó. Es un fallo distinto y a menudo
      no es culpa del agente: rate limit, caída, moderación de contenido.
    - **1.0 — render completo.**

    Aplastar esos dos casos en un cero haría el scorer inútil justo cuando más importa,
    porque el arreglo es opuesto: uno se arregla enseñándole al agente los límites del
    modelo, el otro con reintentos y fallback de proveedor.
    """

    name = "render_validity"

    #: Estados terminales de `generation_jobs` que significan "ni siquiera se intentó".
    _REJECTED = {"invalid", "rejected", "unsupported"}

    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        data = _as_dict(output)
        status = data.get("job_status") or data.get("status")

        if status is None:
            return self._skip("the case performed no render, nothing to validate")

        if status in self._REJECTED:
            return Score(
                name=self.name,
                score=0.0,
                metadata={
                    "reason": "the request was rejected before running",
                    "error": data.get("error"),
                },
            )

        if status in ("failed", "nsfw", "cancelled"):
            return Score(
                name=self.name,
                score=0.5,
                metadata={
                    "reason": "the request was accepted by the provider but the render did not complete",
                    "status": status,
                    "error": data.get("error"),
                },
            )

        if status == "succeeded":
            return Score(name=self.name, score=1.0, metadata={"status": status})

        # Todavía en vuelo cuando terminó el caso: no hay veredicto que dar.
        return self._skip(f"job still in non-terminal state '{status}'")


# --------------------------------------------------------------------------- #
# 7. CostEfficiency                                                            #
# --------------------------------------------------------------------------- #


class CostEfficiency(Scorer):
    """
    ¿El resultado justificaba el modelo elegido?

    Scorer propio, sin equivalente en PostHog, porque el problema es nuestro: el rango
    de precio entre modelos de vídeo es de 30x ($0.05/s a $1.50/s). Un agente que pone
    el modelo más caro en todos los planos produce resultados excelentes y una unit
    economics imposible, y **ningún otro scorer de esta lista lo detecta**: guion,
    continuidad y estilo saldrían todos altos.

    Se puntúa contra un presupuesto de referencia, no contra el mínimo absoluto. Pedirle
    al agente que siempre elija lo más barato es tan malo como lo contrario: un plano de
    apertura merece el modelo bueno. Lo que se penaliza es el gasto sistemáticamente por
    encima de lo que el caso pedía.

    Los reintentos cuentan como gasto. Un agente que acierta a la tercera ha gastado
    tres veces, y esa es exactamente la información que interesa vigilar.
    """

    name = "cost_efficiency"

    def __init__(self, *, tolerance: float = 1.2):
        #: Margen sobre el presupuesto antes de empezar a penalizar. Por debajo de esto
        #: no se premia gastar menos: ahorrar créditos degradando el resultado no es
        #: eficiencia, y ya se mide la calidad en los otros seis scorers.
        self.tolerance = tolerance

    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        data = _as_dict(output)
        spent = data.get("credits_spent")
        budget = _as_dict(expected).get("credits_budget") or kwargs.get("credits_budget")

        if spent is None:
            return self._skip("the case reports no credit spend")
        if not budget:
            return self._skip("no reference budget for this case")

        ratio = float(spent) / float(budget)
        retries = int(data.get("retries") or 0)

        if ratio <= self.tolerance:
            score = 1.0
            reason = "within budget"
        elif ratio <= self.tolerance * 2:
            score = 0.5
            reason = "over budget but within twice the tolerance"
        else:
            score = 0.0
            reason = "spend is more than double the tolerated budget"

        return Score(
            name=self.name,
            score=score,
            metadata={
                "reason": reason,
                "credits_spent": spent,
                "credits_budget": budget,
                "ratio": round(ratio, 3),
                "retries": retries,
            },
        )


# --------------------------------------------------------------------------- #
# Utilidades                                                                   #
# --------------------------------------------------------------------------- #


def _read_bytes(path_or_bytes: Any) -> bytes:
    if isinstance(path_or_bytes, bytes):
        return path_or_bytes
    with open(path_or_bytes, "rb") as fh:
        return fh.read()


ALL_SCORERS: Sequence[type[Scorer]] = (
    ScriptCoherence,
    ShotListCompleteness,
    CharacterContinuity,
    StyleAdherence,
    ParamRelevance,
    RenderValidity,
    CostEfficiency,
)
