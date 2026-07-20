"""
Encolado de generaciones, con idempotencia.

La idempotencia aquí **no es una optimización de coste**: es correctitud. Los webhooks de
fal reintentan hasta 10 veces en 2 horas, el frontend reintenta al reconectar, y el propio
LLM puede repetir una tool call idéntica tras una compactación del historial. Sin clave de
idempotencia, cada uno de esos caminos es un cobro más por el mismo vídeo.

La regla que implementa `enqueue()`:

1. Si ya existe un job **succeeded** con esa clave → se devuelve su asset. No se reserva,
   no se cobra, no se llama al proveedor.
2. Si existe uno **en curso** → nos adjuntamos a él. Tampoco se reserva: la reserva ya la
   hizo quien lo encoló.
3. Si existe uno **terminal fallido** → se reabre esa misma fila para un intento nuevo.
   Reabrir en vez de insertar es obligado: `idempotency_key` es `unique`.
4. Si no existe → reserva de créditos e inserción, en la misma transacción.

Sobre qué entra en la clave: `project_id` sí entra. La restricción `unique` es global a la
tabla, así que sin el proyecto en el hash dos usuarios distintos que pidieran el mismo
prompt con el mismo modelo colisionarían, y el segundo recibiría el asset del primero.
Eso es una fuga de datos entre proyectos, no un acierto de caché.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.agent.state import AssetRef
from app.db import transaction
from app.jobs import credits
from app.providers.base import GenerationAdapter, GenerationRequest, ModelSpec
from app.tools.errors import ModelRetiredError, UnknownEntityError

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATES: tuple[str, ...] = ("queued", "submitted", "running")
"""Estados no terminales. Un job aquí ya tiene su reserva hecha."""


@dataclass(slots=True)
class EnqueueResult:
    """
    Lo que la tool de generación devuelve al agente tras encolar.

    `reused` distingue los tres desenlaces de cara al usuario: un job nuevo (hay que
    esperar), uno adjuntado (hay que esperar, pero no se ha cobrado ahora) y uno cacheado
    (el asset ya está, respuesta inmediata y gratis).
    """

    job_id: str
    status: str
    idempotency_key: str
    credits_reserved: int
    reused: bool
    asset: AssetRef | None = None

    @property
    def is_cached(self) -> bool:
        return self.reused and self.asset is not None and self.asset.status == "ready"


# --------------------------------------------------------------------------- #
# Clave de idempotencia                                                        #
# --------------------------------------------------------------------------- #


def _canonical(value: Any) -> Any:
    """
    Normaliza para que el hash sea estable.

    Los diccionarios se ordenan por clave (el orden de inserción de un dict de Python no
    es semántico y cambiaría el hash sin que cambie la petición), los `Decimal` y `UUID`
    pasan a texto, y los valores `None` y las colecciones vacías se descartan: que el
    llamante pase `negative_prompt=None` explícitamente o no lo pase debe dar la misma
    clave, porque es la misma generación.
    """
    if isinstance(value, dict):
        out = {}
        for k in sorted(value):
            v = _canonical(value[k])
            if v is None or v == [] or v == {}:
                continue
            out[k] = v
        return out
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    return value


def compute_idempotency_key(
    request: GenerationRequest, *, provider: str, project_id: str | UUID
) -> str:
    """
    sha256 estable sobre (proyecto, proveedor, modelo, parámetros, semilla).

    Advertencia deliberada sobre `seed`: si `seed is None` el proveedor elegirá una al
    azar, de modo que dos peticiones "idénticas" **no** producen el mismo vídeo. Aun así
    comparten clave, y por tanto la segunda recibe el resultado de la primera. Es lo que
    queremos — el usuario que pulsa dos veces no quiere pagar dos veces —, pero implica
    que para pedir de verdad una variación hay que pasar una `seed` distinta. Las tools
    de regeneración deben hacerlo explícitamente.
    """
    payload = _canonical(
        {
            "project": str(project_id),
            "provider": provider,
            "model": request.model_id,
            "params": asdict(request),
        }
    )
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Catálogo                                                                     #
# --------------------------------------------------------------------------- #


async def load_model_spec(conn: asyncpg.Connection, model_id: str) -> ModelSpec:
    """
    Lee el modelo de `gen_models`, que es la fuente de verdad.

    Un modelo `retired` se rechaza aquí y no en el adaptador: es más barato, y el error
    lleva alternativas para que el LLM se autocorrija en el siguiente turno en vez de
    quedarse atascado. Pasa de verdad y con frecuencia (Veo 3.0, Runway Gen-3/Gen-4,
    Sora 2), así que este camino no es defensivo, es el camino normal.
    """
    row = await conn.fetchrow("select * from public.gen_models where id = $1", model_id)
    if row is None:
        valid = [
            r["id"]
            for r in await conn.fetch(
                "select id from public.gen_models where status = 'active' order by sort"
            )
        ]
        raise UnknownEntityError("model", model_id, valid)

    if row["status"] == "retired":
        alternatives = [
            r["id"]
            for r in await conn.fetch(
                """
                select id from public.gen_models
                 where status = 'active' and modality = $1
                 order by sort limit 5
                """,
                row["modality"],
            )
        ]
        raise ModelRetiredError(model_id, alternatives)

    return ModelSpec(
        id=row["id"],
        family=row["family"],
        provider=row["provider"],
        modality=row["modality"],
        cost_per_second=Decimal(row["cost_per_second"]),
        max_duration_s=float(row["max_duration_s"]) if row["max_duration_s"] is not None else None,
        min_duration_s=float(row["min_duration_s"]) if row["min_duration_s"] is not None else None,
        resolutions=tuple(row["resolutions"] or ()),
        aspects=tuple(row["aspects"] or ()),
        supports_i2v=row["supports_i2v"],
        supports_last_frame=row["supports_last_frame"],
        supports_char_ref=row["supports_char_ref"],
        supports_audio=row["supports_audio"],
        description_llm=row["description_llm"],
    )


# --------------------------------------------------------------------------- #
# Encolado                                                                     #
# --------------------------------------------------------------------------- #


async def enqueue(
    request: GenerationRequest,
    *,
    project_id: str | UUID,
    shot_id: str | None = None,
    adapter: GenerationAdapter,
    conversation_id: str | UUID | None = None,
) -> EnqueueResult:
    """
    Encola una generación, o devuelve el trabajo ya hecho si es la misma petición.

    Todo ocurre en una transacción y bajo el cerrojo del perfil pagador. El cerrojo se
    toma **antes** de consultar por la clave de idempotencia, no después: la decisión que
    hay que serializar es "¿reutilizo o gasto?", y si se consulta fuera del cerrojo dos
    peticiones concurrentes pueden concluir a la vez que no existe nada y encolar dos
    jobs. La `unique` sobre `idempotency_key` sería la última red, pero convertiría una
    condición de carrera normal en un error de integridad visible para el usuario.
    """
    async with transaction() as conn:
        await credits.lock_project_owner(conn, project_id)

        key = compute_idempotency_key(request, provider=adapter.provider_id, project_id=project_id)
        existing = await conn.fetchrow(
            "select * from public.generation_jobs where idempotency_key = $1", key
        )

        if existing is not None:
            reused = await _reuse(conn, existing, key)
            if reused is not None:
                return reused

        spec = await load_model_spec(conn, request.model_id)
        cost_usd = adapter.estimate_cost(request, spec)
        amount = credits.usd_to_credits(cost_usd)

        if existing is not None:
            # Reapertura de un job terminal fallido: misma fila, intento nuevo. Se
            # reserva otra vez porque el reembolso del intento anterior ya devolvió lo
            # suyo, así que ahora mismo no hay nada retenido para este job.
            job_id: UUID = existing["id"]
            await credits.reserve(
                project_id=project_id,
                amount=amount,
                job_id=job_id,
                note=f"reintento de {request.model_id}",
                conn=conn,
            )
            await conn.execute(
                """
                update public.generation_jobs
                   set status = 'queued', request = $2, credits_reserved = $3,
                       credits_charged = 0, cost_usd = $4, provider_ref = null,
                       progress = null, error = null, asset_id = null,
                       shot_id = coalesce($5, shot_id), attempts = 0,
                       updated_at = now(), started_at = null, finished_at = null
                 where id = $1
                """,
                job_id,
                _serialize(request),
                amount,
                cost_usd,
                shot_id,
            )
            logger.info("job_reopened", extra={"job_id": str(job_id), "model": request.model_id})
            return EnqueueResult(
                job_id=str(job_id),
                status="queued",
                idempotency_key=key,
                credits_reserved=amount,
                reused=False,
            )

        new_id: UUID = await conn.fetchval(
            """
            insert into public.generation_jobs
                (project_id, shot_id, provider, model_id, request, idempotency_key,
                 status, credits_reserved, cost_usd, conversation_id)
            values ($1, $2, $3, $4, $5, $6, 'queued', $7, $8, $9)
            returning id
            """,
            credits.to_uuid(project_id),
            shot_id,
            adapter.provider_id,
            request.model_id,
            _serialize(request),
            key,
            amount,
            cost_usd,
            credits.to_uuid(conversation_id) if conversation_id else None,
        )
        # La reserva va después del insert por la FK de `credit_ledger.job_id`. Ambas
        # están en la misma transacción, así que si la reserva falla por saldo el insert
        # se deshace con ella y no queda ningún job gratis.
        await credits.reserve(
            project_id=project_id,
            amount=amount,
            job_id=new_id,
            note=f"reserva de {request.model_id}",
            conn=conn,
        )

        logger.info(
            "job_enqueued",
            extra={"job_id": str(new_id), "model": request.model_id, "credits": amount},
        )
        return EnqueueResult(
            job_id=str(new_id),
            status="queued",
            idempotency_key=key,
            credits_reserved=amount,
            reused=False,
        )


async def _reuse(
    conn: asyncpg.Connection, existing: asyncpg.Record, key: str
) -> EnqueueResult | None:
    """
    Decide si un job existente sirve. Devuelve `None` si hay que reabrirlo.

    Solo se reutiliza lo que tiene valor: un `succeeded` (con su asset) o uno en curso.
    Un `failed`, `nsfw` o `cancelled` no se reutiliza — el usuario pidió un plano y no lo
    tiene —, pero tampoco se reutiliza su asset, porque no hay ninguno.
    """
    status: str = existing["status"]
    job_id: UUID = existing["id"]

    if status == "succeeded":
        asset = await _asset_ref(conn, existing)
        if asset is None:
            # Succeeded sin asset es un estado incoherente: el worker murió entre subir
            # el fichero y escribir la fila. Se reabre en vez de devolver un resultado
            # vacío que el agente presentaría al usuario como un plano listo.
            logger.warning("job_succeeded_without_asset", extra={"job_id": str(job_id)})
            return None
        logger.info("job_idempotent_hit", extra={"job_id": str(job_id)})
        return EnqueueResult(
            job_id=str(job_id),
            status=status,
            idempotency_key=key,
            credits_reserved=0,
            reused=True,
            asset=asset,
        )

    if status in ACTIVE_JOB_STATES:
        logger.info("job_attached", extra={"job_id": str(job_id), "status": status})
        return EnqueueResult(
            job_id=str(job_id),
            status=status,
            idempotency_key=key,
            credits_reserved=0,
            reused=True,
            asset=await _asset_ref(conn, existing),
        )

    return None


async def _asset_ref(conn: asyncpg.Connection, job: asyncpg.Record) -> AssetRef | None:
    if job["asset_id"] is None:
        return None
    row = await conn.fetchrow(
        "select id, type, status, shot_id from public.assets where id = $1", job["asset_id"]
    )
    if row is None:
        return None
    return AssetRef(
        asset_id=str(row["id"]),
        kind=_asset_kind(row["type"]),
        status=row["status"],
        shot_id=row["shot_id"] or job["shot_id"],
    )


def _asset_kind(raw: str) -> str:
    """
    `assets.type` es texto libre heredado del esquema original; `AssetRef.kind` es un
    `Literal` cerrado. Se normaliza aquí para no propagar el desajuste hacia el estado.
    """
    value = (raw or "").lower()
    for kind in ("video", "image", "audio", "cut"):
        if kind in value:
            return kind
    return "image"


def _serialize(request: GenerationRequest) -> dict[str, Any]:
    """
    `GenerationRequest` → jsonb. Se guarda entera para poder reconstruir el job sin el
    contexto del turno que lo creó: el worker corre en otro proceso y, tras un reinicio,
    esta columna es lo único que queda de la intención original.
    """
    return _canonical(asdict(request))
