"""
Tests de los caminos del worker en los que se pierde dinero de verdad.

Todos los de este fichero comparten una propiedad y por eso están juntos: **fallan
costando dinero, no lanzando excepciones**. Un job que se genera dos veces, un timeout
que reembolsa sin cancelar, un barrido que devuelve el importe de un plano ya entregado.
Ninguno produce un error visible; los tres producen una factura.

Cada test está escrito para fallar si se revierte el arreglo concreto que lo motivó, y en
el docstring de cada uno se dice qué línea hay que romper para verlo fallar. Un test de
regresión que también pasaría con el bug puesto no vale nada, y en esta clase de bug es
fácil escribir justamente ese.

Sobre el fake de base de datos: emula el subconjunto de SQL de `worker`, `webhooks` y
`credits`, incluidas las **guardas** (`status not in (terminales)`, la condición de
propiedad del webhook). Esa es la parte que importa. Un fake que ignorase los `where`
haría pasar los cuatro tests con los cuatro bugs dentro.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")

from app.jobs import credits, webhooks, worker
from app.providers.base import (
    GenerationAdapter,
    GenerationRequest,
    ModelSpec,
    ProviderJobRef,
    ProviderJobStatus,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


TERMINAL = ("succeeded", "failed", "cancelled", "nsfw")


def _guards_terminal(sql: str) -> bool:
    """
    ¿Lleva esta consulta la guarda de estado terminal?

    El fake **no** debe imponer guardas que la consulta real no tenga. Si las impusiera
    por su cuenta, los tests pasarían igual con el bug puesto: comprobarían el fake, no
    el código. Leyendo la guarda del texto de la consulta, quitarla en producción cambia
    el comportamiento aquí, y el test falla como debe.
    """
    return "status not in ('succeeded','failed','cancelled','nsfw')" in " ".join(sql.split())


def _guards_owner(sql: str) -> bool:
    """Ídem para la condición de propiedad del webhook de éxito."""
    flat = " ".join(sql.split())
    return "provider_ref is null" in flat and "updated_at < now()" in flat


def now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Base de datos falsa                                                          #
# --------------------------------------------------------------------------- #


@dataclass
class FakeDB:
    profiles: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    projects: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    ledger: list[dict[str, Any]] = field(default_factory=list)
    locks: dict[UUID, asyncio.Lock] = field(default_factory=dict)
    after_sweep_select: Any = None
    """
    Se invoca una vez, justo después de que el barrido elija sus filas.

    Es lo que permite reproducir la carrera de verdad: el `select` del barrido ve un job
    vivo, y **antes** de que su `update` lo cierre, el worker legítimo lo termina y lo
    cobra. Sin este hueco el test no prueba nada — un job ya terminal ni siquiera sale
    del `select`, así que la guarda del `update` nunca se ejercita.
    """

    def lock_for(self, profile_id: UUID) -> asyncio.Lock:
        return self.locks.setdefault(profile_id, asyncio.Lock())


class FakeConn:
    """Despacha por subcadenas distintivas, respetando las guardas de estado."""

    def __init__(self, db: FakeDB) -> None:
        self.db = db
        self._held: list[asyncio.Lock] = []

    async def release(self, *, rollback: bool = False) -> None:
        for lock in reversed(self._held):
            lock.release()
        self._held.clear()

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
        await asyncio.sleep(0)
        s = " ".join(q.split())
        db = self.db

        # --- cerrojos y perfiles ---
        if "from public.profiles where id = $1 for update" in s:
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

        if "update public.profiles set credits" in s:
            db.profiles[args[0]]["credits"] = args[1]
            return []

        # --- libro mayor ---
        if "as bal, count(*)::int as n" in s:
            rows = [r for r in db.ledger if r["profile_id"] == args[0]]
            return [{"bal": sum(r["amount"] for r in rows), "n": len(rows)}]

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
                db.ledger.append(
                    {
                        "profile_id": args[0],
                        "project_id": None,
                        "job_id": None,
                        "kind": "grant",
                        "amount": args[1],
                    }
                )
            else:
                db.ledger.append(
                    {
                        "profile_id": args[0],
                        "project_id": args[1],
                        "job_id": args[2],
                        "kind": args[3],
                        "amount": args[4],
                    }
                )
            return []

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
            db.jobs[args[0]]["credits_charged"] = args[1]
            return []

        # --- claim del worker ---
        if "update public.generation_jobs set status = 'submitted'" in s.replace("\n", " "):
            queued = sorted(
                (j for j in db.jobs.values() if j["status"] == "queued"),
                key=lambda j: j["created_at"],
            )
            if not queued:
                return []
            job = queued[0]
            job.update(status="submitted", updated_at=now())
            return [dict(job)]

        # --- webhook: reposición condicionada a la propiedad ---
        if "set status = 'queued', progress = 1" in s:
            job = db.jobs[args[0]]
            if _guards_terminal(s) and job["status"] in TERMINAL:
                return []
            # La condición de propiedad se aplica SOLO si la consulta la lleva. Es lo que
            # convierte este fake en un test de la SQL de producción y no de sí mismo:
            # si alguien quita la guarda del UPDATE, aquí deja de aplicarse y el job se
            # repone, que es justo el bug.
            if _guards_owner(s):
                ref = job.get("provider_ref") or {}
                lease = timedelta(seconds=int(args[1]))
                if bool(ref.get("external_id")) and job["updated_at"] > now() - lease:
                    return []
            job.update(status="queued", progress=1, updated_at=now())
            return [{"id": job["id"]}]

        if "set progress = 1" in s and "generation_jobs" in s:
            job = db.jobs[args[0]]
            if not (_guards_terminal(s) and job["status"] in TERMINAL):
                job["progress"] = 1
            return []

        # --- barrido ---
        if "select id from public.generation_jobs" in s and "for update skip locked" in s:
            cutoff = now() - timedelta(seconds=int(args[0]))
            picked = [
                {"id": j["id"]}
                for j in db.jobs.values()
                if j["status"] in ("queued", "submitted", "running") and j["updated_at"] < cutoff
            ]
            if db.after_sweep_select is not None:
                hook, db.after_sweep_select = db.after_sweep_select, None
                hook()
            return picked

        if "recogido por el barrido" in s:
            job = db.jobs[args[0]]
            # La guarda que faltaba. Solo se aplica si el UPDATE real la lleva.
            if _guards_terminal(s) and job["status"] in TERMINAL:
                return []
            job.update(status="cancelled", updated_at=now())
            return [{"id": job["id"]}]

        # --- escrituras del worker ---
        if "set provider_ref = $2" in s:
            job = db.jobs[args[0]]
            if not (_guards_terminal(s) and job["status"] in TERMINAL):
                job.update(provider_ref=args[1], status="running", updated_at=now())
            return []

        if "select provider_ref from public.generation_jobs" in s:
            job = db.jobs.get(args[0])
            return [{"provider_ref": job.get("provider_ref")}] if job else []

        if "set attempts = coalesce(attempts, 0) + 1" in s:
            job = db.jobs[args[0]]
            job["attempts"] = (job.get("attempts") or 0) + 1
            job["updated_at"] = now()
            return []

        if "set status = $2, error = $3" in s:
            job = db.jobs[args[0]]
            if _guards_terminal(s) and job["status"] in TERMINAL:
                return []
            job.update(status=args[1], error=args[2], updated_at=now())
            return [{"id": job["id"]}]

        if "select id, status, provider, provider_ref" in s:
            for job in db.jobs.values():
                ref = job.get("provider_ref") or {}
                if job["provider"] == args[0] and ref.get("external_id") == args[1]:
                    return [dict(job)]
            return []

        # assets / canvas_nodes / progreso: irrelevantes para el dinero.
        return []


def install_fake_db(monkeypatch: pytest.MonkeyPatch, db: FakeDB) -> None:
    @asynccontextmanager
    async def fake_transaction() -> AsyncIterator[FakeConn]:
        conn = FakeConn(db)
        try:
            yield conn
        except BaseException:
            await conn.release(rollback=True)
            raise
        else:
            await conn.release()

    for module in (credits, worker, webhooks):
        monkeypatch.setattr(module, "transaction", fake_transaction, raising=False)


# --------------------------------------------------------------------------- #
# Andamiaje                                                                    #
# --------------------------------------------------------------------------- #


def seeded(reserved: int = 160, balance: int = 1000) -> tuple[FakeDB, UUID, UUID, UUID]:
    db = FakeDB()
    profile_id, project_id, job_id = uuid4(), uuid4(), uuid4()
    db.profiles[profile_id] = {"id": profile_id, "credits": balance}
    db.projects[project_id] = {"id": project_id, "owner_id": profile_id}
    # El saldo inicial va al libro, que es la fuente de verdad. Sembrarlo solo en
    # `profiles.credits` haría que `_balance_bootstrapped` lo migrase en el primer
    # movimiento y el test mediría el puente de migración en vez de lo que le interesa.
    db.ledger.append(
        {"profile_id": profile_id, "project_id": None, "job_id": None, "kind": "grant", "amount": balance}
    )
    db.jobs[job_id] = {
        "id": job_id,
        "project_id": project_id,
        "conversation_id": None,
        "shot_id": None,
        "provider": "kling",
        "model_id": "kling-3.0-turbo",
        "request": {"modality": "video", "model_id": "kling-3.0-turbo", "prompt": "p"},
        "status": "running",
        "attempts": 1,
        "credits_reserved": reserved,
        "credits_charged": 0,
        "provider_ref": {"provider": "kling", "external_id": "ext-real-42", "poll_url": None},
        "progress": 0.5,
        "created_at": now(),
        "updated_at": now(),
        "error": None,
        "asset_id": None,
    }
    return db, profile_id, project_id, job_id


class NoStorage:
    """
    Storage inerte. Razonar sobre dinero no debe exigir un bucket: el constructor real de
    `SupabaseStorage` pide credenciales de Supabase que en test no existen.
    """

    async def put(self, **kw: Any) -> str:
        return "https://example/stored.mp4"


class StubSettings:
    job_timeout_s = 0.05
    job_poll_interval_s = 0.0
    max_concurrent_jobs_per_project = 6
    # El worker firma las referencias justo antes del submit y pide este TTL. No es un
    # relleno: si el stub no lo declara, el timeout que este test provoca se convierte en
    # un AttributeError y deja de probar lo que dice probar.
    provider_signed_url_ttl_s = 3600


class RecordingAdapter(GenerationAdapter):
    """Registra qué referencia recibió `cancel` — que es justo el bug 2."""

    provider_id = "kling"
    supported_modalities = ("video",)
    min_poll_interval_s = 0.0

    def __init__(self, *, external_id: str = "ext-real-42", hang: bool = False) -> None:
        self.external_id = external_id
        self.hang = hang
        self.submits = 0
        self.cancelled: list[ProviderJobRef] = []

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        self.submits += 1
        return ProviderJobRef(provider=self.provider_id, external_id=self.external_id)

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        if self.hang:
            await asyncio.sleep(10)
        return ProviderJobStatus(state="succeeded", output_urls=["https://example/out.mp4"])

    async def cancel(self, ref: ProviderJobRef) -> None:
        self.cancelled.append(ref)

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        return Decimal("1.00")


class StubRegistry:
    def __init__(self, adapter: GenerationAdapter) -> None:
        self.adapter = adapter

    def get(self, provider_id: str) -> GenerationAdapter:
        return self.adapter

    def for_model(self, model_id: str) -> GenerationAdapter:
        return self.adapter


class FakeRedis:
    """Dedup siempre en blanco: cada entrega se procesa."""

    async def set(self, *a: Any, **kw: Any) -> bool:
        return True


def signed(body: bytes, provider: str = "kling") -> dict[str, str]:
    """
    Cabeceras de firma válidas para este cuerpo.

    Se firma de verdad en vez de pasar `headers={}` porque el secreto de firma depende de
    la configuración del entorno: si otro test deja uno puesto, `verify_signature` empieza
    a exigir cabecera y estos tests se caen por un motivo que no tiene nada que ver con lo
    que prueban. Firmando con el secreto que haya —o con ninguno, si no hay— el test mide
    siempre lo suyo.
    """
    secret = webhooks._secret_for(provider)
    if not secret:
        return {}
    return {"x-webhook-signature": hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


class FakeBus:
    async def publish(self, *a: Any, **kw: Any) -> None:
        return None


# --------------------------------------------------------------------------- #
# 1. El webhook de éxito no repone un job que ya tiene dueño                   #
# --------------------------------------------------------------------------- #


def test_success_webhook_does_not_requeue_an_owned_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    El peor bug de dinero del backend.

    Un job con `provider_ref` y latido fresco tiene un worker vivo poleándolo. Si el
    webhook de éxito lo repone a `queued`, `_claim` lo vuelve a coger, se llama a
    `submit()` por segunda vez y el proveedor genera y factura dos veces (~$21/job en
    Seedance 4K) un plano que el usuario reservó una sola vez.

    Para verlo fallar: quitar de `_apply_terminal` la condición de propiedad
    (`provider_ref is null or updated_at < now() - lease`) del UPDATE. El job vuelve a
    `queued`, `_claim` lo recoge y `submits` pasa a 2.
    """
    db, _, _, job_id = seeded()
    install_fake_db(monkeypatch, db)
    adapter = RecordingAdapter()
    receiver = webhooks.WebhookReceiver(
        registry=StubRegistry(adapter), bus=FakeBus(), redis=FakeRedis()
    )

    async def scenario() -> tuple[webhooks.WebhookOutcome, Any]:
        body = b'{"id": "ext-real-42", "status": "succeeded"}'
        outcome = await receiver.handle(
            "kling",
            headers=signed(body),
            body=body,
            payload={"id": "ext-real-42", "status": "succeeded"},
        )
        # Un worker libre pasa por la cola justo después del webhook.
        claimed = await worker.JobWorker(
            registry=StubRegistry(adapter), storage=NoStorage(), bus=FakeBus()
        )._claim()
        return outcome, claimed

    monkeypatch.setattr(worker, "SupabaseStorage", lambda: None)
    outcome, claimed = run(scenario())

    assert db.jobs[job_id]["status"] == "running", (
        "el job tiene dueño vivo: el webhook no debe devolverlo a la cola"
    )
    assert claimed is None, "un segundo worker reclamó el job y lo va a volver a enviar"
    assert outcome.applied is False
    assert outcome.reason is not None and "dueño" in outcome.reason
    # El progreso sí se anota: es lo único útil que el webhook aporta aquí.
    assert db.jobs[job_id]["progress"] == 1


