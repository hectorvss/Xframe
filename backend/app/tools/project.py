"""
Herramientas de lectura del proyecto.

Baratas, sin créditos, disponibles en todos los modos. Su papel es que el agente no
tenga que adivinar: si necesita saber qué planos hay, los pide; si necesita elegir
modelo con criterio de coste, consulta el catálogo.

Regla de todas las tools de este paquete, tomada de PostHog: el valor de retorno separa
`content` (texto barato, lo único que entra en el contexto del LLM) de `ui_payload`
(estructura completa, va al frontend por el canal de streaming). Devolver el JSON
entero al modelo cuesta un orden de magnitud más de tokens y no mejora ni una decisión.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from app import db
from app.taxonomy.builder import (
    SnapshotTool,
    build_args,
    described,
    enumerate_for_prompt,
    literal_of,
)
from app.taxonomy.repo import GenModel, TaxonomySnapshot
from app.tools.base import ToolContext
from app.tools.errors import UnknownEntityError, XframeToolRetryableError

# --------------------------------------------------------------------------- #
# read_project                                                                 #
# --------------------------------------------------------------------------- #


class ReadProjectArgs(BaseModel):
    sections: list[Literal["brief", "shots", "elements", "settings"]] = Field(
        default_factory=lambda: ["brief", "shots", "elements"],
        description=(
            "Which sections to read. Request only what you need: each section costs "
            "context. 'shots' is the shot list in narrative order, 'elements' are the "
            "characters, locations and objects defined for continuity."
        ),
    )


class ReadProjectTool(SnapshotTool):
    """Lectura del estado del proyecto."""

    name: str = "read_project"
    args_schema: type[BaseModel] = ReadProjectArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Read the current state of this project: the brief, the shot list in narrative "
        "order, the defined elements (characters, locations, objects) and the project "
        "settings.\n"
        "\n"
        "USE THIS when you need to know what already exists before writing or "
        "generating anything — before creating a shot, before referencing a character, "
        "or when the user refers to 'the second shot' or 'the same character as before'.\n"
        "\n"
        "DO NOT use this to poll for generation progress; that is check_job_status. "
        "DO NOT call it repeatedly within one turn: the project does not change between "
        "your own tool calls unless you changed it yourself."
    )

    async def _arun_impl(self, sections: list[str] | None = None, **_: Any) -> tuple[str, Any]:
        wanted = set(sections or ["brief", "shots", "elements"])
        ui: dict[str, Any] = {}
        lines: list[str] = []

        project = await db.fetchrow(
            "select id, title, prompt, settings from public.projects where id = $1",
            self.ctx.project_id,
        )
        if project is None:
            raise XframeToolRetryableError(
                "This project no longer exists. Tell the user and stop; there is nothing "
                "to read or generate."
            )
        lines.append(f"Project: {project['title']}")

        if "brief" in wanted:
            rows = await db.fetch(
                """
                select id, position, type, text, checked, src
                  from public.brief_blocks where project_id = $1 order by position
                """,
                self.ctx.project_id,
            )
            ui["brief"] = [dict(r) | {"id": str(r["id"])} for r in rows]
            if rows:
                lines.append("\nBrief:")
                lines += [f"  [{r['position']}] ({r['type']}) {r['text']}" for r in rows]
            else:
                lines.append("\nBrief: empty — nothing written yet.")

        if "shots" in wanted:
            rows = await db.fetch(
                """
                select id, position, title, text, spec, shot_status, thumb, media
                  from public.canvas_nodes
                 where project_id = $1 and type = 'shot'
                 order by position nulls last, title
                """,
                self.ctx.project_id,
            )
            ui["shots"] = [dict(r) | {"id": str(r["id"])} for r in rows]
            if rows:
                lines.append("\nShots (narrative order):")
                for r in rows:
                    lines.append(
                        f"  #{r['position']} {r['title']} [{r['shot_status']}] "
                        f"id={r['id']} — {(r['text'] or '')[:160]}"
                    )
            else:
                lines.append("\nShots: none yet.")

        if "elements" in wanted:
            ui["elements"] = [
                {"id": e.id, "name": e.name, "role": e.role, "url": e.url, "status": e.status}
                for e in self.snap.elements
            ]
            if self.snap.elements:
                lines.append("\nElements (use these exact names in element_refs):")
                lines += [
                    f"  {e.name} ({e.role})"
                    + ("" if e.usable_as_reference else " — no reference image yet")
                    for e in self.snap.elements
                ]
            else:
                lines.append("\nElements: none defined. Use define_element before "
                             "relying on visual continuity.")

        if "settings" in wanted:
            ui["settings"] = dict(project["settings"] or {})
            lines.append(f"\nSettings: {ui['settings'] or 'defaults'}")

        return "\n".join(lines), ui


# --------------------------------------------------------------------------- #
# search_assets                                                                #
# --------------------------------------------------------------------------- #


class SearchAssetsArgs(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Free text matched against asset name, role and description. Use words the "
            "user actually said, not synonyms you invented."
        ),
    )
    kind: Literal["any", "image", "video", "audio"] = Field(
        "any", description="Restrict by asset type."
    )
    limit: int = Field(10, ge=1, le=50, description="Maximum results. Keep it small.")


class SearchAssetsTool(SnapshotTool):
    """Búsqueda sobre los assets del proyecto."""

    name: str = "search_assets"
    args_schema: type[BaseModel] = SearchAssetsArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Search the assets already generated or uploaded in this project by name, role "
        "or description.\n"
        "\n"
        "USE THIS when the user refers to something that may already exist ('the shot of "
        "the car', 'that portrait we made yesterday') and you need its asset id before "
        "editing, upscaling or assembling it.\n"
        "\n"
        "DO NOT use this to discover characters or locations — those are elements and "
        "they are already listed in your tools' enums and in read_project. DO NOT "
        "generate a new asset just because a search returned nothing; ask the user first."
    )

    async def _arun_impl(
        self, query: str, kind: str = "any", limit: int = 10, **_: Any
    ) -> tuple[str, Any]:
        rows = await db.fetch(
            """
            select id, name, type, role, url, status, created_at
              from public.assets
             where project_id = $1
               and ($2 = 'any' or type = $2)
               and (name ilike '%' || $3 || '%' or meta ilike '%' || $3 || '%'
                    or coalesce(role, '') ilike '%' || $3 || '%')
             order by created_at desc
             limit $4
            """,
            self.ctx.project_id,
            kind,
            query,
            limit,
        )
        ui = [dict(r) | {"id": str(r["id"]), "created_at": r["created_at"].isoformat()} for r in rows]
        if not rows:
            return (
                f"No assets in this project match '{query}'. Do not invent an asset id — "
                f"either ask the user which asset they mean or generate a new one.",
                [],
            )
        lines = [f"{len(rows)} asset(s) matching '{query}':"]
        lines += [f"  {r['name']} ({r['type']}, {r['status']}) id={r['id']}" for r in rows]
        return "\n".join(lines), ui


# --------------------------------------------------------------------------- #
# list_available_models                                                        #
# --------------------------------------------------------------------------- #


class ListAvailableModelsTool(SnapshotTool):
    """
    Descubrimiento en dos niveles: la tool de generación lleva el enum con los ids, y
    esta lleva el detalle (capacidades, coste, duraciones) para elegir con criterio.

    Separarlas es lo que evita meter el catálogo completo en la descripción de cada
    tool de generación, que se pagaría en cada turno de cada conversación.
    """

    name: str = "list_available_models"
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    async def _arun_impl(
        self,
        modality: str = "video",
        max_credits_per_unit: int | None = None,
        requires: list[str] | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        models = list(self.snap.models_for(modality))  # type: ignore[arg-type]
        for capability in requires or []:
            models = [m for m in models if getattr(m, f"supports_{capability}", False)]
        if max_credits_per_unit is not None:
            models = [m for m in models if m.credits_per_unit <= max_credits_per_unit]

        ui = [
            {
                "id": m.id,
                "label": m.label,
                "family": m.family,
                "modality": m.modality,
                "credits_per_unit": m.credits_per_unit,
                "min_duration_s": m.min_duration_s,
                "max_duration_s": m.max_duration_s,
                "resolutions": list(m.resolutions),
                "aspects": list(m.aspects),
                "supports_i2v": m.supports_i2v,
                "supports_last_frame": m.supports_last_frame,
                "supports_char_ref": m.supports_char_ref,
                "supports_audio": m.supports_audio,
                "status": m.status,
                "sunset_at": m.sunset_at.isoformat() if m.sunset_at else None,
            }
            for m in models
        ]
        if not models:
            return (
                f"No {modality} model matches those constraints on this plan. Relax the "
                f"constraints or tell the user their plan does not cover it. Do not name "
                f"a model that did not appear in this list.",
                [],
            )
        return f"{len(models)} available:\n" + enumerate_for_prompt(models), ui

    @classmethod
    async def create(
        cls, ctx: ToolContext, snap: TaxonomySnapshot
    ) -> ListAvailableModelsTool | None:
        modalities = sorted({m.modality for m in snap.models})
        if not modalities:
            return None

        args = build_args(
            "ListAvailableModelsArgs",
            modality=described(
                literal_of(modalities), "Which kind of output you need."
            ),
            max_credits_per_unit=described(
                int | None,
                "Cap on credits per unit (per second for video and audio, per image for "
                "stills). Use it when the user asked to keep costs down.",
                None,
            ),
            requires=described(
                list[Literal["i2v", "last_frame", "char_ref", "audio"]] | None,
                "Capabilities the model must support: 'i2v' image-to-video, 'last_frame' "
                "first-and-last-frame interpolation, 'char_ref' character reference "
                "images, 'audio' native audio.",
                None,
            ),
        )

        counts = ", ".join(
            f"{len(snap.models_for(mod))} {mod}" for mod in modalities  # type: ignore[arg-type]
        )
        tool = cls(
            args_schema=args,
            description=(
                f"List the generation models available to this user right now, with their "
                f"capabilities, duration limits and credit cost. Currently {counts}.\n"
                f"\n"
                f"USE THIS before generating when the choice of model actually matters: "
                f"when the user cares about cost, when you need a specific capability "
                f"(character reference, first-and-last-frame, native audio), or when a "
                f"model you were about to use is marked deprecated or retiring.\n"
                f"\n"
                f"DO NOT use it for routine generation — the generate_* tools already "
                f"restrict you to valid models. DO NOT name a model that this tool did "
                f"not return: models are switched off by their providers regularly, and "
                f"anything you remember from training may no longer exist."
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# estimate_cost                                                                #
# --------------------------------------------------------------------------- #


class CostItem(BaseModel):
    """Una línea del presupuesto. Deliberadamente igual de expresiva que una petición
    de generación, para que estimar y ejecutar no puedan divergir."""

    model_id: str = Field(..., description="Exact model id, as returned by list_available_models.")
    count: int = Field(1, ge=1, le=200, description="How many outputs of this kind.")
    duration_s: float | None = Field(
        None, description="Seconds per output. Required for video and audio models."
    )


class EstimateCostArgs(BaseModel):
    items: list[CostItem] = Field(
        ..., description="The generations you are about to run, one entry per model."
    )


class EstimateCostTool(SnapshotTool):
    """Coste en créditos **antes** de gastar."""

    name: str = "estimate_cost"
    args_schema: type[BaseModel] = EstimateCostArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Compute the credit cost of a generation plan before running it, and compare it "
        "against the credits actually available.\n"
        "\n"
        "USE THIS whenever the plan involves more than two generations, whenever the "
        "user asks 'how much', and always before generate_shot_batch — a fan-out over a "
        "shot list is the single easiest way to burn a user's balance by accident.\n"
        "\n"
        "DO NOT treat the result as a quote to hide from the user: if the estimate is "
        "close to or above their balance, say so and wait. DO NOT guess costs yourself; "
        "credit prices vary by a factor of 30 between models."
    )

    async def _arun_impl(self, items: list[Any], **_: Any) -> tuple[str, Any]:
        parsed = [CostItem.model_validate(i) if not isinstance(i, CostItem) else i for i in items]
        total = 0
        lines: list[str] = []
        breakdown: list[dict[str, Any]] = []

        for item in parsed:
            model = self.require_model_any(item.model_id)
            units = self._units(model, item)
            credits = int(units * model.credits_per_unit * item.count)
            total += credits
            lines.append(
                f"  {item.count}x {model.id}"
                + (f" @ {item.duration_s:g}s" if item.duration_s else "")
                + f" = {credits} credits"
            )
            breakdown.append(
                {
                    "model_id": model.id,
                    "label": model.label,
                    "count": item.count,
                    "duration_s": item.duration_s,
                    "credits": credits,
                }
            )

        available = self.ctx.credits_available
        verdict = (
            "affordable"
            if total <= available
            else f"NOT affordable — short by {total - available} credits"
        )
        content = (
            "Estimated cost:\n"
            + "\n".join(lines)
            + f"\n  TOTAL {total} credits (available: {available}) — {verdict}"
        )
        return content, {"total_credits": total, "available": available, "items": breakdown}

    # -- interno ------------------------------------------------------------ #

    def require_model_any(self, model_id: str) -> GenModel:
        """Como `require_model`, pero sin fijar modalidad: aquí el modelo la aporta."""
        model = self.snap.model(model_id)
        if model is None:
            raise UnknownEntityError("model", model_id, [m.id for m in self.snap.models])
        return model

    @staticmethod
    def _units(model: GenModel, item: CostItem) -> Decimal:
        """
        Unidades facturables. La unidad es el segundo salvo en imagen, donde es la
        imagen. Redondeamos hacia arriba porque los proveedores facturan por segundo
        empezado y absorber esa diferencia en silencio es perder dinero por defecto.
        """
        if model.modality == "image":
            return Decimal(1)
        if item.duration_s is None:
            raise XframeToolRetryableError(
                f"Model '{model.id}' bills per second, so duration_s is required to "
                f"estimate its cost. Provide the intended duration for each item."
            )
        seconds = Decimal(str(item.duration_s))
        return seconds.to_integral_value(rounding="ROUND_CEILING")
