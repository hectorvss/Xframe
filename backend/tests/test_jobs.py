"""
Tests del sistema de jobs.

Cuatro propiedades, y las cuatro se eligieron porque su fallo se paga en dinero real o en
trabajo perdido, no porque sean fáciles de comprobar:

1. **Idempotencia** — la misma petición no cobra dos veces.
2. **Reembolso** — `failed` y `nsfw` devuelven el crédito íntegro.
3. **No-doble-gasto concurrente** — dos peticiones simultáneas con saldo para una sola no
   pasan las dos.
4. **Aislamiento del fan-out** — un plano que falla no cancela a sus hermanos.

Sobre la base de datos falsa: emula el subconjunto de SQL que usan `credits` y `queue`, y
—esto es lo importante— emula `SELECT ... FOR UPDATE` con un `asyncio.Lock` por perfil. No
es decorado. El test de concurrencia solo tiene valor porque el cerrojo es real: si se
quita el `for update` del código de producción, `_lock_profile` deja de tomar el cerrojo
del fake, las dos corrutinas leen el mismo saldo antes de que ninguna escriba, y el test
falla. Es decir, el test verifica el mecanismo, no solo el resultado feliz.

Lo que este fake NO cubre, y hay que probar contra Postgres de verdad antes de producción:
el aislamiento real de transacciones, `SKIP LOCKED` del worker, y la restricción `unique`
sobre `idempotency_key` como última red ante una carrera.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# La configuración se lee del entorno al importar; en test no hay .env ni base de datos.
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")

from app.agent.state import JobResult
from app.jobs import credits, fanout, queue
from app.providers.base import (
    GenerationAdapter,
    GenerationRequest,
    ModelSpec,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.tools.errors import InsufficientCreditsError, ProviderError


def run(coro: Any) -> Any:
    """Sin `pytest-asyncio`: una dependencia menos y el control del bucle es explícito."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Base de datos falsa                                                          #
# --------------------------------------------------------------------------- #


@dataclass
class FakeDB:
    """Almacén en memoria. Las tablas son listas de dicts, como devuelve asyncpg."""

    profiles: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    projects: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    ledger: list[dict[str, Any]] = field(default_factory=list)
    jobs: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    assets: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    locks: dict[UUID, asyncio.Lock] = field(default_factory=dict)

    def lock_for(self, profile_id: UUID) -> asyncio.Lock:
        return self.locks.setdefault(profile_id, asyncio.Lock())