def test_success_webhook_does_requeue_an_abandoned_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    La otra mitad del arreglo, y sin ella el arreglo sería una regresión.

    Si el worker murió tras enviar al proveedor, el render está pagado y nadie lo va a
    descargar. Ahí reponer a `queued` es exactamente lo que rescata el dinero. La
    diferencia con el test anterior es un solo dato: el latido caducado.
    """
    db, _, _, job_id = seeded()
    db.jobs[job_id]["updated_at"] = now() - timedelta(seconds=webhooks.OWNER_LEASE_S + 60)
    install_fake_db(monkeypatch, db)
    receiver = webhooks.WebhookReceiver(
        registry=StubRegistry(RecordingAdapter()), bus=FakeBus(), redis=FakeRedis()
    )

    body = b'{"id": "ext-real-42"}'
    outcome = run(
        receiver.handle("kling", headers=signed(body), body=body, payload={"id": "ext-real-42"})
    )

    assert db.jobs[job_id]["status"] == "queued"
    assert outcome.applied is True


# --------------------------------------------------------------------------- #
# 2. El cancel del timeout lleva la referencia real                            #
# --------------------------------------------------------------------------- #


def test_timeout_cancels_with_the_real_external_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Pérdida doble: reembolsamos al usuario y el proveedor nos cobra el render entero.

    Cancelar con `external_id=""` es cancelar un trabajo que no existe. El proveedor
    sigue renderizando y factura, el usuario recibe su reembolso y el vídeo no se
    descarga nunca. Nadie ve un error.

    Para verlo fallar: volver a poner
    `adapter.cancel(ProviderJobRef(provider=job.provider, external_id=""))`.
    """
    db, profile_id, _, job_id = seeded(reserved=160, balance=1000)
    db.jobs[job_id]["status"] = "queued"
    install_fake_db(monkeypatch, db)
    monkeypatch.setattr(worker, "get_settings", lambda: StubSettings())

    adapter = RecordingAdapter(external_id="ext-real-42", hang=True)
    # La reserva ya está hecha, como tras `enqueue`.
    db.ledger.append(
        {"profile_id": profile_id, "project_id": None, "job_id": job_id, "kind": "reserve", "amount": -160}
    )

    w = worker.JobWorker(registry=StubRegistry(adapter), storage=NoStorage(), bus=FakeBus())

    async def scenario() -> None:
        job = await w._claim()
        assert job is not None
        await w._process(job)

    run(scenario())

    assert adapter.cancelled, "no se llamó a cancel: el proveedor sigue renderizando y cobrando"
    ref = adapter.cancelled[0]
    assert ref.external_id == "ext-real-42", (
        f"se canceló con external_id={ref.external_id!r}: el proveedor no reconoce ese "
        "trabajo, lo termina y nos lo factura"
    )
    assert db.jobs[job_id]["status"] == "cancelled"
    # Y el usuario recuperó su dinero, que es la mitad que ya funcionaba.
    assert run(credits.balance(profile_id)) == 1000


