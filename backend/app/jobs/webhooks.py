"""
Receptor de webhooks de proveedor.

Un webhook es un atajo, nunca la fuente de verdad. El polling del worker es el camino
que siempre funciona; el webhook solo sirve para enterarnos antes y ahorrar peticiones.
Todo lo de aquí está escrito desde esa premisa, y de ella salen las tres reglas duras:

1. **Sin firma verificada, el cuerpo no tiene autoridad.** Este endpoint es público —el
   proveedor no tiene el JWT del usuario ni puede tenerlo— y su efecto secundario es mover
   dinero: creerse un cuerpo no firmado permite a cualquiera declarar `succeeded` un job y
   provocar un cobro, o `failed` uno bueno y provocar un reembolso. `verify_signature`
   devuelve si la entrega está autenticada, y solo entonces se lee la carga útil; si no,
   se reconsulta con `poll()`. La distinción entre "firma correcta" y "no hay secreto
   configurado" es lo que este módulo se dejaba antes, con seis de los ocho proveedores
   cayendo en el segundo caso.

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
import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.db import transaction
from app.jobs import credits
from app.providers.base import AdapterRegistry, ProviderJobRef, ProviderJobStatus
from app.providers.registry import UnknownProviderError
from app.stream.bus import EventBus, get_bus

logger = logging.getLogger(__name__)

TERMINAL_STATES: tuple[str, ...] = ("succeeded", "failed", "cancelled", "nsfw")

DEDUP_TTL_S = 7_200
"""Dos horas: cubre la ventana de reintentos más larga que conocemos (fal)."""

OWNER_LEASE_S = 900
"""
Cuánto tiempo se le concede a un worker la propiedad de un job desde su último latido.

Es la marca de propiedad que le faltaba al camino de éxito del webhook. Un job con
`provider_ref` escrito y `updated_at` fresco **tiene dueño**: hay un worker vivo
poleándolo que va a descargar el binario y cerrarlo. Reponerlo a `queued` en ese estado
es ofrecérselo a un segundo worker, y el segundo `submit()` lo genera y lo factura otra
vez (~$21 por job en Seedance 4K).

El valor sale del intervalo de polling, no de la duración del render: mientras el worker
vive, cada poll con cambio de progreso refresca `updated_at`. Quince minutos es holgura
de sobra sobre cualquier intervalo de poll, y queda muy por debajo de `STALE_AFTER_S`
(una hora), así que un job cuya propiedad ha caducado se puede reasignar bastante antes
de que el barrido lo dé por muerto y lo reembolse.
"""


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

    Tres orígenes, del más específico al más general: la credencial propia del proveedor
    cuando ya la tenemos y es la que él usa para firmar (Higgsfield, Kling), el secreto
    que **nosotros** le mandamos en el submit (BFL), y el mapa `WEBHOOK_SECRETS` para
    cualquier otro que se configure sin tocar código.

    Devolver `None` significa "este proveedor no firma **aquí**". Lo que sigue de eso no
    es que la verificación se salte, sino que la entrega **no tiene autoridad**: ver
    `verify_signature` y `_resolve_status`.
    """
    settings = get_settings()
    known = {
        "higgsfield": settings.higgsfield_key_secret or None,
        "kling": settings.kling_secret_key or None,
        "bfl": settings.bfl_webhook_secret or None,
    }
    if secret := known.get(provider):
        return secret
    return _configured_secrets().get(provider)


def _configured_secrets() -> dict[str, str]:
    """`WEBHOOK_SECRETS=proveedor=secreto,otro=secreto` → dict. Entradas rotas: se ignoran."""
    parsed: dict[str, str] = {}
    for chunk in get_settings().webhook_secrets.split(","):
        name, sep, secret = chunk.partition("=")
        if sep and name.strip() and secret.strip():
            parsed[name.strip()] = secret.strip()
    return parsed


