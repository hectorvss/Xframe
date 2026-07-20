"""
Taxonomía runtime.

El catálogo de modelos y de lenguaje cinematográfico es DATOS, no código. Dos piezas y
una sola responsabilidad entre ambas:

- `repo`: leer ese catálogo, cacheado y ya filtrado por estado, plan y modalidad.
- `builder`: convertirlo en herramientas cuyos `Literal[...]` contienen exactamente lo
  que existe hoy para este usuario.
"""

from app.taxonomy.repo import (
    CameraMotion,
    Element,
    GenModel,
    TaxonomySnapshot,
    VisualStyle,
    invalidate_cache,
    load_snapshot,
)

__all__ = [
    "CameraMotion",
    "Element",
    "GenModel",
    "TaxonomySnapshot",
    "VisualStyle",
    "invalidate_cache",
    "load_snapshot",
]
