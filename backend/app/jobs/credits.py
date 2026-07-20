"""
Libro mayor de créditos.

Append-only, sin excepciones. El saldo es `SUM(amount)` sobre `credit_ledger`, nunca un
contador que se actualiza. La razón no es estética: un contador mutable pierde el *por
qué* de cada movimiento, y cuando un usuario reclama que le hemos cobrado un plano que
salió con la cara mal, sin libro mayor no hay forma de responderle. Con libro mayor, la
respuesta es una consulta.

Ciclo de vida de un job, tal y como lo fija la sección 10 de la arquitectura:

    reservar  →  confirmar  →  (o reembolsar)

Cómo se traduce eso a filas, que es la parte que hay que entender antes de tocar nada:

- `reserve` escribe **el débito completo** con signo negativo. El dinero sale del saldo
  en el momento de encolar, no al terminar. Así, mientras el job corre, el usuario no
  puede gastarse dos veces lo mismo abriendo dos pestañas.
- `charge` escribe **solo el delta** `reservado - final`. Si el coste real coincidió con
  la estimación, el delta es 0 y la fila queda como constancia de que el cobro se
  confirmó. Si el proveedor cobró menos, el delta es positivo y devuelve la diferencia.
- `refund` escribe `+reservado`, dejando el neto del job en 0.

Invariante que se deduce de lo anterior: la suma de las filas de un job es exactamente
`-coste_final`, y es 0 si el job no llegó a producir nada. Es comprobable con una sola
consulta, y por eso los tests lo comprueban.

La concurrencia se resuelve con `SELECT ... FOR UPDATE` sobre la fila de `profiles`. El
perfil no se lee porque nos interese su contenido: se lee para **tomar el cerrojo** que
serializa a todos los que gastan del mismo saldo. Sin eso, dos peticiones simultáneas
leen el mismo saldo, ambas lo consideran suficiente, y ambas encolan.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import Literal
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.db import transaction
from app.tools.errors import InsufficientCreditsError

logger = logging.getLogger(__name__)

LedgerKind = Literal["grant", "reserve", "charge", "refund", "expire"]

TERMINAL_LEDGER_KINDS: tuple[LedgerKind, ...] = ("charge", "refund")
"""
Cierres de un job. Que ya exista uno es la señal de que el job está liquidado, y es lo
que hace que `charge()` y `refund()` sean idempotentes: un webhook duplicado los vuelve
a llamar, y la segunda llamada no mueve dinero.
"""


# --------------------------------------------------------------------------- #
# Conversión USD → créditos                                                    #
# --------------------------------------------------------------------------- #


def usd_to_credits(cost_usd: Decimal) -> int:
    """
    Convierte el coste de API a créditos de cliente aplicando el margen.

    Se redondea **hacia arriba**: el rango de coste entre modelos es de 30x, y con
    fracciones de crédito perdidas en cada job el error se acumula siempre en nuestra
    contra. Un crédito de más por job es ruido; medio crédito de menos por job, a escala,
    no lo es.

    El mínimo es 1: un job que se cobra a 0 créditos es un job que se puede repetir
    infinitas veces gratis contra una API que sí nos cobra.
    """
    settings = get_settings()
    raw = Decimal(cost_usd) * Decimal(settings.credits_per_usd) * Decimal(str(settings.credit_margin))
    return max(1, math.ceil(raw))


# --------------------------------------------------------------------------- #
# Lectura                                                                      #
# --------------------------------------------------------------------------- #


async def balance(profile_id: str | UUID, *, conn: asyncpg.Connection | None = None) -> int:
    """
    Saldo actual = suma del libro. Nunca se lee de `profiles.credits`.

    `profiles.credits` existe desde antes que el agente y lo sigue leyendo el frontend,
    así que se mantiene sincronizado como espejo (ver `_mirror_profile_credits`), pero
    **no es la fuente de verdad** y no debe usarse para decidir si se puede gastar.
    """
    q = "select coalesce(sum(amount), 0)::int from public.credit_ledger where profile_id = $1"
    if conn is not None:
        return int(await conn.fetchval(q, _uuid(profile_id)))
    async with transaction() as tx:
        return int(await tx.fetchval(q, _uuid(profile_id)))


async def job_net(job_id: str | UUID, *, conn: asyncpg.Connection | None = None) -> int:
    """
    Neto del libro para un job. Debe ser `-coste_final`, o 0 si se reembolsó.

    Existe para los tests y para auditoría; ninguna decisión de negocio depende de ella.
    """
    q = "select coalesce(sum(amount), 0)::int from public.credit_ledger where job_id = $1"
    if conn is not None:
        return int(await conn.fetchval(q, _uuid(job_id)))
    async with transaction() as tx:
        return int(await tx.fetchval(q, _uuid(job_id)))


# --------------------------------------------------------------------------- #
# Escritura                                                                    #
# --------------------------------------------------------------------------- #


async def reserve(
    *,
    project_id: str | UUID,
    amount: int,
    job_id: str | UUID | None = None,
    note: str | None = None,
    conn: asyncpg.Connection | None = None,
) -> int:
    """
    Retiene `amount` créditos del saldo del dueño del proyecto. Devuelve el saldo tras
    la reserva.

    Lanza `InsufficientCreditsError` si no hay saldo. Es un error fatal a propósito:
    reintentar no crea créditos, y queremos que el agente se lo diga al usuario en vez
    de insistir contra una API de pago.

    Debe ejecutarse dentro de una transacción que ya tenga el cerrojo del perfil. Si se
    llama sin `conn`, abre la suya y lo toma ella. La firma admite ambas porque
    `queue.enqueue()` necesita reservar **y** insertar el job en el mismo átomo: un job
    insertado sin reserva es un job gratis, y una reserva sin job es dinero congelado
    que nadie va a liberar.
    """
    if amount < 0:
        raise ValueError("reserve() no admite importes negativos; para devolver usa refund()")

    if conn is not None:
        return await _reserve_locked(conn, project_id, amount, job_id, note)
    async with transaction() as tx:
        return await _reserve_locked(tx, project_id, amount, job_id, note)


async def _reserve_locked(
    conn: asyncpg.Connection,
    project_id: str | UUID,
    amount: int,
    job_id: str | UUID | None,
    note: str | None,
) -> int:
    profile_id = await lock_project_owner(conn, project_id)
    available = await _balance_bootstrapped(conn, profile_id)

    if available < amount:
        # No se escribe nada en el libro: un intento fallido no es un movimiento.
        raise InsufficientCreditsError(needed=amount, available=available)

    return await _append(
        conn,
        profile_id=profile_id,
        project_id=project_id,
        job_id=job_id,
        kind="reserve",
        amount=-amount,
        balance_before=available,
        note=note,
    )


async def charge(
    *,
    job_id: str | UUID,
    final_credits: int,
    note: str | None = None,
    conn: asyncpg.Connection | None = None,
) -> int:
    """
    Confirma el cobro de un job y libera la diferencia con lo reservado.

    Idempotente: si el job ya tiene un cierre en el libro, no hace nada y devuelve el
    saldo actual. Esta propiedad no es un extra — los webhooks de fal reintentan hasta
    10 veces en 2 horas, y sin idempotencia cada reintento cobraría otra vez.
    """
    if conn is not None:
        return await _settle(conn, job_id, "charge", final_credits, note)
    async with transaction() as tx:
        return await _settle(tx, job_id, "charge", final_credits, note)


async def refund(
    *,
    job_id: str | UUID,
    reason: str | None = None,
    conn: asyncpg.Connection | None = None,
) -> int:
    """
    Devuelve íntegra la reserva de un job que no produjo nada.

    Se llama cuando `ProviderJobStatus.should_refund` es cierto, es decir en `failed`,
    `nsfw` y `cancelled`. Higgsfield reembolsa en los dos primeros, pero no todos los
    proveedores lo hacen: si no lo modelamos aquí, al usuario le cobramos un vídeo que
    no existe y el dinero se pierde en silencio.

    Idempotente por la misma razón que `charge()`.
    """
    if conn is not None:
        return await _settle(conn, job_id, "refund", 0, reason)
    async with transaction() as tx:
        return await _settle(tx, job_id, "refund", 0, reason)


async def _settle(
    conn: asyncpg.Connection,
    job_id: str | UUID,
    kind: Literal["charge", "refund"],
    final_credits: int,
    note: str | None,
) -> int:
    """
    Liquida un job. Cierre único: charge y refund son mutuamente excluyentes.

    El orden importa. Primero se toma el cerrojo del perfil, y solo después se comprueba
    si ya hay cierre. Al revés, dos webhooks simultáneos podrían leer "aún no hay cierre"
    a la vez y escribir dos.
    """
    job = await conn.fetchrow(
        """
        select j.id, j.project_id, j.credits_reserved, p.owner_id
          from public.generation_jobs j
          join public.projects p on p.id = j.project_id
         where j.id = $1
        """,
        _uuid(job_id),
    )
    if job is None:
        raise ValueError(f"job {job_id} no existe; no se puede liquidar")

    profile_id: UUID = job["owner_id"]
    await _lock_profile(conn, profile_id)

    already = await conn.fetchval(
        """
        select exists (
            select 1 from public.credit_ledger
             where job_id = $1 and kind = any($2::text[])
        )
        """,
        _uuid(job_id),
        list(TERMINAL_LEDGER_KINDS),
    )
    if already:
        logger.info("credits_settle_noop", extra={"job_id": str(job_id), "kind": kind})
        return await _balance_bootstrapped(conn, profile_id)

    reserved = int(job["credits_reserved"] or 0)
    charged = 0 if kind == "refund" else max(0, min(final_credits, reserved))

    if kind == "charge" and final_credits > reserved:
        # Se cobra lo reservado, no lo estimado a posteriori. Cobrar por encima de la
        # reserva significaría poder dejar el saldo en negativo sin que el usuario haya
        # aprobado nada, y la reserva es precisamente el contrato con el usuario.
        logger.warning(
            "credits_charge_capped",
            extra={"job_id": str(job_id), "reserved": reserved, "requested": final_credits},
        )

    delta = reserved - charged  # positivo = se devuelve la diferencia
    before = await _balance_bootstrapped(conn, profile_id)

    after = await _append(
        conn,
        profile_id=profile_id,
        project_id=job["project_id"],
        job_id=job_id,
        kind=kind,
        amount=delta,
        balance_before=before,
        note=note,
    )

    await conn.execute(
        "update public.generation_jobs set credits_charged = $2, updated_at = now() where id = $1",
        _uuid(job_id),
        charged,
    )
    return after


# --------------------------------------------------------------------------- #
# Primitivas                                                                   #
# --------------------------------------------------------------------------- #


async def lock_project_owner(conn: asyncpg.Connection, project_id: str | UUID) -> UUID:
    """
    Toma el cerrojo del perfil que paga este proyecto y devuelve su id.

    Es público porque `queue.enqueue()` necesita tomar el mismo cerrojo antes de mirar
    si existe un job idempotente: el cerrojo protege la decisión completa de gastar, no
    solo la fila del libro.
    """
    owner_id = await conn.fetchval(
        "select owner_id from public.projects where id = $1", _uuid(project_id)
    )
    if owner_id is None:
        raise ValueError(f"project {project_id} no existe")
    await _lock_profile(conn, owner_id)
    return owner_id


async def _lock_profile(conn: asyncpg.Connection, profile_id: UUID) -> None:
    """
    `SELECT ... FOR UPDATE` sobre el perfil. El valor leído no se usa; lo que importa es
    que Postgres serialice aquí a todos los que van a tocar el mismo saldo.
    """
    await conn.fetchval("select id from public.profiles where id = $1 for update", profile_id)


async def _balance_bootstrapped(conn: asyncpg.Connection, profile_id: UUID) -> int:
    """
    Saldo del libro, sembrando desde `profiles.credits` la primera vez.

    Puente de migración: los perfiles creados antes del agente tienen saldo en la columna
    y ninguna fila en el libro. Sin este apaño, migrar dejaría a todo el mundo a cero.
    La siembra ocurre una sola vez por perfil, bajo el cerrojo, y queda registrada como
    un `grant` para que el origen del saldo inicial sea auditable como cualquier otro.
    """
    row = await conn.fetchrow(
        """
        select coalesce(sum(amount), 0)::int as bal, count(*)::int as n
          from public.credit_ledger where profile_id = $1
        """,
        profile_id,
    )
    if row["n"] > 0:
        return int(row["bal"])

    legacy = int(
        await conn.fetchval("select coalesce(credits, 0) from public.profiles where id = $1", profile_id)
        or 0
    )
    if legacy <= 0:
        return 0

    await conn.execute(
        """
        insert into public.credit_ledger (profile_id, kind, amount, balance_after, note)
        values ($1, 'grant', $2, $2, 'saldo inicial migrado desde profiles.credits')
        """,
        profile_id,
        legacy,
    )
    return legacy


async def _append(
    conn: asyncpg.Connection,
    *,
    profile_id: UUID,
    project_id: str | UUID | None,
    job_id: str | UUID | None,
    kind: LedgerKind,
    amount: int,
    balance_before: int,
    note: str | None,
) -> int:
    """
    Escribe una fila del libro. Único punto de escritura: si algún día hay que auditar
    o instrumentar los movimientos, se hace aquí y se cubre todo.

    `balance_after` es redundante con la suma, y está a propósito: permite detectar una
    escritura que se coló fuera del cerrojo comparando la columna con la suma acumulada.
    """
    after = balance_before + amount
    await conn.execute(
        """
        insert into public.credit_ledger
            (profile_id, project_id, job_id, kind, amount, balance_after, note)
        values ($1, $2, $3, $4, $5, $6, $7)
        """,
        profile_id,
        _uuid(project_id) if project_id is not None else None,
        _uuid(job_id) if job_id is not None else None,
        kind,
        amount,
        after,
        note,
    )
    await _mirror_profile_credits(conn, profile_id, after)
    return after


async def _mirror_profile_credits(conn: asyncpg.Connection, profile_id: UUID, value: int) -> None:
    """
    Espejo en `profiles.credits` para el frontend, que aún lee esa columna.

    Es derivado, nunca autoritativo. Se hace dentro de la misma transacción para que no
    pueda divergir, y se satura a 0 porque la columna tiene un `check (credits >= 0)`:
    un espejo que reviente la transacción sería mucho peor que un espejo impreciso.
    """
    await conn.execute(
        "update public.profiles set credits = $2 where id = $1", profile_id, max(0, value)
    )


def to_uuid(value: str | UUID) -> UUID:
    """asyncpg no acepta un `str` donde el tipo de columna es `uuid`."""
    return value if isinstance(value, UUID) else UUID(str(value))


_uuid = to_uuid