class FakeConn:
    """
    Conexión falsa. Despacha por subcadenas distintivas de cada consulta.

    Los cerrojos tomados se liberan al cerrar la transacción, igual que en Postgres, y por
    eso `FakeConn` es también el gestor de contexto de la transacción.
    """

    def __init__(self, db: FakeDB) -> None:
        self.db = db
        self._held: list[asyncio.Lock] = []
        self._undo: list[Any] = []

    async def release(self, *, rollback: bool = False) -> None:
        """
        Cierra la transacción. `rollback=True` deshace los cambios en orden inverso.

        El deshacer es por operación y no por instantánea de toda la base: en el test de
        concurrencia hay dos transacciones vivas a la vez, y restaurar una instantánea
        global borraría también el trabajo de la que sí tuvo éxito.
        """
        if rollback:
            for undo in reversed(self._undo):
                undo()
        self._undo.clear()
        for lock in reversed(self._held):
            lock.release()
        self._held.clear()

    # -- despacho ---------------------------------------------------------- #

    async def fetchval(self, q: str, *args: Any) -> Any:
        rows = await self._run(q, *args)
        if not rows:
            return None
        first = rows[0]
        return next(iter(first.values())) if isinstance(first, dict) else first

    async def fetchrow(self, q: str, *args: Any) -> Any:
        rows = await self._run(q, *args)
        return rows[0] if rows else None

    async def fetch(self, q: str, *args: Any) -> list[Any]:
        return await self._run(q, *args)

    async def execute(self, q: str, *args: Any) -> str:
        await self._run(q, *args)
        return "OK"

    async def _run(self, q: str, *args: Any) -> list[Any]:
        # Cede el control en CADA consulta. Sin esto el fake no ejerce concurrencia
        # alguna: `await` sobre una corrutina que nunca se suspende no devuelve el control
        # al bucle de eventos, así que dos `enqueue` bajo `gather` se ejecutarían uno
        # entero detrás del otro y el test de doble gasto pasaría aunque se quitara el
        # cerrojo. Este `sleep(0)` es lo que hace que ese test signifique algo.
        await asyncio.sleep(0)
        s = " ".join(q.split())
        db = self.db

        # --- cerrojo de perfil ---
        if "from public.profiles where id = $1 for update" in s:
            # Re-entrante dentro de la misma transacción, como Postgres: una transacción
            # que ya tiene el cerrojo de una fila puede volver a pedirlo. `enqueue()` lo
            # hace (toma el cerrojo y luego llama a `reserve()`, que lo vuelve a pedir), y
            # un `asyncio.Lock` sin esta comprobación se bloquearía contra sí mismo.
            lock = db.lock_for(args[0])
            if lock not in self._held:
                await lock.acquire()
                self._held.append(lock)
            return [{"id": args[0]}]

        if "select owner_id from public.projects where id = $1" in s:
            project = db.projects.get(args[0])
            return [{"owner_id": project["owner_id"]}] if project else []

        if "select coalesce(credits, 0) from public.profiles" in s:
            return [{"credits": db.profiles[args[0]]["credits"]}]

        # --- libro mayor ---
        if "as bal, count(*)::int as n" in s:
            rows = [r for r in db.ledger if r["profile_id"] == args[0]]
            return [{"bal": sum(r["amount"] for r in rows), "n": len(rows)}]

        # El `exists` va ANTES que la suma por job: ambas consultas contienen
        # "credit_ledger where job_id = $1" y la primera coincidencia gana.
        if "select exists" in s and "credit_ledger" in s:
            kinds = set(args[1])
            hit = any(r["job_id"] == args[0] and r["kind"] in kinds for r in db.ledger)
            return [{"exists": hit}]

        if "from public.credit_ledger where profile_id = $1" in s:
            return [{"sum": sum(r["amount"] for r in db.ledger if r["profile_id"] == args[0])}]

        if "from public.credit_ledger where job_id = $1" in s:
            return [{"sum": sum(r["amount"] for r in db.ledger if r["job_id"] == args[0])}]

        if "insert into public.credit_ledger" in s:
            if "'grant'" in s:
                row = {
                    "profile_id": args[0],
                    "project_id": None,
                    "job_id": None,
                    "kind": "grant",
                    "amount": args[1],
                    "balance_after": args[1],
                }
            else:
                row = {
                    "profile_id": args[0],
                    "project_id": args[1],
                    "job_id": args[2],
                    "kind": args[3],
                    "amount": args[4],
                    "balance_after": args[5],
                }
            db.ledger.append(row)
            self._undo.append(lambda: db.ledger.remove(row))
            return []

        if "update public.profiles set credits" in s:
            profile = db.profiles[args[0]]
            previous = profile["credits"]
            self._undo.append(lambda: profile.__setitem__("credits", previous))
            profile["credits"] = args[1]
            return []

        # --- jobs ---
        if "j.credits_reserved, p.owner_id" in s:
            job = db.jobs.get(args[0])
            if job is None:
                return []
            return [
                {
                    "id": job["id"],
                    "project_id": job["project_id"],
                    "credits_reserved": job["credits_reserved"],
                    "owner_id": db.projects[job["project_id"]]["owner_id"],
                }
            ]

        if "set credits_charged = $2" in s:
            job = db.jobs[args[0]]
            previous = job["credits_charged"]
            self._undo.append(lambda: job.__setitem__("credits_charged", previous))
            job["credits_charged"] = args[1]
            return []

        if "where idempotency_key = $1" in s:
            return [j for j in db.jobs.values() if j["idempotency_key"] == args[0]]

        if "insert into public.generation_jobs" in s:
            job_id = uuid4()
            db.jobs[job_id] = {
                "id": job_id,
                "project_id": args[0],
                "shot_id": args[1],
                "provider": args[2],
                "model_id": args[3],
                "request": args[4],
                "idempotency_key": args[5],
                "status": "queued",
                "credits_reserved": args[6],
                "credits_charged": 0,
                "cost_usd": args[7],
                "conversation_id": args[8],
                "asset_id": None,
                "attempts": 0,
            }
            self._undo.append(lambda: db.jobs.pop(job_id, None))
            return [{"id": job_id}]

        if "update public.generation_jobs" in s and "set status = 'queued'" in s:
            job = db.jobs[args[0]]
            previous = dict(job)
            self._undo.append(lambda: job.update(previous))
            job.update(status="queued", credits_reserved=args[2], credits_charged=0, asset_id=None)
            return []

        # --- catálogo y assets ---
        if "from public.gen_models where id = $1" in s:
            model = db.models.get(args[0])
            return [model] if model else []

        if "from public.gen_models" in s:
            return list(db.models.values())

        if "from public.assets where id = $1" in s:
            asset = db.assets.get(args[0])
            return [asset] if asset else []

        return []


