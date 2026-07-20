"""
Herramientas del agente.

Deliberadamente vacío de importaciones de los submódulos: quien decide qué tools
existen es `app.taxonomy.builder`, en runtime y según el modo. Importarlas aquí daría
la impresión de que el toolset es una lista fija, que es justo lo que este diseño evita.

`base` (contrato) y `errors` (política de reintento) sí son estables y se exponen.
"""

from app.tools.base import ToolContext, ToolFactory, XframeTool
from app.tools.errors import (
    InsufficientCreditsError,
    ModelRetiredError,
    ProviderError,
    ProviderRejectedError,
    UnknownEntityError,
    XframeToolError,
    XframeToolFatalError,
    XframeToolRetryableError,
    XframeToolTransientError,
)

__all__ = [
    "InsufficientCreditsError",
    "ModelRetiredError",
    "ProviderError",
    "ProviderRejectedError",
    "ToolContext",
    "ToolFactory",
    "UnknownEntityError",
    "XframeTool",
    "XframeToolError",
    "XframeToolFatalError",
    "XframeToolRetryableError",
    "XframeToolTransientError",
]
