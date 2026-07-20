"""
Bus de eventos sobre Redis Streams.

Tres capas, como en el sandbox de PostHog (`ee/hogai/sandbox/`):

    worker / grafo  ──▶  Redis Stream (uno por conversación)  ──▶  SSE  ──▶  EditorChat

El motivo de meter Redis en medio en vez de que el generador del grafo alimente al SSE
directamente es la reconexión. Un render de doce planos dura minutos; el usuario cierra
el portátil, cambia de red o recarga. Si el flujo de eventos vive solo en la memoria de
un generador de Python, esa reconexión pierde todo lo ocurrido mientras tanto. Con un
stream persistido, reconectar es releer desde un `last_event_id`, y sale gratis.

El productor y el consumidor están desacoplados también en el tiempo: el worker publica
aunque no haya nadie escuchando. Es lo que permite que cerrar el navegador no cancele un
render que ya se ha pagado.

Dos detalles portados tal cual, que son los que hacen que esto no se rompa en producción:

1. **Timeout asimétrico.** Infinito en arranque en frío, 60 s de inactividad tras el
   primer dato. Un job encolado en Kling puede tardar minutos en emitir su primera señal;
   uno que ya emitió y lleva 60 s callado, ha terminado o ha muerto. Un único timeout no
   distingue esos dos casos y siempre está mal para uno de ellos.
2. **`wait_for` sobre una cola, no sobre el generador.** `asyncio.wait_for` aplicado a
   `__anext__()` cancela y cierra el generador asíncrono al expirar, y con él la conexión
   a Redis. Se lee en una tarea de fondo que empuja a una `asyncio.Queue` y el timeout se
   aplica a la cola, que sí se puede abandonar sin romper nada.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal
from uuid import UUID

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

EventType = Literal[
    "message_delta",
    "tool_start",
    "tool_progress",
    # Distinto de tool_progress: progress es "sigo trabajando", result es el valor
    # devuelto, con su ui_payload. El frontend los pinta de forma distinta.
    "tool_result",
    "asset_ready",
    "job_status",
    "interrupt_request",
    "error",
]

STREAM_TTL_S = 3600
"""
Caducidad del stream. Una conversación viva lo refresca en cada publicación; una muerta
se recoge sola. Sin esto, Redis acumularía un stream por conversación para siempre.
"""

IDLE_TIMEOUT_S = 60.0
"""Silencio tolerado **después** del primer evento. Antes del primero, no hay timeout."""

MAX_STREAM_LEN = 10_000
"""
Tope aproximado de entradas por conversación. `maxlen` con `approximate=True` porque el
recorte exacto obliga a Redis a trabajar en cada XADD y aquí no necesitamos precisión:
lo que sobra es historial que el cliente ya consumió.
"""

FIRST_EVENT_ID = "0-0"
"""Reconexión desde el principio del stream. `$` significa "solo lo que llegue nuevo"."""


class _Sentinel(enum.Enum):
    END = "end"


@dataclass(slots=True)
class StreamEvent:
    """
    Un evento tal y como lo ve el consumidor SSE.

    `id` es el identificador de Redis (`<ms>-<seq>`), y es lo que el cliente devuelve como
    `last_event_id` al reconectar. Es monótono y lo asigna Redis, así que no hace falta
    llevar un contador propio ni confiar en el reloj del productor.
    """

    id: str
    type: EventType
    data: dict[str, Any]
    ts: str

    def to_sse(self) -> str:
        """Serializa al formato del protocolo SSE, con `id:` para que el navegador reanude solo."""
        payload = json.dumps({"type": self.type, "data": self.data, "ts": self.ts}, ensure_ascii=False)
        return f"id: {self.id}\nevent: {self.type}\ndata: {payload}\n\n"


def stream_key(conversation_id: str | UUID) -> str:
    return f"xframe:conv:{conversation_id}"


class EventBus:
    """
    Productor y consumidor del stream de una conversación.

    Una sola instancia por proceso: el pool de `redis.asyncio` ya multiplexa, y crear un
    cliente por publicación agotaría los descriptores del worker en un fan-out grande.
    """

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client or aioredis.from_url(
            get_settings().redis_url, decode_responses=True
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- productor --------------------------------------------------------- #

    async def publish(
        self,
        conversation_id: str | UUID,
        event_type: EventType,
        data: dict[str, Any],
    ) -> str:
        """
        Publica un evento y devuelve su id.

        Nunca propaga el fallo de Redis. Es deliberado y conviene entenderlo antes de
        "arreglarlo": este bus transporta *progreso*, no *estado*. La verdad de un job
        vive en Postgres y en el storage. Si Redis se cae en mitad de un render, lo
        correcto es que el render termine y el usuario vea el resultado al recargar, no
        que el worker aborte —y haya que reembolsar— por un problema de la capa de avisos.
        """
        key = stream_key(conversation_id)
        fields = {
            "type": event_type,
            "data": json.dumps(data, ensure_ascii=False, default=str),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            event_id: str = await self._client.xadd(
                key, fields, maxlen=MAX_STREAM_LEN, approximate=True
            )
            await self._client.expire(key, STREAM_TTL_S)
            return event_id
        except Exception:  # noqa: BLE001
            logger.warning("bus_publish_failed", extra={"conversation_id": str(conversation_id)})
            return ""

    async def seed(self, conversation_id: str | UUID) -> str:
        """
        Crea el stream antes de que arranque el productor.

        Sin esto hay una carrera de manual: el SSE se suscribe a una clave que aún no
        existe, `XREAD` con `$` la resuelve como "desde ahora", y los primeros eventos —
        que en un turno corto pueden ser todos — se pierden. Sembrar es barato y elimina
        la clase entera de bug.
        """
        return await self.publish(conversation_id, "job_status", {"status": "stream_ready"})

    # -- consumidor -------------------------------------------------------- #

    async def latest_id(self, conversation_id: str | UUID) -> str:
        """
        Último id del stream. Se usa al mandar un mensaje de seguimiento: leer desde aquí
        evita reproducir los turnos anteriores en el chat del usuario.
        """
        try:
            entries = await self._client.xrevrange(stream_key(conversation_id), count=1)
            if entries:
                return entries[0][0]
        except Exception:  # noqa: BLE001
            logger.warning("bus_latest_id_failed", extra={"conversation_id": str(conversation_id)})
        return FIRST_EVENT_ID

    async def subscribe(
        self,
        conversation_id: str | UUID,
        *,
        last_event_id: str = FIRST_EVENT_ID,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
    ) -> AsyncIterator[StreamEvent]:
        """
        Itera los eventos de una conversación desde `last_event_id`, exclusivo.

        `last_event_id` por defecto es `0-0`, es decir, todo lo que quede en el stream.
        Un cliente que reconecta pasa el id del último evento que pintó y no ve
        duplicados; uno que solo quiere lo nuevo pasa el que devuelve `latest_id()`.

        Termina por inactividad (60 s sin nada **tras** haber visto algo) o cuando llega
        un evento de fin de turno. No termina por un stream vacío: eso es un turno que
        todavía no ha arrancado.
        """
        queue: asyncio.Queue[StreamEvent | _Sentinel] = asyncio.Queue()
        reader = asyncio.create_task(self._read_into(conversation_id, last_event_id, queue))
        saw_data = False

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=idle_timeout_s)
                except TimeoutError:
                    if saw_data:
                        logger.info(
                            "bus_idle_timeout", extra={"conversation_id": str(conversation_id)}
                        )
                        return
                    # Arranque en frío: el proveedor sigue en cola. Se sigue esperando.
                    continue

                if item is _Sentinel.END:
                    return

                saw_data = True
                yield item  # type: ignore[misc]
        finally:
            # Cubre tanto el fin normal como el `aclose()` que dispara el cliente SSE al
            # desconectar. Sin cancelar aquí, cada reload del navegador dejaría un lector
            # huérfano ocupando una conexión a Redis.
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _read_into(
        self,
        conversation_id: str | UUID,
        last_event_id: str,
        queue: asyncio.Queue[StreamEvent | _Sentinel],
    ) -> None:
        """
        Lector de fondo. Bloquea en `XREAD` y empuja a la cola; el timeout lo aplica quien
        consume la cola. El `block` de 5 s no es un timeout de negocio, solo permite que
        la tarea sea cancelable en un plazo razonable.
        """
        key = stream_key(conversation_id)
        cursor = last_event_id
        try:
            while True:
                batch = await self._client.xread({key: cursor}, count=64, block=5_000)
                if not batch:
                    continue
                for _key, entries in batch:
                    for event_id, fields in entries:
                        cursor = event_id
                        event = _parse(event_id, fields)
                        if event is None:
                            continue
                        await queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("bus_reader_failed", extra={"error": str(exc)})
            await queue.put(
                StreamEvent(
                    id=cursor,
                    type="error",
                    data={"message": "El canal de progreso se ha interrumpido. Recarga para continuar."},
                    ts=datetime.now(timezone.utc).isoformat(),
                )
            )
            await queue.put(_Sentinel.END)


def _parse(event_id: str, fields: dict[str, str]) -> StreamEvent | None:
    """
    Deserializa una entrada. Una entrada corrupta se descarta y no tumba el flujo:
    perder un evento de progreso es tolerable, cortar el stream del usuario no.
    """
    try:
        return StreamEvent(
            id=event_id,
            type=fields["type"],  # type: ignore[arg-type]
            data=json.loads(fields.get("data") or "{}"),
            ts=fields.get("ts", ""),
        )
    except Exception:  # noqa: BLE001
        logger.warning("bus_bad_entry", extra={"event_id": event_id})
        return None


_bus: EventBus | None = None


def get_bus() -> EventBus:
    """Singleton perezoso, en la línea de `db.pool()`."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