def install_fake_db(monkeypatch: pytest.MonkeyPatch, db: FakeDB) -> None:
    """
    Sustituye `transaction()` en los módulos que ya lo importaron por nombre.

    Se parchea en cada módulo y no en `app.db` porque `from app.db import transaction`
    resuelve el nombre en tiempo de importación.
    """

    @asynccontextmanager
    async def fake_transaction() -> AsyncIterator[FakeConn]:
        conn = FakeConn(db)
        try:
            yield conn
        except BaseException:
            # Atomicidad: si `enqueue` inserta el job y luego la reserva se queda sin
            # saldo, el job NO debe sobrevivir. Sin esto el fake dejaría pasar un bug
            # que en producción significa una generación gratis.
            await conn.release(rollback=True)
            raise
        else:
            await conn.release()

    for module in (credits, queue, fanout):
        monkeypatch.setattr(module, "transaction", fake_transaction, raising=False)


# --------------------------------------------------------------------------- #
# Andamiaje                                                                    #
# --------------------------------------------------------------------------- #


def seeded_db(credits_available: int = 1000) -> tuple[FakeDB, UUID, UUID]:
    db = FakeDB()
    profile_id, project_id = uuid4(), uuid4()
    db.profiles[profile_id] = {"id": profile_id, "credits": credits_available}
    db.projects[project_id] = {"id": project_id, "owner_id": profile_id}
    db.models["kling-3.0-turbo"] = {
        "id": "kling-3.0-turbo",
        "family": "Kling",
        "provider": "kling",
        "modality": "video",
        "status": "active",
        "cost_per_second": Decimal("0.10"),
        "min_duration_s": None,
        "max_duration_s": 10,
        "resolutions": ["1080p"],
        "aspects": ["16:9"],
        "supports_i2v": True,
        "supports_last_frame": False,
        "supports_char_ref": True,
        "supports_audio": False,
        "description_llm": "modelo de prueba",
    }
    return db, profile_id, project_id


class StubAdapter(GenerationAdapter):
    """Adaptador mínimo. El coste es fijo para que los tests razonen con números redondos."""

    provider_id = "kling"
    supported_modalities = ("video",)
    min_poll_interval_s = 0.0

    def __init__(self, cost_usd: str = "1.00") -> None:
        self.cost_usd = Decimal(cost_usd)
        self.submits = 0

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        self.submits += 1
        return ProviderJobRef(provider=self.provider_id, external_id=f"ext-{self.submits}")

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        return ProviderJobStatus(state="succeeded", output_urls=["https://example/out.mp4"])

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        return self.cost_usd


