"""
Prueba de humo del agente contra infraestructura real.

Ejercita el camino completo de **preproducción** —el que no gasta créditos de
generación— con el Postgres real, el checkpointer real, la taxonomía real y el modelo
real. Es lo más parecido a un test de integración que se puede correr sin Docker.

Lo que verifica, y que ningún test con dobles puede verificar:

- Que el grafo compila y arranca con `AsyncPostgresSaver` sobre Postgres de verdad.
- Que el `ContextManager` sabe leer un proyecto real.
- Que la taxonomía construye las herramientas desde la BD y sus `Literal` se pueblan.
- Que el modelo responde por `/v1/responses` con herramientas (la vía obligatoria en
  GPT-5.6) y las llama de forma coherente.
- Que las escrituras aterrizan en las tablas.

Crea su propio proyecto de usar y tirar y lo borra al final, pase lo que pase: no toca
los datos que ya existen.

    python -m scripts.smoke_agent
"""

from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.runtime import configure_event_loop
from app.agent.runner import ConversationRunner
from app.config import get_settings
from app.db import close_pool, execute, fetch, fetchrow, init_pool


# Antes de que nadie cree un bucle. Ver app/runtime.py.
configure_event_loop()


class NullBus:
    """
    Bus de pega. El bus real necesita Redis, que aquí no hay, y lo que se quiere probar
    es el agente, no el transporte de eventos hacia el navegador.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, conversation_id, event_type, data):  # noqa: ANN001
        self.events.append((event_type, data))
        return "0-0"

    async def seed(self, conversation_id):  # noqa: ANN001
        return "0-0"


async def main() -> int:
    settings = get_settings()
    print(f"proveedor LLM : {settings.llm_provider} / {settings.model_root}")
    await init_pool()

    owner = await fetchrow("select id from public.profiles order by created_at limit 1")
    if owner is None:
        print("FALLO: no hay ningún perfil en la base de datos")
        return 1

    project_id = str(uuid4())
    conversation_id = str(uuid4())
    failures: list[str] = []

    await execute(
        "insert into public.projects (id, owner_id, title, prompt, settings) "
        "values ($1, $2, $3, $4, '{}'::jsonb)",
        project_id,
        owner["id"],
        "[SMOKE] proyecto temporal",
        "Un faro abandonado en una isla, al amanecer.",
    )
    await execute(
        "insert into public.conversations (id, project_id, owner_id, mode) "
        "values ($1, $2, $3, 'preproduction')",
        conversation_id,
        project_id,
        owner["id"],
    )
    print(f"proyecto      : {project_id}")

    try:
        checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
        async with checkpointer_cm as checkpointer:
            await checkpointer.setup()
            bus = NullBus()
            runner = ConversationRunner(checkpointer, bus)

            print("\n--- turno 1: pedir tratamiento y shot list ---")
            tools_seen: list[str] = []
            text: list[str] = []
            async for event in runner.run(
                conversation_id=conversation_id,
                project_id=project_id,
                user_id=str(owner["id"]),
                message=(
                    "Escribe un tratamiento breve para un corto sobre un faro abandonado "
                    "al amanecer, y crea una shot list de 3 planos."
                ),
                ui_context={"open_tab": "brief"},
            ):
                kind = event.get("type")
                if kind == "tool_start":
                    tools_seen.extend(event.get("tools", []))
                    print("  tool_start:", event.get("tools"))
                elif kind == "tool_result":
                    print("  tool_result:", str(event.get("content"))[:120])
                elif kind == "message_delta":
                    text.append(str(event.get("content", "")))
                elif kind == "error":
                    failures.append(f"evento de error: {event.get('message')}")
                    print("  ERROR:", event.get("message"))

            answer = "".join(text).strip()
            print("\nrespuesta:", answer[:400] or "(vacía)")
            print("herramientas usadas:", tools_seen or "NINGUNA")

            if not tools_seen:
                failures.append("el agente no llamó a ninguna herramienta")

            brief = await fetch(
                "select type, text from public.brief_blocks where project_id = $1 order by position",
                project_id,
            )
            shots = await fetch(
                "select title, position, shot_status from public.canvas_nodes "
                "where project_id = $1 and type = 'shot' order by position",
                project_id,
            )
            print(f"\nbrief_blocks escritos : {len(brief)}")
            print(f"planos escritos       : {len(shots)}")
            for s in shots:
                print(f"  [{s['position']}] {s['title']} ({s['shot_status']})")

            if not brief and not shots:
                failures.append("no se escribió ni brief ni planos en la base de datos")

            state = await checkpointer.aget(
                {"configurable": {"thread_id": conversation_id}}
            )
            print("checkpoint guardado   :", "sí" if state else "NO")
            if not state:
                failures.append("el checkpointer no persistió el estado")

    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        failures.append(f"excepción: {type(exc).__name__}: {exc}")

    finally:
        # El `cascade` del esquema se lleva conversación, brief, planos y assets.
        await execute("delete from public.projects where id = $1", project_id)
        await close_pool()
        print("\nproyecto temporal borrado")

    print("\n" + "=" * 60)
    if failures:
        print("RESULTADO: FALLO")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULTADO: OK — el agente razona, usa herramientas y escribe en la BD")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