def test_timeout_recovers_the_ref_from_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    La referencia se rescata de `provider_ref` aunque este worker no la tenga en memoria.

    Es el caso del worker que retoma un job ajeno, o del timeout que cae entre el submit
    y su retorno: el trabajo está enviado y pagado, y sin leerlo de base de datos no hay
    forma de cancelarlo.
    """
    db, _, _, job_id = seeded()
    install_fake_db(monkeypatch, db)
    w = worker.JobWorker(registry=StubRegistry(RecordingAdapter()), storage=NoStorage(), bus=FakeBus())

    job = worker.ClaimedJob(
        id=job_id,
        project_id=db.jobs[job_id]["project_id"],
        conversation_id=None,
        shot_id=None,
        provider="kling",
        model_id="kling-3.0-turbo",
        request={},
        attempts=1,
        credits_reserved=160,
    )
    ref = run(w._load_ref(job))

    assert ref is not None and ref.external_id == "ext-real-42"

    # Sin referencia persistida no se inventa ninguna: devolver un ref vacío sería
    # volver al bug por otro camino.
    db.jobs[job_id]["provider_ref"] = None
    assert run(w._load_ref(job)) is None


# --------------------------------------------------------------------------- #
# 3. Backpressure del claim                                                    #
# --------------------------------------------------------------------------- #


def test_claim_respects_free_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Reclamar es un acto contable, no solo de planificación.

    Sin freno, el worker reclama los 200 jobs de la cola en segundos: todos pasan a
    `submitted` con el `updated_at` congelado esperando el semáforo, `sweep_stale` los da
    por muertos y los reembolsa, y después el semáforo se libera y se ejecutan y se pagan
    igual. Vídeo entregado, proveedor cobrado, dinero devuelto.

    Para verlo fallar: quitar la guarda `if not self._has_capacity()` de `run_forever`.
    Se reclaman los diez jobs en vez de dos.
    """
    db = FakeDB()
    profile_id, project_id = uuid4(), uuid4()
    db.profiles[profile_id] = {"id": profile_id, "credits": 10_000}
    db.projects[project_id] = {"id": project_id, "owner_id": profile_id}
    for i in range(10):
        job_id = uuid4()
        db.jobs[job_id] = {
            "id": job_id,
            "project_id": project_id,
            "conversation_id": None,
            "shot_id": None,
            "provider": "kling",
            "model_id": "m",
            "request": {},
            "status": "queued",
            "attempts": 0,
            "credits_reserved": 10,
            "credits_charged": 0,
            "provider_ref": None,
            "progress": None,
            "created_at": now() + timedelta(seconds=i),
            "updated_at": now(),
            "error": None,
            "asset_id": None,
        }
    install_fake_db(monkeypatch, db)
    monkeypatch.setattr(worker, "get_settings", lambda: StubSettings())

    w = worker.JobWorker(
        registry=StubRegistry(RecordingAdapter()),
        storage=NoStorage(),
        bus=FakeBus(),
        max_provider_concurrency=2,
        max_inflight=2,
    )

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_process(job: Any) -> None:
        started.set()
        await release.wait()  # ocupa la capacidad hasta que el test la suelte

    monkeypatch.setattr(w, "_process", blocking_process)

    async def scenario() -> int:
        loop = asyncio.create_task(w.run_forever(poll_idle_s=0.01))
        await started.wait()
        await asyncio.sleep(0.15)  # tiempo de sobra para vaciar la cola si no hay freno

        # Se mide ANTES de soltar: lo que importa es cuánto llegó a reclamar mientras la
        # capacidad estaba ocupada.
        claimed = sum(1 for j in db.jobs.values() if j["status"] != "queued")

        # Drenaje ordenado. Sin esto, el test se cuelga en vez de fallar cuando la guarda
        # no está — y un test que se cuelga no informa de nada.
        await w.stop()
        release.set()
        await asyncio.wait_for(loop, timeout=5)
        return claimed

    claimed = run(scenario())

    assert claimed <= 2, (
        f"se reclamaron {claimed} jobs con capacidad para 2: los sobrantes quedan en "
        "'submitted' con el latido parado y el barrido los reembolsará"
    )


