"""
Tests de la reanudación automática de conversaciones.

Se prueban las cuatro guardas de `app/jobs/resume.py`, y solo esas. No son cuatro casos
elegidos por cobertura: cada una, si se cae, tiene una consecuencia concreta y cara.

1. **Se reanuda al caer el último job.** Sin esto, la funcionalidad entera no existe y
   "genera seis planos y móntalos" siguen siendo dos mensajes del usuario.
2. **No se reanuda con jobs pendientes.** Reanudar a mitad de un lote hace que el agente
   monte un corte con agujeros y dé por perdidos planos que están renderizando.
3. **Dos terminaciones simultáneas producen un solo turno.** Dos turnos sobre el mismo
   checkpoint son dos facturas de LLM y dos tandas de generaciones duplicadas.
4. **Se respeta el tope.** Un bucle turno→genera→aterriza→turno no tiene final natural.

Sobre la base de datos falsa. Emula el subconjunto de SQL que usa `resume`, y —esto es lo
único que hace que el test nº3 valga algo— emula `select ... for update` con un
`asyncio.Lock` por conversación que se **mantiene hasta el commit**. El cerrojo es real:
quitar el `for update` del código de producción hace que las dos corrutinas lean
`awaiting_jobs = true` antes de que ninguna escriba, y el test falla. Se verifica por
mutación al final del fichero, que es lo que distingue un test que comprueba el mecanismo
de uno que comprueba el camino feliz.

Lo que este fake NO cubre y hay que probar contra Postgres: el aislamiento real de
transacciones y que el `for update` de verdad bloquee a la otra sesión. La suite de
integración levanta un Postgres para eso.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")

from app.jobs import resume


def run(coro: Any) -> Any:
    """Sin `pytest-asyncio`: una dependencia menos y el control del bucle es explícito."""
    return asyncio.run(coro)


CONV = UUID("33333333-3333-4333-8333-333333333333")
PROJECT = UUID("22222222-2222-4222-8222-222222222222")
OWNER = UUID("11111111-1111-4111-8111-111111111111")


# --------------------------------------------------------------------------- #
# Base de datos falsa                                                          #
# --------------------------------------------------------------------------- #


@dataclass
class FakeDB:
    """
    Almacén en memoria del subconjunto que toca `resume`.

    `conversation` es un dict porque asyncpg devuelve `Record`, que se lee por clave
    igual. `jobs` es una lista de dicts con lo justo: estado, momento de cierre y los
    campos que entran en el texto del evento.
    """

    conversation: dict[str, Any] | None = None
    jobs: list[dict[str, Any]] = field(default_factory=list)
    locks: dict[UUID, asyncio.Lock] = field(default_factory=dict)
    updates: list[str] = field(default_factory=list)

    def lock_for(self, conversation_id: UUID) -> asyncio.Lock:
        return self.locks.setdefault(conversation_id, asyncio.Lock())


class FakeConn:
    """
    Conexión fingida. Despacha por fragmentos del SQL real.

    Se compara contra el texto de las consultas de producción a propósito: si alguien
    reescribe la consulta de `plan_resume` y deja de tomar el cerrojo, el fake deja de
    verlo y el test de concurrencia se cae, que es exactamente lo que queremos que pase.
    """

    def __init__(self, db: FakeDB) -> None:
        self.db = db
        self._held: list[asyncio.Lock] = []

    @staticmethod
    async def _roundtrip() -> None:
        """
        Cede el control del bucle en cada consulta, como haría una ida y vuelta real a
        Postgres.

        Sin esto el fake es un impostor peligroso: sus métodos son `async` pero no
        esperan a nada, así que dos corrutinas lanzadas con `gather` se ejecutan de
        principio a fin una detrás de otra y **nunca se entrelazan**. El test de
        concurrencia daba verde con el `for update` quitado del código de producción —es
        decir, no probaba nada—, y solo se vio verificándolo por mutación. Con el
        `sleep(0)`, la segunda corrutina llega a la fila mientras la primera aún no ha
        escrito, que es exactamente la carrera que el cerrojo existe para perder.
        """
        await asyncio.sleep(0)

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        await self._roundtrip()
        if "from public.conversations" in sql:
            if "for update" in sql:
                lock = self.db.lock_for(args[0])
                await lock.acquire()
                self._held.append(lock)
            row = self.db.conversation
            if row is None or row["id"] != args[0]:
                return None
            return dict(row)
        raise AssertionError(f"consulta no emulada: {sql}")

    async def fetchval(self, sql: str, *args: Any) -> Any:
        await self._roundtrip()
        if "count(*)" in sql and "generation_jobs" in sql:
            states = set(args[1])
            return sum(1 for j in self.db.jobs if j["status"] in states)
        raise AssertionError(f"consulta no emulada: {sql}")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        await self._roundtrip()
        if "generation_jobs" in sql:
            states, since = set(args[1]), args[2]
            return [
                {
                    "shot_id": j.get("shot_id"),
                    "status": j["status"],
                    "model_id": j.get("model_id", "test-video"),
                    "asset_id": j.get("asset_id"),
                    "error": j.get("error"),
                    "shot_title": j.get("shot_title"),
                }
                for j in self.db.jobs
                if j["status"] in states
                and (since is None or j.get("finished_at", _now()) > since)
            ]
        raise AssertionError(f"consulta no emulada: {sql}")

    async def execute(self, sql: str, *args: Any) -> None:
        await self._roundtrip()
        if "update public.conversations" not in sql:
            raise AssertionError(f"consulta no emulada: {sql}")
        self.db.updates.append(sql)
        row = self.db.conversation
        if row is None:
            return

        # El release va primero y sale: su SQL lleva `status = 'running'` en el WHERE, y
        # mirarlo con los mismos `in sql` que el resto lo confundiría con el SET de
        # `plan_resume`. El `where status = 'running'` se emula de verdad porque de él
        # depende que un release tardío no pise un estado que ya cambió otro.
        if "set status = $2" in sql:
            if row["status"] == "running":
                row["status"] = args[1]
            return

        if "awaiting_jobs = false" in sql:
            row["awaiting_jobs"] = False
        if "auto_resumes = $2" in sql:
            row["auto_resumes"] = args[1]
        if "auto_resumes = 0" in sql:
            row["auto_resumes"] = 0
        if "status = 'running'" in sql:
            row["status"] = "running"
        if "last_resumed_at = now()" in sql:
            row["last_resumed_at"] = _now()

    def release(self) -> None:
        for lock in self._held:
            lock.release()
        self._held.clear()


def _now() -> datetime:
    return datetime.now(UTC)


def install(monkeypatch: pytest.MonkeyPatch, db: FakeDB) -> None:
    """Sustituye `resume.transaction` por una que abre una `FakeConn` sobre `db`."""

    @asynccontextmanager
    async def fake_transaction() -> AsyncIterator[FakeConn]:
        conn = FakeConn(db)
        try:
            yield conn
        finally:
            # El commit suelta el cerrojo, como en Postgres. Soltarlo antes convertiría
            # el `for update` en un no-op y el test de concurrencia daría verde en falso.
            conn.release()

    monkeypatch.setattr(resume, "transaction", fake_transaction)


def conversation(**overrides: Any) -> dict[str, Any]:
    """Una conversación esperando jobs, en el estado normal previo a la reanudación."""
    return {
        "id": CONV,
        "project_id": PROJECT,
        "owner_id": OWNER,
        "status": "idle",
        "awaiting_jobs": True,
        "auto_resumes": 0,
        "last_resumed_at": None,
    } | overrides


def job(status: str = "succeeded", **overrides: Any) -> dict[str, Any]:
    return {
        "status": status,
        "shot_id": str(uuid4()),
        "asset_id": str(uuid4()),
        "model_id": "test-video",
        "shot_title": "Plano 1",
        "error": None,
        "finished_at": _now(),
    } | overrides


class SpyRunner:
    """
    Runner que cuenta turnos en vez de llamar a un LLM.

    Implementa `run` como generador asíncrono con la firma real —keyword-only, con
    `system_event`— porque el valor de este doble depende de que la llamada de
    `resume._run_turn` encaje con la firma de `ConversationRunner.run`. El test de
    contratos comprueba lo mismo por introspección; aquí se comprueba en ejecución.
    """

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.delay_s = delay_s

    async def run(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
        message: str | None,
        ui_context: dict[str, Any] | None = None,
        resume_payload: dict[str, Any] | None = None,
        system_event: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "project_id": project_id,
                "user_id": user_id,
                "message": message,
                "system_event": system_event,
            }
        )
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        yield {"type": "message_delta", "content": "listo"}


@pytest.fixture
def runner() -> Any:
    spy = SpyRunner()
    resume.set_runner(spy)
    try:
        yield spy
    finally:
        resume.set_runner(None)


# --------------------------------------------------------------------------- #
# 1. Se reanuda cuando cae el último job                                       #
# --------------------------------------------------------------------------- #


def test_reanuda_cuando_cae_el_ultimo_job(monkeypatch: pytest.MonkeyPatch, runner: SpyRunner) -> None:
    """
    Con la marca puesta, sin jobs pendientes y con algo que contar, sale un turno.

    Es el caso que justifica el módulo entero: el usuario pidió seis planos y se fue; el
    agente tiene que enterarse de que están sin que nadie se lo pregunte.
    """
    db = FakeDB(conversation=conversation(), jobs=[job(), job(), job()])
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is True
    assert len(runner.calls) == 1

    call = runner.calls[0]
    assert call["message"] is None, "el turno reanudado no puede fingir un mensaje del usuario"
    assert "<job_completion_event>" in call["system_event"]
    assert "3 succeeded, 0 failed" in call["system_event"]
    assert call["user_id"] == str(OWNER)


def test_el_evento_detalla_los_fallos(monkeypatch: pytest.MonkeyPatch, runner: SpyRunner) -> None:
    """
    El texto lleva el motivo de cada fallo, no un "algo salió mal".

    Con el motivo, el agente reintenta solo el plano roto y monta con los buenos. Sin él,
    su único movimiento razonable es releer el proyecto entero: un turno más y una
    llamada más por cada lote con un fallo, que es el caso común.
    """
    db = FakeDB(
        conversation=conversation(),
        jobs=[
            job(),
            job("failed", shot_id="plano-7", error={"message": "prompt rechazado por contenido"}),
        ],
    )
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is True
    event = runner.calls[0]["system_event"]
    assert "1 succeeded, 1 failed" in event
    assert "plano-7" in event
    assert "prompt rechazado por contenido" in event


def test_un_lote_que_falla_entero_tambien_reanuda(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """
    El fallo también es noticia, y de las que el usuario no puede ver por sí mismo.

    Si solo se reanudara con éxitos, un lote que falla entero dejaría la conversación
    esperando para siempre: la marca puesta, ningún job vivo y nadie que la limpie.
    """
    db = FakeDB(conversation=conversation(), jobs=[job("failed"), job("nsfw")])
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is True
    assert "0 succeeded, 2 failed" in runner.calls[0]["system_event"]


def test_sin_marca_de_espera_no_se_reanuda(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """
    Guarda nº1. Una generación que el agente no encoló —un reintento manual, otra
    pestaña— no puede abrirle un turno a nadie.
    """
    db = FakeDB(conversation=conversation(awaiting_jobs=False), jobs=[job()])
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is False
    assert runner.calls == []


def test_con_turno_en_curso_no_se_reanuda(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """
    Guarda nº4. Dos turnos sobre el mismo checkpoint se pisan el estado.

    La marca se deja puesta: el turno en curso puede ser del usuario y aún quedar jobs
    por caer, así que el siguiente que aterrice tiene que poder reintentarlo.
    """
    db = FakeDB(conversation=conversation(status="running"), jobs=[job()])
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is False
    assert db.conversation is not None and db.conversation["awaiting_jobs"] is True


# --------------------------------------------------------------------------- #
# 2. No se reanuda con jobs pendientes                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("pending_state", ["queued", "submitted", "running"])
def test_no_reanuda_con_jobs_pendientes(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner, pending_state: str
) -> None:
    """
    Guarda nº0, la que da sentido a todo: solo el **último** job reanuda.

    Los tres estados no terminales por separado, porque el fallo real sería olvidarse de
    uno: con `submitted` fuera de la lista, un lote reanuda en cuanto el primer plano
    sale de la cola y el agente monta el corte con un solo clip.
    """
    db = FakeDB(conversation=conversation(), jobs=[job(), job(pending_state)])
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is False
    assert runner.calls == []
    assert db.conversation is not None
    assert db.conversation["awaiting_jobs"] is True, (
        "la marca tiene que sobrevivir: quien la consuma debe ser el último job, no el primero"
    )


def test_marca_sin_nada_que_contar_se_limpia(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """
    Marca puesta y ningún job terminado desde la última vez: no hay noticia, no hay turno,
    y la marca se apaga para que no quede esperando un evento que no va a llegar.
    """
    db = FakeDB(
        conversation=conversation(last_resumed_at=_now() + timedelta(minutes=1)),
        jobs=[job()],
    )
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is False
    assert db.conversation is not None and db.conversation["awaiting_jobs"] is False


# --------------------------------------------------------------------------- #
# 3. Idempotencia: dos terminaciones simultáneas, un solo turno                 #
# --------------------------------------------------------------------------- #


def test_dos_terminaciones_simultaneas_producen_un_solo_turno(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """
    Guarda nº3, y la única que no se puede comprobar mirando el código.

    Dos workers cierran el penúltimo y el último job a la vez. Los dos ven cero jobs
    pendientes y los dos ven la marca puesta, porque el segundo lee antes de que el
    primero haya escrito. Lo que los separa es el cerrojo de fila: el segundo entra
    cuando el primero ya ha hecho commit y encuentra `awaiting_jobs = false`.

    El fake toma el cerrojo en el `for update` y lo suelta al salir de la transacción,
    igual que Postgres. Si el `for update` desaparece de la consulta de producción, este
    test se pone rojo — está verificado por mutación más abajo.
    """
    db = FakeDB(conversation=conversation(), jobs=[job(), job()])
    install(monkeypatch, db)

    async def both() -> list[bool]:
        return list(await asyncio.gather(resume.on_job_settled(CONV), resume.on_job_settled(CONV)))

    outcomes = run(both())

    assert sorted(outcomes) == [False, True], f"esperaba exactamente una reanudación: {outcomes}"
    assert len(runner.calls) == 1
    assert db.conversation is not None and db.conversation["auto_resumes"] == 1


def test_seis_terminaciones_simultaneas_producen_un_solo_turno(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """
    El caso de verdad: un fan-out de seis planos que terminan a la vez, que es lo que
    ocurre cuando el proveedor devuelve un lote entero de golpe.
    """
    db = FakeDB(conversation=conversation(), jobs=[job() for _ in range(6)])
    install(monkeypatch, db)

    async def all_six() -> list[bool]:
        return list(await asyncio.gather(*(resume.on_job_settled(CONV) for _ in range(6))))

    assert sum(run(all_six())) == 1
    assert len(runner.calls) == 1


# --------------------------------------------------------------------------- #
# 4. Tope de reanudaciones                                                     #
# --------------------------------------------------------------------------- #


def test_se_respeta_el_tope(monkeypatch: pytest.MonkeyPatch, runner: SpyRunner) -> None:
    """
    Guarda nº2. Al llegar al tope se para, se apaga la marca y se registra.

    El bucle que esto corta es real y es el modo de fallo caro del módulo: el turno
    reanudado genera, esas generaciones aterrizan, eso reanuda otro turno que vuelve a
    generar. Cada vuelta es una factura de LLM y puede cursar renders.
    """
    db = FakeDB(
        conversation=conversation(auto_resumes=resume.MAX_AUTO_RESUMES),
        jobs=[job()],
    )
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is False
    assert runner.calls == []
    assert db.conversation is not None
    assert db.conversation["awaiting_jobs"] is False, (
        "al pararse hay que apagar la marca, o cada job posterior vuelve a evaluar el tope"
    )


def test_la_ultima_reanudacion_avisa_de_que_es_la_ultima(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """
    En la última vuelta el evento se lo dice al modelo, para que cierre el turno
    contándoselo al usuario en vez de encolar más y quedarse esperando un aviso que ya
    no va a llegar.
    """
    db = FakeDB(
        conversation=conversation(auto_resumes=resume.MAX_AUTO_RESUMES - 1),
        jobs=[job()],
    )
    install(monkeypatch, db)

    assert run(resume.on_job_settled(CONV)) is True
    assert "last automatic notification" in runner.calls[0]["system_event"]


def test_el_contador_cuenta_hasta_el_tope_y_para(
    monkeypatch: pytest.MonkeyPatch, runner: SpyRunner
) -> None:
    """La cadena entera: MAX_AUTO_RESUMES turnos y ni uno más."""
    db = FakeDB(conversation=conversation(), jobs=[job()])
    install(monkeypatch, db)

    async def chain() -> int:
        turns = 0
        for _ in range(resume.MAX_AUTO_RESUMES + 3):
            assert db.conversation is not None
            db.conversation["awaiting_jobs"] = True  # el turno reanudado volvió a generar
            db.conversation["last_resumed_at"] = None
            if await resume.on_job_settled(CONV):
                turns += 1
        return turns

    assert run(chain()) == resume.MAX_AUTO_RESUMES


def test_un_mensaje_del_usuario_reinicia_el_contador(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    El tope acota la autonomía, no el uso. Sin este reinicio, a la cuarta generación de
    una sesión larga el agente deja de enterarse de sus propios renders para siempre.
    """
    db = FakeDB(conversation=conversation(auto_resumes=resume.MAX_AUTO_RESUMES))
    install(monkeypatch, db)

    run(resume.note_user_turn(CONV))
    assert db.conversation is not None and db.conversation["auto_resumes"] == 0


