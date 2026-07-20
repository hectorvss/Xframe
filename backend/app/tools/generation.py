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

from typing import TYPE_CHECKING, Any, ClassVar, Sequence

from pydantic import BaseModel, Field

from app import db
from app.providers.base import GenerationAdapter, GenerationRequest
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
    ) -> "EnqueueResult":
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
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> "GenerateImageTool | None":
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
    async def create(cls, ctx: ToolContext, snap: TaxonomySnapshot) -> "GenerateVideoTool | None":
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
            "resolution": described(str | None, "Resolution the model supports, e.g. '1080p'.", None),
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
        duration_s: float | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        model = self.require_model(model_id, "video")

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

        from app.agent.state import JobResult
        from app.jobs.fanout import ShotSpec, run_fanout

        # Una petición por plano, construida antes de cotizar nada: es la petición
        # concreta la que tiene precio, no el modelo.
        requests: dict[str, GenerationRequest] = {}
        for row in rows:
            spec = dict(row["spec"] or {})
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
                elements=self.resolve_elements(spec.get("elements")),
                camera_motion=self.motion_or_none(spec.get("camera_motion")),
                camera_motion_strength=spec.get("camera_motion_strength"),
                style=self.style_fragments(spec.get("styles")),
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
                shot.payload, adapter=adapter, shot_id=shot.shot_id  # type: ignore[arg-type]
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
        return "\n".join(lines), {
            "results": [r.model_dump() for r in report.results],
            "credits_reserved": reserved,
            "credits_quoted": quoted,
            "model_id": model.id,
        }

    @classmethod
    async def create(
        cls, ctx: ToolContext, snap: TaxonomySnapshot
    ) -> "GenerateShotBatchTool | None":
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
                duration_s=described(
                    float | None,
                    "Override the duration of every shot. Omit to use each shot's own "
                    "duration from its spec.",
                    None,
                ),
            ),
            description=(
                "Render several shots in parallel, one job per shot, and report the "
                "outcome shot by shot. Partial failure is expected and reported; the "
                "batch does not abort because one shot failed.\n"
                "\n"
                "USE THIS to produce a sequence once the shot list is written and the "
                "user has approved the plan. Always call estimate_cost first and tell the "
                "user the total: this single call can spend more credits than everything "
                "else in the conversation combined.\n"
                "\n"
                "DO NOT use it to retry a failed batch wholesale — the shots that "
                "succeeded would be charged again. Retry the failed shots individually "
                "with generate_video. DO NOT pass shots whose spec is still empty; render "
                "what was planned, not what you improvised.\n"
                "\n"
                "Video models available:\n" + enumerate_for_prompt(models)
            ),
        )
        return tool.bind_context(ctx).bind_snapshot(snap)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# generate_lipsync / upscale_asset / assemble_video                            #
# --------------------------------------------------------------------------- #


class GenerateLipsyncTool(_GenerationTool):
    """Sincronía labial sobre un clip ya generado."""

    name: str = "generate_lipsync"

    async def _arun_impl(
        self,
        asset_id: str,
        model_id: str,
        text: str | None = None,
        audio_url: str | None = None,
        **_: Any,
    ) -> tuple[str, Any]:
        if not text and not audio_url:
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
            extra={"audio_url": audio_url, "source_asset_id": asset_id},
        )
        adapter, credits = await self.quote(req)
        self.assert_affordable(credits)

        job = await self.enqueue(req, adapter=adapter, shot_id=source.get("shot_id"))
        return (
            f"Lipsync queued on {model.id} over asset {asset_id} "
            f"({job.credits_reserved} credits reserved). Job {job.job_id}.",
            {
                "job_id": job.job_id,
                "credits": job.credits_reserved,
                "reused": job.reused,
                "kind": "lipsync",
            },
        )

    @classmethod
    async def create(
        cls, ctx: ToolContext, snap: TaxonomySnapshot
    ) -> "GenerateLipsyncTool | None":
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
                    str | None, "Existing audio track to sync against.", None
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