# --------------------------------------------------------------------------- #
# 4. El barrido no reembolsa un job ya entregado                               #
# --------------------------------------------------------------------------- #


def test_sweep_does_not_refund_a_job_that_succeeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Carrera con dinero dentro: entre el `select` del barrido y su `update`, el worker
    legítimo termina el job, escribe el asset y lo cobra. Sin la guarda de terminalidad,
    el barrido pisa ese `succeeded` con un `cancelled` y encima reembolsa: el usuario se
    queda con el vídeo y con el dinero, y el proveedor nos lo ha cobrado.

    Para verlo fallar: quitar `and status not in ('succeeded',...)` del UPDATE de
    `sweep_stale`, o reembolsar sin comprobar que el UPDATE afectó a la fila.
    """
    db, profile_id, _, job_id = seeded(reserved=160, balance=1000)
    install_fake_db(monkeypatch, db)

    job = db.jobs[job_id]
    job["updated_at"] = now() - timedelta(seconds=worker.STALE_AFTER_S + 60)
    db.ledger.append(
        {"profile_id": profile_id, "project_id": None, "job_id": job_id, "kind": "reserve", "amount": -160}
    )

    def worker_lands_the_asset() -> None:
        """El worker legítimo cierra y cobra el job entre el select y el update."""
        job["status"] = "succeeded"
        db.ledger.append(
            {
                "profile_id": profile_id,
                "project_id": None,
                "job_id": job_id,
                "kind": "charge",
                "amount": 0,
            }
        )

    db.after_sweep_select = worker_lands_the_asset

    swept = run(worker.sweep_stale(older_than_s=worker.STALE_AFTER_S))

    assert swept == 0, "el barrido cerró un job que ya estaba entregado"
    assert db.jobs[job_id]["status"] == "succeeded", "el barrido revirtió un estado terminal"
    assert run(credits.balance(profile_id)) == 1000 - 160, (
        "se reembolsó un plano que el usuario ya tiene: el proveedor nos lo cobró y "
        "nosotros hemos devuelto el importe"
    )


def test_sweep_still_refunds_a_genuinely_dead_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    El barrido tiene que seguir haciendo su trabajo: un job sin latido y no terminal es
    una reserva congelada que nadie va a liberar. La guarda acota el barrido, no lo anula.
    """
    db, profile_id, _, job_id = seeded(reserved=160, balance=1000)
    install_fake_db(monkeypatch, db)
    db.jobs[job_id]["updated_at"] = now() - timedelta(seconds=worker.STALE_AFTER_S + 60)
    db.ledger.append(
        {"profile_id": profile_id, "project_id": None, "job_id": job_id, "kind": "reserve", "amount": -160}
    )

    swept = run(worker.sweep_stale(older_than_s=worker.STALE_AFTER_S))

    assert swept == 1
    assert db.jobs[job_id]["status"] == "cancelled"
    assert run(credits.balance(profile_id)) == 1000


