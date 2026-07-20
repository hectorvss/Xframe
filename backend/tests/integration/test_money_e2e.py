"""
Los escenarios de dinero que un fake no puede cubrir.

La auditoría dio por buena la contabilidad de créditos y la idempotencia del encolado —y
lo son—, pero señaló que ambas se habían validado contra un doble en memoria. Eso deja sin
comprobar exactamente las propiedades por las que están escritas así:

- `SELECT ... FOR UPDATE` sobre `profiles` solo serializa si hay un Postgres que serialice.
  En un fake, dos corrutinas que "toman el cerrojo" no se bloquean entre sí, así que el
  test de doble cobro pasa aunque el cerrojo no estuviera.
- La `unique` sobre `idempotency_key` no existe en un dict; su papel de última red ante
  una carrera es indemostrable sin la restricción real.
- El invariante "la suma del libro de un job reembolsado es 0" se comprueba con una
  consulta de agregación, que en un fake es una comprensión de listas escrita por quien
  escribió el código que se está probando.

Por eso este fichero exige Postgres y se salta si no lo hay, en lugar de degradar.
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import pytest

from tests.integration.conftest import Seed, wait_for_job

pytestmark = pytest.mark.integration


def _request(seed: Seed, prompt: str = "Marta entra en el bar, contraluz") -> Any:
    from app.providers.base import GenerationRequest

    return GenerationRequest(
        modality="video",
        model_id=seed.video_model,
        prompt=prompt,
        duration_s=6,
        aspect="16:9",
    )


async def test_dos_enqueue_identicos_concurrentes_cobran_una_vez(
    db: Any, seed: Seed, adapter: Any
) -> None:
    """
    Dos peticiones idénticas y simultáneas producen un job y una reserva, no dos.

    Es el caso real del usuario que pulsa dos veces, del frontend que reintenta al
    reconectar y del LLM que repite una tool call tras compactar el historial. El
    mecanismo que lo impide es el orden cerrojo → consulta dentro de `enqueue()`: si la
    consulta por clave de idempotencia se hiciera antes de tomar el cerrojo del perfil,
    ambas concluirían a la vez que no existe nada y encolarían dos veces.

    Se lanzan de verdad en paralelo con `gather` sobre conexiones distintas del pool.
    Serializadas, este test pasaría aunque el cerrojo no estuviera.
    """
    from app.jobs import credits
    from app.jobs.queue import enqueue

    saldo_inicial = await credits.balance(seed.user_id)

    primero, segundo = await asyncio.gather(
        enqueue(_request(seed), project_id=seed.project_id, adapter=adapter),
        enqueue(_request(seed), project_id=seed.project_id, adapter=adapter),
    )

    assert primero.idempotency_key == segundo.idempotency_key
    assert primero.job_id == segundo.job_id, (
        "Dos peticiones idénticas crearon jobs distintos: la decisión de reutilizar se "
        "está tomando fuera del cerrojo del perfil."
    )

    jobs = await db.fetchval(
        "select count(*) from public.generation_jobs where project_id = $1::uuid", seed.project_id
    )
    assert jobs == 1

    # Solo una de las dos reservó; la otra se adjuntó al job en curso.
    reservas = sorted([primero.credits_reserved, segundo.credits_reserved])
    assert reservas[0] == 0 and reservas[1] > 0, f"reservas={reservas}"

    filas = await db.fetchval(
        "select count(*) from public.credit_ledger where job_id = $1::uuid and kind = 'reserve'",
        primero.job_id,
    )
    assert filas == 1, f"Se escribieron {filas} reservas para el mismo job"

    cobrado = saldo_inicial - await credits.balance(seed.user_id)
    assert cobrado == reservas[1], (
        f"Se retiraron {cobrado} créditos por una sola generación de {reservas[1]}. "
        f"El usuario ha pagado el vídeo dos veces."
    )


async def test_el_unique_de_idempotencia_aguanta_una_carrera_real(
    db: Any, seed: Seed, adapter: Any
) -> None:
    """
    La `unique` sobre `idempotency_key` es la última red, y aquí se comprueba que existe.

    `enqueue()` no debería llegar nunca a apoyarse en ella: el cerrojo del perfil resuelve
    la carrera antes. Pero un `INSERT` que se colara por otro camino —una migración, un
    script de reproceso, un bug futuro— tiene que rebotar contra la base de datos, no
    duplicar un cobro en silencio.

    Se inserta a pelo y en paralelo, saltándose el cerrojo a propósito: es la única forma
    de ejercitar la restricción en vez del código que la evita.
    """
    from app.jobs.queue import compute_idempotency_key

    clave = compute_idempotency_key(
        _request(seed), provider=adapter.provider_id, project_id=seed.project_id
    )

    async def insertar() -> str | None:
        try:
            async with db.transaction() as conn:
                return str(
                    await conn.fetchval(
                        """
                        insert into public.generation_jobs
                            (project_id, provider, model_id, request, idempotency_key, status)
                        values ($1::uuid, 'fake', $2, '{}'::jsonb, $3, 'queued')
                        returning id
                        """,
                        seed.project_id,
                        seed.video_model,
                        clave,
                    )
                )
        except asyncpg.UniqueViolationError:
            return None

    resultados = await asyncio.gather(insertar(), insertar())

    assert sorted(r is None for r in resultados) == [False, True], (
        "Los dos INSERT con la misma idempotency_key han pasado. La restricción `unique` "
        "no está aplicada, y con ella se pierde la última defensa contra el doble cobro."
    )
    total = await db.fetchval(
        "select count(*) from public.generation_jobs where idempotency_key = $1", clave
    )
    assert total == 1


async def test_el_reembolso_de_un_job_fallido_deja_el_neto_a_cero(
    db: Any, seed: Seed, adapter: Any, worker: Any
) -> None:
    """
    Un job que falla devuelve íntegra su reserva: neto del libro 0 y saldo intacto.

    Se ejercita por el camino real —el worker es quien llama a `refund()`— y no llamando
    a `credits.refund()` a mano, porque el fallo que importa no es que `refund` sume mal:
    es que el worker no lo llame, o lo llame sobre un job que otro camino ya cerró.

    El invariante se comprueba con la misma consulta de agregación que usaría una
    auditoría contable, sobre las filas reales del libro.
    """
    from app.jobs import credits
    from app.jobs.queue import enqueue

    adapter.outcome = "failed"
    adapter.error = "el proveedor rechazó el plano"

    saldo_inicial = await credits.balance(seed.user_id)
    resultado = await enqueue(
        _request(seed),
        project_id=seed.project_id,
        adapter=adapter,
        conversation_id=seed.conversation_id,
    )
    assert resultado.credits_reserved > 0

    tras_reservar = await credits.balance(seed.user_id)
    assert tras_reservar == saldo_inicial - resultado.credits_reserved, (
        "La reserva debe salir del saldo al encolar, no al terminar: si no, el usuario "
        "puede gastarse lo mismo dos veces abriendo dos pestañas."
    )

    tarea = asyncio.create_task(worker.run_forever(poll_idle_s=0.01))
    try:
        estado = await wait_for_job(db, resultado.job_id, states=("failed", "cancelled", "nsfw"))
    finally:
        await worker.stop()
        await asyncio.wait_for(tarea, timeout=10)

    assert estado == "failed"

    neto = await credits.job_net(resultado.job_id)
    assert neto == 0, (
        f"El neto del libro para un job fallido es {neto}, no 0. El usuario está pagando "
        f"un plano que no existe."
    )
    assert await credits.balance(seed.user_id) == saldo_inicial

    # Cierre único: un reembolso, ningún cobro. Es la propiedad que hace idempotente el
    # cierre frente a los reintentos de webhook, y se comprueba sobre las filas reales.
    tipos = [
        r["kind"]
        for r in await db.fetch(
            "select kind from public.credit_ledger where job_id = $1::uuid order by created_at",
            resultado.job_id,
        )
    ]
    assert tipos == ["reserve", "refund"], f"Movimientos inesperados en el libro: {tipos}"


async def test_un_segundo_cierre_no_mueve_dinero(db: Any, seed: Seed, adapter: Any) -> None:
    """
    Reembolsar y luego cobrar el mismo job no escribe una segunda fila.

    Los webhooks de fal reintentan hasta 10 veces en 2 horas y pueden llegar
    desordenados, así que esta situación no es hipotética. La idempotencia se comprueba
    contra Postgres porque depende de leer el libro **bajo el cerrojo** del perfil: en un
    fake, dos llamadas concurrentes leen "aún no hay cierre" a la vez y escriben dos.
    """
    from app.jobs import credits
    from app.jobs.queue import enqueue

    resultado = await enqueue(_request(seed), project_id=seed.project_id, adapter=adapter)
    saldo = await credits.balance(seed.user_id)

    await credits.refund(job_id=resultado.job_id, reason="primer cierre")
    tras_reembolso = await credits.balance(seed.user_id)
    assert tras_reembolso == saldo + resultado.credits_reserved

    await credits.charge(
        job_id=resultado.job_id, final_credits=resultado.credits_reserved, note="webhook tardío"
    )
    assert await credits.balance(seed.user_id) == tras_reembolso, (
        "Un cobro posterior al reembolso ha movido dinero. El cierre debe ser único."
    )
    assert await credits.job_net(resultado.job_id) == 0