class AssembleVideoArgs(BaseModel):
    shot_ids: list[str] = Field(
        ...,
        description=(
            "Shots to concatenate, in playback order. Each must already have a rendered "
            "video asset; check with read_project first."
        ),
    )
    audio_asset_id: str | None = Field(
        None, description="Optional music or voice-over track to lay under the cut."
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
        "USE THIS when every shot the user wants in the cut has a finished video asset, "
        "typically as the last step before delivery.\n"
        "\n"
        "DO NOT call it while shots are still rendering — check_job_status must show them "
        "all succeeded, or the cut will be assembled with gaps. DO NOT assemble shots the "
        "user has not seen yet; show them the shots first."
    )

    async def _arun_impl(
        self,
        shot_ids: list[str],
        audio_asset_id: str | None = None,
        title: str = "Montaje",
        **_: Any,
    ) -> tuple[str, Any]:
        rows = await db.fetch(
            """
            select n.id as shot_id, n.position, n.title, a.id as asset_id, a.url, a.status
              from public.canvas_nodes n
              left join lateral (
                   select id, url, status from public.assets
                    where shot_id = n.id::text and type = 'video' and status = 'ready'
                    order by created_at desc limit 1
              ) a on true
             where n.project_id = $1::uuid and n.id = any($2::uuid[])
            """,
            self.ctx.project_id,
            shot_ids,
        )
        by_shot = {str(r["shot_id"]): r for r in rows}
        pending = [s for s in shot_ids if s not in by_shot or by_shot[s]["asset_id"] is None]
        if pending:
            raise XframeToolRetryableError(
                f"These shots have no finished video asset yet: {', '.join(pending)}. "
                f"Wait for their jobs to succeed (check_job_status) or render them before "
                f"assembling. Assembling now would produce a cut with holes in it."
            )

        from app.artifacts.manager import ArtifactManager
        from app.artifacts.types import AssetRefBlock, CutArtifactContent
        from app.assembly import AssemblySpec, TimelineClip, assemble_cut
        from app.assembly.ffmpeg import default_output_path

        from app.storage import sign_reference

        # ffmpeg descarga cada entrada por HTTP, así que aquí también hace falta firmar:
        # con el bucket privado, un `src` en crudo es un 400 y un montaje vacío. Se firma
        # justo antes de invocar a ffmpeg y no se guarda en ningún sitio — el corte se
        # ensambla en segundos y estas URLs mueren con él.
        audio_track: str | None = None
        if audio_asset_id:
            audio_track = await sign_reference(
                str((await _asset_or_raise(self.ctx.project_id, audio_asset_id, kind="audio"))["url"])
            )

        manager = ArtifactManager(self.ctx.project_id)
        # El corte se versiona como el guion y el timeline: regenerarlo es una versión
        # nueva, no una sobrescritura. La versión entra en la ruta de salida para que dos
        # montajes concurrentes no se pisen el fichero temporal.
        version = len(await manager.alist("cut")) + 1

        spec = AssemblySpec(
            clips=[
                TimelineClip(
                    asset_id=str(by_shot[s]["asset_id"]),
                    src=str(await sign_reference(str(by_shot[s]["url"]))),
                    shot_id=s,
                    status="ready",
                )
                for s in shot_ids
            ],
            output_path=default_output_path(self.ctx.project_id, version),
            audio_track=audio_track,
            version=version,
        )
        result = await assemble_cut(spec)

        # El montaje no estaba persistido en ninguna parte: se renderizaba un mp4 en un
        # directorio temporal y se le contaba al usuario que existía un asset que nadie
        # había escrito. Un entregable que solo vive en /tmp no es un entregable.
        asset_id = await _persist_cut(self.ctx.project_id, result, title=title)
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
            },
        )


# --------------------------------------------------------------------------- #
# Ayudas                                                                       #
# --------------------------------------------------------------------------- #


async def _persist_cut(project_id: str, result: "AssemblyResult", *, title: str) -> str:
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
        result.to_artifact_content(),
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
    if row is None or (kind and row["type"] != kind):
        valid = await db.fetch(
            """
            select id, name, type from public.assets
             where project_id = $1::uuid and status = 'ready'
               and ($2::text is null or type = $2)
             order by created_at desc limit 40
            """,
            project_id,
            kind,
        )
        raise UnknownEntityError(
            f"{kind or 'asset'}", asset_id, [f"{r['id']} ({r['name']})" for r in valid]
        )
    out = dict(row) | {"id": str(row["id"])}
    out["duration_s"] = (row["params"] or {}).get("duration_s")
    return out