# --------------------------------------------------------------------------- #
# 5. Cobro por debajo de la reserva cuando el proveedor declara el coste       #
# --------------------------------------------------------------------------- #


def test_final_credits_uses_the_reported_cost_when_there_is_one() -> None:
    """
    El delta de `charge()` era código muerto porque siempre se le pasaba la reserva. La
    reserva es un techo, no un precio: si el proveedor dice lo que costó y costó menos,
    la diferencia vuelve al usuario.
    """
    w = worker.JobWorker.__new__(worker.JobWorker)
    job = worker.ClaimedJob(
        id=uuid4(),
        project_id=uuid4(),
        conversation_id=None,
        shot_id=None,
        provider="kling",
        model_id="m",
        request={},
        attempts=1,
        credits_reserved=160,
    )

    # 0.50 USD * 100 créditos/USD * 1.6 de margen = 80 créditos, la mitad de la reserva.
    reported = ProviderJobStatus(state="succeeded", raw={"cost_usd": "0.50"})
    assert worker.JobWorker._final_credits(w, job, reported) == 80

    # Anidado bajo un envoltorio habitual.
    assert worker.JobWorker._final_credits(
        w, job, ProviderJobStatus(state="succeeded", raw={"usage": {"cost": 0.50}})
    ) == 80

    # Sin dato: se cobra la reserva, que es lo que el usuario aprobó.
    assert worker.JobWorker._final_credits(
        w, job, ProviderJobStatus(state="succeeded", raw={})
    ) == 160

    # Nunca por encima de la reserva, aunque el proveedor diga que costó más.
    assert worker.JobWorker._final_credits(
        w, job, ProviderJobStatus(state="succeeded", raw={"cost_usd": "99.0"})
    ) == 160

    # Nunca a cero: una generación gratis repetible contra una API de pago.
    assert worker.JobWorker._final_credits(
        w, job, ProviderJobStatus(state="succeeded", raw={"cost_usd": "0"})
    ) == 1

    # Basura o valores absurdos no se interpretan: se cae al camino seguro.
    for raw in ({"cost_usd": "no-soy-un-numero"}, {"cost_usd": -3}, {"cost_usd": True}):
        assert worker.JobWorker._final_credits(
            w, job, ProviderJobStatus(state="succeeded", raw=raw)
        ) == 160


