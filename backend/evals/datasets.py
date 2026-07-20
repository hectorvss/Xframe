"""
Datasets semilla.

Hardcodeados y tipados aquí, no en YAML ni en un servicio externo. Tres razones, y las
tres son de PostHog:

1. **El tipo los valida.** Un `expected` mal formado revienta al importar, no a mitad de
   una suite de veinte minutos.
2. **El diff se lee en la review.** Cambiar un caso de referencia es cambiar la vara de
   medir; debe verse igual que un cambio de código.
3. **Los casos de regresión llevan su nota.** Cada fallo de producción se convierte en un
   `EvalCase` permanente con `regression_note`, para que nadie lo borre dentro de seis
   meses por parecerle redundante.

Son semilla, no cobertura. La disciplina que hace útil un eval no es escribir el dataset
una vez, es revisar trazas de producción y curarlo continuamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from evals.base import EvalCase

# --------------------------------------------------------------------------- #
# Tipos                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Brief:
    """Lo que pide el cliente. Es la entrada del pipeline de preproducción."""

    text: str
    piece_kind: Literal["spot", "trailer", "explainer", "short"] = "spot"
    duration_s: float = 30.0
    aspect: str = "16:9"
    constraints: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [
            f"Piece: {self.piece_kind}, {self.duration_s:.0f}s, {self.aspect}",
            f"Brief: {self.text}",
        ]
        if self.constraints:
            parts.append("Constraints: " + "; ".join(self.constraints))
        return "\n".join(parts)


@dataclass(slots=True)
class ShotSpec:
    """Un plano de la shot list de referencia. Es el vocabulario del guion técnico."""

    beat: str
    """Intención narrativa: qué hace este plano en la historia."""

    shot_size: Literal["ews", "ws", "ms", "mcu", "cu", "ecu"]
    camera_motion: str | None = None
    duration_s: float = 3.0
    elements: list[str] = field(default_factory=list)
    generation: Literal["t2v", "i2v", "keyframe"] = "i2v"

    def __str__(self) -> str:
        motion = self.camera_motion or "static"
        who = f" [{', '.join(self.elements)}]" if self.elements else ""
        return f"{self.shot_size.upper()} {motion} {self.duration_s:.1f}s — {self.beat}{who}"


@dataclass(slots=True)
class ExpectedGenerationCall:
    """Llamada de generación esperada, para `ParamRelevance`."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContinuityInput:
    """Entrada de un caso de continuidad: una secuencia ya planificada, lista para render."""

    project_brief: str
    character_sheet: str
    style_bible: str
    shots: list[ShotSpec]
    reference_frame: str | None = None
    credits_budget: int = 0


def format_shots(shots: list[ShotSpec]) -> str:
    return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(shots))


# --------------------------------------------------------------------------- #
# Criterios de evaluación                                                      #
# --------------------------------------------------------------------------- #

SCRIPT_CRITERIA = """
1. The script must cover every beat the brief explicitly requires. Heavily penalise a missing required beat.
2. Heavily penalise material the brief did not ask for: an extra character, an extra location, a
   call to action nobody requested. Excess is as much a failure as omission.
3. The total of the shot durations implied by the script must fit the requested duration within
   about 15%. A 30s spot whose script needs 50s is not a valid script.
4. Stated constraints (no on-screen text, no visible faces, single location, brand safety) are hard
   requirements. Violating one caps the rating at somewhat_misaligned regardless of other quality.
5. Two scripts that hit the same beats with different imagery are BOTH correct. Do not penalise
   divergence from the reference where the brief left the choice open.
6. Do not reward craft. A beautifully written script that misses a required beat scores worse than
   a plain one that covers everything.
""".strip()

SHOTLIST_CRITERIA = """
1. Every beat of the script must be covered by at least one shot. Heavily penalise an uncovered beat.
2. Heavily penalise shots that serve no beat of the script.
3. Shot sizes must serve the beat: an emotional turn covered only in extreme wide shot is a failure,
   as is a location reveal covered only in close-up.
4. Shots referencing a character must list that character in their elements, otherwise the
   generation step has no reference image and continuity is lost by construction.
5. Camera motion must be motivated. Penalise motion applied to every shot indiscriminately: it reads
   as a default that was never chosen.
6. Shot count may differ from the reference. Different coverage of the same beats is legitimate.
""".strip()

SHOT_SCHEMA = """
beat:          string  — the narrative intent of the shot; what it does for the story
shot_size:     ews | ws | ms | mcu | cu | ecu
camera_motion: id from the camera_motions taxonomy, or null for a locked-off shot
duration_s:    number — must fall inside the chosen model's min/max duration
elements:      list of project element names (characters, locations, props) used as visual references
generation:    t2v (text to video) | i2v (image to video) | keyframe (first/last frame interpolation)
""".strip()