def a_request(seed: int | None = 7) -> GenerationRequest:
    return GenerationRequest(
        modality="video",
        model_id="kling-3.0-turbo",
        prompt="plano general del desierto al amanecer",
        duration_s=5,
        seed=seed,
    )


# --------------------------------------------------------------------------- #
# 1. Idempotencia                                                              #
# --------------------------------------------------------------------------- #


def test_idempotency_key_is_stable_and_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    La clave depende del contenido, no del orden ni de los ausentes, y está acotada al
    proyecto. Lo último es lo que impide que el asset de un usuario acabe en el proyecto
    de otro por coincidencia de prompt.
    """
    project_a, project_b = uuid4(), uuid4()
    key = queue.compute_idempotency_key(a_request(), provider="kling", project_id=project_a)

    assert key == queue.compute_idempotency_key(
        a_request(), provider="kling", project_id=project_a
    )
    assert key != queue.compute_idempotency_key(
        a_request(), provider="kling", project_id=project_b
    )
    assert key != queue.compute_idempotency_key(a_request(seed=8), provider="kling", project_id=project_a)


def test_same_request_charges_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Encolar dos veces la misma petición reserva una sola vez. La segunda llamada se
    adjunta al job en curso y devuelve `reused=True` sin tocar el saldo.
    """
    db, profile_id, project_id = seeded_db(credits_available=1000)
    install_fake_db(monkeypatch, db)
    adapter = StubAdapter("1.00")

    async def scenario() -> tuple[queue.EnqueueResult, queue.EnqueueResult, int]:
        first = await queue.enqueue(a_request(), project_id=project_id, adapter=adapter)
        second = await queue.enqueue(a_request(), project_id=project_id, adapter=adapter)
        return first, second, await credits.balance(profile_id)

    first, second, balance = run(scenario())

    assert first.reused is False
    assert second.reused is True
    assert second.job_id == first.job_id
    assert second.credits_reserved == 0
    assert len(db.jobs) == 1, "no debe crearse un segundo job para la misma petición"
    # 1.00 USD * 100 créditos/USD * 1.6 de margen = 160 créditos, cobrados una sola vez.
    assert first.credits_reserved == 160
    assert balance == 1000 - 160


