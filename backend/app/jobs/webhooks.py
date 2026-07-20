"""
Receptor de webhooks de proveedor.

Un webhook es un atajo, nunca la fuente de verdad. El polling del worker es el camino
que siempre funciona; el webhook solo sirve para enterarnos antes y ahorrar peticiones.
Todo lo de aquí está escrito desde esa premisa, y de ella salen las tres reglas duras:

1. **La firma se verifica siempre que el proveedor la ofrezca.** Este endpoint es
   público y su efecto secundario es mover dinero: aceptar un cuerpo no firmado permite a
   cualquiera declarar `succeeded` un job y provocar un cobro, o `failed` uno bueno y
   provocar un reembolso.

2. **Un webhook tardío jamás revierte un estado terminal.** Los webhooks se reintentan
   (fal, hasta 10 veces en 2 horas) y llegan desordenados. Es perfectamente normal recibir
   un `running` después del `succeeded` que ya cerró el job. La guarda no está en comparar
   marcas de tiempo — el reloj del proveedor no es de fiar — sino en una condición
   sintáctica: si el job ya está en un estado terminal, no se toca.

3. **El cuerpo del webhook no decide nada por sí solo.** Cuando el adaptador no expone un
   parseo propio, se ignora la carga útil y se le pregunta al proveedor con `poll()`, que
   es barato e idempotente por contrato. Así una entrega duplicada, desordenada o
   falsificada acaba resolviéndose contra el estado real.

La deduplicación por id de entrega es una optimización sobre lo anterior: evita trabajo
repetido, pero la corrección ya está garantizada por la guarda de estado terminal. Por
eso, si Redis no está disponible, se sigue adelante sin dedup en vez de rechazar la
entrega.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from app.config import get_settings
from app.db import transaction
from app.jobs import credits
from app.providers.base import AdapterRegistry, ProviderJobRef, ProviderJobStatus
from app.stream.bus import EventBus, get_bus

logger = logging.getLogger(__name__)

TERMINAL_STATES: tuple[str, ...] = ("succeeded", "failed", "cancelled", "nsfw")

DEDUP_TTL_S = 7_200
"""Dos horas: cubre la ventana de reintentos más larga que conocemos (fal)."""


class WebhookRejected(Exception):
    """
    Firma inválida o job desconocido. El endpoint HTTP debe traducirlo a 401/404 y
    **no** a 5xx: un 5xx invita al proveedor a reintentar algo que nunca va a aceptarse.
    """


@dataclass(slots=True)
class WebhookOutcome:
    """Qué se hizo con la entrega. `applied=False` cubre duplicados y llegadas tardías."""

    job_id: str | None
    applied: bool
    state: str | None = None
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Firmas                                                                       #
# --------------------------------------------------------------------------- #


def _secret_for(provider: str) -> str | None:
    """
    Secreto de firma por proveedor.

    Devolver `None` significa "este proveedor no firma", y entonces la verificación se
    salta. Es un agujero conocido y acotado: se compensa con que el estado real se
    reconsulta con `poll()` y con la guarda de terminalidad, de modo que lo peor que
    consigue un atacante es forzarnos a hacer una petición de más al proveedor.
    """
    settings = get_settings()
    return {
        "higgsfield": settings.higgsfield_key_secret or None,
        "kling": settings.kling_secret_key or None,
    }.get(provider)


def verify_signature(provider: str, headers: Mapping[str, str], body: bytes) -> None:
    """
    HMAC-SHA256 del cuerpo crudo contra la cabecera de firma.

    Sobre el cuerpo **crudo**, nunca sobre el JSON reserializado: cualquier diferencia de
    espaciado u orden de claves cambiaría el digest y haría fallar entregas legítimas.

    `compare_digest` y no `==`: la comparación byte a byte con salida temprana filtra por
    tiempo cuántos caracteres del prefijo eran correctos, y eso permite reconstruir una
    firma válida a base de intentos.
    """
    secret = _secret_for(provider)
    if not secret:
        return

    lowered = {k.lower(): v for k, v in headers.items()}
    received = (
        lowered.get("x-webhook-signature")
        or lowered.get("x-signature")
        or lowered.get("x-hub-signature-256")
        or ""
    ).removeprefix("sha256=")

    if not received:
        raise WebhookRejected(f"webhook de '{provider}' sin cabecera de firma")

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise WebhookRejected(f"firma inválida en webhook de '{provider}'")


# --------------------------------------------------------------------------- #
# Recepción                                                                    #
# --------------------------------------------------------------------------- #


class WebhookReceiver:
    """
    Punto de entrada de las notificaciones de proveedor.

    Depende del mismo `AdapterRegistry` que el worker: quien sabe leer el dialecto de un
    proveedor es su adaptador, y aquí solo se orquesta.
    """

    def __init__(
        self,
        *,
        registry: AdapterRegistry,
        bus: EventBus | None = None,
        redis: Any | None = None,
    ) -> None:
        self._registry = registry
        self._bus = bus or get_bus()
        self._redis = redis

    async def handle(
        self,
        provider: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        payload: dict[str, Any],
    ) -> WebhookOutcome:
        """
        Procesa una entrega. Nunca lanza por causas normales (duplicado, tardío, job ya
        cerrado): devuelve `applied=False`. Solo lanza `WebhookRejected`, que es lo único
        que el proveedor no debe reintentar.
        """
        verify_signature(provider, headers, body)

        external_id = _external_id(payload)
        if not external_id:
            raise WebhookRejected(f"webhook de '{provider}' sin identificador de trabajo")

        delivery = _delivery_id(headers, payload, body)
        if await self._seen(provider, delivery):
            logger.info("webhook_duplicate", extra={"provider": provider, "delivery": delivery})
            return WebhookOutcome(job_id=None, applied=False, reason="duplicado")

        job = await self._find_job(provider, external_id)
        if job is None:
            # Puede ser legítimo: el worker aún no ha guardado el `provider_ref` cuando el
            # proveedor ya está notificando. No es un error, y el polling lo resolverá.
            logger.info(
                "webhook_unknown_job", extra={"provider": provider, "external": external_id}
            )
            return WebhookOutcome(job_id=None, applied=False, reason="job desconocido")

        if job["status"] in TERMINAL_STATES:
            logger.info("webhook_late", extra={"job_id": str(job["id"]), "status": job["status"]})
            return WebhookOutcome(job_id=str(job["id"]), applied=False, reason="ya terminal")

        status = await self._resolve_status(provider, payload, job)
        if not status.is_terminal:
            await self._note_progress(job, status)
            return WebhookOutcome(job_id=str(job["id"]), applied=True, state=status.state)

        return await self._apply_terminal(job, status)

    # -- resolución del estado --------------------------------------------- #

    async def _resolve_status(
        self, provider: str, payload: dict[str, Any], job: Any
    ) -> ProviderJobStatus:
        """
        Estado real del trabajo.

        Si el adaptador expone `parse_webhook`, se usa su lectura del cuerpo. Si no,
        se le pregunta al proveedor con `poll()`. La segunda vía es más lenta pero
        inmune a cuerpos falsificados o desordenados, así que es el defecto correcto:
        un adaptador solo debe implementar `parse_webhook` si además verifica firma.
        """
        adapter = self._registry.get(provider)
        parse = getattr(adapter, "parse_webhook", None)
        if callable(parse):
            return await parse(payload)  # type: ignore[no-any-return]

        raw_ref = job["provider_ref"] or {}
        ref = ProviderJobRef(
            provider=provider,
            external_id=raw_ref.get("external_id", ""),
            poll_url=raw_ref.get("poll_url"),
        )
        return await adapter.poll(ref)

    # -- aplicación --------------------------------------------------------- #

    async def _note_progress(self, job: Any, status: ProviderJobStatus) -> None:
        """Actualiza progreso sin tocar el estado. Un webhook intermedio no cierra nada."""
        async with transaction() as conn:
            await conn.execute(
                """
                update public.generation_jobs
                   set progress = coalesce($2, progress), status = 'running', updated_at = now()
                 where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                """,
                job["id"],
                status.progress,
            )
        if job["conversation_id"]:
            await self._bus.publish(
                job["conversation_id"],
                "tool_progress",
                {"job_id": str(job["id"]), "shot_id": job["shot_id"], "progress": status.progress},
            )

    async def _apply_terminal(self, job: Any, status: ProviderJobStatus) -> WebhookOutcome:
        """
        Cierra el job por la vía del webhook.

        El caso de éxito **no** se cierra aquí: se marca `queued` de nuevo para que el
        worker recoja el job, descargue el binario y lo suba al storage. Esa parte es
        trabajo de red pesado y no cabe en el manejador de un webhook, que debe responder
        en milisegundos o el proveedor lo dará por fallido y lo reintentará. El webhook,
        en el camino feliz, solo sirve para acortar la espera del siguiente poll.

        El caso de fallo sí se cierra aquí, porque no hay nada que descargar y cuanto
        antes vuelva el crédito al usuario, mejor.
        """
        job_id: UUID = job["id"]

        if not status.should_refund:
            async with transaction() as conn:
                await conn.execute(
                    """
                    update public.generation_jobs
                       set status = 'queued', progress = 1, updated_at = now()
                     where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                    """,
                    job_id,
                )
            return WebhookOutcome(job_id=str(job_id), applied=True, state="succeeded")

        async with transaction() as conn:
            updated = await conn.fetchval(
                """
                update public.generation_jobs
                   set status = $2, error = $3, updated_at = now(), finished_at = now()
                 where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                returning id
                """,
                job_id,
                status.state,
                {"message": status.error or f"el proveedor terminó en {status.state}"},
            )
            if updated is None:
                # Carrera con el poll del worker: llegó primero y ya cerró. Correcto.
                return WebhookOutcome(job_id=str(job_id), applied=False, reason="ya terminal")

            await credits.refund(job_id=job_id, reason=f"webhook {status.state}", conn=conn)
            await conn.execute(
                "update public.assets set status = 'failed' where job_id = $1 and status = 'generating'",
                job_id,
            )

        if job["conversation_id"]:
            await self._bus.publish(
                job["conversation_id"],
                "error",
                {
                    "job_id": str(job_id),
                    "shot_id": job["shot_id"],
                    "status": status.state,
                    "message": status.error,
                    "refunded": True,
                },
            )
        logger.info("webhook_terminal", extra={"job_id": str(job_id), "state": status.state})
        return WebhookOutcome(job_id=str(job_id), applied=True, state=status.state)

    # -- deduplicación ------------------------------------------------------ #

    async def _seen(self, provider: str, delivery: str) -> bool:
        """
        `SET NX EX` como marca de "ya visto". Atómico, así que dos entregas simultáneas de
        la misma notificación no pasan las dos.

        Si Redis falla se devuelve `False` (procesar). Perder la dedup solo cuesta trabajo
        repetido; rechazar entregas porque la caché está caída cuesta jobs que se quedan
        colgados hasta que el polling los recoge.
        """
        client = self._redis or _redis_client()
        if client is None:
            return False
        try:
            stored = await client.set(
                f"xframe:webhook:{provider}:{delivery}", "1", nx=True, ex=DEDUP_TTL_S
            )
            return not bool(stored)
        except Exception:  # noqa: BLE001
            logger.warning("webhook_dedup_unavailable", extra={"provider": provider})
            return False

    async def _find_job(self, provider: str, external_id: str) -> Any | None:
        return await _fetch_job(provider, external_id)


# --------------------------------------------------------------------------- #
# Auxiliares                                                                   #
# --------------------------------------------------------------------------- #


async def _fetch_job(provider: str, external_id: str) -> Any | None:
    async with transaction() as conn:
        return await conn.fetchrow(
            """
            select id, status, provider, provider_ref, shot_id, project_id,
                   conversation_id, credits_reserved, model_id
              from public.generation_jobs
             where provider = $1 and provider_ref->>'external_id' = $2
             order by created_at desc
             limit 1
            """,
            provider,
            external_id,
        )


def _external_id(payload: Mapping[str, Any]) -> str | None:
    """
    Identificador del trabajo en el proveedor. Cada uno lo llama de una forma; se prueban
    los nombres conocidos en vez de exigir un adaptador solo para leer una clave.
    """
    for key in ("request_id", "job_id", "id", "task_id", "generation_id"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    data = payload.get("data")
    if isinstance(data, Mapping):
        return _external_id(data)
    return None


def _delivery_id(headers: Mapping[str, str], payload: Mapping[str, Any], body: bytes) -> str:
    """
    Identidad de **esta entrega concreta**, no del trabajo.

    Si el proveedor manda una cabecera de id de entrega, se usa. Si no, se hashea el
    cuerpo: dos reintentos de la misma notificación tienen cuerpo idéntico, mientras que
    una notificación distinta del mismo trabajo (running → succeeded) no. Un id de entrega
    basado solo en el id del trabajo descartaría transiciones legítimas.
    """
    lowered = {k.lower(): v for k, v in headers.items()}
    for key in ("x-delivery-id", "x-webhook-id", "x-request-id", "idempotency-key"):
        if lowered.get(key):
            return lowered[key]
    return hashlib.sha256(body).hexdigest()[:32]


def _redis_client() -> Any | None:
    try:
        import redis.asyncio as aioredis

        return aioredis.from_url(get_settings().redis_url, decode_responses=True)
    except Exception:  # noqa: BLE001
        return None