# --------------------------------------------------------------------------- #
# Casos: brief → guion                                                         #
# --------------------------------------------------------------------------- #

SCRIPT_CASES: list[EvalCase[Brief, str]] = [
    EvalCase(
        name="spot_coffee_morning",
        input=Brief(
            text=(
                "30-second spot for a specialty coffee brand. A city waking up at dawn; "
                "a barista opening the shop; the first customer of the day. End on the logo."
            ),
            piece_kind="spot",
            duration_s=30.0,
        ),
        expected="""
1. Dawn over the empty city. Blue hour, streets still wet, no people.
2. A hand pulls up the shop shutter. The interior lights come on.
3. The barista sets up: grinder, tamper, portafilter locked in.
4. Espresso pours. Steam. Close on the crema.
5. The door opens; the first customer walks in as the light turns golden.
6. The cup slides across the counter. A nod between them.
7. Logo on the shop window, city moving behind it.
""".strip(),
    ),
    EvalCase(
        name="trailer_thriller_apartment",
        input=Brief(
            text=(
                "60-second trailer for a psychological thriller set entirely inside one apartment. "
                "One protagonist. Build dread through repetition of an ordinary action."
            ),
            piece_kind="trailer",
            duration_s=60.0,
            constraints=["single location", "one character on screen at any time"],
        ),
        expected="""
1. Morning. She locks the front door: three turns of the key. Ordinary.
2. Coffee, window, city outside. Calm.
3. Night. She locks the door again: three turns. Slightly faster.
4. She notices the chain is already fastened. She did not fasten it.
5. Morning again. The lock turns. The sound is wrong — heavier.
6. She checks the peephole. Black.
7. Night. She locks the door. The camera stays on the door after she leaves frame.
8. The handle turns from the other side. Cut to black on the title.
""".strip(),
        # Critical: caso de regresión. El agente metía un segundo personaje en el
        # exterior "para dar contexto", violando la restricción de un solo personaje,
        # y el juez lo dejaba pasar porque el resultado era bueno cinematográficamente.
        regression_note="hard constraints must cap the rating even when the piece is good",
    ),
    EvalCase(
        name="explainer_saas_onboarding",
        input=Brief(
            text=(
                "45-second explainer for a B2B scheduling tool. Show the problem (double bookings, "
                "email ping-pong), then the product resolving it. Sober, no humour."
            ),
            piece_kind="explainer",
            duration_s=45.0,
            constraints=["no on-screen text", "no visible brand logos other than ours"],
        ),
        expected="""
1. An office worker stares at a calendar with three overlapping meetings.
2. Close on a phone: an email thread that keeps growing.
3. She misses a call; the room she walks into is already occupied.
4. Transition: the calendar clears itself, one block at a time.
5. She opens the product; a single available slot is confirmed with one action.
6. She walks into an empty, ready room. She is on time.
7. Logo, held, on a clean desk.
""".strip(),
        # Critical: el agente quemaba texto en pantalla ("Double booked!") pese a la
        # restricción, porque el modelo de vídeo lo genera con facilidad.
        regression_note="no-on-screen-text is violated by default unless it is judged explicitly",
    ),
    EvalCase(
        name="spot_underspecified_perfume",
        input=Brief(
            text="Something for a perfume launch. Make it feel expensive.",
            piece_kind="spot",
            duration_s=20.0,
        ),
        expected="""
1. Extreme close on fabric moving in slow motion, backlit.
2. A silhouette crossing a shaft of light in an empty room.
3. Close on the neck and jawline; light passes across.
4. The bottle, held, catching a single hard highlight.
5. The bottle on a stone surface. Shadow settles. Logo.
""".strip(),
        # Un brief vago es un caso de primera clase: mide si el agente propone una
        # dirección coherente en vez de interrogar al usuario o producir un guion genérico.
        metadata={"underspecified": True},
    ),
]


# --------------------------------------------------------------------------- #
# Casos: guion → shot list                                                     #
# --------------------------------------------------------------------------- #