def test_succeeded_job_returns_cached_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Un job ya terminado con éxito devuelve su asset sin reservar nada. Es el camino que
    convierte los 10 reintentos de webhook de fal en 10 respuestas gratis.
    """
    db, profile_id, project_id = seeded_db()
    install_fake_db(monkeypatch, db)
    adapter = StubAdapter("1.00")

    async def scenario() -> tuple[queue.EnqueueResult, int]:
        first = await queue.enqueue(a_request(), project_id=project_id, adapter=adapter)

        # Simula el aterrizaje del worker: asset escrito y job cerrado.
        asset_id = uuid4()
        db.assets[asset_id] = {
            "id": asset_id,
            "type": "video",
            "status": "ready",
            "shot_id": "shot-1",
        }
        job = db.jobs[UUID(first.job_id)]
        job.update(status="succeeded", asset_id=asset_id)

        balance_before = await credits.balance(profile_id)
        again = await queue.enqueue(a_request(), project_id=project_id, adapter=adapter)
        assert await credits.balance(profile_id) == balance_before
        return again, balance_before

    again, _ = run(scenario())

    assert again.reused is True
    assert again.is_cached is True
    assert again.credits_reserved == 0
    assert again.asset is not None and again.asset.status == "ready"


# --------------------------------------------------------------------------- #
# 2. Reembolso                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", ["failed", "nsfw", "cancelled"])
def test_refund_returns_everything(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    """
    En los tres estados que `should_refund` marca, el neto del job queda en cero y el
    saldo vuelve al valor original. Cero, no "casi cero": una reserva parcialmente
    devuelta es dinero que desaparece sin traza.
    """
    assert ProviderJobStatus(state=state).should_refund is True  # type: ignore[arg-type]

    db, profile_id, project_id = seeded_db(credits_available=500)
    install_fake_db(monkeypatch, db)
    adapter = StubAdapter("1.00")

    async def scenario() -> tuple[int, int, int]:
        result = await queue.enqueue(a_request(), project_id=project_id, adapter=adapter)
        after_reserve = await credits.balance(profile_id)
        await credits.refund(job_id=result.job_id, reason=state)
        return after_reserve, await credits.balance(profile_id), await credits.job_net(result.job_id)

    after_reserve, after_refund, net = run(scenario())

    assert after_reserve == 500 - 160
    assert after_refund == 500
    assert net == 0


def test_refund_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Los webhooks se reintentan hasta 10 veces. El segundo reembolso no debe regalar
    créditos, y el `charge` posterior no debe cobrar un job ya reembolsado.
    """
    db, profile_id, project_id = seeded_db(credits_available=500)
    install_fake_db(monkeypatch, db)
    adapter = StubAdapter("1.00")

    async def scenario() -> int:
        result = await queue.enqueue(a_request(), project_id=project_id, adapter=adapter)
        for _ in range(5):
            await credits.refund(job_id=result.job_id, reason="webhook duplicado")
        # Un cobro tardío tras el reembolso tampoco debe mover nada.
        await credits.charge(job_id=result.job_id, final_credits=160)
        return await credits.balance(profile_id)

    assert run(scenario()) == 500


def test_charge_is_idempotent_and_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Cobrar varias veces cobra una. Y no se puede cobrar por encima de lo reservado: la
    reserva es el contrato con el usuario, y superarla sería gastar sin aprobación.
    """
    db, profile_id, project_id = seeded_db(credits_available=500)
    install_fake_db(monkeypatch, db)
    adapter = StubAdapter("1.00")

    async def scenario() -> tuple[int, int]:
        result = await queue.enqueue(a_request(), project_id=project_id, adapter=adapter)
        await credits.charge(job_id=result.job_id, final_credits=99_999)
        await credits.charge(job_id=result.job_id, final_credits=99_999)
        return await credits.balance(profile_id), await credits.job_net(result.job_id)

    balance, net = run(scenario())
    assert balance == 500 - 160
    assert net == -160


# --------------------------------------------------------------------------- #
# 3. No-doble-gasto concurrente                                                #
# --------------------------------------------------------------------------- #


def test_concurrent_enqueue_cannot_overspend(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Saldo para un solo job, dos peticiones **distintas** lanzadas a la vez: exactamente
    una pasa.

    Peticiones distintas a propósito (semillas distintas): con la misma, la idempotencia
    resolvería el caso y no se estaría probando el cerrojo. Aquí no hay clave compartida,
    así que lo único que impide que ambas encolen es el `SELECT ... FOR UPDATE` sobre el
    perfil.

    Este test falla si se quita el cerrojo del código de producción, que es la razón de
    que exista.
    """
    db, profile_id, project_id = seeded_db(credits_available=200)  # alcanza para uno de 160
    install_fake_db(monkeypatch, db)
    adapter = StubAdapter("1.00")

    async def scenario() -> list[Any]:
        return await asyncio.gather(
            queue.enqueue(a_request(seed=1), project_id=project_id, adapter=adapter),
            queue.enqueue(a_request(seed=2), project_id=project_id, adapter=adapter),
            return_exceptions=True,
        )

    outcomes = run(scenario())

    ok = [o for o in outcomes if isinstance(o, queue.EnqueueResult)]
    rejected = [o for o in outcomes if isinstance(o, InsufficientCreditsError)]

    assert len(ok) == 1, f"se encolaron {len(ok)} jobs con saldo para uno solo"
    assert len(rejected) == 1
    assert run(credits.balance(profile_id)) == 200 - 160 >= 0


