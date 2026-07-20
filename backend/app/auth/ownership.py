"""
Frontera de tenant.

Autenticar dice *quién eres*; esto dice *qué es tuyo*. Sin lo segundo, lo primero no
sirve de nada: un usuario legítimo con el uuid de un proyecto ajeno leía el proyecto,
lo borraba (`rewrite_brief` hace `delete ... where project_id = $1`) y gastaba créditos
contra el monedero de la víctima.

Se comprueba **antes** de instanciar el runner, no dentro de las tools. Motivo: las tools
son muchas y crecen; la frontera tiene que estar en un sitio por el que se pase siempre.

404 y no 403 cuando el recurso no es tuyo: distinguir "no existe" de "existe pero no es
tuyo" es un oráculo de enumeración de uuids ajenos y no le aporta nada al usuario
legítimo, que nunca ve ninguno de los dos.
"""

from __future__ import annotations

from fastapi import HTTPException

from app import db


async def project_belongs_to(project_id: str, user_id: str) -> bool:
    return bool(
        await db.fetchval(
            "select 1 from public.projects where id = $1::uuid and owner_id = $2::uuid",
            project_id,
            user_id,
        )
    )


async def conversation_belongs_to(conversation_id: str, user_id: str) -> bool:
    """
    Propiedad de la conversación.

    `owner_id` de la propia conversación **y** propiedad del proyecto al que cuelga: una
    conversación cuyo proyecto se transfirió no debe seguir siendo legible por el dueño
    anterior solo porque su uuid quedó escrito en la fila.
    """
    return bool(
        await db.fetchval(
            """
            select 1
              from public.conversations c
              join public.projects p on p.id = c.project_id
             where c.id = $1::uuid
               and c.owner_id = $2::uuid
               and p.owner_id = $2::uuid
            """,
            conversation_id,
            user_id,
        )
    )


async def assert_project_owner(project_id: str, user_id: str) -> None:
    if not await project_belongs_to(project_id, user_id):
        raise HTTPException(404, "proyecto no encontrado")


async def assert_conversation_owner(conversation_id: str, user_id: str) -> None:
    if not await conversation_belongs_to(conversation_id, user_id):
        raise HTTPException(404, "conversación no encontrada")


async def assert_conversation_available(
    conversation_id: str, project_id: str, user_id: str
) -> None:
    """
    La conversación es tuya — o todavía no existe.

    El cliente genera el uuid antes del primer turno, así que exigir que la fila exista
    rompería el arranque de toda conversación nueva. Lo que no puede ocurrir nunca es
    continuar la de otro: si la fila existe y su `owner_id` no eres tú, o cuelga de otro
    proyecto, 404. El caso "no existe" solo es seguro porque a esta función se llega
    después de haber validado la propiedad del proyecto.
    """
    row = await db.fetchrow(
        "select owner_id, project_id from public.conversations where id = $1::uuid",
        conversation_id,
    )
    if row is None:
        return
    if str(row["owner_id"]) != user_id or str(row["project_id"]) != project_id:
        raise HTTPException(404, "conversación no encontrada")
