"""
Primitivas del framework de evaluación.

Porta el diseño de `ee/hogai/eval/` de PostHog sin la dependencia de Braintrust: el
harness es pequeño y lo que aporta valor no es la plataforma, son las reglas. Las que
se copian literalmente, porque son las que hacen que un eval sirva para algo:

1. **`score=None` no es `score=0.0`.** `None` significa "no aplica" y **no entra en la
   media**. Un scorer de continuidad de personaje sobre un caso sin personajes debe
   abstenerse; si devolviera 0.0, contaminaría la métrica y empujaría a optimizar algo
   que no se está midiendo.

2. **Scorers graduados, nunca binarios.** El crédito parcial (0.5) es lo que permite
   distinguir "eligió mal la herramienta" de "eligió bien la herramienta con un
   argumento flojo". Un scorer binario dice que ambos fallaron y no orienta el arreglo.

3. **El juez elige una etiqueta cualitativa; el número lo pone el código.** Pedirle un
   número a un LLM produce un 0.8 que no significa nada y que se mueve entre
   ejecuciones. Pedirle "slightly_off" produce una decisión reproducible y auditable.

4. **"Be harsh" y "do not apply general knowledge".** Los jueces LLM son
   sistemáticamente generosos y tienden a opinar por su cuenta en vez de comparar con
   la referencia. Las dos frases están en todos los prompts de juez de este paquete.

5. **Gating antes de llamar al juez.** Si no hay nada que juzgar, se devuelve `None` sin
   gastar una llamada. En un dominio donde el "output" puede ser un vídeo de 4K, esto
   no es un ahorro marginal.

Ejecución: pytest con `python_files = eval_*.py` (ver `pyproject.toml`). Se filtran
casos con `--eval <substr>`.
"""

from __future__ import annotations

import asyncio
import os
import re
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, Sequence, TypeVar

import structlog

logger = structlog.get_logger(__name__)

Input = TypeVar("Input")
Output = TypeVar("Output")

#: Timeout por caso. Un caso que genera vídeo de verdad tarda minutos, no segundos.
DEFAULT_CASE_TIMEOUT_S = float(os.getenv("EVAL_CASE_TIMEOUT_S", "480"))

#: Concurrencia. Alta a propósito: el cuello de botella es la latencia del proveedor,
#: no nuestra CPU. Se baja con la variable de entorno cuando se está haciendo rate limit.
DEFAULT_CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "8"))


# --------------------------------------------------------------------------- #
# Score                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Score:
    """
    Resultado de un scorer sobre un caso.

    `score=None` es un valor de primera clase: significa "no aplicable / saltado".
    Se excluye de la agregación en vez de contarse como cero.
    """

    name: str
    score: float | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.score is not None and not (0.0 <= self.score <= 1.0):
            raise ValueError(
                f"Scorer '{self.name}' returned {self.score}, outside [0.0, 1.0]. "
                f"Scores must be normalised so that suites remain comparable."
            )

    @property
    def applies(self) -> bool:
        return self.score is not None


