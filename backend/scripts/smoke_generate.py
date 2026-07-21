"""
Prueba de humo de una generación real, de punta a punta.

Es la única parte del sistema que ningún test puede cubrir: nueve adaptadores escritos
contra documentación, sin que ninguno haya hablado nunca con su API. Esto encola un
trabajo de verdad, lo procesa el worker de verdad, y comprueba que el binario acaba en
el bucket y los créditos en el libro mayor.

**Gasta dinero.** Una imagen, del orden de céntimos. Usa el modelo más barato de la
modalidad pedida y genera una sola.

    python -m scripts.smoke_generate            # imagen (barato)
    python -m scripts.smoke_generate --video    # vídeo (bastante más caro)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import uuid4

from app.runtime import configure_event_loop

configure_event_loop()

from app.db import close_pool, execute, fetch, fetchrow, init_pool  # noqa: E402
from app.jobs import credits  # noqa: E402
from app.jobs.queue import enqueue  # noqa: E402
from app.jobs.worker import JobWorker  # noqa: E402
from app.providers.base import GenerationRequest  # noqa: E402
from app.providers.registry import get_registry  # noqa: E402


async def pick_model(modality: str) -> dict:
    """El modelo activo más barato de esa modalidad para el que haya clave configurada."""
    rows = await fetch(
        """
        select id, provider, label, credits_per_unit, cost_per_second, cost_per_image
          from public.gen_models
         where modality = $1 and status <> 'retired' and provider like 'openai%'
         order by credits_per_unit asc
        """,
        modality,
    )
    if not rows:
        raise SystemExit(f"No hay modelos de {modality} para OpenAI en el catálogo.")
    return dict(rows[0])


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", action="store_true", help="genera vídeo en vez de imagen")
    args = parser.parse_args()
    modality = "video" if args.video else "image"

    await init_pool()
    model = await pick_model(modality)
    owner = await fetchrow("select id from public.profiles order by created_at limit 1")
    balance_before = await credits.balance(str(owner["id"]))

    print(f"modalidad  : {modality}")
    print(f"modelo     : {model['id']} ({model['label']}) — {model['credits_per_unit']} créditos/unidad")
    print(f"saldo antes: {balance_before}")

    project_id = str(uuid4())
    await execute(
        "insert into public.projects (id, owner_id, title, settings) "
        "values ($1, $2, '[SMOKE] generación real', '{}'::jsonb)",
        project_id,
        owner["id"],
    )

    ok = False
    try:
        registry = get_registry()
        adapter, _spec = await registry.resolve(model["id"])
        print(f"adaptador  : {adapter.provider_id}")

        request = GenerationRequest(
            modality=modality,  # type: ignore[arg-type]
            model_id=model["id"],
            prompt=(
                "Un faro de piedra en un acantilado al amanecer, niebla baja, "
                "luz cálida rasante, fotografía cinematográfica"
            ),
            aspect="16:9",
            duration_s=4 if modality == "video" else None,
        )

        job = await enqueue(
            request,
            project_id=project_id,
            adapter=adapter,
            shot_id=None,
            conversation_id=None,
        )
        print(f"job        : {job.job_id} (reservados {job.credits_reserved} créditos)")

        # Un worker que procesa exactamente este job y para. `run_forever` no sirve aquí:
        # no queremos que se quede escuchando la cola indefinidamente.
        worker = JobWorker(registry=registry)
        print("procesando… (puede tardar minutos)")
        await asyncio.wait_for(worker.run_once(), timeout=600)

        row = await fetchrow(
            "select status, error, credits_charged, asset_id from public.generation_jobs where id = $1",
            job.job_id,
        )
        print(f"\nestado     : {row['status']}")
        if row["error"]:
            print(f"error      : {row['error']}")
        print(f"cobrado    : {row['credits_charged']} créditos")

        if row["asset_id"]:
            asset = await fetchrow(
                "select name, type, status, url from public.assets where id = $1", row["asset_id"]
            )
            print(f"asset      : {asset['status']} — {asset['url']}")
            ok = row["status"] == "succeeded" and asset["status"] == "ready"

        balance_after = await credits.balance(str(owner["id"]))
        print(f"saldo tras : {balance_after} (delta {balance_after - balance_before})")

    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(f"\nFALLO: {type(exc).__name__}: {exc}")

    finally:
        await execute("delete from public.projects where id = $1", project_id)
        await close_pool()

    print("\n" + "=" * 60)
    print("RESULTADO:", "OK — generación real completada" if ok else "FALLO")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
