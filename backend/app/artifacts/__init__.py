"""
Artefactos por referencia.

`types` define los bloques (lo que se guarda son refs, no copias) y `manager` persiste,
versiona y resuelve esas refs contra la BD degradando las rotas a `ErrorBlock`.
"""

from app.artifacts.manager import (
    ArtifactHandler,
    ArtifactManager,
    EnrichmentContext,
    register_handler,
)
from app.artifacts.types import (
    AssetRefBlock,
    CutArtifactContent,
    ErrorBlock,
    PlanArtifactContent,
    ScriptArtifactContent,
    ShotRefBlock,
    TextBlock,
    TimelineArtifactContent,
)

__all__ = [
    "ArtifactHandler",
    "ArtifactManager",
    "AssetRefBlock",
    "CutArtifactContent",
    "EnrichmentContext",
    "ErrorBlock",
    "PlanArtifactContent",
    "ScriptArtifactContent",
    "ShotRefBlock",
    "TextBlock",
    "TimelineArtifactContent",
    "register_handler",
]
