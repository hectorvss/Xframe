"""
Reanudación de una conversación cuando sus generaciones aterrizan.

El agujero que cierra este módulo, dicho sin rodeos. El grafo no espera: la tool de
generación encola, devuelve un `AssetRef` en `generating` y termina su turno. El worker
acaba minutos después y publica `asset_ready` en el bus. Ese evento va al frontend por
SSE y **no reentra en el grafo**. Consecuencia: "genera seis planos y móntalos" eran hoy
dos mensajes del usuario, porque el agente nunca sabía que los planos ya estaban.

Aquí se le cuenta. Cuando cae el **último** job no terminal de una conversación, se
invoca un turno nuevo del grafo con un mensaje sintético que describe lo que ha
aterrizado. No es un `HumanMessage` que finja ser el usuario: va marcado con
`JOB_EVENT_FLAG` para que el frontend lo pinte distinto y para que el prompt lo entienda
como un evento del sistema, no como una petición nueva.

Las cuatro guardas, que son lo que separa esto de una bomba:

1. **Marca de espera** (`conversations.awaiting_jobs`). Solo se reanuda si la
   conversación estaba esperando. La ponen las tools de generación al encolar y se
   limpia al reanudar. Sin ella, cualquier generación suelta —un reintento manual, un
   job de otra pestaña— dispararía un turno que nadie pidió.
2. **Tope de reanudaciones** (`auto_resumes` vs `MAX_AUTO_RESUMES`). Un turno reanudado
   puede generar más, y esas generaciones vuelven a aterrizar aquí. Sin tope, la cadena
   no tiene final y cada eslabón cuesta dinero en LLM y puede cursar renders.
3. **Idempotencia** (`select ... for update` sobre la fila de la conversación). Dos
   workers que terminan el último job a la vez ven los dos "ya no queda nada". El
   cerrojo los serializa: el primero limpia `awaiting_jobs` dentro de su transacción y
   el segundo, al entrar, ya lee la marca apagada y se retira. Es el mismo mecanismo que
   usa `credits._lock_profile` para el saldo, y por la misma razón: lo que hay que
   serializar es la **decisión**, no la escritura.
4. **Turno en curso** (`conversations.status`). Si el usuario está escribiendo o hay un
   turno corriendo, no se arranca otro encima. En ese caso la marca se deja puesta: es
   preferible perder una reanudación que apilar dos turnos sobre el mismo checkpoint.

Sobre el ciclo de imports, que es la decisión de diseño no obvia. `worker.py` **no puede**
importar el runner a nivel de módulo: el runner arrastra langgraph y el checkpointer de
Postgres, y el worker debe poder importarse en un proceso que no tenga ese árbol. La
inversión es este módulo: el worker importa `app.jobs.resume` (que a nivel de módulo solo
depende de `app.db` y del logging), y es `resume` quien hace el import perezoso del runner
dentro de `_get_runner()`, en el único punto donde de verdad hace falta. Así el grafo se
carga en el worker la primera vez que hay algo que reanudar, y nunca antes.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.db import transaction
from app.jobs.credits import to_uuid

logger = logging.getLogger(__name__)

MAX_AUTO_RESUMES = 3
"""
Reanudaciones automáticas consecutivas por conversación.

