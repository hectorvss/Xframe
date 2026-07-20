"""
Herramientas meta: cambiar de modo, cerrar el plan, consultar jobs.

`switch_mode` es la que justifica este módulo. Su descripción y su `Literal[*modes]` se
generan **construyendo las tools reales de cada modo**, no leyendo una tabla escrita a
mano. Es el mismo principio que el resto del sistema llevado a su conclusión: si el
catálogo de modelos no puede mentir, el catálogo de modos tampoco.

La alternativa —una constante con "en producción tienes generate_video"— se desincroniza
el día que alguien cambia `modes` en una clase, y el síntoma es de los peores: el agente
cambia de modo esperando una herramienta que no aparece, y se queda sin plan.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app import db
from app.taxonomy.builder import SnapshotTool, build_args, described, literal_of, modes_with_tools
from app.taxonomy.repo import TaxonomySnapshot
from app.tools.base import ToolContext
from app.tools.errors import XframeToolRetryableError


# --------------------------------------------------------------------------- #
# switch_mode                                                                  #
# --------------------------------------------------------------------------- #


class SwitchModeTool(SnapshotTool):
    """Cambio de modo. El toolset se reconstruye entero después."""

    name: str = "switch_mode"
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")
    is_meta: ClassVar[bool] = True
    """Marca para el builder: se omite al sondear los otros modos, o la construcción
    de esta tool se llamaría a sí misma indefinidamente."""

    async def _arun_impl(self, mode: str, reason: str, **_: Any) -> tuple[str, Any]:
        if mode == self.ctx.mode:
            raise XframeToolRetryableError(
                f"Already in '{mode}' mode. If a tool you expected is missing, it does not "
                f"exist in this mode — switching to the mode you are already in will not "
                f"make it appear."
            )
        await db.execute(
            """
            update public.conversations set mode = $2, updated_at = now()
             where id = $1::uuid
            """,
            self.ctx.conversation_id,
            mode,
        )
        return (
            f"Mode switched to '{mode}': {reason}. Your available tools have changed — "
            f"work from the tools you can see now, not the ones you remember.",
            {"mode": mode, "previous": self.ctx.mode, "reason": reason},
        )

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> "SwitchModeTool | None":
        catalogue = await modes_with_tools(ctx, snap)
        others = [m for m in catalogue if m != ctx.mode]
        if not others:
            return None

        blurbs = {
            "preproduction": "planning only — brief, shot list, elements. No generation "
            "tools exist here, so nothing can spend credits.",
            "production": "rendering — the generation tools exist here and cost real money.",
            "edit": "post — upscaling, lipsync and assembling what is already rendered.",
        }
        lines = [
            f"- {mode}: {blurbs.get(mode, '')}\n    tools: {', '.join(catalogue[mode]) or 'none'}"
            for mode in others
        ]
        tool = cls(
            args_schema=build_args(
                "SwitchModeArgs",
                mode=described(literal_of(others), "The mode to switch to."),
                reason=described(
                    str,
                    "Why the switch is needed, in one sentence. The user sees this, so it "
                    "must name the actual next step, not restate the mode.",
                ),
            ),
            description=(
                f"Switch the agent to another working mode. Each mode has a different set "
                f"of tools, and the tools of the other modes genuinely do not exist while "
                f"you are not in them.\n"
                f"\n"
                f"USE THIS when the work has moved on: from planning to rendering once the "
                f"user approved the shot list, or from rendering to post once the shots "
                f"are done.\n"
                f"\n"
                f"DO NOT switch to production to 'check' something — switching is visible "
                f"to the user and implies the plan is settled. DO NOT switch as a way to "
                f"reach a tool the user did not ask you to use; if generating was not "
                f"requested, staying in preproduction is the correct behaviour, not a "
                f"limitation to work around.\n"
                f"\n"
                f"You are currently in '{ctx.mode}'. Available modes:\n" + "\n".join(lines)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# finalize_plan                                                                #
# --------------------------------------------------------------------------- #


class FinalizePlanArgs(BaseModel):
    summary: str = Field(
        ...,
        description=(
            "What will be produced, in the user's terms: how many shots, roughly how "
            "long, which look. Two or three sentences."
        ),
    )
    estimated_credits: int = Field(
        ...,
        ge=0,
        description=(
            "Total credits the plan will cost, taken from estimate_cost. Do not invent "
            "this number — run estimate_cost and copy its total."
        ),
    )


class FinalizePlanTool(SnapshotTool):
    """Cierra la preproducción y pide aprobación."""

    name: str = "finalize_plan"
    args_schema: type[BaseModel] = FinalizePlanArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction",)
    is_meta: ClassVar[bool] = False

    description: str = (
        "Close preproduction: record the plan and its cost as a versioned artifact and "
        "hand it to the user for approval.\n"
        "\n"
        "USE THIS when the brief and the shot list are complete and you have a cost "
        "estimate. It is the checkpoint between free planning and paid rendering, and "
        "it is where the user gets to say no before any money is spent.\n"
        "\n"
        "DO NOT call it with a plan the user has not seen, and DO NOT treat calling it as "
        "approval — approval is the user's answer, not your tool call. DO NOT skip it and "
        "switch straight to production."
    )

    async def _arun_impl(
        self, summary: str, estimated_credits: int, **_: Any
    ) -> tuple[str, Any]:
        shots = await db.fetch(
            """
            select id, position, title, spec from public.canvas_nodes
             where project_id = $1::uuid and type = 'shot' order by position nulls last
            """,
            self.ctx.project_id,
        )
        if not shots:
            raise XframeToolRetryableError(
                "There are no shots in this project, so there is no plan to finalize. "
                "Build the shot list with create_shot first."
            )

        from app.artifacts.manager import ArtifactManager
        from app.artifacts.types import PlanArtifactContent, ShotRefBlock, TextBlock

        content = PlanArtifactContent(
            title="Plan de producción",
            estimated_credits=estimated_credits,
            blocks=[
                TextBlock(text=summary),
                *[ShotRefBlock(shot_id=str(s["id"])) for s in shots],
            ],
        )
        artifact = await ArtifactManager(self.ctx.project_id).acreate(content, name="Plan")

        return (
            f"Plan finalized: {len(shots)} shots, ~{estimated_credits} credits "
            f"(available: {self.ctx.credits_available}). Artifact {artifact['id']} v"
            f"{artifact['version']}. Now wait for the user to approve before switching to "
            f"production.",
            {
                "artifact_id": str(artifact["id"]),
                "version": artifact["version"],
                "shots": len(shots),
                "estimated_credits": estimated_credits,
                "requires_approval": True,
            },
        )


# --------------------------------------------------------------------------- #
# check_job_status                                                             #
# --------------------------------------------------------------------------- #


class CheckJobStatusArgs(BaseModel):
    job_ids: list[str] | None = Field(
        None,
        description=(
            "Specific job ids to check. Omit to get every job of this project that is "
            "still running."
        ),
    )


class CheckJobStatusTool(SnapshotTool):
    """Estado de las generaciones en curso."""

    name: str = "check_job_status"
    args_schema: type[BaseModel] = CheckJobStatusArgs
    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")

    description: str = (
        "Check the status of generation jobs: queued, running, succeeded, failed or "
        "rejected by content moderation, with the credits actually charged.\n"
        "\n"
        "USE THIS when the user asks whether something is ready, and before "
        "assemble_video — assembling while shots are still rendering produces a cut with "
        "holes.\n"
        "\n"
        "DO NOT poll it in a loop within one turn: renders take minutes and the user gets "
        "progress by streaming anyway. DO NOT describe the content of a job that has not "
        "succeeded; you have not seen it."
    )

    async def _arun_impl(self, job_ids: list[str] | None = None, **_: Any) -> tuple[str, Any]:
        if job_ids:
            rows = await db.fetch(
                """
                select id, model_id, status, progress, shot_id, credits_charged, error
                  from public.generation_jobs
                 where project_id = $1::uuid and id = any($2::uuid[])
                 order by created_at
                """,
                self.ctx.project_id,
                job_ids,
            )
        else:
            rows = await db.fetch(
                """
                select id, model_id, status, progress, shot_id, credits_charged, error
                  from public.generation_jobs
                 where project_id = $1::uuid
                   and status in ('queued','submitted','running')
                 order by created_at
                """,
                self.ctx.project_id,
            )

        if not rows:
            return "No matching jobs. Nothing is rendering right now.", []

        lines: list[str] = []
        for r in rows:
            progress = f" {float(r['progress']) * 100:.0f}%" if r["progress"] is not None else ""
            err = f" — {(r['error'] or {}).get('message', '')}" if r["error"] else ""
            lines.append(
                f"  {r['id']} {r['model_id']} [{r['status']}{progress}] "
                f"shot={r['shot_id'] or '-'} charged={r['credits_charged']}{err}"
            )
        ui = [dict(r) | {"id": str(r["id"])} for r in rows]
        return f"{len(rows)} job(s):\n" + "\n".join(lines), ui
