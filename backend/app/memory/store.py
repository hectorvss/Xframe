"""
La biblia del proyecto: CRUD sobre `project_memory`.

`CoreMemory` de PostHog es un blob de texto por equipo. El nuestro es por **proyecto** y
está partido en cuatro clases, porque las cuatro tienen ciclos de vida distintos:

- `style_bible` — paleta, iluminación, film stock, referencias. Se escribe en el
  onboarding y cambia poco.
- `character_sheet` — una por element (`element_id`). Es lo que hace que un personaje se
  parezca a sí mismo entre planos.
- `continuity_rules` — qué debe mantenerse constante. Crece con cada corrección.
- `director_prefs` — qué ha rechazado el usuario y por qué. Crece con cada rechazo.

Formato: **frases atómicas, una por línea**. No prosa. La razón es puramente operativa:
`replace` busca por fragmento exacto, y sobre prosa larga el modelo falla el match casi
siempre. Sobre una lista de frases cortas acierta.

Y el motivo por el que esta tabla importa más que cualquier otra del sistema: es lo que
hay que **reinyectar tras compactar**. Si se pierde "Marco tiene una cicatriz en la ceja
izquierda", el siguiente plano rompe la continuidad, y ese fallo no se paga en tokens
sino en créditos de generación.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app import db
from app.context.manager import _attr, _body
from app.context.prompts import MEMORY_KIND_LABELS, MEMORY_TEMPLATE


class MemoryKind(StrEnum):
    """Los cuatro tipos que admite el CHECK de `project_memory.kind`."""

    STYLE_BIBLE = "style_bible"
    CHARACTER_SHEET = "character_sheet"
    CONTINUITY_RULES = "continuity_rules"
    DIRECTOR_PREFS = "director_prefs"


@dataclass(slots=True)
class MemoryEntry:
    id: str
    project_id: str
    kind: MemoryKind
    element_id: str | None
    content: str
    updated_at: datetime | None = None


MAX_MEMORY_CHARS = 12_000
"""
Techo por entrada. Una biblia que crece sin límite acaba comiéndose el presupuesto de
contexto que debía proteger. Al llegar aquí, el colector tiene que consolidar con
`replace` en vez de seguir haciendo `append`.
"""


class ProjectMemoryStore:
    """
    CRUD de la memoria de un proyecto.

    Todas las consultas filtran por `project_id` explícitamente: el backend usa la
    conexión de servicio y salta RLS, así que el filtro es responsabilidad nuestra.
    """

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    # -- lectura ----------------------------------------------------------- #

    async def all(self) -> list[MemoryEntry]:
        rows = await db.fetch(
            """
            select id, project_id, kind, element_id, content, updated_at
              from public.project_memory
             where project_id = $1::uuid
             order by kind, element_id nulls first
            """,
            self._project_id,
        )
        return [_row_to_entry(r) for r in rows]

    async def get(self, kind: MemoryKind, element_id: str | None = None) -> MemoryEntry | None:
        row = await db.fetchrow(
            """
            select id, project_id, kind, element_id, content, updated_at
              from public.project_memory
             where project_id = $1::uuid
               and kind = $2
               and element_id is not distinct from $3::uuid
            """,
            self._project_id,
            kind.value,
            element_id,
        )
        return _row_to_entry(row) if row else None

    async def is_empty(self) -> bool:
        """¿Hace falta onboarding? Sin biblia de estilo, el proyecto no tiene identidad."""
        return not await db.fetchval(
            """
            select exists(
              select 1 from public.project_memory
               where project_id = $1::uuid and kind = 'style_bible'
                 and length(trim(content)) > 0)
            """,
            self._project_id,
        )

    # -- escritura --------------------------------------------------------- #

    async def set(
        self, kind: MemoryKind, content: str, element_id: str | None = None
    ) -> MemoryEntry:
        """Upsert. Sobrescribe entera la entrada; es lo que usa el onboarding."""
        row = await db.fetchrow(
            """
            insert into public.project_memory (project_id, kind, element_id, content)
            values ($1::uuid, $2, $3::uuid, $4)
            on conflict (project_id, kind, element_id)
              do update set content = excluded.content, updated_at = now()
            returning id, project_id, kind, element_id, content, updated_at
            """,
            self._project_id,
            kind.value,
            element_id,
            _normalize(content)[:MAX_MEMORY_CHARS],
        )
        return _row_to_entry(row)

    async def append(
        self, kind: MemoryKind, fragment: str, element_id: str | None = None
    ) -> MemoryEntry:
        """
        Añade una frase atómica.

        Ignora el duplicado exacto en silencio y devuelve la entrada sin tocar: el
        colector corre en cada turno y tiende a redescubrir lo mismo. Convertir eso en
        error solo enseñaría al modelo a pelearse con la herramienta.

        Levanta `ValueError` si la entrada está llena, con un mensaje escrito para que
        el modelo lo lea y consolide con `replace`.
        """
        fragment = _normalize(fragment)
        if not fragment:
            raise ValueError("Memory fragment is empty. Write one atomic factual sentence.")

        current = await self.get(kind, element_id)
        if current is None:
            return await self.set(kind, fragment, element_id)

        if fragment in _lines(current.content):
            return current

        if len(current.content) + len(fragment) + 1 > MAX_MEMORY_CHARS:
            raise ValueError(
                f"The '{kind.value}' memory is full ({MAX_MEMORY_CHARS} characters). "
                f"Consolidate two existing lines into one with memory_replace before "
                f"appending anything new."
            )

        return await self.set(kind, f"{current.content}\n{fragment}", element_id)

    async def replace(
        self,
        kind: MemoryKind,
        original_fragment: str,
        new_fragment: str,
        element_id: str | None = None,
    ) -> MemoryEntry:
        """
        Sustituye un fragmento por otro.

        Levanta `ValueError` cuando el fragmento no aparece. El mensaje enumera las
        líneas actuales, siguiendo la regla de PostHog para los errores de tool: un error
        que dice qué es válido se corrige solo en el siguiente turno; uno que solo dice
        "no encontrado" produce un bucle.
        """
        current = await self.get(kind, element_id)
        if current is None:
            raise ValueError(f"There is no '{kind.value}' memory yet — use memory_append instead.")

        original_fragment = _normalize(original_fragment)
        if original_fragment not in current.content:
            existing = "\n".join(f"- {line}" for line in _lines(current.content)) or "- (empty)"
            raise ValueError(
                f"Fragment not found in '{kind.value}'. The current memory is:\n{existing}\n"
                f"Copy one of these lines verbatim as original_fragment."
            )

        updated = current.content.replace(original_fragment, _normalize(new_fragment))
        return await self.set(kind, _normalize(updated), element_id)

    async def delete(self, kind: MemoryKind, element_id: str | None = None) -> None:
        await db.execute(
            """
            delete from public.project_memory
             where project_id = $1::uuid
               and kind = $2
               and element_id is not distinct from $3::uuid
            """,
            self._project_id,
            kind.value,
            element_id,
        )

    # -- formateo ---------------------------------------------------------- #

    async def format_for_prompt(self, *, max_chars: int = 8_000) -> str:
        """
        La memoria como bloque XML listo para inyectar.

        Se usa en dos sitios y esa duplicidad es intencionada: en el contexto del turno,
        y otra vez en la reinyección post-compactación. Es la única parte del contexto
        que se permite aparecer dos veces, porque es la única cuya pérdida cuesta dinero.
        """
        return format_memory(await self.all(), max_chars=max_chars)


def format_memory(entries: Sequence[MemoryEntry], *, max_chars: int = 8_000) -> str:
    """
    Formatea entradas de memoria. Puro, para poder testearlo sin BD.

    El orden no es alfabético: biblia de estilo primero, después fichas de personaje,
    después reglas y preferencias. Si hay que truncar, se trunca por la cola, y la cola
    es lo que menos rompe la continuidad visual.

    **El contenido se escapa.** Era el único bloque del contexto que se interpolaba en
    crudo, y a la vez el único al que el prompt le concede autoridad explícita ("outranks
    anything you infer from a single shot"). Esa combinación era el agujero: una línea de
    la biblia de estilo, que se escribe desde la UI, podía cerrar `</project_memory>` y
    abrir un `<system_reminder>` falso al que el modelo llegaba ya predispuesto a
    obedecer. Con `_attr`/`_body` —los mismos de `context/manager.py`, importados y no
    duplicados, para que no puedan divergir— la línea entra como texto y se lee como
    texto.
    """
    if not entries:
        return ""

    order = {
        MemoryKind.STYLE_BIBLE: 0,
        MemoryKind.CHARACTER_SHEET: 1,
        MemoryKind.CONTINUITY_RULES: 2,
        MemoryKind.DIRECTOR_PREFS: 3,
    }
    blocks: list[str] = []
    used = 0
    dropped = 0

    for entry in sorted(entries, key=lambda e: (order.get(e.kind, 9), e.element_id or "")):
        content = entry.content.strip()
        if not content:
            continue
        label = MEMORY_KIND_LABELS.get(entry.kind.value, entry.kind.value)
        attrs = f'kind="{_attr(entry.kind.value)}"'
        if entry.element_id:
            attrs += f' element_id="{_attr(entry.element_id)}"'
        block = f'<memory {attrs} label="{_attr(label)}">\n{_body(content)}\n</memory>'
        if used + len(block) > max_chars:
            dropped += 1
            continue
        used += len(block)
        blocks.append(block)

    if not blocks:
        return ""
    if dropped:
        blocks.append(f"<truncated>…y {dropped} bloques de memoria más.</truncated>")
    return MEMORY_TEMPLATE.format(blocks="\n".join(blocks))


# --------------------------------------------------------------------------- #
# Utilidades                                                                   #
# --------------------------------------------------------------------------- #


def _normalize(text: str) -> str:
    """
    Comprime a frases atómicas: sin líneas en blanco, sin espacios sobrantes.

    Es el `compressed_memory_parser` de PostHog. Importa porque `replace` casa por
    fragmento exacto y un salto de línea de más convierte un match en un fallo.
    """
    lines = [line.strip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _lines(content: str) -> list[str]:
    return [line for line in content.split("\n") if line.strip()]


def _row_to_entry(row) -> MemoryEntry:  # type: ignore[no-untyped-def]
    return MemoryEntry(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        kind=MemoryKind(row["kind"]),
        element_id=str(row["element_id"]) if row["element_id"] else None,
        content=row["content"],
        updated_at=row["updated_at"],
    )
