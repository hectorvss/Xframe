"""
Prueba de humo del montaje final, contra storage real y ffmpeg real.

Es el último eslabón: `shots listos → assemble_cut → asset 'cut' en el bucket`.

Los clips se sintetizan con ffmpeg **a propósito con formatos distintos** —1280x720 a
30 fps, 1920x1080 a 24 fps y 1024x1024 a 25 fps— en vez de generarlos con un proveedor.
Dos motivos: generar tres clips cuesta dinero y el camino de generación ya está probado
por `smoke_generate`; y sobre todo, lo que aquí se quiere ejercitar es exactamente lo que
un lote real produce y ningún test con dobles reproduce — clips heterogéneos que hay que
normalizar a un formato común antes de concatenar. Un montaje que funciona con tres clips
idénticos no demuestra nada.

    python -m scripts.smoke_assemble
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from app.runtime import configure_event_loop

configure_event_loop()

from app.config import get_settings  # noqa: E402
from app.db import close_pool, execute, fetch, fetchrow, init_pool  # noqa: E402
from app.jobs.worker import SupabaseStorage  # noqa: E402

#: (ancho, alto, fps, segundos). Mismo aspecto, distinta resolución y cadencia: es
#: exactamente lo que produce un lote repartido entre proveedores, y lo que la
#: normalización tiene que resolver. No se mezclan aspectos a propósito —`assemble_cut`
#: se niega a hacerlo sin `allow_letterbox`, y ese rechazo es una decisión de diseño, no
#: un fallo que haya que rodear en la prueba.
CLIPS = ((1280, 720, 30, 2), (1920, 1080, 24, 2), (854, 480, 25, 2))


def synth(path: Path, w: int, h: int, fps: int, secs: int) -> None:
    """Un clip de barras con un tono, del tamaño y cadencia pedidos."""
    ffmpeg = get_settings().ffmpeg_path
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate={fps}:duration={secs}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


async def main() -> int:
    await init_pool()
    owner = await fetchrow("select id from public.profiles order by created_at limit 1")
    project_id = str(uuid4())
    ok = False

    await execute(
        "insert into public.projects (id, owner_id, title, settings) "
        "values ($1, $2, '[SMOKE] montaje', '{}'::jsonb)",
        project_id,
        owner["id"],
    )

    try:
        storage = SupabaseStorage()
        with tempfile.TemporaryDirectory() as tmp:
            for i, (w, h, fps, secs) in enumerate(CLIPS):
                local = Path(tmp) / f"clip{i}.mp4"
                synth(local, w, h, fps, secs)
                print(f"clip {i}: {w}x{h} @{fps}fps  {local.stat().st_size} bytes")

                # `assets.shot_id` referencia el UUID del nodo, no su `node_key`: es la
                # convención que usan las tools de generación y el worker, y con la que
                # `assemble_video` hace el join.
                node = await fetchrow(
                    """
                    insert into public.canvas_nodes
                           (project_id, node_key, type, title, text, position, shot_status)
                    values ($1::uuid, $2, 'shot', $3, '', $4, 'ready')
                    returning id
                    """,
                    project_id,
                    f"shot-smoke-{i}",
                    f"Plano {i + 1}",
                    i,
                )
                shot_id = str(node["id"])

                path = await storage.put(
                    project_id=project_id,
                    job_id=f"smoke-{i}",
                    filename="output.mp4",
                    data=local.read_bytes(),
                    content_type="video/mp4",
                )
                await execute(
                    """
                    insert into public.assets
                           (project_id, name, type, status, url, shot_id)
                    values ($1::uuid, $2, 'video', 'ready', $3, $4)
                    """,
                    project_id,
                    f"Plano {i + 1}",
                    path,
                    shot_id,
                )

        print("\nmontando…")
        from app.taxonomy.builder import build_tools_for_mode
        from app.tools.base import ToolContext

        ctx = ToolContext(
            project_id=project_id,
            user_id=str(owner["id"]),
            conversation_id=str(uuid4()),
            mode="production",
            credits_available=10_000,
        )
        tools = {t.name: t for t in await build_tools_for_mode(ctx)}
        assemble = tools.get("assemble_video")
        if assemble is None:
            print("FALLO: assemble_video no está montada en modo producción")
            return 1

        # La tool recibe los planos explícitamente: montar "todo lo que haya" sería una
        # forma fácil de entregar un corte con material que el usuario no ha visto.
        shots = await fetch(
            "select id from public.canvas_nodes where project_id = $1::uuid "
            "and type = 'shot' order by position",
            project_id,
        )
        content, payload = await assemble.bind_context(ctx)._arun_impl(
            shot_ids=[str(r["id"]) for r in shots], title="Corte de prueba"
        )
        print("resultado:", str(content)[:220])

        cut = await fetchrow(
            "select id, type, status, url from public.assets "
            "where project_id = $1::uuid and type = 'cut' order by created_at desc limit 1",
            project_id,
        )
        if cut:
            print(f"cut       : {cut['status']} — {cut['url']}")
            ok = cut["status"] == "ready"

        arts = await fetch(
            "select kind, version from public.artifacts where project_id = $1::uuid", project_id
        )
        print("artefactos:", [(a["kind"], a["version"]) for a in arts] or "ninguno")

    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(f"\nFALLO: {type(exc).__name__}: {exc}")

    finally:
        await execute("delete from public.projects where id = $1", project_id)
        await close_pool()

    print("\n" + "=" * 60)
    print("RESULTADO:", "OK — montaje real completado" if ok else "FALLO")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