def verify_signature(provider: str, headers: Mapping[str, str], body: bytes) -> bool:
    """
    HMAC-SHA256 del cuerpo crudo contra la cabecera de firma.

    Devuelve **si la entrega está autenticada**, y ese booleano es la pieza que faltaba.
    Antes esta función hacía `return` sin más cuando no había secreto configurado —seis
    de los ocho proveedores— y el llamante no podía distinguir "firma correcta" de "no
    se ha comprobado nada". El resultado es que un cuerpo anónimo recorría exactamente el
    mismo camino que uno firmado, incluido `parse_webhook`, que traduce el cuerpo a un
    estado terminal. Cualquiera con la URL podía declarar `failed` un job ajeno y
    dispararle un reembolso.

    Ahora el contrato es: `True` = firmado y verificado, el cuerpo se puede creer.
    `False` = sin secreto configurado, la entrega solo vale como *señal* de "mira este
    job", y quien decide es `poll()`. Lo que nunca devuelve es `False` por una firma
    incorrecta: eso lanza.

    Sobre el cuerpo **crudo**, nunca sobre el JSON reserializado: cualquier diferencia de
    espaciado u orden de claves cambiaría el digest y haría fallar entregas legítimas.

    `compare_digest` y no `==`: la comparación byte a byte con salida temprana filtra por
    tiempo cuántos caracteres del prefijo eran correctos, y eso permite reconstruir una
    firma válida a base de intentos.
    """
    secret = _secret_for(provider)
    if not secret:
        logger.info("webhook_unsigned_provider", extra={"provider": provider})
        return False

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
    return True


def callback_url(provider: str) -> str | None:
    """
    URL que se le pasa al proveedor para que nos avise, o `None` si no tiene sentido.

    Se construye sobre `PUBLIC_BASE_URL` porque el proveedor llama desde internet: si eso
    apunta a `localhost` —el valor por defecto, y lo normal en desarrollo— no hay callback
    que valga y se devuelve `None` en vez de mandarle una URL que no puede resolver y
    provocarle reintentos inútiles durante dos horas.

    El `?t=` es el token de `WEBHOOK_PATH_TOKEN`. Va en la URL y no en una cabecera
    porque es lo único que estos proveedores nos dejan controlar del lado de la llamada
    entrante. No es autenticación de verdad (una URL acaba en logs), pero convierte la
    ruta pública en algo que hay que conocer, y eso es lo que impide que un tercero venga
    a pedir que releamos jobs ajenos.
    """
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    if not base or "localhost" in base or "127.0.0.1" in base:
        return None
    url = f"{base}/webhooks/{provider}"
    if settings.webhook_path_token:
        url = f"{url}?t={settings.webhook_path_token}"
    return url