Bajo a propósito. Cubre el encadenamiento legítimo —generar planos, montarlos, corregir
uno— y corta la cadena autónoma antes de que se note en la factura. El contador se pone a
cero cuando el usuario escribe (`note_user_turn`), así que el tope acota la **autonomía**,
no el uso.
"""

ACTIVE_JOB_STATES: tuple[str, ...] = ("queued", "submitted", "running")
"""
Estados no terminales. Se declara aquí y no se importa de `queue` porque son la misma
lista por coincidencia semántica y no por dependencia: si mañana `queue` añade un estado
intermedio propio del encolado, esta pregunta —"¿queda algo por aterrizar?"— no cambia.
"""

BUSY_CONVERSATION_STATES: tuple[str, ...] = ("running", "interrupted")
"""
Estados en los que ya hay alguien usando el checkpoint. `interrupted` cuenta: hay un
interrupt esperando respuesta del usuario y meterle un turno por debajo dejaría el grafo
con dos caminos abiertos sobre el mismo hilo.
"""


@dataclass(slots=True)
class ResumePlan:
    """
    La decisión, ya tomada y ya cobrada en base de datos.

    Que exista como dato y no como una llamada encadenada es lo que permite que el
    veredicto (bajo cerrojo, transaccional, barato) y la ejecución del turno (larga, con
    LLM de por medio) no compartan transacción. Mantener abierta la fila de la
    conversación durante un turno entero bloquearía a todo el que quisiera escribir en
    esa conversación mientras el modelo piensa.
    """

    conversation_id: UUID
    project_id: UUID
    user_id: UUID
    event_text: str
    resume_number: int


# --------------------------------------------------------------------------- #
# Marcas que ponen otros                                                       #
# --------------------------------------------------------------------------- #


async def mark_awaiting(
    *,
    conversation_id: str | UUID,
    project_id: str | UUID,
    conn: asyncpg.Connection | None = None,
) -> None:
    """
    Declara que esta conversación espera a que aterricen unas generaciones.

    La llaman las tools de generación al encolar, en su único punto común
    (`_GenerationTool.enqueue`). Es la guarda nº1: sin esta marca no hay reanudación.

    Es un upsert y no un update, y la razón es un hueco real del esquema: **nadie inserta
    nunca la fila de `conversations`**. El cliente genera el uuid antes del primer turno
    (por eso `assert_conversation_available` acepta que la fila no exista todavía) y el
    backend solo la actualiza. Un `update` a secas afectaría a cero filas en la primera
    conversación de cada usuario, la marca no existiría, y la reanudación sería una
    función que nunca se ejecuta en producción sin dar un solo error. El `owner_id` sale
    del proyecto, que es de donde sale la propiedad de todo lo demás.

    Nunca propaga un fallo. Esta marca es la puerta de una comodidad, no de una
    corrección: si falla, el usuario tiene que volver a preguntar "¿ya están?", que es
    exactamente el comportamiento anterior a este módulo. Tumbar por esto una tool que
    acaba de reservar créditos sería cambiar una molestia por una factura.
    """
    sql = """
        insert into public.conversations (id, project_id, owner_id, awaiting_jobs)
        select $1::uuid, p.id, p.owner_id, true
          from public.projects p
         where p.id = $2::uuid
        on conflict (id) do update
           set awaiting_jobs = true, updated_at = now()
    """
    try:
        if conn is not None:
            await conn.execute(sql, to_uuid(conversation_id), to_uuid(project_id))
            return
        async with transaction() as tx:
            await tx.execute(sql, to_uuid(conversation_id), to_uuid(project_id))
    except Exception:  # noqa: BLE001
        logger.warning("resume_mark_failed", extra={"conversation_id": str(conversation_id)})


async def note_user_turn(conversation_id: str | UUID) -> None:
    """
    El usuario ha escrito: se reinicia el contador de reanudaciones automáticas.

    Lo llama la frontera HTTP cuando llega un mensaje de verdad. El tope existe para
    acotar la cadena que el sistema recorre **solo**; una conversación larga en la que el
    usuario participa no es esa cadena, y dejar el contador acumulando haría que a la
    cuarta generación de la sesión el agente dejara de enterarse de nada.

    Silencioso ante fallo por el mismo motivo que `mark_awaiting`: el peor desenlace es
    que el usuario tenga que preguntar, no que su mensaje se pierda.
    """
    try:
        async with transaction() as tx:
            await tx.execute(
                """
                update public.conversations
                   set auto_resumes = 0, updated_at = now()
                 where id = $1::uuid and auto_resumes <> 0
                """,
                to_uuid(conversation_id),
            )
    except Exception:  # noqa: BLE001
        logger.warning("resume_counter_reset_failed", extra={"conversation_id": str(conversation_id)})


# --------------------------------------------------------------------------- #
# Decisión                                                                     #
# --------------------------------------------------------------------------- #


async def plan_resume(conversation_id: str | UUID) -> ResumePlan | None:
    """
    ¿Hay que reanudar esta conversación? Si sí, devuelve el plan y **ya ha consumido** la
    marca de espera y sumado uno al contador.

    Todo ocurre en una transacción y bajo `select ... for update` sobre la fila de la
    conversación. El cerrojo se toma **antes** de contar los jobs pendientes, no después:
    lo que hay que serializar es la decisión completa "¿queda algo? ¿esperábamos? pues
    voy", igual que `queue.enqueue` serializa "¿reutilizo o gasto?". Consultar fuera del
    cerrojo permite que dos workers concluyan a la vez que son el último, y entonces
    salen dos turnos sobre el mismo checkpoint.

    Que el plan salga con la marca ya limpiada es lo que hace idempotente al mecanismo:
    el segundo worker entra al cerrojo cuando el primero ya ha hecho commit, lee
    `awaiting_jobs = false` y se retira sin haber ejecutado nada.
    """
    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            select id, project_id, owner_id, status, awaiting_jobs, auto_resumes,
                   last_resumed_at
              from public.conversations
             where id = $1
             for update
            """,
            to_uuid(conversation_id),
        )
        if row is None:
            # No hay fila, así que tampoco hay dueño al que atribuirle el turno.
            logger.info("resume_no_conversation", extra={"conversation_id": str(conversation_id)})
            return None

        if not row["awaiting_jobs"]:
            # Guarda 1. También es el camino por el que sale el segundo worker de una
            # carrera: el primero ya limpió la marca.
            return None

        if row["status"] in BUSY_CONVERSATION_STATES:
            # Guarda 4. La marca se deja puesta a propósito: si el turno en curso es del
            # usuario y quedan jobs por caer, el próximo que aterrice reintentará.
            logger.info(
                "resume_skipped_busy",
                extra={"conversation_id": str(conversation_id), "status": row["status"]},
            )
            return None

        pending = int(
            await conn.fetchval(
                """
                select count(*) from public.generation_jobs
                 where conversation_id = $1 and status = any($2::text[])
                """,
                row["id"],
                list(ACTIVE_JOB_STATES),
            )
            or 0
        )
        if pending:
            # No es el último. Callarse aquí es el 90 % del valor del módulo: reanudar
            # con planos a medias haría que el agente montara un corte con agujeros.
            return None

        resume_number = int(row["auto_resumes"] or 0) + 1
        if resume_number > MAX_AUTO_RESUMES:
            # Guarda 2. Se apaga la marca al pararse: dejarla puesta convertiría cada job
            # posterior de la conversación en otra evaluación de este mismo camino.
            await conn.execute(
                "update public.conversations set awaiting_jobs = false, updated_at = now() where id = $1",
                row["id"],
            )
            logger.warning(
                "resume_cap_reached",
                extra={
                    "conversation_id": str(conversation_id),
                    "auto_resumes": int(row["auto_resumes"] or 0),
                    "cap": MAX_AUTO_RESUMES,
                },
            )
            return None

        landed = await conn.fetch(
            """
            select j.shot_id, j.status, j.model_id, j.asset_id, j.error,
                   n.title as shot_title
              from public.generation_jobs j
              left join public.canvas_nodes n
                     on n.id::text = j.shot_id and n.project_id = j.project_id
             where j.conversation_id = $1
               and j.status = any($2::text[])
               and j.finished_at > coalesce($3, '-infinity'::timestamptz)
             order by n.position nulls last, j.finished_at
            """,
            row["id"],
            ["succeeded", "failed", "cancelled", "nsfw"],
            row["last_resumed_at"],
        )
        if not landed:
            # Marca puesta y nada que contar: la generación se resolvió por caché
            # idempotente y no hubo render. No hay noticia, así que no hay turno.
            await conn.execute(
                "update public.conversations set awaiting_jobs = false, updated_at = now() where id = $1",
                row["id"],
            )
            logger.info("resume_nothing_landed", extra={"conversation_id": str(conversation_id)})
            return None

        await conn.execute(
            """
            update public.conversations
               set awaiting_jobs = false, auto_resumes = $2, status = 'running',
                   last_resumed_at = now(), updated_at = now()
             where id = $1
            """,
            row["id"],
            resume_number,
        )

    return ResumePlan(
        conversation_id=row["id"],
        project_id=row["project_id"],
        user_id=row["owner_id"],
        event_text=describe(landed, resume_number=resume_number, cap=MAX_AUTO_RESUMES),
        resume_number=resume_number,
    )