# --------------------------------------------------------------------------- #
# 6. Recarga de créditos                                                       #
# --------------------------------------------------------------------------- #


def test_grant_survives_the_profile_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    El bug que bloqueaba integrar pagos: `_mirror_profile_credits` sobrescribe
    `profiles.credits` con la suma del libro en cada movimiento, así que una recarga
    aplicada directamente sobre la columna se evapora en el siguiente gasto del usuario.
    `grant()` escribe en el libro, y por eso sobrevive.
    """
    db, profile_id, _project_id, job_id = seeded(reserved=160, balance=1000)
    install_fake_db(monkeypatch, db)
    db.ledger.append(
        {"profile_id": profile_id, "project_id": None, "job_id": job_id, "kind": "reserve", "amount": -160}
    )

    async def scenario() -> tuple[int, int]:
        # Recarga "a mano" sobre la columna espejo, tal y como saldría de un webhook de
        # pago mal integrado.
        db.profiles[profile_id]["credits"] += 500
        # Cualquier movimiento posterior la borra.
        await credits.refund(job_id=job_id, reason="fallo del proveedor")
        naive = db.profiles[profile_id]["credits"]

        # La misma recarga por el camino bueno.
        await credits.grant(profile_id, 500, note="stripe pi_3QtestABC")
        return naive, await credits.balance(profile_id)

    naive, balance = run(scenario())

    assert naive == 1000, "la recarga directa sobre profiles.credits se perdió, como debía"
    assert balance == 1500, "grant() debe sobrevivir al espejo"
    assert db.profiles[profile_id]["credits"] == 1500, "el espejo refleja el libro"
    assert any(r["kind"] == "grant" and r["amount"] == 500 for r in db.ledger)


def test_grant_demands_an_auditable_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un abono sin procedencia es indistinguible de un error de contabilidad."""
    db, profile_id, _, _ = seeded()
    install_fake_db(monkeypatch, db)

    with pytest.raises(ValueError):
        run(credits.grant(profile_id, 100, note="   "))
    with pytest.raises(ValueError):
        run(credits.grant(profile_id, -100, note="devolución"))


