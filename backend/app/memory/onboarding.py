"""
Onboarding de la memoria: la biblia inicial.

Equivale al `/init` de PostHog, pero con una diferencia de fondo que cambia el diseño.
PostHog *no puede* saber a qué se dedica la empresa sin preguntar o sin scrapear la web,
así que su onboarding es un grafo de seis nodos con formulario de confirmación y hasta
tres preguntas de seguimiento.

Nosotros sí lo sabemos: **el brief y los assets aprobados ya son la respuesta**. Un asset
aprobado es una decisión estética que el usuario ya ha tomado, y volver a preguntarle por
ella es la forma más rápida de parecer que no estabas mirando. Por eso este onboarding
infiere primero y pregunta después, con un máximo duro de dos preguntas, y solo de las
que cambian materialmente el trabajo (formato de entrega, si un personaje debe ser la
misma persona entre planos). Nunca de gusto: el gusto se decide y se corrige.

Se dispara cuando el proyecto no tiene `style_bible` y ya hay material del que inferir.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app import db
from app.memory.prompts import MEMORY_ONBOARDING_PROMPT, ONBOARDING_INTRO
from app.memory.store import MemoryKind, ProjectMemoryStore

logger = logging.getLogger(__name__)

MIN_ASSETS_FOR_ONBOARDING = 1
"""
Material mínimo. Con cero assets aprobados, la biblia saldría del brief a secas y sería
adivinación disfrazada de memoria: mejor esperar al primer render que el usuario valide.
"""

MAX_QUESTIONS = 2


# --------------------------------------------------------------------------- #
# Salida estructurada                                                          #
# --------------------------------------------------------------------------- #


class CharacterSheetDraft(BaseModel):
    element_name: str = Field(description="Name of the element, exactly as in the project.")
    content: str = Field(description="Atomic sentences describing the character, one per line.")


class InitialMemory(BaseModel):
    """
    Lo que devuelve el modelo. Estructurado y no texto libre porque cada campo va a una
    fila distinta de `project_memory` y parsear prosa para repartirla es un fallo latente.
    """

    style_bible: str = Field(description="4-10 atomic sentences, one per line.")
    continuity_rules: str = Field(default="", description="0-5 atomic sentences. May be empty.")
    character_sheets: list[CharacterSheetDraft] = Field(default_factory=list)
    questions: list[str] = Field(
        default_factory=list,
        description=(
            "At most 2, and only if a wrong answer would change the work materially. "
            "Prefer an empty list."
        ),
    )


class OnboardingResult(BaseModel):
    """Resultado del onboarding, listo para que el nodo llamante lo cuente al usuario."""

    ran: bool = False
    reason: str = ""
    style_bible: str = ""
    questions: list[str] = Field(default_factory=list)
    sheets_written: int = 0

    @property
    def message(self) -> str:
        """El texto que ve el usuario. Corto: la biblia ya se la enseña la UI."""
        if not self.ran:
            return ""
        parts = [ONBOARDING_INTRO]
        if self.questions:
            parts.append("Solo me falta esto:")
            parts.extend(f"- {q}" for q in self.questions)
        return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Onboarding                                                                   #
# --------------------------------------------------------------------------- #


class MemoryOnboarding:
    """Genera y persiste la memoria inicial de un proyecto."""

    def __init__(
        self,
        project_id: str,
        *,
        store: ProjectMemoryStore | None = None,
        model: Any | None = None,
    ) -> None:
        self._project_id = project_id
        self._store = store or ProjectMemoryStore(project_id)
        self._model = model

    async def should_run(self) -> bool:
        """
        ¿Toca? Solo si no hay biblia y hay material aprobado del que inferirla.

        Es idempotente y barato de consultar, así que se puede llamar en cada turno sin
        pensárselo.
        """
        if not await self._store.is_empty():
            return False
        return await self._approved_asset_count() >= MIN_ASSETS_FOR_ONBOARDING

    async def run(self, *, config: Any | None = None) -> OnboardingResult:
        """
        Escribe la memoria inicial y devuelve las (pocas) preguntas pendientes.

        Persiste aunque haya preguntas: una biblia provisional en la que trabajar es más
        útil que ninguna, y la respuesta a la pregunta la aplicará después el colector
        con `memory_replace`. Bloquear la escritura hasta tener respuesta dejaría al
        proyecto sin identidad visual justo mientras se generan los primeros planos.
        """
        if not await self.should_run():
            return OnboardingResult(ran=False, reason="already_initialised_or_no_material")

        brief, assets, elements = await self._gather()
        prompt = MEMORY_ONBOARDING_PROMPT.format(
            brief=brief or "(the user has not written a brief yet)",
            assets=assets or "(no approved assets)",
            elements=elements or "(no elements defined yet)",
        )

        try:
            memory = await self._generate(prompt, config)
        except Exception:
            logger.exception("memory_onboarding_failed", extra={"project_id": self._project_id})
            return OnboardingResult(ran=False, reason="generation_failed")

        return await self._persist(memory)

    # -- persistencia ------------------------------------------------------- #

    async def _persist(self, memory: InitialMemory) -> OnboardingResult:
        await self._store.set(MemoryKind.STYLE_BIBLE, memory.style_bible)
        if memory.continuity_rules.strip():
            await self._store.set(MemoryKind.CONTINUITY_RULES, memory.continuity_rules)

        by_name = await self._elements_by_name()
        written = 0
        for sheet in memory.character_sheets:
            element_id = by_name.get(sheet.element_name.strip().lower())
            if not element_id:
                # Un personaje inventado no se guarda. Una ficha huérfana no la ve nadie
                # y contamina la memoria con un nombre que el usuario nunca escribió.
                logger.info(
                    "onboarding_unknown_element",
                    extra={"project_id": self._project_id, "name": sheet.element_name},
                )
                continue
            await self._store.set(MemoryKind.CHARACTER_SHEET, sheet.content, element_id)
            written += 1

        return OnboardingResult(
            ran=True,
            style_bible=memory.style_bible,
            questions=memory.questions[:MAX_QUESTIONS],
            sheets_written=written,
        )

    # -- material ----------------------------------------------------------- #

    async def _gather(self) -> tuple[str, str, str]:
        """Brief, assets aprobados y elements, ya en texto plano para el prompt."""
        brief_rows = await db.fetch(
            """
            select text from public.brief_blocks
             where project_id = $1::uuid and length(trim(text)) > 0
             order by position
            """,
            self._project_id,
        )
        brief = "\n".join(r["text"] for r in brief_rows)

        asset_rows = await db.fetch(
            """
            select a.name, a.type, a.meta, a.prompt, a.model_id
              from public.assets a
              left join public.canvas_nodes n on n.id::text = a.shot_id
             where a.project_id = $1::uuid
               and a.status = 'ready'
               and (n.shot_status = 'approved' or n.id is null)
             order by a.created_at desc
             limit 20
            """,
            self._project_id,
        )
        assets = "\n".join(
            f"- {r['name']} ({r['type']}): {r['prompt'] or r['meta'] or 'sin prompt'}"
            for r in asset_rows
        )

        element_rows = await db.fetch(
            """
            select name, role, meta from public.assets
             where project_id = $1::uuid and role is not null
             order by role, name
            """,
            self._project_id,
        )
        elements = "\n".join(
            f"- {r['name']} [{r['role']}]: {r['meta'] or 'sin descripción'}" for r in element_rows
        )
        return brief, assets, elements

    async def _approved_asset_count(self) -> int:
        return int(
            await db.fetchval(
                "select count(*) from public.assets where project_id = $1::uuid and status = 'ready'",
                self._project_id,
            )
            or 0
        )

    async def _elements_by_name(self) -> dict[str, str]:
        rows = await db.fetch(
            "select id, name from public.assets where project_id = $1::uuid and role is not null",
            self._project_id,
        )
        return {r["name"].strip().lower(): str(r["id"]) for r in rows}

    # -- modelo ------------------------------------------------------------- #

    async def _generate(self, prompt: str, config: Any | None) -> InitialMemory:
        """
        Una sola llamada con salida estructurada. Modelo barato: esto es extracción.

        Si el proveedor no devuelve el objeto tipado (pasa con respuestas envueltas en
        markdown), se intenta parsear el JSON a mano antes de rendirse. Un onboarding que
        falla por una valla de código es un onboarding que nunca se ejecuta.
        """
        model = self._get_model()
        response = await model.ainvoke(prompt, config=config)
        if isinstance(response, InitialMemory):
            return response
        if isinstance(response, dict):
            return InitialMemory(**response)
        return InitialMemory(**json.loads(_strip_fences(str(getattr(response, "content", response)))))

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        from app import llm

        self._model = llm.chat_model(
            "fast",
            max_tokens=4_096,
            temperature=0.3,
            streaming=False,
        ).with_structured_output(InitialMemory)
        return self._model


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()
