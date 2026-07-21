"""
Herramientas de generación. Las caras.

Dos cosas las separan del resto y ambas son estructurales, no de prompt:

1. `modes` **excluye** `preproduction`. En ese modo estas clases no se instancian, así
   que no aparecen en el JSON Schema que ve el modelo. No es que se le pida no generar
   mientras planifica: es que no puede. Un ruego al prompt falla un pequeño porcentaje
   de las veces, y aquí cada fallo tiene precio en créditos.
2. `consumes_credits = True`. El ejecutor las cuenta contra `MAX_GENERATIONS_PER_TURN`,
   que es el tercer límite del sistema: los otros dos (tool calls y recursion limit)
   acotan un bucle de razonamiento, pero un bucle de razonamiento sale barato y un
   bucle de renders no.

Todas encolan y vuelven: ningún proveedor tier-1 es síncrono. El valor de retorno es un
job id, y el agente consulta con `check_job_status` o recibe el evento por streaming.
Bloquear el turno esperando a un render de 90 segundos convierte el chat en un spinner.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from app import db
from app.providers.base import ElementRef, GenerationAdapter, GenerationRequest
from app.taxonomy.builder import (
    SnapshotTool,
    build_args,
    described,
    enumerate_for_prompt,
    literal_of,
)
from app.taxonomy.repo import GenModel, TaxonomySnapshot
from app.tools.base import ToolContext
from app.tools.errors import InsufficientCreditsError, UnknownEntityError, XframeToolRetryableError

if TYPE_CHECKING:  # pragma: no cover - solo para tipos
    from app.assembly.ffmpeg import AssemblyResult
    from app.jobs.queue import EnqueueResult

GENERATION_MODES: tuple[str, ...] = ("production", "edit")
"""
Los modos en los que generar tiene sentido. `preproduction` está fuera y esa ausencia
es toda la aplicación de la regla — no hay ningún otro sitio donde se compruebe.
"""


class _GenerationTool(SnapshotTool):
    """Base con lo común: comprobación de saldo, coste y encolado."""

    __abstract__ = True

    consumes_credits: bool = True
    modes: ClassVar[tuple[str, ...]] = GENERATION_MODES

    # -- coste y saldo ------------------------------------------------------ #

    async def quote(self, req: GenerationRequest) -> tuple[GenerationAdapter, int]:
        """
        Cotiza una petición **por el mismo camino exacto que la reserva**.

        Antes había aquí un `credits_for()` propio que multiplicaba
        `credits_per_unit` de la taxonomía por los segundos pedidos. La reserva, en
        cambio, la calcula `queue.enqueue` como `usd_to_credits(adapter.estimate_cost(...))`.
        Los dos números divergían hasta 4x, y siempre en el mismo sentido: el agente
        anunciaba el barato y el monedero pagaba el caro. Un precio anunciado que no es
        el precio cobrado no es una imprecisión, es una factura equivocada.

        La única forma de que no vuelvan a separarse es que no haya dos fórmulas. Por eso
        esto resuelve el adaptador y el `ModelSpec` reales y llama a `estimate_cost`,
        aunque cueste una resolución de catálogo más: el adaptador es quien conoce las
        rarezas de facturación de su proveedor (Minimax cobra por clip, no por segundo),
        y la taxonomía no.

        Devuelve también el adaptador porque `queue.enqueue` lo exige como keyword-only
        sin defecto, y resolverlo dos veces sería pedirle al catálogo lo mismo dos veces.
        """
        from app.jobs.credits import usd_to_credits
        from app.providers.registry import get_registry

        adapter, spec = await get_registry().resolve(req.model_id)
        return adapter, usd_to_credits(adapter.estimate_cost(req, spec))

    def assert_affordable(self, credits: int) -> None:
        if credits > self.ctx.credits_available:
            raise InsufficientCreditsError(credits, self.ctx.credits_available)

    # -- validación que el esquema no puede expresar ------------------------ #

    def check_duration(self, model: GenModel, duration_s: float | None) -> float | None:
        """
        El `Literal` acota qué modelo, no cuántos segundos: el rango válido depende del
        modelo elegido y un JSON Schema no expresa esa dependencia. Se valida aquí, con
        un error que dice el rango, para que el modelo corrija en un turno.
        """
        if duration_s is None:
            return None
        lo = model.min_duration_s or 0.0
        hi = model.max_duration_s
        if hi is not None and (duration_s < lo or duration_s > hi):
            raise XframeToolRetryableError(
                f"Model '{model.id}' only supports durations between {lo:g}s and {hi:g}s, "
                f"but {duration_s:g}s was requested. Adjust the duration, or pick another "
                f"model with list_available_models."
            )
        return duration_s

    def check_aspect(self, model: GenModel, aspect: str | None) -> str | None:
        if aspect and model.aspects and aspect not in model.aspects:
            raise UnknownEntityError(f"aspect ratio for '{model.id}'", aspect, list(model.aspects))
        return aspect

    def motion_or_none(self, motion_id: str | None) -> str | None:
        if motion_id is None:
            return None
        if self.snap.motion(motion_id) is None:
            raise UnknownEntityError("camera motion", motion_id, self.snap.motion_ids())
        return motion_id

    def style_fragments(self, style_ids: Sequence[str] | None) -> dict[str, str]:
        """Ids de estilo → fragmentos de prompt, indexados por dimensión. El fragmento
        vive en la BD y no en el código porque afinar un estilo no debe ser un despliegue."""
        out: dict[str, str] = {}
        for style_id in style_ids or []:
            style = self.snap.style(style_id)
            if style is None:
                raise UnknownEntityError("visual style", style_id, self.snap.style_ids())
            out[style.dimension] = style.prompt_fragment
        return out

    # -- encolado ----------------------------------------------------------- #

    async def enqueue(
        self,
        req: GenerationRequest,
        *,
        adapter: GenerationAdapter,
        shot_id: str | None = None,
    ) -> EnqueueResult:
        """
        Delegación a la cola. Import perezoso: el módulo de jobs se carga cuando de
        verdad se va a generar, no al construir el toolset.

        Dos argumentos que antes no se pasaban y sin los cuales esto no funcionaba:

        - `adapter`: `queue.enqueue` lo exige keyword-only y sin defecto, porque de él
          salen el `provider_id` que entra en la clave de idempotencia y el coste que se
          reserva. Sin él la llamada era un `TypeError` en las cuatro tools de generación.
        - `conversation_id`: es lo que enlaza el job con la conversación que lo pidió. Sin
          él la columna queda a NULL, `worker._emit` sale por su return temprano y el
          usuario no ve aparecer ningún plano: el render ocurre, se cobra, y nadie se
          entera hasta que alguien recarga el proyecto.
        """
        from app.jobs.queue import enqueue as _enqueue
        from app.jobs.resume import mark_awaiting

        job = await _enqueue(
            req,
            project_id=self.ctx.project_id,
            shot_id=shot_id,
            adapter=adapter,
            conversation_id=self.ctx.conversation_id or None,
        )

        # Marca de espera: es la guarda que autoriza al worker a reanudar la conversación
        # cuando el último job aterrice, y por eso se pone **aquí**, en el único punto que
        # comparten las cuatro tools de generación. Puesta en cada tool por separado, la
        # que se olvidara de ponerla generaría planos de los que el agente no se enteraría
        # nunca, y el síntoma sería "a veces continúa solo y a veces no".
        #
        # No se marca un resultado ya cacheado: `is_cached` significa que el asset existe
        # desde antes y que no va a terminar ningún job, así que la marca se quedaría
        # puesta esperando un evento que no va a llegar.
        if self.ctx.conversation_id and not job.is_cached:
            await mark_awaiting(
                conversation_id=self.ctx.conversation_id,
                project_id=self.ctx.project_id,
            )
        return job


# --------------------------------------------------------------------------- #
# generate_image                                                               #
# --------------------------------------------------------------------------- #


class GenerateImageTool(_GenerationTool):
    """Imagen fija: fichas de personaje, referencias de localización, primeros frames."""

    name: str = "generate_image"

    async def _arun_impl(
        self,
        prompt: str,
        model_id: str,
        aspect: str | None = None,
        element_refs: list[str] | None = None,
        styles: list[str] | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        model = self.require_model(model_id, "image")
        refs = self.resolve_elements(element_refs)
        if refs and not model.supports_char_ref:
            raise XframeToolRetryableError(
                f"Model '{model.id}' does not support character reference images, but "
                f"{len(refs)} element(s) were passed. Either drop element_refs or choose a "
                f"model with the 'char_ref' capability (list_available_models requires=['char_ref'])."
            )
        # La petición se construye ANTES de cotizar: `estimate_cost` mira sus campos
        # (duración, resolución, si lleva audio), así que cotizar sobre otra cosa sería
        # cotizar otra generación.
        req = GenerationRequest(
            modality="image",
            model_id=model.id,
            prompt=prompt,
            negative_prompt=negative_prompt,
            aspect=self.check_aspect(model, aspect),
            seed=seed,
            elements=refs,
            style=self.style_fragments(styles),
        )
        adapter, credits = await self.quote(req)
        self.assert_affordable(credits)

        job = await self.enqueue(req, adapter=adapter)
        return (
            f"Image queued on {model.id} ({job.credits_reserved} credits reserved). "
            f"Job {job.job_id}. It is not ready yet — do not describe the result until "
            f"check_job_status says it succeeded.",
            {
                "job_id": job.job_id,
                "model_id": model.id,
                "credits": job.credits_reserved,
                "reused": job.reused,
                "kind": "image",
            },
        )

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> GenerateImageTool | None:
        models = snap.models_for("image")
        if not models:
            return None
        fields: dict[str, tuple[Any, Any]] = {
            "prompt": described(
                str,
                "What to render, in prose: subject, action, staging, light. Describe the "
                "image, not your intent.",
            ),
            "model_id": described(
                literal_of([m.id for m in models]),
                "Which image model to use. Only these exist for this user right now.",
            ),
            "aspect": described(
                str | None, "Aspect ratio, e.g. '16:9'. Must be one the model supports.", None
            ),
            "negative_prompt": described(str | None, "What to avoid in the image.", None),
            "seed": described(
                int | None,
                "Fixed seed for reproducibility. Reuse the same seed when iterating on a "
                "prompt so the change you see comes from the prompt, not from noise.",
                None,
            ),
        }
        if snap.styles:
            fields["styles"] = described(
                list[literal_of(snap.style_ids())] | None,  # type: ignore[valid-type]
                "Visual style ids to apply (palette, lighting, film stock, lens).",
                None,
            )
        if snap.elements:
            fields["element_refs"] = described(
                list[literal_of(snap.element_names())] | None,  # type: ignore[valid-type]
                "Names of project elements to use as visual references. Only works with "
                "models that support character reference.",
                None,
            )
        tool = cls(
            args_schema=build_args("GenerateImageArgs", **fields),
            description=(
                "Generate a still image and charge the user's credits for it.\n"
                "\n"
                "USE THIS for character sheets, location references, mood frames and the "
                "first frame of an image-to-video shot. Attach the result to an element "
                "with define_element when it is meant to anchor continuity.\n"
                "\n"
                "DO NOT call it speculatively or in a loop of small variations — every "
                "call costs real money. DO NOT use it for anything that moves; that is "
                "generate_video. DO NOT name a model that is not in the enum below.\n"
                "\n"
                "Image models available:\n" + enumerate_for_prompt(models)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# generate_video                                                               #
# --------------------------------------------------------------------------- #


class GenerateVideoTool(_GenerationTool):
    """Un plano de vídeo: t2v, i2v o first-last-frame."""

    name: str = "generate_video"

    async def _arun_impl(
        self,
        prompt: str,
        model_id: str,
        duration_s: float | None = None,
        shot_id: str | None = None,
        aspect: str | None = None,
        resolution: str | None = None,
        camera_motion: str | None = None,
        camera_motion_strength: float | None = None,
        init_image_url: str | None = None,
        last_frame_url: str | None = None,
        element_refs: list[str] | None = None,
        styles: list[str] | None = None,
        negative_prompt: str | None = None,
        audio: bool = False,
        seed: int | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        model = self.require_model(model_id, "video")
        duration = self.check_duration(model, duration_s or model.min_duration_s)

        if init_image_url and not model.supports_i2v:
            raise XframeToolRetryableError(
                f"Model '{model.id}' cannot start from an image. Use a model with the "
                f"'i2v' capability or drop init_image_url."
            )
        if last_frame_url and not model.supports_last_frame:
            raise XframeToolRetryableError(
                f"Model '{model.id}' does not support a target last frame. Use a model "
                f"with the 'last_frame' capability or drop last_frame_url."
            )
        if audio and not model.supports_audio:
            raise XframeToolRetryableError(
                f"Model '{model.id}' has no native audio. Generate the video without "
                f"audio and add it separately, or pick a model with the 'audio' capability."
            )

        refs = self.resolve_elements(element_refs)
        req = GenerationRequest(
            modality="video",
            model_id=model.id,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration_s=duration,
            aspect=self.check_aspect(model, aspect),
            resolution=resolution,
            seed=seed,
            init_image_url=init_image_url,
            last_frame_url=last_frame_url,
            elements=refs,
            camera_motion=self.motion_or_none(camera_motion),
            camera_motion_strength=camera_motion_strength,
            style=self.style_fragments(styles),
            audio=audio,
        )
        adapter, credits = await self.quote(req)
        self.assert_affordable(credits)

        job = await self.enqueue(req, adapter=adapter, shot_id=shot_id)
        return (
            f"Video queued on {model.id}, {duration:g}s ({job.credits_reserved} credits "
            f"reserved). Job {job.job_id}. Rendering takes minutes — do not wait for it "
            f"in this turn and do not claim it is done.",
            {
                "job_id": job.job_id,
                "model_id": model.id,
                "credits": job.credits_reserved,
                "reused": job.reused,
                "duration_s": duration,
                "shot_id": shot_id,
                "kind": "video",
            },
        )

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> GenerateVideoTool | None:
        models = snap.models_for("video")
        if not models:
            return None

        fields: dict[str, tuple[Any, Any]] = {
            "prompt": described(
                str,
                "The shot, in prose: subject, action, staging, light. Describe what the "
                "camera sees over the duration, not the story around it.",
            ),
            "model_id": described(
                literal_of([m.id for m in models]),
                "Which video model to use. This enum is the complete list available to "
                "this user right now; models are retired by their providers regularly.",
            ),
            "duration_s": described(
                float | None,
                "Duration in seconds. Must fall inside the range of the chosen model.",
                None,
            ),
            "shot_id": described(
                str | None,
                "Id of the shot this render belongs to, so the result lands on the "
                "timeline instead of floating loose in the asset list.",
                None,
            ),
            "aspect": described(str | None, "Aspect ratio the model supports, e.g. '16:9'.", None),
            "resolution": described(
                str | None, "Resolution the model supports, e.g. '1080p'.", None
            ),
            "init_image_url": described(
                str | None,
                "First frame, for image-to-video. Use the URL of an image asset already "
                "generated in this project.",
                None,
            ),
            "last_frame_url": described(
                str | None,
                "Target last frame, for first-and-last-frame interpolation.",
                None,
            ),
            "negative_prompt": described(str | None, "What to avoid.", None),
            "audio": described(
                bool, "Ask the model for native audio. Only some models have it.", False
            ),
            "seed": described(int | None, "Fixed seed for reproducible iteration.", None),
        }
        if snap.motions:
            fields["camera_motion"] = described(
                literal_of(snap.motion_ids()) | None,
                "Camera movement from the project catalogue. Choose it for narrative "
                "reasons; an unmotivated move reads as noise.",
                None,
            )
            fields["camera_motion_strength"] = described(
                float | None, "Intensity of the movement, 0-1. Defaults to the preset value.", None
            )
        if snap.styles:
            fields["styles"] = described(
                list[literal_of(snap.style_ids())] | None,  # type: ignore[valid-type]
                "Visual style ids to apply on top of the prompt.",
                None,
            )
        if snap.elements:
            fields["element_refs"] = described(
                list[literal_of(snap.element_names())] | None,  # type: ignore[valid-type]
                "Names of the elements appearing in this shot, for visual continuity.",
                None,
            )

        motions_note = (
            "\n\nCamera motions available:\n" + enumerate_for_prompt(snap.motions, limit=40)
            if snap.motions
            else ""
        )
        tool = cls(
            args_schema=build_args("GenerateVideoArgs", **fields),
            description=(
                "Generate one video shot — text-to-video, image-to-video, or "
                "first-and-last-frame — and charge the user's credits for it.\n"
                "\n"
                "USE THIS to render a single shot, typically one whose spec you already "
                "wrote with create_shot. Pass shot_id so the result attaches to the "
                "timeline. For a whole sequence use generate_shot_batch instead: it runs "
                "the shots in parallel and reports partial failures per shot.\n"
                "\n"
                "DO NOT call it to 'see what happens' — video is the most expensive thing "
                "in this system, by a wide margin. DO NOT invent a model id, a camera "
                "motion or an element name: only the values in these enums exist. DO NOT "
                "report the shot as finished when this returns; it returns a queued job.\n"
                "\n"
                "Video models available:\n" + enumerate_for_prompt(models) + motions_note
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# generate_shot_batch — fan-out                                                #
# --------------------------------------------------------------------------- #


class GenerateShotBatchTool(_GenerationTool):
    """
    Fan-out sobre la shot list.

    Es la tool con más apalancamiento y la más peligrosa del sistema: una llamada puede
    lanzar veinte renders.

    **Sobre la atomicidad del presupuesto, dicha con precisión.** Se comprueba el total
    antes de encolar nada, pero esa comprobación **no es la reserva**: la reserva la hace
    `queue.enqueue` job a job, cada una en su propia transacción y bajo el cerrojo del
    perfil. Son N+1 transacciones separadas, no una. La consecuencia real, y hay que
    saberla porque afecta al dinero del usuario: si el saldo cambia entre la comprobación
    y el último encolado (otra pestaña generando, un reembolso que no llegó, un lote
    concurrente), los primeros planos se reservan y los últimos fallan por saldo.

    Lo que se garantiza es que ese fallo sea limpio, y eso sí está construido aquí:

    - El chequeo previo descarta el caso normal —pedir un lote que nunca cupo— antes de
      gastar un solo crédito.
    - El fallo por saldo de un plano concreto lo captura `fanout._run_one` y se convierte
      en un `JobResult(ok=False)`, no en una excepción que cancele a sus hermanos.
    - Se informa de los créditos **realmente reservados**, sumados de cada `EnqueueResult`,
      y no del total cotizado. Anunciar el total cotizado cuando la mitad falló es
      exactamente la clase de mentira contable que este backend no debe cometer.

    Una reserva verdaderamente atómica del lote exige una transacción única que abarque
    las N reservas, y eso es un cambio en `queue.enqueue` (aceptar varias peticiones y
    una sola conexión), no en esta tool. Queda pendiente y documentado, no disimulado.
    """

    name: str = "generate_shot_batch"

    async def _arun_impl(
        self,
        shot_ids: list[str],
        model_id: str,
        manifest_id: str,
        duration_s: float | None = None,
        seed: int | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        model = self.require_model(model_id, "video")

        manifest = await db.fetchrow(
            """select id,status,specification,fingerprint from public.production_manifests
                where id=$1::uuid and project_id=$2::uuid""",
            manifest_id,
            self.ctx.project_id,
        )
        if not manifest or manifest["status"] not in {"approved", "executing"}:
            raise XframeToolRetryableError(
                "A multi-shot batch requires an approved production manifest. Build it, "
                "resolve every validation error, show it to the user and approve it first."
            )
        manifest_shots = [
            str(item.get("id"))
            for item in dict(manifest["specification"] or {}).get("shots", [])
        ]
        expected = (
            manifest_shots
            if manifest["status"] == "approved"
            else [shot_id for shot_id in manifest_shots if shot_id in set(shot_ids)]
        )
        if not shot_ids or shot_ids != expected:
            raise XframeToolRetryableError(
                "For an approved manifest, shot_ids must exactly match its canonical order. "
                "For an executing manifest, retries may contain only the failed/rejected "
                "subset, still in canonical order."
            )
        if manifest["status"] == "executing":
            latest_attempts = await db.fetch(
                """select distinct on (j.shot_id)
                          j.shot_id,j.status,j.asset_id,
                          exists(
                            select 1 from public.quality_reports q
                             where q.project_id=j.project_id and q.asset_id=j.asset_id
                               and q.passed is false
                               and not exists (
                                 select 1 from public.quality_reports newer
                                  where newer.asset_id=q.asset_id
                                    and newer.check_type=q.check_type
                                    and newer.created_at > q.created_at
                               )
                          ) as has_current_rejection
                     from public.generation_jobs j
                    where j.project_id=$1::uuid and j.shot_id=any($2::text[])
                      and j.request #>> '{extra,manifest_id}' = $3
                    order by j.shot_id,j.created_at desc""",
                self.ctx.project_id,
                shot_ids,
                manifest_id,
            )
            blocked: list[dict[str, Any]] = []
            for attempt in latest_attempts:
                status = str(attempt["status"])
                rejected = bool(attempt.get("has_current_rejection"))
                if status not in {"failed", "cancelled", "nsfw"} and not rejected:
                    blocked.append(
                        {
                            "shot_id": str(attempt["shot_id"]),
                            "job_status": status,
                            "asset_id": str(attempt["asset_id"]) if attempt["asset_id"] else None,
                        }
                    )
            if blocked:
                raise XframeToolRetryableError(
                    "Retry refused: these shots are active, succeeded without a current QA "
                    f"rejection, or awaiting review: {blocked}. Retry only failed jobs or "
                    "outputs whose latest quality report explicitly failed."
                )

        rows = await db.fetch(
            """
            select id, position, title, text, spec from public.canvas_nodes
             where project_id = $1::uuid and type = 'shot' and id = any($2::uuid[])
             order by position nulls last
            """,
            self.ctx.project_id,
            shot_ids,
        )
        found = {str(r["id"]) for r in rows}
        missing = [s for s in shot_ids if s not in found]
        if missing:
            valid = await db.fetch(
                """
                select id, position, title from public.canvas_nodes
                 where project_id = $1::uuid and type = 'shot' order by position nulls last
                """,
                self.ctx.project_id,
            )
            raise UnknownEntityError(
                "shot",
                missing[0],
                [f"{r['id']} (#{r['position']} {r['title']})" for r in valid],
            )

        row_by_id = {str(row["id"]): row for row in rows}
        rows = [row_by_id[shot_id] for shot_id in shot_ids]

        from app.agent.state import JobResult
        from app.jobs.fanout import ShotSpec, run_fanout

        # Una petición por plano, construida antes de cotizar nada: es la petición
        # concreta la que tiene precio, no el modelo.
        requests: dict[str, GenerationRequest] = {}
        for row in rows:
            spec = dict(row["spec"] or {})
            element_names = [
                str(item.get("name")) if isinstance(item, dict) else str(item)
                for item in (spec.get("elements") or [])
                if (item.get("name") if isinstance(item, dict) else item)
            ]
            duration = self.check_duration(
                model, duration_s or spec.get("duration_s") or model.min_duration_s
            )
            requests[str(row["id"])] = GenerationRequest(
                modality="video",
                model_id=model.id,
                prompt=(row["text"] or row["title"] or "").strip(),
                duration_s=duration,
                aspect=self.check_aspect(model, spec.get("aspect")),
                resolution=spec.get("resolution"),
                seed=seed,
                elements=self.resolve_elements(element_names),
                camera_motion=self.motion_or_none(spec.get("camera_motion")),
                camera_motion_strength=spec.get("camera_motion_strength"),
                style=self.style_fragments(spec.get("styles")),
                extra={
                    "manifest_id": manifest_id,
                    "manifest_fingerprint": manifest["fingerprint"],
                },
            )

        # El adaptador es el mismo para todo el lote (un solo modelo), así que se resuelve
        # una vez; el precio no, porque las duraciones difieren plano a plano.
        adapter: GenerationAdapter | None = None
        quoted = 0
        for req in requests.values():
            adapter, price = await self.quote(req)
            quoted += price
        self.assert_affordable(quoted)

        async def _run_shot(shot: ShotSpec) -> JobResult:
            """
            Lo que `fanout` ejecuta por plano: encolar de verdad.

            `fanout.py` nunca había estado conectado a la cola — su `ShotRunner` no tenía
            ninguna implementación real. Esta es. Puede lanzar sin miedo: `_run_one` lo
            captura y lo devuelve como `JobResult(ok=False)`, que es justamente la regla
            que impide que un plano roto cancele a sus hermanos ya pagados.
            """
            job = await self.enqueue(
                shot.payload,
                adapter=adapter,
                shot_id=shot.shot_id,  # type: ignore[arg-type]
            )
            return JobResult(
                job_id=job.job_id,
                shot_id=shot.shot_id,
                ok=True,
                asset=job.asset,
                credits_charged=job.credits_reserved,
            )

        report = await run_fanout(
            [ShotSpec(shot_id=sid, payload=req) for sid, req in requests.items()],
            _run_shot,
            # Cero umbral: aquí "éxito" significa *encolado*, no renderizado. Abortar el
            # lote no desharía las reservas ya hechas ni pararía a los proveedores, así
            # que el aborto sería una mentira cara. El agente informa plano a plano.
            failed_shots_min_ratio=0.0,
            # Nada que limpiar: en este punto no existe ningún asset todavía. Borrar
            # aquí solo podría llevarse por delante assets de un lote anterior.
            cleanup_partials=False,
        )

        ok = report.succeeded
        failed = report.failed
        reserved = sum(r.credits_charged for r in ok)
        lines = [
            f"Batch of {len(report.results)} shots on {model.id}: {len(ok)} queued, "
            f"{len(failed)} failed. Reserved {reserved} credits (quoted {quoted})."
        ]
        lines += [f"  FAILED shot {r.shot_id}: {r.error}" for r in failed]
        if failed:
            lines.append(
                "Report the failures to the user shot by shot. Do not silently retry the "
                "whole batch: the successful shots would be charged twice."
            )
        if ok:
            await db.execute(
                "update public.production_manifests set status='executing' where id=$1::uuid",
                manifest_id,
            )
        return "\n".join(lines), {
            "results": [r.model_dump() for r in report.results],
            "credits_reserved": reserved,
            "credits_quoted": quoted,
            "model_id": model.id,
            "manifest_id": manifest_id,
        }

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> GenerateShotBatchTool | None:
        models = snap.models_for("video")
        if not models:
            return None
        tool = cls(
            args_schema=build_args(
                "GenerateShotBatchArgs",
                shot_ids=described(
                    list[str],
                    "Ids of the shots to render, as returned by read_project. Each shot's "
                    "own spec (framing, camera motion, elements, duration) is used to "
                    "build its prompt.",
                ),
                model_id=described(
                    literal_of([m.id for m in models]),
                    "Video model used for every shot in the batch. Using one model across "
                    "a sequence is itself a continuity decision.",
                ),
                manifest_id=described(
                    str,
                    "Approved production manifest whose shot snapshot exactly matches shot_ids.",
                ),
                duration_s=described(
                    float | None,
                    "Override the duration of every shot. Omit to use each shot's own "
                    "duration from its spec.",
                    None,
                ),
                seed=described(
                    int | None,
                    "Optional new seed for a directed variation after quality rejection. "
                    "Omit it to reopen a genuinely failed identical job idempotently.",
                    None,
                ),
            ),
            description=(
                "Render several shots in parallel, one job per shot, and report the "
                "outcome shot by shot. Partial failure is expected and reported; the "
                "batch does not abort because one shot failed.\n"
                "\n"
                "USE THIS to produce a sequence once the shot list is written and its "
                "production manifest is validated and explicitly approved. Always call "
                "estimate_cost first and tell the "
                "user the total: this single call can spend more credits than everything "
                "else in the conversation combined.\n"
                "\n"
                "DO NOT retry a failed batch wholesale. Once the manifest is executing, "
                "pass only the failed or rejected subset in canonical order; use a new "
                "seed only for an intentional variation. DO NOT pass shots whose spec is "
                "still empty; render "
                "what was planned, not what you improvised.\n"
                "\n"
                "Video models available:\n" + enumerate_for_prompt(models)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# generate_audio / generate_lipsync / assemble_video                           #
# --------------------------------------------------------------------------- #


class GenerateAudioTool(_GenerationTool):
    """Generate an audio asset from the approved screenplay or a music/SFX brief."""

    name: str = "generate_audio"

    async def _arun_impl(
        self,
        kind: str,
        model_id: str,
        script_line_ids: list[str] | None = None,
        voice_profile_id: str | None = None,
        prompt: str | None = None,
        duration_s: float | None = None,
        composition_plan: dict[str, Any] | None = None,
        prompt_influence: float = 0.5,
        loop: bool = False,
        placement_start_ms: int | None = None,
        placement_end_ms: int | None = None,
        scene_id: str | None = None,
        shot_id: str | None = None,
        placement_time_basis: str = "project",
        output_format: str | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        if not 0 <= prompt_influence <= 1:
            raise XframeToolRetryableError(
                "prompt_influence must be between 0 and 1."
            )
        model = self.require_model(model_id, "audio")
        duration_s = self.check_duration(model, duration_s)
        capabilities = set(model.capabilities)
        required = "sfx" if kind in {"sfx", "ambience"} else kind
        if capabilities and required not in capabilities:
            raise XframeToolRetryableError(
                f"Model '{model.id}' cannot generate {kind}. Its capabilities are: "
                f"{', '.join(model.capabilities)}. Choose a compatible audio model."
            )

        line_ids = list(dict.fromkeys(script_line_ids or []))
        lines: list[dict[str, Any]] = []
        if line_ids:
            rows = await db.fetch(
                """
                select l.id, l.scene_id, l.shot_id, l.text, l.target_duration_ms,
                       l.emotion, l.direction, l.voice_profile_id,
                       vp.provider_voice_id, vp.settings
                  from public.script_lines l
             left join public.voice_profiles vp on vp.id=coalesce(l.voice_profile_id,$3::uuid)
                 where l.project_id=$1::uuid and l.id=any($2::uuid[])
                 order by l.scene_id, l.position
                """,
                self.ctx.project_id,
                line_ids,
                voice_profile_id,
            )
            found = {str(row["id"]) for row in rows}
            missing = [line_id for line_id in line_ids if line_id not in found]
            if missing:
                raise XframeToolRetryableError("Unknown screenplay line ids: " + ", ".join(missing))
            for row in rows:
                if not row["provider_voice_id"]:
                    raise XframeToolRetryableError(
                        f"Script line {row['id']} has no ready provider voice. Assign a "
                        "voice profile to its character before generating speech."
                    )
                lines.append(dict(row))

        if kind in {"voice", "dialogue"} and not lines:
            raise XframeToolRetryableError(
                "Speech must reference screenplay line ids so the generated words, speaker "
                "and later lipsync all share one source of truth. Create the screenplay first."
            )
        if kind in {"music", "sfx", "ambience"} and not (prompt or composition_plan):
            raise XframeToolRetryableError(
                f"{kind} generation needs a precise prompt or composition plan."
            )

        text = "\n".join(str(line["text"]) for line in lines) if lines else (prompt or "")
        inferred = sum((line["target_duration_ms"] or 0) for line in lines) / 1000
        if not duration_s:
            duration_s = inferred or max(1.0, len(text) / 14)
            duration_s = self.check_duration(model, duration_s)

        extra: dict[str, Any] = {
            "audio_kind": kind,
            "script_line_ids": line_ids,
            "composition_plan": composition_plan,
            "prompt_influence": prompt_influence,
            "loop": loop,
            "output_format": output_format or "mp3_44100_128",
            "provider_model_id": {
                "eleven-v3-voice": "eleven_v3",
                "eleven-v3-dialogue": "eleven_v3",
                "eleven-multilingual-v2": "eleven_multilingual_v2",
                "eleven-music-v2": "music_v2",
            }.get(model.id),
        }
        line_scene_ids = {str(line["scene_id"]) for line in lines}
        if scene_id and any(value != str(scene_id) for value in line_scene_ids):
            raise XframeToolRetryableError(
                "Every referenced screenplay line must belong to the selected scene."
            )
        if not scene_id and len(line_scene_ids) == 1:
            scene_id = next(iter(line_scene_ids))

        if shot_id:
            shot = await db.fetchrow(
                """select n.id,ss.scene_id from public.canvas_nodes n
                left join public.scene_shots ss
                  on ss.project_id=n.project_id and ss.shot_id=n.id
                    where n.id=$1::uuid and n.project_id=$2::uuid and n.type='shot'""",
                shot_id,
                self.ctx.project_id,
            )
            if not shot:
                raise XframeToolRetryableError(f"Unknown production shot {shot_id}.")
            if not shot["scene_id"]:
                raise XframeToolRetryableError(
                    f"Shot {shot_id} must be assigned to a scene before audio can target it."
                )
            shot_scene_id = str(shot["scene_id"])
            if scene_id and str(scene_id) != shot_scene_id:
                raise XframeToolRetryableError(
                    f"Shot {shot_id} belongs to scene {shot_scene_id}, not {scene_id}."
                )
            if any(
                line.get("shot_id") and str(line["shot_id"]) != str(shot_id)
                for line in lines
            ):
                raise XframeToolRetryableError(
                    "A referenced screenplay line is bound to a different shot."
                )
            scene_id = scene_id or shot_scene_id

        if scene_id:
            scene = await db.fetchrow(
                """select id,timeline_start_ms from public.script_scenes
                    where id=$1::uuid and project_id=$2::uuid""",
                scene_id,
                self.ctx.project_id,
            )
            if not scene:
                raise XframeToolRetryableError(f"Unknown scene {scene_id} in this project.")
        else:
            scene = None
        if placement_start_ms is not None:
            if placement_start_ms < 0:
                raise XframeToolRetryableError("placement_start_ms cannot be negative.")
            relative_start = placement_start_ms
            inferred_end = relative_start + int((duration_s or 0) * 1000)
            relative_end = placement_end_ms or inferred_end
            if relative_end <= relative_start:
                raise XframeToolRetryableError(
                    "placement_end_ms must be greater than placement_start_ms."
                )
            if placement_time_basis not in {"project", "scene"}:
                raise XframeToolRetryableError("placement_time_basis must be project or scene.")
            if placement_time_basis == "scene" and not scene:
                raise XframeToolRetryableError(
                    "Scene-relative placement requires an explicit scene_id."
                )
            offset = int(scene["timeline_start_ms"] or 0) if placement_time_basis == "scene" else 0
            extra["placement"] = {
                "start_ms": relative_start + offset,
                "end_ms": relative_end + offset,
                "relative_start_ms": relative_start,
                "relative_end_ms": relative_end,
                "time_basis": placement_time_basis,
                "track_kind": "voiceover" if kind == "voice" else kind,
                "script_line_id": line_ids[0] if len(line_ids) == 1 else None,
                "scene_id": scene_id,
                "shot_id": shot_id,
            }
        if kind == "dialogue":
            extra["dialogue_inputs"] = [
                {"text": line["text"], "voice_id": line["provider_voice_id"]} for line in lines
            ]
        elif kind == "voice":
            # A single render cannot honestly use several speaker identities.
            voices = {str(line["provider_voice_id"]) for line in lines}
            if len(voices) != 1:
                raise XframeToolRetryableError(
                    "Single-speaker voice generation received multiple voices; use kind='dialogue'."
                )
            extra["voice_id"] = voices.pop()
            extra["voice_settings"] = lines[0].get("settings") or {}

        req = GenerationRequest(
            modality="audio",
            model_id=model.id,
            prompt=text,
            duration_s=duration_s,
            audio=True,
            extra=extra,
        )
        adapter, credits = await self.quote(req)
        self.assert_affordable(credits)
        job = await self.enqueue(req, adapter=adapter)
        return (
            f"{kind.capitalize()} queued on {model.id} ({job.credits_reserved} credits "
            f"reserved). Job {job.job_id}.",
            {
                "job_id": job.job_id,
                "model_id": model.id,
                "credits": job.credits_reserved,
                "kind": "audio",
                "audio_kind": kind,
                "script_line_ids": line_ids,
                "reused": job.reused,
            },
        )

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> GenerateAudioTool | None:
        models = snap.models_for("audio")
        if not models:
            return None
        tool = cls(
            args_schema=build_args(
                "GenerateAudioArgs",
                kind=described(
                    literal_of(["voice", "dialogue", "music", "sfx", "ambience"]),
                    "Audio role. Dialogue is multi-speaker; voice is one speaker.",
                ),
                model_id=described(literal_of([m.id for m in models]), "Compatible audio model."),
                script_line_ids=described(
                    list[str] | None,
                    "Exact screenplay line ids for voice/dialogue. Required for speech.",
                    None,
                ),
                voice_profile_id=described(
                    str | None, "Optional voice override for otherwise unassigned lines.", None
                ),
                prompt=described(
                    str | None,
                    "Music, SFX or ambience brief. Never substitutes screenplay dialogue.",
                    None,
                ),
                duration_s=described(float | None, "Target audio duration in seconds.", None),
                composition_plan=described(
                    dict[str, Any] | None,
                    "Optional section-level music plan with durations and styles.",
                    None,
                ),
                loop=described(bool, "Make SFX/ambience loopable when supported.", False),
                placement_start_ms=described(
                    int | None,
                    "Optional exact timeline start in milliseconds. When supplied, the "
                    "finished asset is automatically inserted into the audio plan.",
                    None,
                ),
                placement_end_ms=described(
                    int | None,
                    "Optional exact timeline end in milliseconds; defaults to start plus "
                    "the generated duration.",
                    None,
                ),
                prompt_influence=described(
                    float,
                    "How strongly SFX/ambience follows the prompt, from 0 to 1.",
                    0.5,
                ),
                scene_id=described(
                    str | None,
                    "Optional scene context and cue link. Required for scene-relative timing.",
                    None,
                ),
                shot_id=described(
                    str | None, "Optional production shot that this sound belongs to.", None
                ),
                placement_time_basis=described(
                    literal_of(["project", "scene"]),
                    "Interpret placement milliseconds against the whole project or scene start.",
                    "project",
                ),
                output_format=described(
                    str | None,
                    "Provider output format, for example mp3_44100_128 or pcm_44100.",
                    None,
                ),
            ),
            description=(
                "Generate reusable voice, multi-character dialogue, music, sound effects or "
                "ambience assets. USE THIS after screenplay wording and voice identities are "
                "defined, or after the music/SFX brief is explicit. DO NOT generate speech "
                "from free-form invented copy; pass screenplay line ids. Generated audio is "
                "an asset; when exact placement arguments are supplied, it is inserted "
                "into the audio timeline automatically.\n\nAudio models:\n"
                + enumerate_for_prompt(models)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


class ExecuteAssetOperationTool(_GenerationTool):
    """Execute a previously audited non-destructive asset operation."""

    name: str = "execute_asset_operation"

    async def _arun_impl(
        self,
        operation_id: str,
        model_id: str,
        duration_s: float | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        operation = await db.fetchrow(
            """select * from public.asset_operations
                where id=$1::uuid and project_id=$2::uuid""",
            operation_id,
            self.ctx.project_id,
        )
        if not operation:
            raise XframeToolRetryableError(
                f"Unknown asset operation {operation_id} in this project."
            )
        if operation["status"] not in {"planned", "failed"}:
            raise XframeToolRetryableError(
                f"Operation {operation_id} is already {operation['status']}; do not run it twice."
            )
        inputs = await db.fetch(
            """select a.* from public.asset_operation_inputs i
                join public.assets a on a.id=i.asset_id
               where i.operation_id=$1::uuid and i.project_id=$2::uuid
               order by i.position""",
            operation_id,
            self.ctx.project_id,
        )
        if not inputs or any(row["status"] != "ready" for row in inputs):
            raise XframeToolRetryableError("Every operation input must be a ready asset.")

        kind = str(operation["operation"])
        params = dict(operation["params"] or {})
        prompt = str(operation["prompt"] or "").strip()
        source = dict(inputs[0])
        source_kind = str(source.get("type") or "").lower()

        if kind == "upscale":
            raise XframeToolRetryableError(
                "No configured provider declares a real upscale capability. Keep this "
                "operation planned until an upscale model is installed; do not fake it."
            )
        if kind == "character":
            if "image" not in source_kind and "imagen" not in source_kind:
                raise XframeToolRetryableError("A reusable character needs an image source.")
            row = await db.fetchrow(
                """update public.assets set role='Personaje', meta=$3
                    where id=$1::uuid and project_id=$2::uuid returning id,name,role,meta""",
                source["id"], self.ctx.project_id, prompt,
            )
            await db.execute(
                """update public.asset_operations set status='succeeded',output_asset_id=$2,
                   completed_at=now() where id=$1::uuid""",
                operation_id, source["id"],
            )
            return (
                f"Character Element '{row['name']}' created from the approved source without a paid render.",
                {"operation_id": operation_id, "asset_id": str(source["id"]), "reused": True},
            )

        is_image = "image" in source_kind or "imagen" in source_kind
        modality = "image" if is_image else "video"
        model = self.require_model(model_id, modality)
        annotations = await db.fetch(
            """select kind,body,time_ms,geometry from public.asset_annotations
                where project_id=$1::uuid and id=any($2::uuid[]) order by created_at""",
            self.ctx.project_id,
            list(params.get("annotation_ids") or []),
        ) if params.get("annotation_ids") else []
        annotation_note = "\n".join(
            f"Annotation {row['kind']} at {row['time_ms']}ms: {row['body']} geometry={dict(row['geometry'] or {})}"
            for row in annotations
        )
        preserve = ", ".join(params.get("preserve") or [])
        full_prompt = prompt
        if preserve:
            full_prompt += f"\nPreserve exactly: {preserve}."
        if annotation_note:
            full_prompt += f"\nApply these exact annotations:\n{annotation_note}"

        mask_geometry = [
            dict(row["geometry"] or {})
            for row in annotations
            if dict(row["geometry"] or {}).get("type") in {"rect", "drawing"}
        ]
        if modality == "image" and kind == "edit" and not mask_geometry:
            raise XframeToolRetryableError(
                "Exact component editing requires at least one selected region or drawing "
                "annotation. Add it on the asset and include its annotation id in the plan; "
                "a point comment is context, not a pixel mask."
            )

        if modality == "image":
            refs = [
                ElementRef(
                    element_id=str(row["id"]),
                    name=str(row["name"]),
                    role="source",
                    image_url=str(row["url"]),
                )
                for row in inputs
                if row["url"]
            ]
            req = GenerationRequest(
                modality="image",
                model_id=model.id,
                prompt=full_prompt,
                aspect=params.get("aspect"),
                seed=params.get("seed"),
                elements=refs,
                extra={"operation_id": operation_id, "operation": kind,
                       "mask_geometry": mask_geometry},
            )
        else:
            if not model.supports_i2v:
                raise XframeToolRetryableError(
                    f"Model '{model.id}' cannot derive video from an exact source frame."
                )
            if kind == "edit" and "video_edit" not in set(model.capabilities):
                raise XframeToolRetryableError(
                    f"Model '{model.id}' does not declare frame-preserving video_edit. "
                    "Use extend/remix/variation, or configure a video-edit provider."
                )
            from app.jobs.worker import SupabaseStorage
            from app.storage import sign_reference

            signed = str(await sign_reference(str(source["url"])))
            with tempfile.TemporaryDirectory(prefix="xframe-operation-") as tmp:
                frame_path = str(Path(tmp) / "boundary.png")
                await _extract_boundary_frame(signed, frame_path, last=kind == "extend")
                frame_ref = await SupabaseStorage().put(
                    project_id=self.ctx.project_id,
                    job_id=f"operation-{operation_id}",
                    filename="boundary.png",
                    data=Path(frame_path).read_bytes(),
                    content_type="image/png",
                )
            duration = self.check_duration(
                model,
                duration_s or params.get("duration_s") or (source.get("params") or {}).get("duration_s") or model.min_duration_s,
            )
            continuity = (
                "Continue seamlessly from this exact last frame. "
                if kind == "extend"
                else "Use this exact source boundary as the visual anchor. "
            )
            req = GenerationRequest(
                modality="video",
                model_id=model.id,
                prompt=continuity + full_prompt,
                duration_s=duration,
                aspect=params.get("aspect"),
                resolution=params.get("resolution"),
                seed=params.get("seed"),
                init_image_url=frame_ref,
                audio=bool(params.get("audio", False)),
                extra={"operation_id": operation_id, "operation": kind, "source_asset_id": str(source["id"])},
            )

        adapter, credits = await self.quote(req)
        self.assert_affordable(credits)
        job = await self.enqueue(req, adapter=adapter, shot_id=source.get("shot_id"))
        await db.execute(
            """update public.asset_operations set status='queued',provider=$2,model_id=$3,
               job_id=$4::uuid where id=$1::uuid""",
            operation_id, adapter.provider_id, model.id, job.job_id,
        )
        return (
            f"{kind.capitalize()} operation {operation_id} queued on {model.id}; "
            f"{job.credits_reserved} credits reserved. Source assets remain unchanged.",
            {"operation_id": operation_id, "job_id": job.job_id, "credits": job.credits_reserved},
        )

    @classmethod
    async def create(
        cls, ctx: ToolContext, snap: TaxonomySnapshot
    ) -> ExecuteAssetOperationTool | None:
        models = (*snap.models_for("image"), *snap.models_for("video"))
        if not models:
            return None
        tool = cls(
            args_schema=build_args(
                "ExecuteAssetOperationArgs",
                operation_id=described(str, "Id returned by plan_asset_operation."),
                model_id=described(literal_of([model.id for model in models]), "Compatible output model."),
                duration_s=described(float | None, "Optional duration for video operations.", None),
            ),
            description=(
                "Execute a planned edit, extension, remix, variation or character extraction "
                "as a non-destructive derived asset. USE THIS after plan_asset_operation has "
                "captured sources, annotations, seed and preservation rules. DO NOT call it "
                "twice for the same operation, overwrite a source, or claim exact video editing "
                "when the chosen model does not declare that capability. Available models:\n"
                + enumerate_for_prompt(models)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


class GenerateLipsyncTool(_GenerationTool):
    """Sincronía labial sobre un clip ya generado."""

    name: str = "generate_lipsync"

    async def _arun_impl(
        self,
        asset_id: str,
        model_id: str,
        text: str | None = None,
        audio_url: str | None = None,
        audio_asset_id: str | None = None,
        segments: list[dict[str, Any]] | None = None,
        sync_mode: str = "cut_off",
        **_: Any,
    ) -> tuple[str, Any]:
        if audio_asset_id:
            audio = await _asset_or_raise(self.ctx.project_id, audio_asset_id, kind="audio")
            audio_url = audio["url"]
        if not text and not audio_url and not segments:
            raise XframeToolRetryableError(
                "generate_lipsync needs either the line to be spoken (text) or an audio "
                "track (audio_url). Ask the user for the dialogue if you do not have it — "
                "do not write lines for their characters on your own."
            )
        model = self.require_model(model_id, "lipsync")
        source = await _asset_or_raise(self.ctx.project_id, asset_id, kind="video")
        req = GenerationRequest(
            modality="lipsync",
            model_id=model.id,
            prompt=text or "",
            # La duración va en la petición y no solo en el mensaje: `estimate_cost` la
            # lee para cotizar, y sin ella el lipsync se cotizaba como si durase cero.
            duration_s=source.get("duration_s") or 5,
            init_image_url=source["url"],
            extra={
                "audio_url": audio_url,
                "audio_asset_id": audio_asset_id,
                "source_asset_id": asset_id,
                "segments": segments or [],
                "sync_mode": sync_mode,
            },
        )
        adapter, credits = await self.quote(req)
        self.assert_affordable(credits)

        job = await self.enqueue(req, adapter=adapter, shot_id=source.get("shot_id"))
        # Lipsync is a derived asset, never an overwrite. Recording the operation at
        # queue time lets the worker attach the output and QC report even after restart.
        async with db.transaction() as conn:
            operation_id = await conn.fetchval(
                """
                insert into public.asset_operations
                  (project_id, operation, status, provider, model_id, prompt, params, job_id)
                values ($1::uuid,'lipsync','queued',$2,$3,$4,$5::jsonb,$6::uuid)
                returning id
                """,
                self.ctx.project_id,
                adapter.provider_id,
                model.id,
                text or "",
                req.extra,
                job.job_id,
            )
            await conn.execute(
                """
                insert into public.asset_operation_inputs
                  (operation_id, project_id, asset_id, role, position)
                values ($1::uuid,$2::uuid,$3::uuid,'source',0)
                on conflict do nothing
                """,
                operation_id,
                self.ctx.project_id,
                asset_id,
            )
            if audio_asset_id:
                await conn.execute(
                    """
                    insert into public.asset_operation_inputs
                      (operation_id, project_id, asset_id, role, position)
                    values ($1::uuid,$2::uuid,$3::uuid,'audio',1)
                    on conflict do nothing
                    """,
                    operation_id,
                    self.ctx.project_id,
                    audio_asset_id,
                )
        return (
            f"Lipsync queued on {model.id} over asset {asset_id} "
            f"({job.credits_reserved} credits reserved). Job {job.job_id}.",
            {
                "job_id": job.job_id,
                "credits": job.credits_reserved,
                "reused": job.reused,
                "kind": "lipsync",
                "operation_id": str(operation_id),
            },
        )

    @classmethod
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> GenerateLipsyncTool | None:
        models = snap.models_for("lipsync")
        if not models:
            return None
        tool = cls(
            args_schema=build_args(
                "GenerateLipsyncArgs",
                asset_id=described(
                    str, "Id of the existing video asset whose character should speak."
                ),
                model_id=described(
                    literal_of([m.id for m in models]), "Which lipsync model to use."
                ),
                text=described(
                    str | None, "The line to be spoken. Provide this or audio_url.", None
                ),
                audio_url=described(
                    str | None, "Existing external audio URL; prefer audio_asset_id.", None
                ),
                audio_asset_id=described(
                    str | None, "Ready project audio asset to synchronize.", None
                ),
                segments=described(
                    list[dict[str, Any]] | None,
                    "Optional multi-speaker segments: start_s, end_s, audio_url and explicit face mapping.",
                    None,
                ),
                sync_mode=described(
                    literal_of(["cut_off", "loop", "bounce", "silence"]),
                    "How Sync reconciles unequal video/audio lengths.",
                    "cut_off",
                ),
            ),
            description=(
                "Add lip-synced speech to a character in a video asset that already "
                "exists.\n"
                "\n"
                "USE THIS after the shot is rendered and the user has given you the actual "
                "dialogue.\n"
                "\n"
                "DO NOT invent dialogue for the user's characters — ask for the line. DO "
                "NOT use it on a shot that has no visible face, and DO NOT use it as a way "
                "to add narration; that is an audio track, not lipsync.\n"
                "\n"
                "Lipsync models available:\n" + enumerate_for_prompt(models)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# `upscale_asset` se ha retirado, y la retirada es la corrección.
#
# Apuntaba a `model_id=f"upscale-{factor}x"`, que no existe en `gen_models` ni en la
# semilla, y no puede existir: la columna `modality` tiene un CHECK sobre
# ('image','video','audio','lipsync'), y ningún adaptador de los ocho registrados sirve
# reescalado. Tampoco comprobaba saldo ni calculaba créditos, así que era la única tool
# de generación que podía gastar sin cotizar.
#
# Había dos salidas. Darle "el mismo tratamiento que las demás" la dejaría cotizando y
# encolando contra un modelo inexistente: `load_model_spec` lanzaría `UnknownEntityError`
# enumerando modelos válidos, y el agente —que ve la tool montada en su esquema— se
# pondría a probar ids de modelo hasta agotar el turno. Es un fallo peor que no tenerla,
# porque parece corregible y no lo es.
#
# La otra es no ofrecer lo que no se puede servir, que es la regla que ya sigue el resto
# del sistema: una taxonomía vacía no monta la tool en vez de fallar de forma críptica.
# Cuando haya un modelo de upscale real en la semilla, esto vuelve como una tool normal
# con su `create()` leyendo `snap.models_for(...)`, igual que las otras cuatro.


class GenerateTransitionTool(_GenerationTool):
    """Render a deterministic bridge from exact clip boundary frames."""

    name: str = "generate_transition"

    async def _arun_impl(self, transition_id: str, model_id: str, **_: Any) -> tuple[str, Any]:
        row = await db.fetchrow(
            """
            select t.*, fa.url as from_url, fa.status as from_status,
                   ta.url as to_url, ta.status as to_status
              from public.timeline_transitions t
              join public.assets fa on fa.id=t.from_asset_id
              join public.assets ta on ta.id=t.to_asset_id
             where t.id=$1::uuid and t.project_id=$2::uuid
            """,
            transition_id,
            self.ctx.project_id,
        )
        if not row or row["kind"] != "generated":
            raise XframeToolRetryableError(
                f"Transition {transition_id} is not a generated transition in this project."
            )
        if row["status"] == "ready" and row["generated_asset_id"]:
            return (
                f"Transition {transition_id} is already ready; reused its deterministic output.",
                {
                    "transition_id": transition_id,
                    "asset_id": str(row["generated_asset_id"]),
                    "reused": True,
                },
            )
        if row["from_status"] != "ready" or row["to_status"] != "ready":
            raise XframeToolRetryableError("Both transition boundary assets must be ready.")
        model = self.require_model(model_id, "video")
        if not (model.supports_i2v and model.supports_last_frame):
            raise XframeToolRetryableError(
                f"Model '{model.id}' cannot honor both transition boundaries. Choose a "
                "video model with i2v and last-frame support."
            )
        duration_s = self.check_duration(model, float(row["duration_ms"]) / 1000)

        from app.jobs.worker import SupabaseStorage
        from app.storage import sign_reference

        from_url = str(await sign_reference(str(row["from_url"])))
        to_url = str(await sign_reference(str(row["to_url"])))
        with tempfile.TemporaryDirectory(prefix="xframe-transition-") as tmp:
            from_path = str(Path(tmp) / "from-last.png")
            to_path = str(Path(tmp) / "to-first.png")
            await _extract_boundary_frame(from_url, from_path, last=True)
            await _extract_boundary_frame(to_url, to_path, last=False)
            storage = SupabaseStorage()
            from_ref = await storage.put(
                project_id=self.ctx.project_id,
                job_id=f"transition-{transition_id}",
                filename="from-last.png",
                data=Path(from_path).read_bytes(),
                content_type="image/png",
            )
            to_ref = await storage.put(
                project_id=self.ctx.project_id,
                job_id=f"transition-{transition_id}",
                filename="to-first.png",
                data=Path(to_path).read_bytes(),
                content_type="image/png",
            )

        parameters = dict(row["parameters"] or {})
        preserve_ids = set(parameters.get("preserve_element_ids") or [])
        req = GenerationRequest(
            modality="video",
            model_id=model.id,
            prompt=str(
                parameters.get("prompt")
                or "A seamless visual bridge between the exact boundary frames."
            ),
            duration_s=duration_s,
            init_image_url=from_ref,
            last_frame_url=to_ref,
            seed=int(row["seed"]),
            elements=self.resolve_elements(
                [element.name for element in self.snap.elements if element.id in preserve_ids]
            ),
            camera_motion=parameters.get("motion_direction"),
            extra={
                "transition_id": transition_id,
                "transition_signature": row["signature"],
                "operation_id": str(row["operation_id"]) if row["operation_id"] else None,
            },
        )
        adapter, credits = await self.quote(req)
        self.assert_affordable(credits)
        job = await self.enqueue(req, adapter=adapter)
        await db.execute(
            "update public.timeline_transitions set status='queued', model_id=$2, updated_at=now() where id=$1::uuid",
            transition_id,
            model.id,
        )
        if row["operation_id"]:
            await db.execute(
                "update public.asset_operations set status='queued', provider=$2, model_id=$3, job_id=$4::uuid where id=$1::uuid",
                row["operation_id"],
                adapter.provider_id,
                model.id,
                job.job_id,
            )
        return (
            f"Deterministic transition {transition_id} queued from exact boundary frames "
            f"with seed {row['seed']}. Job {job.job_id}; {job.credits_reserved} credits reserved.",
            {
                "job_id": job.job_id,
                "transition_id": transition_id,
                "signature": row["signature"],
                "seed": row["seed"],
                "credits": job.credits_reserved,
            },
        )

    @classmethod
    async def create(
        cls, ctx: ToolContext, snap: TaxonomySnapshot
    ) -> GenerateTransitionTool | None:
        models = tuple(
            model
            for model in snap.models_for("video")
            if model.supports_i2v and model.supports_last_frame
        )
        if not models:
            return None
        tool = cls(
            args_schema=build_args(
                "GenerateTransitionArgs",
                transition_id=described(str, "Id returned by plan_transition."),
                model_id=described(
                    literal_of([model.id for model in models]),
                    "Model supporting exact first and last frames.",
                ),
            ),
            description=(
                "Render a planned generated transition from the exact last frame of asset A "
                "to the exact first frame of asset B. USE THIS only after plan_transition "
                "and cost approval. DO NOT change its stored seed or endpoints.\n\nCompatible models:\n"
                + enumerate_for_prompt(models)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


async def _extract_boundary_frame(source: str, output: str, *, last: bool) -> None:
    """Extract a boundary frame before any paid provider call."""
    from app.config import get_settings

    args = [get_settings().ffmpeg_path, "-hide_banner", "-nostdin", "-y"]
    if last:
        args += ["-sseof", "-0.05"]
    args += ["-i", source, "-frames:v", "1", "-f", "image2", output]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not Path(output).exists():
        raise XframeToolRetryableError(
            "Could not extract a transition boundary frame before generation. "
            + stderr.decode(errors="replace")[-1200:]
        )


class AssembleVideoArgs(BaseModel):
    manifest_id: str = Field(
        ...,
        description=(
            "Completed production manifest whose quality-gated shot snapshot exactly "
            "matches shot_ids."
        ),
    )
    shot_ids: list[str] | None = Field(
        None,
        description=(
            "Optional safety assertion. The completed manifest's frozen output order is "
            "authoritative and cannot be overridden."
        ),
    )
    audio_asset_id: str | None = Field(
        None, description="Optional music or voice-over track to lay under the cut."
    )
    use_audio_plan: bool = Field(
        True,
        description=(
            "Mix the project's structured dialogue/music/SFX/ambience cues. Keep true "
            "unless the user explicitly requests a picture-only or legacy single-track cut."
        ),
    )
    title: str = Field("Montaje", description="Name for the resulting cut asset.")


class AssembleVideoTool(_GenerationTool):
    """Montaje final. No llama a un proveedor: es ffmpeg local."""

    name: str = "assemble_video"
    consumes_credits: bool = False

    args_schema: type[BaseModel] = AssembleVideoArgs

    description: str = (
        "Concatenate the rendered shots into a single cut, optionally over an audio "
        "track. Runs locally with ffmpeg and does not consume generation credits.\n"
        "\n"
        "USE THIS when every shot in a completed, quality-gated production manifest has "
        "a finished video asset, typically as the last step before delivery.\n"
        "\n"
        "DO NOT call it while shots are still rendering — check_job_status must show them "
        "all succeeded, or the cut will be assembled with gaps. DO NOT assemble shots the "
        "user has not seen yet; show them the shots first."
    )

    async def _arun_impl(
        self,
        manifest_id: str,
        shot_ids: list[str] | None = None,
        audio_asset_id: str | None = None,
        use_audio_plan: bool = True,
        title: str = "Montaje",
        **_: Any,
    ) -> tuple[str, Any]:
        manifest = await db.fetchrow(
            """select status,specification,execution_snapshot,execution_fingerprint
                 from public.production_manifests
                where id=$1::uuid and project_id=$2::uuid""",
            manifest_id, self.ctx.project_id,
        )
        execution = dict(manifest["execution_snapshot"] or {}) if manifest else {}
        frozen_outputs = list(execution.get("outputs") or [])
        manifest_shots = [str(item.get("shot_id")) for item in frozen_outputs]
        if not manifest or manifest["status"] != "complete" or not frozen_outputs:
            raise XframeToolRetryableError(
                "Final assembly requires a completed production manifest with a frozen "
                "execution snapshot. Finish output review and complete the manifest first."
            )
        if shot_ids is not None and shot_ids != manifest_shots:
            raise XframeToolRetryableError(
                "shot_ids cannot override the completed manifest's frozen playback order."
            )
        shot_ids = manifest_shots
        frozen_asset_ids = [str(item.get("asset_id")) for item in frozen_outputs]
        rows = await db.fetch(
            """
            select id as asset_id,shot_id,url,status,type
              from public.assets
             where project_id=$1::uuid and id=any($2::uuid[])
            """,
            self.ctx.project_id,
            frozen_asset_ids,
        )
        by_asset = {str(row["asset_id"]): row for row in rows}
        by_shot = {
            str(item["shot_id"]): by_asset.get(str(item["asset_id"]))
            for item in frozen_outputs
        }
        pending = [
            shot_id for shot_id in shot_ids
            if not by_shot.get(shot_id) or by_shot[shot_id]["status"] != "ready"
        ]
        if pending:
            raise XframeToolRetryableError(
                f"These shots have no finished video asset yet: {', '.join(pending)}. "
                f"Wait for their jobs to succeed (check_job_status) or render them before "
                f"assembling. Assembling now would produce a cut with holes in it."
            )

        from app.artifacts.manager import ArtifactManager
        from app.artifacts.types import AssetRefBlock, CutArtifactContent
        from app.assembly import AssemblySpec, AudioTimelineClip, TimelineClip, assemble_cut
        from app.assembly.ffmpeg import default_output_path
        from app.storage import sign_reference

        # ffmpeg descarga cada entrada por HTTP, así que aquí también hace falta firmar:
        # con el bucket privado, un `src` en crudo es un 400 y un montaje vacío. Se firma
        # justo antes de invocar a ffmpeg y no se guarda en ningún sitio — el corte se
        # ensambla en segundos y estas URLs mueren con él.
        audio_track: str | None = None
        if audio_asset_id:
            audio_track = await sign_reference(
                str(
                    (await _asset_or_raise(self.ctx.project_id, audio_asset_id, kind="audio"))[
                        "url"
                    ]
                )
            )

        audio_cues: list[AudioTimelineClip] = []
        target_lufs = -14.0
        true_peak_dbtp = -1.0
        if use_audio_plan:
            cue_rows = list(execution.get("audio_cues") or [])
            cue_asset_ids = list(
                dict.fromkeys(str(cue["asset_id"]) for cue in cue_rows if cue.get("asset_id"))
            )
            cue_assets = (
                await db.fetch(
                    """select id,url,status from public.assets
                        where project_id=$1::uuid and id=any($2::uuid[])""",
                    self.ctx.project_id,
                    cue_asset_ids,
                )
                if cue_asset_ids
                else []
            )
            cue_asset_by_id = {str(row["id"]): row for row in cue_assets}
            for cue in cue_rows:
                cue_asset = cue_asset_by_id.get(str(cue["asset_id"]))
                if not cue_asset or cue_asset["status"] != "ready":
                    raise XframeToolRetryableError(
                        f"Frozen audio asset {cue['asset_id']} is no longer ready. "
                        "Restore it or complete a new manifest version."
                    )
                audio_cues.append(
                    AudioTimelineClip(
                        asset_id=str(cue["asset_id"]),
                        src=str(await sign_reference(str(cue_asset["url"]))),
                        track_kind=str(cue["track_kind"]),
                        start_s=float(cue["start_ms"]) / 1000,
                        end_s=float(cue["end_ms"]) / 1000,
                        source_in_s=float(cue["source_in_ms"]) / 1000,
                        source_out_s=(
                            float(cue["source_out_ms"]) / 1000
                            if cue["source_out_ms"] is not None
                            else None
                        ),
                        gain_db=float(cue["gain_db"]),
                        fade_in_s=float(cue["fade_in_ms"]) / 1000,
                        fade_out_s=float(cue["fade_out_ms"]) / 1000,
                        pan=float(cue["pan"]),
                        loop=bool(cue["loop"]),
                        ducking_group=cue["ducking_group"],
                        ducking_db=(
                            float(cue["ducking_db"]) if cue["ducking_db"] is not None else None
                        ),
                    )
                )
            audio_plan = execution.get("audio_plan")
            if audio_plan:
                content = dict(audio_plan["content"] or {})
                target_lufs = float(content.get("target_lufs", target_lufs))
                true_peak_dbtp = float(content.get("true_peak_dbtp", true_peak_dbtp))

        manager = ArtifactManager(self.ctx.project_id)
        # El corte se versiona como el guion y el timeline: regenerarlo es una versión
        # nueva, no una sobrescritura. La versión entra en la ruta de salida para que dos
        # montajes concurrentes no se pisen el fichero temporal.
        version = len(await manager.alist("cut")) + 1

        transition_rows = list(execution.get("transitions") or [])
        generated_ids = list(
            dict.fromkeys(
                str(row["generated_asset_id"])
                for row in transition_rows
                if row.get("generated_asset_id")
            )
        )
        generated_assets = (
            await db.fetch(
                """select id,url,status from public.assets
                    where project_id=$1::uuid and id=any($2::uuid[])""",
                self.ctx.project_id,
                generated_ids,
            )
            if generated_ids
            else []
        )
        generated_by_id = {str(row["id"]): row for row in generated_assets}
        for transition in transition_rows:
            generated = generated_by_id.get(str(transition.get("generated_asset_id")))
            transition["generated_url"] = generated["url"] if generated else None
            transition["generated_status"] = generated["status"] if generated else None
        transition_by_pair = {
            (str(row["from_asset_id"]), str(row["to_asset_id"])): row for row in transition_rows
        }
        timeline_clips: list[TimelineClip] = []
        for index, shot_id in enumerate(shot_ids):
            current_asset = str(by_shot[shot_id]["asset_id"])
            transition_in = "cut"
            transition_duration = 0.5
            if index:
                previous_asset = str(by_shot[shot_ids[index - 1]]["asset_id"])
                transition = transition_by_pair.get((previous_asset, current_asset))
                if transition and transition["kind"] == "crossfade":
                    transition_in = "crossfade"
                    transition_duration = float(transition["duration_ms"]) / 1000
                elif transition and transition["kind"] == "generated":
                    if transition["status"] != "ready" or not transition["generated_url"]:
                        raise XframeToolRetryableError(
                            "Generated transition "
                            f"{transition['signature']} between assets {previous_asset} and "
                            f"{current_asset} is not ready. Render/approve it or switch the "
                            "structured transition to cut/crossfade before assembly."
                        )
                    timeline_clips.append(
                        TimelineClip(
                            asset_id=str(transition["generated_asset_id"]),
                            src=str(await sign_reference(str(transition["generated_url"]))),
                            status="ready",
                        )
                    )
            timeline_clips.append(
                TimelineClip(
                    asset_id=current_asset,
                    src=str(await sign_reference(str(by_shot[shot_id]["url"]))),
                    shot_id=shot_id,
                    status="ready",
                    transition_in=transition_in,
                    transition_duration_s=transition_duration,
                )
            )

        spec = AssemblySpec(
            clips=timeline_clips,
            output_path=default_output_path(self.ctx.project_id, version),
            audio_track=audio_track,
            audio_cues=audio_cues,
            target_lufs=target_lufs,
            true_peak_dbtp=true_peak_dbtp,
            version=version,
        )
        result = await assemble_cut(spec)

        # El montaje no estaba persistido en ninguna parte: se renderizaba un mp4 en un
        # directorio temporal y se le contaba al usuario que existía un asset que nadie
        # había escrito. Un entregable que solo vive en /tmp no es un entregable.
        #
        # Una vez subido, el mp4 local ya no vale nada: la verdad es la fila de `assets`
        # y el objeto del bucket. Se borra en `finally` para que un montaje fallido —o el
        # normal— no deje ficheros acumulándose en el disco del contenedor, que corre
        # meses sin reiniciarse. La verdad ya está en el storage; el temporal es basura.
        try:
            asset_id = await _persist_cut(
                self.ctx.project_id, result, title=title, manifest_id=manifest_id
            )
        finally:
            _discard_temp(result.output_path)
        artifact = await manager.acreate(
            CutArtifactContent(
                title=title,
                cut_asset_id=asset_id,
                # Referencias, nunca copias: si un plano se regenera, el artefacto lo
                # refleja sin propagar nada a mano.
                blocks=[AssetRefBlock(asset_id=a) for a in result.clip_asset_ids],
            ),
            name=title,
        )

        warnings = "".join(f"\n  WARNING: {w}" for w in result.warnings)
        return (
            f"Cut '{title}' (v{version}) assembled from {len(shot_ids)} shots, "
            f"{result.duration_s:.1f}s at {result.target}. Asset {asset_id}.{warnings}",
            {
                "asset_id": asset_id,
                "artifact_id": artifact["id"],
                "shots": shot_ids,
                "version": version,
                "duration_s": result.duration_s,
                "warnings": result.warnings,
                "kind": "cut",
                "manifest_id": manifest_id,
            },
        )


# --------------------------------------------------------------------------- #
# Ayudas                                                                       #
# --------------------------------------------------------------------------- #


def _discard_temp(path: str | None) -> None:
    """
    Borra el mp4 temporal del montaje, sin ruido.

    Que falle el borrado no puede tumbar el turno: el asset ya está en el storage y esto
    es solo higiene de disco. Un fichero que no se pudo borrar es un problema de operación
    (lo recogerá el barrido de /tmp del sistema), no del usuario, que ya tiene su corte.
    """
    if not path:
        return
    import logging
    from pathlib import Path

    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:  # best-effort; el asset ya está a salvo en el storage
        logging.getLogger(__name__).warning(
            "cut_temp_cleanup_failed", extra={"path": path, "error": str(exc)}
        )


async def _persist_cut(
    project_id: str, result: AssemblyResult, *, title: str, manifest_id: str
) -> str:
    """
    Sube el mp4 montado al storage y escribe su fila en `assets`. Devuelve el id.

    Se reutiliza `SupabaseStorage` del worker en vez de escribir otra subida: es el mismo
    bucket, la misma clave de servicio y el mismo `x-upsert`, y tener dos rutas de subida
    es tener dos sitios donde se puede romper la política del bucket. `job_id` no es un
    job de proveedor aquí —el montaje es local— sino la carpeta del corte, que es lo que
    esa función usa el parámetro para construir.

    El asset se marca `ready` directamente porque cuando esto corre el fichero ya existe
    y ya está verificado por `assemble_cut`. No hay estado intermedio que observar.

    Lo que `put()` devuelve es la **ruta** del objeto, y eso es lo que se escribe en
    `assets.url`. Igual que los planos: el corte lo pinta el frontend firmando la ruta,
    nunca leyendo una URL guardada que caducaría.
    """
    from pathlib import Path

    from app.jobs.worker import SupabaseStorage

    data = Path(result.output_path).read_bytes()
    object_path = await SupabaseStorage().put(
        project_id=project_id,
        job_id=f"cut-v{result.version}",
        filename="cut.mp4",
        data=data,
        content_type="video/mp4",
    )
    row = await db.fetchrow(
        """
        insert into public.assets
            (project_id, name, type, url, status, params)
        values ($1::uuid, $2, 'cut', $3, 'ready', $4::jsonb)
        returning id
        """,
        project_id,
        title[:80],
        object_path,
        result.to_artifact_content() | {"manifest_id": manifest_id},
    )
    return str(row["id"])


async def _asset_or_raise(
    project_id: str, asset_id: str, *, kind: str | None = None
) -> dict[str, Any]:
    """Asset del proyecto o error que enumera los candidatos. Filtra por `project_id`
    porque el backend salta RLS y este filtro es el control de acceso real."""
    row = await db.fetchrow(
        """
        select id, name, type, url, status, shot_id, params
          from public.assets
         where id = $1::uuid and project_id = $2::uuid
        """,
        asset_id,
        project_id,
    )
    def matches(value: Any, expected: str | None) -> bool:
        if expected is None:
            return True
        normalized = str(value or "").strip().lower()
        aliases = {
            "image": ("image", "imagen", "imágen"),
            "video": ("video", "vídeo", "cut"),
            "audio": ("audio", "sound", "sonido", "music", "música"),
        }
        return any(token in normalized for token in aliases.get(expected, (expected,)))

    if row is None or not matches(row["type"], kind):
        valid = await db.fetch(
            """
            select id, name, type from public.assets
             where project_id = $1::uuid and status = 'ready'
             order by created_at desc limit 40
            """,
            project_id,
        )
        valid = [candidate for candidate in valid if matches(candidate["type"], kind)]
        raise UnknownEntityError(
            f"{kind or 'asset'}", asset_id, [f"{r['id']} ({r['name']})" for r in valid]
        )
    out = dict(row) | {"id": str(row["id"])}
    out["duration_s"] = (row["params"] or {}).get("duration_s")
    return out