# --------------------------------------------------------------------------- #
# 5. Estado tras el turno                                                      #
# --------------------------------------------------------------------------- #


def test_el_estado_vuelve_a_idle_aunque_el_turno_falle(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Un `running` pegado bloquea la guarda nº4 para siempre: esa conversación no se
    reanuda nunca más, y el síntoma es que "dejó de funcionar" sin ningún error.
    """

    class ExplodingRunner:
        async def run(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            raise RuntimeError("el modelo se cayó")
            yield {}  # pragma: no cover - hace de esto un generador asíncrono

    db = FakeDB(conversation=conversation(), jobs=[job()])
    install(monkeypatch, db)
    resume.set_runner(ExplodingRunner())
    try:
        assert run(resume.on_job_settled(CONV)) is False
    finally:
        resume.set_runner(None)

    assert db.conversation is not None and db.conversation["status"] == "idle"


def test_sin_conversacion_no_hay_reanudacion(monkeypatch: pytest.MonkeyPatch, runner: SpyRunner) -> None:
    """Un job suelto, sin conversación, no puede abrirle un turno a nadie."""
    db = FakeDB(conversation=None, jobs=[job()])
    install(monkeypatch, db)

    assert run(resume.on_job_settled(None)) is False
    assert run(resume.on_job_settled(CONV)) is False
    assert runner.calls == []