def verify_path_token(token: str | None) -> None:
    """
    Comprueba el token de la URL de callback, si hay uno configurado.

    Sin token configurado no se exige nada: activar esto obliga a re-registrar las URLs
    en los proveedores que las tengan guardadas, y un despliegue que lo active a medias
    dejaría de recibir webhooks en silencio. Con token, se compara en tiempo constante
    por el mismo motivo que la firma.
    """
    expected = get_settings().webhook_path_token
    if not expected:
        return
    if not token or not hmac.compare_digest(expected, token):
        raise WebhookRejected("token de callback inválido")


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
        trusted = verify_signature(provider, headers, body)

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

        status = await self._resolve_status(provider, payload, job, trusted=trusted)
        if not status.is_terminal:
            await self._note_progress(job, status)
            return WebhookOutcome(job_id=str(job["id"]), applied=True, state=status.state)

        return await self._apply_terminal(job, status)

    # -- resolución del estado --------------------------------------------- #

    async def _resolve_status(
        self, provider: str, payload: dict[str, Any], job: Any, *, trusted: bool
    ) -> ProviderJobStatus:
        """
        Estado real del trabajo.

        `trusted` es lo que decide, y es el arreglo del agujero que tenía este módulo.
        Solo cuando la entrega venía firmada **y** la firma se comprobó se le hace caso al
        cuerpo a través de `parse_webhook`. Si no —que hoy es el caso de la mayoría de
        proveedores, porque no hay secreto configurado para ellos— la carga útil se
        ignora entera y se le pregunta al proveedor con `poll()`.

        Reconsultar es más lento y cuesta una petición, y es exactamente el precio que
        hay que pagar: sin firma, el cuerpo lo ha escrito quien sea, y creerle significa
        dejar que un desconocido declare `failed` un job vivo (reembolso indebido, plano
        perdido) o `succeeded` uno que no lo está. `poll()` es barato e idempotente por
        contrato, así que la entrega falsificada acaba resolviéndose contra la realidad y
        lo peor que consigue el atacante es que hagamos una petición de más.
        """
        adapter = self._registry.get(provider)
        parse = getattr(adapter, "parse_webhook", None)
        if trusted and callable(parse):
            return await parse(payload)  # type: ignore[no-any-return]
        if callable(parse):
            logger.info("webhook_body_ignored_unsigned", extra={"provider": provider})

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

        El caso de éxito **no** se cierra aquí: la descarga del binario y la subida al
        storage son trabajo de red pesado y no caben en el manejador de un webhook, que
        debe responder en milisegundos o el proveedor lo dará por fallido y lo
        reintentará. Eso lo hace el worker.

        Pero "lo hace el worker" no significa "hay que devolverlo a la cola". Reponer a
        `queued` un job que **ya tiene dueño** es el peor bug de dinero que ha tenido
        este backend: el worker que lo está poleando sigue vivo y va a cerrarlo él, y
        además `_claim` lo vuelve a coger desde cero, llama a `submit()` por segunda vez
        y el proveedor genera y factura dos veces el mismo plano. El usuario reservó uno.

        La distinción que faltaba es la propiedad, y se decide con dos datos que ya
        estaban en la fila: hay `provider_ref` (alguien llegó a enviar el trabajo) y el
        `updated_at` es reciente (ese alguien sigue latiendo). Si hay dueño, el webhook
        se limita a anotar el progreso — su único trabajo útil aquí es informativo — y el
        worker cierra el job en su siguiente poll, que ya verá el estado terminal.

        Solo si **no** hay dueño (el worker murió tras enviar, o murió antes de escribir
        la referencia) se repone a `queued`, que es cuando reponer es justamente lo que
        rescata un render ya pagado al proveedor.

        El caso de fallo sí se cierra aquí, porque no hay nada que descargar y cuanto
        antes vuelva el crédito al usuario, mejor.
        """
        job_id: UUID = job["id"]

        if not status.should_refund:
            async with transaction() as conn:
                requeued = await conn.fetchval(
                    """
                    update public.generation_jobs
                       set status = 'queued', progress = 1, updated_at = now()
                     where id = $1
                       and status not in ('succeeded','failed','cancelled','nsfw')
                       and (
                             provider_ref is null
                          or provider_ref->>'external_id' is null
                          or updated_at < now() - ($2 || ' seconds')::interval
                       )
                    returning id
                    """,
                    job_id,
                    str(OWNER_LEASE_S),
                )
                if requeued is None:
                    # Tiene dueño vivo (o ya es terminal). Se anota el progreso y nada
                    # más: no se toca `status` ni `updated_at`. Refrescar el latido aquí
                    # sería peor que inútil — mantendría viva la propiedad de un worker
                    # muerto a base de reintentos del proveedor, y el job no se
                    # reasignaría nunca.
                    await conn.execute(
                        """
                        update public.generation_jobs
                           set progress = 1
                         where id = $1 and status not in ('succeeded','failed','cancelled','nsfw')
                        """,
                        job_id,
                    )
                    logger.info("webhook_success_owned", extra={"job_id": str(job_id)})
                    return WebhookOutcome(
                        job_id=str(job_id),
                        applied=False,
                        state="succeeded",
                        reason="job con dueño; lo cierra el worker",
                    )
            logger.info("webhook_success_requeued", extra={"job_id": str(job_id)})
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
    """
    Localiza el job por `(proveedor, id externo)`.

    No filtra por proyecto y **no puede hacerlo**: el proveedor no sabe nada de nuestros
    proyectos y la URL de callback es la misma para todos. Eso significa que esta consulta
    alcanza jobs de cualquier usuario, y hay que decir con precisión qué implica y qué no.

    Lo que **no** permite: leer nada de un job ajeno. No se devuelve ni un dato al
    llamante. El endpoint contesta lo mismo —202 y un cuerpo fijo— exista el job o no, así
    que no hay oráculo con el que enumerar. Ese era el riesgo real: no la falta del filtro,
    sino que la respuesta cambiara según el resultado.

    Lo que sí permite, y por eso hay dos capas más: gastar una consulta y quizá un `poll()`
    por cada petición. Contra eso están el token de la URL (`verify_path_token`) y el hecho
    de que `external_id` lo genera el proveedor y no es adivinable. Y sobre el efecto: sin
    firma, encontrar el job no cambia nada por sí solo, porque el veredicto lo pone
    `poll()` contra el proveedor.
    """
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


# --------------------------------------------------------------------------- #
# Ruta HTTP                                                                    #
# --------------------------------------------------------------------------- #

MAX_BODY_BYTES = 1 * 1024 * 1024
"""
Un megabyte. Ninguna notificación legítima se acerca —son unos cientos de bytes de JSON—
y el endpoint es público y sin autenticar antes de leer el cuerpo, así que sin tope
cualquiera puede hacernos reservar memoria a voluntad.
"""

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
"""
Router de las notificaciones de proveedor.