def describe(rows: list[Any], *, resume_number: int, cap: int) -> str:
    """
    Lo que ha aterrizado, en el texto que va a leer el modelo.

    Se le dan ids de plano, estado y motivo del fallo, y no un "tus generaciones están
    listas". La diferencia importa: con el detalle, el agente puede reintentar solo el
    plano roto y montar con los buenos; sin él, su único movimiento razonable es volver a
    leer el proyecto entero, que es un turno más y una llamada más.

    El aviso de tope se incluye cuando queda una reanudación o menos, para que el modelo
    sepa que si vuelve a generar puede que nadie le cuente el resultado, y cierre el
    turno diciéndoselo al usuario en vez de dejar el plan a medias.
    """
    ok = [r for r in rows if r["status"] == "succeeded"]
    ko = [r for r in rows if r["status"] != "succeeded"]

    lines = ["<job_completion_event>"]
    lines.append(
        f"Generation jobs for this conversation have finished: "
        f"{len(ok)} succeeded, {len(ko)} failed. Nothing else is queued."
    )
    lines.append("")
    for row in rows:
        label = row["shot_title"] or row["shot_id"] or "loose asset"
        target = f"shot {row['shot_id']} ({label})" if row["shot_id"] else f"asset ({row['model_id']})"
        if row["status"] == "succeeded":
            lines.append(f"- {target}: succeeded, asset {row['asset_id']}")
        else:
            reason = (row["error"] or {}).get("message") if isinstance(row["error"], dict) else None
            lines.append(f"- {target}: {row['status']}{f' — {reason}' if reason else ''}")

    if resume_number >= cap:
        lines.append("")
        lines.append(
            "This is the last automatic notification for this conversation. If you queue "
            "more generations now, nobody will tell you when they land — finish the turn "
            "by telling the user what is left and let them prompt you."
        )
    lines.append("</job_completion_event>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Ejecución                                                                    #
# --------------------------------------------------------------------------- #


async def on_job_settled(conversation_id: str | UUID | None) -> bool:
    """
    Punto de entrada del worker: acaba de cerrarse un job de esta conversación.

    Devuelve si se ha llegado a ejecutar un turno, que es lo que miran los tests. Nunca
    lanza: el worker que la llama ya ha cobrado, ya ha escrito el asset y ya ha publicado
    su evento. Un fallo reanudando no puede deshacer nada de eso ni justificar marcar el
    job como fallido.
    """
    if conversation_id is None:
        return False
    try:
        plan = await plan_resume(conversation_id)
        if plan is None:
            return False
        await _run_turn(plan)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("resume_failed", extra={"conversation_id": str(conversation_id)})
        await _release(conversation_id, "failed")
        return False


async def _run_turn(plan: ResumePlan) -> None:
    """
    Ejecuta el turno reanudado.

    Se consume el generador entero sin mirar los eventos: el runner ya los publica en el
    bus, así que un cliente conectado los ve llegar por SSE como los de cualquier otro
    turno. Si no hay nadie conectado da igual — el checkpoint guarda el resultado y al
    reconectar está ahí. Es la misma propiedad que hace que cerrar el navegador no
    cancele un render.
    """
    runner = await _get_runner()
    logger.info(
        "resume_turn_started",
        extra={"conversation_id": str(plan.conversation_id), "n": plan.resume_number},
    )
    try:
        async for _ in runner.run(
            conversation_id=str(plan.conversation_id),
            project_id=str(plan.project_id),
            user_id=str(plan.user_id),
            message=None,
            system_event=plan.event_text,
        ):
            pass
    finally:
        # El estado vuelve a `idle` pase lo que pase. Un `running` que se queda pegado
        # bloquea para siempre la guarda nº4 y con ella toda reanudación futura de esta
        # conversación.
        await _release(plan.conversation_id, "idle")
    logger.info("resume_turn_finished", extra={"conversation_id": str(plan.conversation_id)})


async def _release(conversation_id: str | UUID, status: str) -> None:
    try:
        async with transaction() as conn:
            await conn.execute(
                """
                update public.conversations
                   set status = $2, updated_at = now()
                 where id = $1 and status = 'running'
                """,
                to_uuid(conversation_id),
                status,
            )
    except Exception:  # noqa: BLE001
        logger.warning("resume_release_failed", extra={"conversation_id": str(conversation_id)})


# --------------------------------------------------------------------------- #
# El runner, cargado tarde                                                     #
# --------------------------------------------------------------------------- #

_runner: Any = None
_runner_stack: AsyncExitStack | None = None
_runner_lock: asyncio.Lock | None = None


def set_runner(runner: Any) -> None:
    """
    Inyecta el runner. Lo usa `main.py`, que ya tiene uno construido y con su
    checkpointer abierto, y lo usan los tests.

    Sin esto, un backend que reanudara desde el proceso de la API abriría un segundo
    checkpointer contra la misma base para hacer exactamente lo mismo que el primero.
    """
    global _runner
    _runner = runner


async def _get_runner() -> Any:
    """
    El runner del proceso, construido la primera vez que hace falta.

    Aquí vive el import perezoso de langgraph. `worker.py` importa este módulo a nivel de
    módulo y este módulo no importa el grafo hasta que hay algo que reanudar: es la
    inversión de dependencia que rompe el ciclo, y el motivo de que el worker siga siendo
    importable sin el árbol del agente instalado.

    El cerrojo cubre la construcción concurrente: sin él, dos jobs que terminan a la vez
    en un worker recién arrancado montan dos checkpointers y uno queda huérfano con su
    conexión tomada.
    """
    global _runner, _runner_stack, _runner_lock

    if _runner is not None:
        return _runner

    if _runner_lock is None:
        _runner_lock = asyncio.Lock()

    async with _runner_lock:
        if _runner is not None:
            return _runner

        from app.agent.runner import ConversationRunner, make_checkpointer
        from app.stream.bus import get_bus

        stack = AsyncExitStack()
        checkpointer = await stack.enter_async_context(await make_checkpointer())
        await checkpointer.setup()
        _runner_stack = stack
        _runner = ConversationRunner(checkpointer, get_bus())
        logger.info("resume_runner_ready")
        return _runner


async def close_runner() -> None:
    """Suelta el checkpointer propio, si este proceso llegó a construir uno."""
    global _runner, _runner_stack
    if _runner_stack is not None:
        await _runner_stack.aclose()
        _runner_stack = None
    _runner = None