def test_reserve_rejects_when_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin saldo no se encola, y el error lleva las cifras para que el agente las diga."""
    db, profile_id, project_id = seeded_db(credits_available=10)
    install_fake_db(monkeypatch, db)

    with pytest.raises(InsufficientCreditsError) as exc:
        run(queue.enqueue(a_request(), project_id=project_id, adapter=StubAdapter("1.00")))

    assert exc.value.needed == 160
    assert exc.value.available == 10
    assert db.jobs == {}, "un encolado rechazado no debe dejar el job insertado"


# --------------------------------------------------------------------------- #
# 4. Aislamiento del fan-out                                                   #
# --------------------------------------------------------------------------- #


def test_failing_child_does_not_cancel_siblings() -> None:
    """
    El test que justifica todo el diseño de `fanout`.

    Un plano lanza una excepción; los otros cuatro deben completarse igual. Si `_run_one`
    dejara escapar la excepción, `TaskGroup` cancelaría a las hermanas y aquí veríamos
    menos de cinco resultados — con la particularidad de que en producción esos planos
    cancelados ya estarían pagados al proveedor.
    """
    shots = [fanout.ShotSpec(shot_id=f"shot-{i}") for i in range(5)]
    completed: list[str] = []

    async def runner(shot: fanout.ShotSpec) -> JobResult:
        if shot.shot_id == "shot-2":
            raise ProviderError("kling", "el proveedor se cayó a mitad")
        # El resto tarda más que el que falla: sin aislamiento, no llegarían a terminar.
        await asyncio.sleep(0.05)
        completed.append(shot.shot_id)
        return JobResult(job_id=shot.shot_id, shot_id=shot.shot_id, ok=True, credits_charged=10)

    async def scenario() -> list[JobResult]:
        return [
            r
            async for r in fanout.stream_fanout(shots, runner, failed_shots_min_ratio=0.0)
        ]

    results = run(scenario())

    assert len(results) == 5, "se perdieron resultados: una hermana fue cancelada"
    assert sorted(completed) == ["shot-0", "shot-1", "shot-3", "shot-4"]

    failed = [r for r in results if not r.ok]
    assert len(failed) == 1 and failed[0].shot_id == "shot-2"
    assert "kling" in (failed[0].error or "")
    assert sum(r.credits_charged for r in results if r.ok) == 40


def test_results_arrive_in_completion_order() -> None:
    """
    Orden de finalización, no de envío. Es lo que hace que el usuario vea el primer plano
    a los diez segundos en vez de a los cuatro minutos.
    """
    delays = {"lento": 0.15, "medio": 0.08, "rapido": 0.01}
    shots = [fanout.ShotSpec(shot_id=name) for name in ("lento", "medio", "rapido")]

    async def runner(shot: fanout.ShotSpec) -> JobResult:
        await asyncio.sleep(delays[shot.shot_id])
        return JobResult(job_id=shot.shot_id, shot_id=shot.shot_id, ok=True)

    async def scenario() -> list[str]:
        return [
            r.shot_id or ""
            async for r in fanout.stream_fanout(shots, runner, failed_shots_min_ratio=0.0)
        ]

    assert run(scenario()) == ["rapido", "medio", "lento"]


def test_loop_variable_is_captured_per_shot() -> None:
    """
    Cada tarea recibe SU plano.

    Sin el argumento por defecto en la closure, las N cierran sobre la misma variable y
    todas ejecutan el último plano: N renders idénticos, cobrados N veces. El bug es
    silencioso —no hay excepción, solo resultados repetidos—, así que se comprueba.
    """
    shots = [fanout.ShotSpec(shot_id=f"shot-{i}") for i in range(6)]
    seen: list[str] = []

    async def runner(shot: fanout.ShotSpec) -> JobResult:
        seen.append(shot.shot_id)
        return JobResult(job_id=shot.shot_id, shot_id=shot.shot_id, ok=True)

    async def scenario() -> None:
        async for _ in fanout.stream_fanout(shots, runner, failed_shots_min_ratio=0.0):
            pass

    run(scenario())
    assert sorted(seen) == sorted(s.shot_id for s in shots)


def test_batch_aborts_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Si falla demasiada parte del lote se aborta y se limpian los assets parciales. Medio
    storyboard no le sirve al usuario, y las filas sueltas ensucian el canvas.

    El aborto llega **después** de haber emitido todos los resultados: el agente necesita
    verlos para explicar qué pasó.
    """
    shots = [fanout.ShotSpec(shot_id=f"shot-{i}") for i in range(4)]
    cleaned: list[list[str]] = []

    async def fake_cleanup(asset_ids: Any) -> int:
        cleaned.append([str(a) for a in asset_ids])
        return len(list(asset_ids))

    monkeypatch.setattr(fanout, "cleanup_partial_assets", fake_cleanup)

    async def runner(shot: fanout.ShotSpec) -> JobResult:
        if shot.shot_id == "shot-0":
            from app.agent.state import AssetRef

            return JobResult(
                job_id="j0",
                shot_id=shot.shot_id,
                ok=True,
                asset=AssetRef(asset_id="asset-0", kind="video", status="ready"),
            )
        raise ProviderError("kling", "sin capacidad")

    async def scenario() -> tuple[list[JobResult], fanout.FanoutAborted | None]:
        seen: list[JobResult] = []
        try:
            async for r in fanout.stream_fanout(shots, runner, failed_shots_min_ratio=0.5):
                seen.append(r)
        except fanout.FanoutAborted as exc:
            return seen, exc
        return seen, None

    seen, aborted = run(scenario())

    assert aborted is not None, "1 de 4 está por debajo del 50 % exigido"
    assert len(seen) == 4, "el consumidor debe recibir todos los resultados antes del aborto"
    assert cleaned == [["asset-0"]], "el asset del plano válido debe limpiarse"