Se monta en `main.py`. Hasta ahora este módulo existía entero y no lo llamaba nadie: todo
dependía del polling, que funciona pero tarda más y multiplica las peticiones contra el
proveedor.
"""

ACCEPTED: dict[str, str] = {"status": "accepted"}
"""
La **única** respuesta de éxito, idéntica en todos los casos.

Devolver aquí el `WebhookOutcome` sería cómodo para depurar y convertiría el endpoint en
un oráculo: "job desconocido" frente a "ya terminal" le dice a quien pruebe identificadores
cuáles existen y en qué estado están. El detalle va al log, que es donde se depura.
"""


def _receiver() -> WebhookReceiver:
    from app.providers.registry import get_registry

    return WebhookReceiver(registry=get_registry())


@router.post("/{provider}", status_code=202)
async def receive_webhook(provider: str, request: Request) -> dict[str, str]:
    """
    Notificación de un proveedor.

    **Esta ruta es pública a propósito**: el proveedor llama desde su infraestructura y no
    tiene ni puede tener el JWT del usuario. La autenticación es la firma del cuerpo, no
    una sesión. Por eso no lleva `Depends(current_user)`, y por eso lo que decide qué
    puede hacer una entrega es `verify_signature`, no el hecho de haber llegado hasta
    aquí.

    Códigos, elegidos por cómo reacciona el proveedor a cada uno:

    - `202` en todo lo que no sea una firma mala, incluido "no conozco ese job". Un job
      desconocido es normal: el proveedor puede notificar antes de que el worker haya
      escrito el `provider_ref`. Contestarle 404 le haría reintentar dos horas algo que
      el polling ya está resolviendo.
    - `401` solo ante firma o token inválidos. Es lo único que el proveedor no debe
      reintentar nunca.
    - `413` si el cuerpo se pasa de tamaño.
    - Nunca un 5xx por una causa esperada: un 5xx es una invitación a reintentar.
    """
    verify_path_token(request.query_params.get("t"))

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(413, "cuerpo demasiado grande")

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "cuerpo demasiado grande")

    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        # Sin JSON no hay identificador de trabajo que extraer. 400 y no 5xx: reintentar
        # el mismo cuerpo malformado daría el mismo resultado.
        raise HTTPException(400, "cuerpo no es JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "cuerpo no es un objeto JSON")

    try:
        outcome = await _receiver().handle(
            provider, headers=dict(request.headers), body=body, payload=payload
        )
    except WebhookRejected as exc:
        logger.warning("webhook_rejected", extra={"provider": provider, "reason": str(exc)})
        raise HTTPException(401, "webhook rechazado") from exc
    except UnknownProviderError as exc:
        # Qué proveedores existen no es secreto —están en el catálogo público de modelos—
        # así que un 404 aquí no filtra nada y ayuda a detectar una URL mal registrada.
        raise HTTPException(404, "proveedor desconocido") from exc

    logger.info(
        "webhook_handled",
        extra={
            "provider": provider,
            "job_id": outcome.job_id,
            "applied": outcome.applied,
            "reason": outcome.reason,
        },
    )
    return ACCEPTED
