"""
Errores de herramienta.

Puerto casi literal de `ee/hogai/tool_errors.py` de PostHog (Apache-2.0). Es de las
pocas piezas de su código que no depende de Django, así que se reutiliza tal cual
cambiando solo el prefijo del nombre y añadiendo las clases propias de generación.

La idea central que hay que preservar: **la política de reintento vive en la clase de
excepción**, no en el llamante. El ejecutor solo lee `retry_strategy` y `retry_hint`,
y el hint está escrito en lenguaje natural dirigido al LLM.
"""

from typing import Literal


class XframeToolError(Exception):
    """
    Excepción base de las herramientas. Todos estos errores producen mensajes de
    herramienta visibles para el LLM, pero no para el usuario final.

    Estrategia:
    - XframeToolFatalError: no recuperable (permisos, config ausente).
    - XframeToolTransientError: intermitente, reintentable sin cambios (rate limit).
    - XframeToolRetryableError: resoluble ajustando la entrada (parámetro inválido).
    - Exception genérica: fallo desconocido, se trata como fatal (red de seguridad).

    Al lanzarlas, da contexto accionable: qué falló, por qué, y qué se puede hacer.
    """

    def __init__(self, message: str):
        super().__init__(message)

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "never"

    @property
    def retry_hint(self) -> str:
        """Sufijo que se añade al mensaje de error para orientar al LLM."""
        return {
            "never": "",
            "once": " You may retry this operation once without changes.",
            "adjusted": " You may retry with adjusted inputs.",
        }[self.retry_strategy]

    def to_summary(self, max_length: int = 500) -> str:
        """Resumen truncado, para no reventar el contexto con un stacktrace."""
        exception_msg = str(self).strip()
        if len(exception_msg) > max_length:
            exception_msg = exception_msg[:max_length] + "…"
        return f"{self.__class__.__name__}: {exception_msg}"


class XframeToolFatalError(XframeToolError):
    """No recuperable. No reintentar."""

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "never"


class XframeToolTransientError(XframeToolError):
    """Problema temporal del servicio. Reintentable una vez sin cambios."""

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "once"


class XframeToolRetryableError(XframeToolError):
    """Resoluble ajustando la entrada."""

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "adjusted"


# --------------------------------------------------------------------------- #
# Específicos de Xframe                                                        #
# --------------------------------------------------------------------------- #


class InsufficientCreditsError(XframeToolFatalError):
    """
    Saldo insuficiente. Fatal a propósito: reintentar no arregla nada, y queremos que
    el agente se lo diga al usuario en vez de insistir contra la API de pago.
    """

    def __init__(self, needed: int, available: int):
        self.needed = needed
        self.available = available
        super().__init__(
            f"This generation costs {needed} credits but the project only has {available}. "
            f"Tell the user they need to top up before generating. Do not retry, and do not "
            f"silently pick a cheaper model without telling them."
        )


class UnknownEntityError(XframeToolRetryableError):
    """
    Se ha referenciado algo que no existe (elemento, modelo, movimiento de cámara).

    Enumera siempre las opciones válidas: es el patrón del taxonomy toolkit de PostHog
    y es lo que permite al modelo autocorregirse en el siguiente turno.
    """

    def __init__(self, kind: str, value: str, valid: list[str], limit: int = 40):
        shown = valid[:limit]
        tail = f" …and {len(valid) - limit} more" if len(valid) > limit else ""
        super().__init__(
            f"There is no {kind} called '{value}' in this project. "
            f"Valid options are: {', '.join(shown)}{tail}. "
            f"Use one of these exactly, or create it first."
        )


class ProviderError(XframeToolTransientError):
    """Fallo del proveedor de generación reintentable (5xx, rate limit, timeout)."""

    def __init__(self, provider: str, message: str, *, retry_after_s: float | None = None):
        self.provider = provider
        self.retry_after_s = retry_after_s
        super().__init__(f"Provider '{provider}' failed: {message}")


class ProviderRejectedError(XframeToolRetryableError):
    """
    El proveedor rechazó la petición por su contenido o parámetros (moderación,
    duración fuera de rango, aspect no soportado). Se arregla ajustando la entrada.
    """

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"Provider '{provider}' rejected the request: {message}")


class ModelRetiredError(XframeToolRetryableError):
    """
    El modelo pedido está apagado. Pasa de verdad y con frecuencia: Veo 3.0 se apagó en
    junio de 2026, Runway Gen-3/Gen-4 el 30 de julio, Sora 2 el 24 de septiembre.
    """

    def __init__(self, model_id: str, alternatives: list[str]):
        super().__init__(
            f"Model '{model_id}' has been retired by its provider and is no longer available. "
            f"Use one of these instead: {', '.join(alternatives)}."
        )
