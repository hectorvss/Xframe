"""
Lectura del catálogo.

El catálogo cambia poco (un `UPDATE` cuando un proveedor apaga un modelo) pero se lee
muchísimo: **una vez por turno de agente y por cada modo que se sondea**. Por eso hay
caché con TTL corto.

El TTL es corto a propósito, no largo: cuando el 30 de julio marquemos Runway como
`retired`, queremos que el agente deje de ofrecerlo esa misma noche sin desplegar ni
reiniciar. Sesenta segundos es el compromiso entre "no martillear Postgres" y "apagar
un proveedor es un UPDATE".

Todo lo que sale de aquí ya viene filtrado por `status`, por plan y por modalidad. El
filtrado **no** es responsabilidad del llamante: si un modelo llega al builder, es que
este usuario puede usarlo. Un recurso restringido por plan no se marca como bloqueado,
simplemente no se devuelve — para el agente es indistinguible de uno que no existe, que
es exactamente lo que queremos (no puede proponer algo que luego va a fallar).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar

from app import db
from app.config import get_settings
from app.providers.base import Modality

# --------------------------------------------------------------------------- #
# Planes                                                                       #
# --------------------------------------------------------------------------- #

PLAN_ORDER: tuple[str, ...] = ("free", "pro", "business", "enterprise")
"""
Orden de inclusión de planes. Se compara por índice, no por nombre: `min_plan='pro'`
significa "pro y por encima". Tenerlo como lista y no como una tabla de permisos es
deliberado — los planes de un SaaS son una escalera, no un grafo.
"""


def plan_rank(plan: str) -> int:
    """Índice del plan en la escalera. Un plan desconocido degrada al más bajo."""
    try:
        return PLAN_ORDER.index(plan)
    except ValueError:
        return 0


# --------------------------------------------------------------------------- #
# Registros del catálogo                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GenModel:
    """
    Un modelo de generación tal y como lo ve el agente.

    `description_llm` es distinta de `label` a propósito: el usuario lee "Kling 3.0
    Turbo", el modelo lee "vídeo de 5-10 s, buen movimiento de cámara, sin audio".
    Mezclarlas produce descripciones que no sirven ni para una cosa ni para la otra.
    """

    id: str
    family: str
    provider: str
    modality: Modality
    label: str
    description_llm: str

    min_duration_s: float | None
    max_duration_s: float | None
    resolutions: tuple[str, ...]
    aspects: tuple[str, ...]

    supports_i2v: bool
    supports_last_frame: bool
    supports_char_ref: bool
    supports_audio: bool

    cost_per_second: Decimal
    cost_per_image: Decimal | None
    credits_per_unit: int

    min_plan: str
    status: str
    sunset_at: datetime | None
    capabilities: tuple[str, ...] = ()

    @property
    def is_sunsetting(self) -> bool:
        """Tiene fecha de apagado conocida. Se avisa en la descripción de la tool."""
        return self.sunset_at is not None

    def summary_for_llm(self) -> str:
        """Una línea por modelo. Va dentro de la `description` de la tool, así que
        cada carácter se paga en todos los turnos: solo lo que cambia una decisión."""
        bits: list[str] = [self.description_llm.strip()]
        if self.max_duration_s:
            lo = self.min_duration_s or 0
            bits.append(f"{lo:g}-{self.max_duration_s:g}s")
        if self.aspects:
            bits.append("/".join(self.aspects))
        caps = [
            name
            for name, on in (
                ("i2v", self.supports_i2v),
                ("last-frame", self.supports_last_frame),
                ("char-ref", self.supports_char_ref),
                ("audio", self.supports_audio),
            )
            if on
        ]
        if caps:
            bits.append("+".join(caps))
        if self.capabilities:
            bits.append("capabilities=" + ",".join(self.capabilities))
        bits.append(f"{self.credits_per_unit} credits/unit")
        if self.status == "deprecated":
            bits.append("DEPRECATED, prefer another model")
        if self.sunset_at is not None:
            bits.append(f"retiring {self.sunset_at.date().isoformat()}")
        return f"{self.id} — " + "; ".join(bits)


@dataclass(frozen=True, slots=True)
class CameraMotion:
    """Movimiento de cámara. El id es nuestro; el UUID de cada proveedor vive en
    `provider_ref`, porque Higgsfield identifica sus presets por UUID y ese detalle
    no debe filtrarse ni al agente ni al esquema de la tool."""

    id: str
    label: str
    description_llm: str
    provider_ref: dict[str, Any]
    supports_strength: bool
    category: str | None

    def summary_for_llm(self) -> str:
        return f"{self.id} — {self.description_llm.strip()}"


@dataclass(frozen=True, slots=True)
class VisualStyle:
    """Un valor de una dimensión estética (paleta, luz, film stock, lente)."""

    id: str
    dimension: str
    label: str
    description_llm: str
    prompt_fragment: str

    def summary_for_llm(self) -> str:
        return f"{self.id} ({self.dimension}) — {self.description_llm.strip()}"


@dataclass(frozen=True, slots=True)
class Element:
    """
    Un asset con rol: personaje, localización u objeto.

    Es la unidad de continuidad del proyecto. El agente los referencia **por nombre**
    porque es lo que aparece en el guion; la resolución nombre → uuid la hacemos
    nosotros para que el modelo nunca tenga que manejar identificadores opacos.
    """

    id: str
    name: str
    role: str
    url: str | None
    meta: str
    status: str

    @property
    def usable_as_reference(self) -> bool:
        """Sin imagen lista no sirve como referencia visual, por muy definido que esté."""
        return self.status == "ready" and bool(self.url)


@dataclass(frozen=True, slots=True)
class TaxonomySnapshot:
    """
    Foto del catálogo para un (proyecto, usuario) en un instante.

    El builder trabaja **solo** sobre esto. Consecuencia práctica: construir el toolset
    de un turno hace un número fijo y pequeño de consultas, y los `Literal` de todas las
    tools de ese turno son coherentes entre sí (no puede pasar que `generate_video` vea
    un modelo que `estimate_cost` ya no ve).
    """

    plan: str
    models: tuple[GenModel, ...]
    motions: tuple[CameraMotion, ...]
    styles: tuple[VisualStyle, ...]
    elements: tuple[Element, ...]

    def models_for(self, modality: Modality) -> tuple[GenModel, ...]:
        return tuple(m for m in self.models if m.modality == modality)

    def model(self, model_id: str) -> GenModel | None:
        return next((m for m in self.models if m.id == model_id), None)

    def motion(self, motion_id: str) -> CameraMotion | None:
        return next((m for m in self.motions if m.id == motion_id), None)

    def style(self, style_id: str) -> VisualStyle | None:
        return next((s for s in self.styles if s.id == style_id), None)

    def element_by_name(self, name: str) -> Element | None:
        """Comparación laxa: el modelo escribe el nombre tal y como aparece en el
        guion, y la diferencia entre "Marta" y "marta " no debería costar un turno."""
        needle = name.strip().casefold()
        return next((e for e in self.elements if e.name.strip().casefold() == needle), None)

    # -- vocabularios para los Literal ------------------------------------- #

    def model_ids(self, modality: Modality) -> list[str]:
        return [m.id for m in self.models_for(modality)]

    def motion_ids(self) -> list[str]:
        return [m.id for m in self.motions]

    def style_ids(self) -> list[str]:
        return [s.id for s in self.styles]

    def element_names(self) -> list[str]:
        return [e.name for e in self.elements]


# --------------------------------------------------------------------------- #
# Caché con TTL                                                                #
# --------------------------------------------------------------------------- #

CATALOG_TTL_S: float = 60.0
"""Catálogo global. Corto para que apagar un modelo surta efecto sin desplegar."""

PROJECT_TTL_S: float = 10.0
"""
Datos del proyecto. Muy corto porque el propio agente los muta a mitad de turno: si
`define_element` crea un personaje, la siguiente tool tiene que verlo en su `Literal`.
"""

T = TypeVar("T")

_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def _cached(key: str, ttl: float, loader: Callable[[], Awaitable[T]]) -> T:
    """
    Memoización async con TTL y anti-estampida.

    El lock por clave importa más de lo que parece: en un fan-out de N planos, N ramas
    piden el catálogo en el mismo milisegundo. Sin lock son N consultas idénticas.
    """
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]
        value = await loader()
        _cache[key] = (time.monotonic() + ttl, value)
        return value


def invalidate_cache(prefix: str | None = None) -> None:
    """
    Purga la caché. Sin argumento, entera.

    Las tools de escritura la llaman con el prefijo de su proyecto: tras crear un
    element, el `Literal` de la siguiente tool tiene que incluirlo o el agente no
    podrá usar lo que acaba de crear.
    """
    if prefix is None:
        _cache.clear()
        return
    for key in [k for k in _cache if k.startswith(prefix)]:
        _cache.pop(key, None)


# --------------------------------------------------------------------------- #
# Consultas                                                                    #
# --------------------------------------------------------------------------- #


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(value or ())


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


async def plan_for_user(user_id: str) -> str:
    """Plan del perfil. Si el perfil no existe, `free`: degradar hacia abajo nunca
    concede acceso de más."""

    async def load() -> str:
        row = await db.fetchrow("select plan from public.profiles where id = $1", user_id)
        return (row["plan"] if row else None) or "free"

    return await _cached(f"plan:{user_id}", PROJECT_TTL_S, load)


async def active_models(plan: str, modality: Modality | None = None) -> list[GenModel]:
    """
    Modelos que este plan puede usar hoy.

    `retired` se excluye siempre; `deprecated` se mantiene pero se etiqueta, porque
    sigue funcionando y a veces es el único que soporta una capacidad concreta. Es la
    diferencia entre "no lo recomiendo" y "no existe", y el agente necesita las dos.
    """
    rank = plan_rank(plan)

    async def load() -> list[GenModel]:
        rows = await db.fetch(
            """
            select * from public.gen_models
             where status <> 'retired'
             order by modality, sort, id
            """
        )
        out: list[GenModel] = []
        for r in rows:
            if plan_rank(r["min_plan"]) > rank:
                continue
            if not get_settings().provider_is_configured(r["provider"]):
                continue
            out.append(
                GenModel(
                    id=r["id"],
                    family=r["family"],
                    provider=r["provider"],
                    modality=r["modality"],
                    label=r["label"],
                    description_llm=r["description_llm"],
                    min_duration_s=_float(r["min_duration_s"]),
                    max_duration_s=_float(r["max_duration_s"]),
                    resolutions=_tuple(r["resolutions"]),
                    aspects=_tuple(r["aspects"]),
                    supports_i2v=bool(r["supports_i2v"]),
                    supports_last_frame=bool(r["supports_last_frame"]),
                    supports_char_ref=bool(r["supports_char_ref"]),
                    supports_audio=bool(r["supports_audio"]),
                    capabilities=_tuple(r.get("capabilities") if hasattr(r, "get") else r["capabilities"]),
                    cost_per_second=Decimal(str(r["cost_per_second"])),
                    cost_per_image=_decimal(r["cost_per_image"]),
                    credits_per_unit=int(r["credits_per_unit"]),
                    min_plan=r["min_plan"],
                    status=r["status"],
                    sunset_at=r["sunset_at"],
                )
            )
        return out

    models = await _cached(f"models:{plan}", CATALOG_TTL_S, load)
    if modality is None:
        return list(models)
    return [m for m in models if m.modality == modality]


async def active_camera_motions() -> list[CameraMotion]:
    """Movimientos de cámara activos. Catálogo global, no depende del plan."""

    async def load() -> list[CameraMotion]:
        rows = await db.fetch(
            """
            select * from public.camera_motions
             where status = 'active'
             order by sort, id
            """
        )
        return [
            CameraMotion(
                id=r["id"],
                label=r["label"],
                description_llm=r["description_llm"],
                provider_ref=dict(r["provider_ref"] or {}),
                supports_strength=bool(r["supports_strength"]),
                category=r["category"],
            )
            for r in rows
        ]

    return list(await _cached("motions", CATALOG_TTL_S, load))


async def active_visual_styles(dimension: str | None = None) -> list[VisualStyle]:
    """Estilos activos, opcionalmente de una sola dimensión."""

    async def load() -> list[VisualStyle]:
        rows = await db.fetch(
            """
            select * from public.visual_styles
             where status = 'active'
             order by dimension, sort, id
            """
        )
        return [
            VisualStyle(
                id=r["id"],
                dimension=r["dimension"],
                label=r["label"],
                description_llm=r["description_llm"],
                prompt_fragment=r["prompt_fragment"],
            )
            for r in rows
        ]

    styles = await _cached("styles", CATALOG_TTL_S, load)
    if dimension is None:
        return list(styles)
    return [s for s in styles if s.dimension == dimension]


async def project_elements(project_id: str) -> list[Element]:
    """
    Elements del proyecto: assets con `role` no nulo.

    Filtra por `project_id` explícitamente. El backend usa la conexión de servicio y
    salta RLS, así que este filtro **es** el control de acceso, no una optimización.
    """

    async def load() -> list[Element]:
        rows = await db.fetch(
            """
            select id, name, role, url, meta, status
              from public.assets
             where project_id = $1 and role is not null and role <> ''
             order by role, name
            """,
            project_id,
        )
        return [
            Element(
                id=str(r["id"]),
                name=r["name"],
                role=r["role"],
                url=r["url"],
                meta=r["meta"] or "",
                status=r["status"],
            )
            for r in rows
        ]

    return list(await _cached(f"project:{project_id}:elements", PROJECT_TTL_S, load))


async def load_snapshot(project_id: str, user_id: str) -> TaxonomySnapshot:
    """
    Carga todo lo que el builder necesita, en paralelo.

    Es el único punto de entrada que debería usar el builder. Que sea una sola función
    es lo que garantiza la coherencia entre los `Literal` de todas las tools del turno.
    """
    plan = await plan_for_user(user_id)
    models, motions, styles, elements = await asyncio.gather(
        active_models(plan),
        active_camera_motions(),
        active_visual_styles(),
        project_elements(project_id),
    )
    return TaxonomySnapshot(
        plan=plan,
        models=tuple(models),
        motions=tuple(motions),
        styles=tuple(styles),
        elements=tuple(elements),
    )