def test_report_variant_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    `run_fanout` degrada el aborto a un informe. Un nodo del grafo no debe tumbar el turno
    entero porque un lote saliera mal: el agente tiene que poder contarlo.
    """
    monkeypatch.setattr(fanout, "cleanup_partial_assets", lambda ids: _zero())

    async def runner(shot: fanout.ShotSpec) -> JobResult:
        raise ProviderError("kling", "caído")

    report = run(
        fanout.run_fanout(
            [fanout.ShotSpec(shot_id="a"), fanout.ShotSpec(shot_id="b")],
            runner,
            failed_shots_min_ratio=0.5,
        )
    )

    assert report.aborted is True
    assert report.abort_reason is not None
    assert len(report.failed) == 2
    assert report.credits_charged == 0


async def _zero() -> int:
    return 0


# --------------------------------------------------------------------------- #
# Conversión de coste                                                          #
# --------------------------------------------------------------------------- #


def test_usd_to_credits_rounds_up_and_has_a_floor() -> None:
    """
    Hacia arriba y con suelo de 1. Redondear hacia abajo acumula pérdida en cada job y
    siempre en nuestra contra; permitir el 0 crea una generación gratis repetible contra
    una API que sí nos cobra.
    """
    assert credits.usd_to_credits(Decimal("1.00")) == 160
    assert credits.usd_to_credits(Decimal("0.001")) == 1
    assert credits.usd_to_credits(Decimal("0")) == 1
    # 0.03 USD * 100 * 1.6 = 4.8 créditos exactos. Hacia abajo serían 4, y esos 0.8
    # perdidos por job son la fuga silenciosa que este redondeo evita.
    assert credits.usd_to_credits(Decimal("0.03")) == 5