# --------------------------------------------------------------------------- #
# 7. Reintentos anidados y jitter                                              #
# --------------------------------------------------------------------------- #


def test_submit_is_not_retried_on_top_of_the_http_layer() -> None:
    """
    4 intentos de `_http.py` x 3 del worker = 12 submits por job, y un fan-out de 12 son
    144 peticiones contra un proveedor caído — cada una facturable si llega a cursar.
    Una sola política de reintento, y vive en la capa HTTP.
    """
    assert worker.SUBMIT_ATTEMPTS == 1, (
        "reintentar el submit aquí multiplica con el reintento de la capa HTTP"
    )


def test_jitter_matches_the_http_layer() -> None:
    """
    Con un 25 % los doce planos de un fan-out reintentan dentro de una ventana estrecha:
    siguen llegando en ráfaga y vuelven a provocar el rate limit que los frenó.
    """
    assert worker.JITTER_RATIO == 1.0


# --------------------------------------------------------------------------- #
# 8. Contador de intentos                                                      #
# --------------------------------------------------------------------------- #


def test_bump_attempts_accumulates(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    `attempts = attempt` machacaba el histórico: un job reintentado, caído y retomado por
    otro worker volvía a marcar 1. La columna dejaba de distinguir el job que falló una
    vez del que lleva ocho quemando dinero.
    """
    db, _, _, job_id = seeded()
    install_fake_db(monkeypatch, db)
    db.jobs[job_id]["attempts"] = 3

    w = worker.JobWorker(registry=StubRegistry(RecordingAdapter()), storage=NoStorage(), bus=FakeBus())
    run(w._bump_attempts(job_id))

    assert db.jobs[job_id]["attempts"] == 4


# --------------------------------------------------------------------------- #
# 9. Semáforos acotados                                                        #
# --------------------------------------------------------------------------- #


def test_semaphore_caches_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    `_project_sem` crece una entrada por proyecto y no la suelta jamás. Es una fuga lenta
    y monótona, y un proceso que solo se reinicia al quedarse sin memoria se reinicia
    siempre en el peor momento.
    """
    monkeypatch.setattr(worker, "get_settings", lambda: StubSettings())
    w = worker.JobWorker(registry=StubRegistry(RecordingAdapter()), storage=NoStorage(), bus=FakeBus())

    async def scenario() -> None:
        for _ in range(worker.MAX_SEM_ENTRIES + 50):
            w._sem_for_project(uuid4())

    run(scenario())
    assert len(w._project_sem) <= worker.MAX_SEM_ENTRIES + 1


def test_semaphores_in_use_are_never_evicted(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    La evicción solo puede tocar semáforos libres. Soltar uno tomado rompería la
    exclusión mutua que impide que un proyecto monopolice la cola.
    """
    monkeypatch.setattr(worker, "get_settings", lambda: StubSettings())
    w = worker.JobWorker(registry=StubRegistry(RecordingAdapter()), storage=NoStorage(), bus=FakeBus())
    busy_id = uuid4()

    async def scenario() -> bool:
        sem = w._sem_for_project(busy_id)
        # Se agota: queda `locked()` y por tanto intocable para la evicción.
        for _ in range(StubSettings.max_concurrent_jobs_per_project):
            await sem.acquire()
        for _ in range(worker.MAX_SEM_ENTRIES + 50):
            w._sem_for_project(uuid4())
        return w._project_sem.get(busy_id) is sem

    assert run(scenario()) is True