SHOTLIST_CASES: list[EvalCase[str, list[ShotSpec]]] = [
    EvalCase(
        name="shotlist_coffee_morning",
        input=SCRIPT_CASES[0].expected,
        expected=[
            ShotSpec("Dawn over the empty city", "ews", "slow-push-in", 4.0, ["City"], "t2v"),
            ShotSpec("The shutter goes up", "ms", None, 3.0, ["Barista", "Shop"]),
            ShotSpec("Setting up the machine", "cu", "handheld", 3.0, ["Barista"]),
            ShotSpec("Espresso pours, crema forms", "ecu", None, 4.0, ["Shop"]),
            ShotSpec("First customer enters", "ws", None, 4.0, ["Barista", "Customer", "Shop"]),
            ShotSpec("The cup slides across the counter", "mcu", None, 3.0, ["Barista", "Customer"]),
            ShotSpec("Logo on the window", "ms", "slow-pull-out", 4.0, ["Shop"]),
        ],
    ),
    EvalCase(
        name="shotlist_thriller_repetition",
        input=SCRIPT_CASES[1].expected,
        expected=[
            ShotSpec("She locks the door, ordinary", "mcu", None, 4.0, ["Protagonist", "Door"]),
            ShotSpec("Coffee by the window, calm", "ms", None, 4.0, ["Protagonist"]),
            ShotSpec("She locks the door again, faster", "mcu", None, 3.0, ["Protagonist", "Door"]),
            ShotSpec("The chain is already fastened", "ecu", "slow-push-in", 4.0, ["Door"]),
            ShotSpec("The lock sounds wrong", "cu", None, 3.0, ["Door"]),
            ShotSpec("The peephole is black", "ecu", None, 3.0, ["Protagonist", "Door"]),
            ShotSpec("She leaves frame; the door stays", "ws", None, 5.0, ["Door"]),
            ShotSpec("The handle turns from outside", "ecu", None, 4.0, ["Door"]),
        ],
        # Los planos repetidos del mismo motivo (la puerta) deben reutilizar el mismo
        # element: es lo que sostiene la continuidad de la localización entre tomas.
        regression_note="repeated motifs must reuse one element, not spawn a new one per shot",
    ),
]


# --------------------------------------------------------------------------- #
# Casos: parámetros de generación                                              #
# --------------------------------------------------------------------------- #

PARAM_CASES: list[EvalCase[str, ExpectedGenerationCall | None]] = [
    EvalCase(
        name="param_i2v_with_character_ref",
        input=(
            "Generate shot 3 of the thriller: close on the door chain, slow push in, 4 seconds. "
            "The protagonist element already has a reference image."
        ),
        expected=ExpectedGenerationCall(
            name="generate_video",
            args={
                "prompt": "extreme close-up of a fastened door chain, slow push in, cold light",
                "duration_s": 4.0,
                "aspect": "16:9",
                "camera_motion": "slow-push-in",
                "generation": "i2v",
            },
        ),
    ),
    EvalCase(
        name="param_no_generation_in_preproduction",
        input="I like beat 4. Can you rewrite it so the chain is discovered later?",
        expected=None,
        # Critical: el agente llamaba a generate_video al hablar de un plano concreto,
        # aunque el usuario solo estuviera editando el guion. Gastar créditos sin que
        # nadie los pida es el fallo más caro que puede cometer.
        regression_note="discussing a shot is not a request to render it",
    ),
]


# --------------------------------------------------------------------------- #
# Casos: continuidad y estilo (requieren render real)                          #
# --------------------------------------------------------------------------- #

CONTINUITY_CASES: list[EvalCase[ContinuityInput, dict[str, Any]]] = [
    EvalCase(
        name="continuity_thriller_apartment",
        input=ContinuityInput(
            project_brief="Psychological thriller in one apartment. One protagonist.",
            character_sheet=(
                "PROTAGONIST — woman, late thirties, shoulder-length dark hair worn down, "
                "no visible jewellery, grey wool cardigan over a white shirt throughout the piece. "
                "Wardrobe does not change: the piece spans several days but she is always dressed "
                "identically, which is itself a story point."
            ),
            style_bible=(
                "Desaturated cool palette, teal shadows, no warm highlights. Single hard practical "
                "light source per shot with deep falloff. Handheld only where noted. Grain "
                "consistent with pushed 500T stock. No lens flares."
            ),
            shots=SHOTLIST_CASES[1].expected or [],
            credits_budget=900,
        ),
        expected={"credits_budget": 900},
    ),
    EvalCase(
        name="continuity_coffee_two_characters",
        input=ContinuityInput(
            project_brief="Coffee brand spot. Barista and one customer.",
            character_sheet=(
                "BARISTA — man, twenties, short curly hair, dark green apron over a white tee, "
                "forearm tattoo on the right arm. CUSTOMER — woman, fifties, silver bob, camel coat."
            ),
            style_bible=(
                "Warm golden hour palette shifting from blue-hour cool to warm across the piece. "
                "Soft top light, shallow depth of field, clean highlights, gentle halation."
            ),
            shots=SHOTLIST_CASES[0].expected or [],
            credits_budget=1100,
        ),
        expected={"credits_budget": 1100},
        # Dos personajes en el mismo plano es donde más deriva la identidad: el modelo
        # tiende a mezclar rasgos entre ambos cuando comparten encuadre.
        regression_note="identity bleed between characters sharing a frame",
    ),
]