class Scorer(ABC):
    """
    Un scorer mide **una** dimensión. Nunca se compone un "score global".

    Es la metodología de la §6.4 del informe: una sola ejecución del pipeline, N
    scorers ortogonales sobre esa misma traza. Un número agregado esconde exactamente
    la información que se necesita para arreglar el fallo.
    """

    name: str

    @abstractmethod
    async def score_case(self, *, input: Any, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        """Devuelve el `Score` de este caso. Debe abstenerse con `None` si no aplica."""

    def _skip(self, reason: str) -> Score:
        return Score(name=self.name, score=None, metadata={"reason": reason})

    def _fail(self, reason: str, **extra: Any) -> Score:
        return Score(name=self.name, score=0.0, metadata={"reason": reason, **extra})


# --------------------------------------------------------------------------- #
# Casos y suites                                                               #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class EvalCase(Generic[Input, Output]):
    """
    Un caso de evaluación, tipado.

    Los datasets van hardcodeados en `datasets.py` como objetos, no como strings
    sueltos ni como YAML: así el tipo los valida y el diff de un cambio de dataset se
    lee en la review. Cada bug de producción debería acabar aquí como un caso con un
    comentario que explique por qué existe.
    """

    input: Input
    expected: Output | None = None
    #: Identificador legible. Es contra esto contra lo que filtra `--eval`.
    name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Nota de regresión: qué se rompió una vez y por eso este caso existe.
    regression_note: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            self.name = re.sub(r"\W+", "_", str(self.input))[:60].strip("_").lower()


@dataclass(slots=True)
class CaseResult:
    case_name: str
    scores: list[Score]
    error: str | None = None


@dataclass(slots=True)
class EvalReport:
    """Resultado agregado de una suite. Es lo que se imprime y sobre lo que se asierta."""

    experiment_name: str
    results: list[CaseResult]

    def mean(self, scorer_name: str) -> float | None:
        """
        Media de un scorer **ignorando los `None`**.

        Devuelve `None` si ningún caso aplicaba: no hay dato, y fingir un 0.0 o un 1.0
        sería inventarlo.
        """
        values = [
            s.score
            for r in self.results
            for s in r.scores
            if s.name == scorer_name and s.score is not None
        ]
        return statistics.fmean(values) if values else None

    @property
    def scorer_names(self) -> list[str]:
        seen: dict[str, None] = {}
        for r in self.results:
            for s in r.scores:
                seen.setdefault(s.name, None)
        return list(seen)

    @property
    def errors(self) -> list[CaseResult]:
        return [r for r in self.results if r.error]

    def assert_min(self, **thresholds: float) -> None:
        """
        Falla la suite si algún scorer baja de su umbral.

        Los umbrales se fijan **por scorer**, no globalmente: una regresión de
        continuidad de personaje no se debe poder compensar con un guion más bonito.
        """
        if self.errors:
            detail = "; ".join(f"{r.case_name}: {r.error}" for r in self.errors[:5])
            raise AssertionError(f"{len(self.errors)} case(s) raised: {detail}")

        failures: list[str] = []
        for scorer_name, minimum in thresholds.items():
            mean = self.mean(scorer_name)
            if mean is None:
                failures.append(f"{scorer_name}: no applicable cases (all scores were None)")
            elif mean < minimum:
                failures.append(f"{scorer_name}: {mean:.3f} < {minimum:.3f}")

        if failures:
            raise AssertionError(
                f"[{self.experiment_name}] below threshold — " + "; ".join(failures)
            )

    def render(self) -> str:
        lines = [f"\n=== {self.experiment_name} · {len(self.results)} cases ==="]
        for scorer_name in self.scorer_names:
            mean = self.mean(scorer_name)
            applicable = sum(
                1
                for r in self.results
                for s in r.scores
                if s.name == scorer_name and s.applies
            )
            value = f"{mean:.3f}" if mean is not None else "  n/a"
            lines.append(f"  {scorer_name:<28} {value}   (n={applicable})")
        for r in self.errors:
            lines.append(f"  ERROR {r.case_name}: {r.error}")
        return "\n".join(lines)


EvalTask = Callable[[Any], Awaitable[Any]]


async def run_eval(
    experiment_name: str,
    *,
    data: Sequence[EvalCase],
    task: EvalTask,
    scores: Sequence[Scorer],
    case_filter: str | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout_s: float = DEFAULT_CASE_TIMEOUT_S,
) -> EvalReport:
    """
    Ejecuta la suite: para cada caso, **una** llamada a `task` y N scorers sobre su
    salida.

    Un caso que revienta no aborta la suite: se registra su error y se sigue. En una
    suite que cuesta dinero y tarda veinte minutos, perder los otros 19 casos por el
    fallo del primero es inaceptable.
    """
    cases = [c for c in data if not case_filter or case_filter.lower() in c.name.lower()]
    if not cases:
        raise AssertionError(
            f"[{experiment_name}] no cases matched filter '{case_filter}'. "
            f"Available: {', '.join(c.name for c in data[:20])}"
        )

    sem = asyncio.Semaphore(concurrency)

    async def _run_case(case: EvalCase) -> CaseResult:
        async with sem:
            try:
                output = await asyncio.wait_for(task(case.input), timeout=timeout_s)
            except Exception as exc:  # noqa: BLE001 — el error del caso es un dato del informe
                logger.warning("eval case failed", case=case.name, error=str(exc))
                return CaseResult(case_name=case.name, scores=[], error=f"{type(exc).__name__}: {exc}")

            scored: list[Score] = []
            for scorer in scores:
                try:
                    scored.append(
                        await scorer.score_case(
                            input=case.input,
                            output=output,
                            expected=case.expected,
                            **case.metadata,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    # Un scorer que revienta se abstiene: no se puede distinguir de "no
                    # aplica" desde fuera, y puntuarlo 0.0 sería inventar un veredicto.
                    scored.append(
                        Score(
                            name=scorer.name,
                            score=None,
                            metadata={"reason": f"scorer raised: {type(exc).__name__}: {exc}"},
                        )
                    )
            return CaseResult(case_name=case.name, scores=scored)

    results = await asyncio.gather(*(_run_case(c) for c in cases))
    report = EvalReport(experiment_name=experiment_name, results=list(results))
    print(report.render())  # noqa: T201 — pytest corre los evals con -s a propósito
    return report


# --------------------------------------------------------------------------- #
# Jueces LLM                                                                   #
# --------------------------------------------------------------------------- #

#: Escala ordinal compartida por los jueces de calidad. Es la de PostHog, sin tocar.
#:
#: El juez **elige una de estas etiquetas**; el número lo asigna este diccionario. Que
#: los tramos no sean equidistantes (1.0, 0.9, 0.75, 0.5, 0.25, 0.0) es deliberado:
#: refleja que "casi perfecto" está mucho más cerca de "perfecto" que "algo desalineado"
#: de "muy desalineado".
ORDINAL_SCALE: dict[str, float | None] = {
    "perfect": 1.0,
    "near_perfect": 0.9,
    "slightly_off": 0.75,
    "somewhat_misaligned": 0.5,
    "strongly_misaligned": 0.25,
    "useless": 0.0,
}

#: Coletilla de calibración. Va al final del prompt, después de los datos, porque las
#: instrucciones críticas se obedecen mejor en posición reciente.
HARSHNESS = (
    "Details matter greatly here, so be harsh. "
    "Do not apply general knowledge about filmmaking: judge only against the reference "
    "provided above. If you are uncertain, choose the lower-scoring label."
)


def _judge_model() -> str:
    """
    Modelo del juez. Se fija por entorno y no se toca a la ligera: cambiar el juez
    invalida la comparación con todas las ejecuciones anteriores.
    """
    from app.config import get_settings

    return os.getenv("EVAL_JUDGE_MODEL") or get_settings().model_root


def render_template(template: str, variables: dict[str, Any]) -> str:
    """
    Sustitución Mustache mínima: `{{var}}` y `{{{var}}}` (sin escapar).

    Se usa el mismo templating que los prompts de producción para que un prompt de juez
    se pueda mover a producción, y al revés, sin reescribirlo.
    """
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return str(variables.get(key, ""))

    text = re.sub(r"\{\{\{(.*?)\}\}\}", _sub, template)
    return re.sub(r"\{\{(.*?)\}\}", _sub, text)


class LLMClassifier(Scorer):
    """
    Juez LLM que elige una etiqueta de un conjunto cerrado.

    Nunca se le pide un número. Se le pide una palabra de una lista, y el mapa
    `choice_scores` la convierte. Una etiqueta puede mapear a `None` (típicamente
    `empty`): "no había nada que juzgar" no es "lo hizo mal".
    """

    def __init__(
        self,
        *,
        name: str,
        prompt_template: str,
        choice_scores: dict[str, float | None],
        model: str | None = None,
        max_tokens: int = 512,
    ):
        self.name = name
        self.prompt_template = prompt_template
        self.choice_scores = choice_scores
        self.model = model or _judge_model()
        self.max_tokens = max_tokens

    async def classify(self, variables: dict[str, Any], images: list[bytes] | None = None) -> Score:
        """Renderiza el prompt, llama al juez y traduce su etiqueta a número."""
        from langchain_anthropic import ChatAnthropic

        prompt = render_template(self.prompt_template, variables)
        options = ", ".join(k for k, v in self.choice_scores.items() if v is not None or k == "empty")
        prompt += (
            f"\n\n{HARSHNESS}\n\n"
            f"Respond with exactly one of these labels and nothing else: {options}."
        )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images or []:
            import base64

            content.insert(
                0,
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                },
            )

        client = ChatAnthropic(model=self.model, max_tokens=self.max_tokens, temperature=0)
        response = await client.ainvoke([{"role": "user", "content": content}])
        raw = str(response.content if isinstance(response.content, str) else response.content[0].get("text", ""))

        label = self._parse_label(raw)
        if label is None:
            # El juez se salió del conjunto de etiquetas. Abstenerse y dejar constancia
            # es más honesto que asignarle un 0.0 al sistema por un fallo del juez.
            return Score(
                name=self.name,
                score=None,
                metadata={"reason": "judge returned an unrecognised label", "raw": raw[:300]},
            )

        return Score(
            name=self.name,
            score=self.choice_scores[label],
            metadata={"label": label, "judge_model": self.model},
        )

    def _parse_label(self, raw: str) -> str | None:
        text = raw.strip().strip(".*_` \n").lower()
        for label in self.choice_scores:
            if text == label.lower():
                return label
        # Tolerancia mínima: el juez a veces envuelve la etiqueta en una frase.
        matches = [label for label in self.choice_scores if label.lower() in text]
        return max(matches, key=len) if matches else None


# --------------------------------------------------------------------------- #
# Muestreo de vídeo para jueces visuales                                       #
# --------------------------------------------------------------------------- #

#: Factor de aceleración antes de pasar el vídeo al juez.
#:
#: El truco del informe, y no es cosmético: los modelos visuales muestrean vídeo a ~1
#: fps. Un plano de 8 segundos a velocidad normal se convierte en 8 frames, y ocho
#: frames casi idénticos no permiten juzgar continuidad — el juez ve el mismo instante
#: repetido. Acelerando 8x, esos mismos 8 frames cubren 64 segundos de acción, que es
#: donde se ve si el personaje deriva o si el estilo cambia a mitad de secuencia.
JUDGE_SPEEDUP = 8

#: Tope de frames por caso. Más allá, el coste sube linealmente y la señal no.
MAX_JUDGE_FRAMES = 12


async def sample_frames_for_judge(
    src: str, *, speedup: int = JUDGE_SPEEDUP, max_frames: int = MAX_JUDGE_FRAMES
) -> list[bytes]:
    """
    Extrae frames JPEG representativos de un vídeo, acelerándolo antes de muestrear.

    Se hace en una sola invocación de ffmpeg: `setpts=PTS/N` acelera y `fps=1` muestrea
    sobre el resultado acelerado, así que cada frame extraído dista `speedup` segundos
    del anterior en tiempo real. Se escala a 512 de ancho porque el juez no necesita
    resolución para valorar identidad y estilo, y los tokens de imagen sí se pagan.
    """
    from app.config import get_settings

    args = [
        get_settings().ffmpeg_path,
        "-hide_banner", "-nostdin", "-v", "error",
        "-i", src,
        "-vf", f"setpts=PTS/{speedup},fps=1,scale=512:-2",
        "-frames:v", str(max_frames),
        "-q:v", "4",
        "-f", "image2pipe", "-vcodec", "mjpeg",
        "pipe:1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"frame sampling failed for '{src}': {stderr.decode('utf-8', 'replace')[-400:]}")

    return _split_jpegs(stdout)[:max_frames]


def _split_jpegs(blob: bytes) -> list[bytes]:
    """
    Parte el stream MJPEG en imágenes sueltas por sus marcadores SOI/EOI.

    Se hace a mano en vez de escribir a disco porque los evals corren en CI, en
    paralelo, y un directorio temporal compartido entre casos concurrentes es una
    fuente de fallos intermitentes que cuesta días localizar.
    """
    frames: list[bytes] = []
    start = blob.find(b"\xff\xd8")
    while start != -1:
        end = blob.find(b"\xff\xd9", start + 2)
        if end == -1:
            break
        frames.append(blob[start : end + 2])
        start = blob.find(b"\xff\xd8", end + 2)
    return frames
