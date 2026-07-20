"""
Contrato de herramienta.

Porta `ee/hogai/tool.py` de PostHog, quitándole el acoplamiento a Django/RBAC y
quedándonos con lo que de verdad importa:

- `response_format = "content_and_artifact"`: **content** es texto barato para el LLM,
  **artifact** es el `ui_payload` completo para el frontend. Separarlos ahorra muchísimos
  tokens (una tool que devuelve 6 assets manda 6 líneas al modelo, no 6 objetos JSON).
- Registro por `__init_subclass__`: heredar registra.
- `context_prompt_template`: cada tool aporta su propio trozo de contexto al root.
- Construcción dinámica del `args_schema` para que los enums salgan de la BD.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any, ClassVar, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.tools.errors import XframeToolError

logger = logging.getLogger(__name__)


class ToolContext(BaseModel):
    """Lo que toda herramienta necesita saber para operar. Se inyecta al instanciar."""

    model_config = {"arbitrary_types_allowed": True}

    project_id: str
    user_id: str
    conversation_id: str
    mode: str
    credits_available: int


class XframeTool(BaseTool):
    """Base de todas las herramientas del agente."""

    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    context_prompt_template: str | None = None
    """
    Trozo de contexto que esta tool inyecta en el root cuando está montada. Se formatea
    con las variables del contexto de la tool. Sirve para orientar *cuándo* usarla.
    """

    consumes_credits: bool = False
    """Marca las tools caras. El ejecutor las cuenta contra MAX_GENERATIONS_PER_TURN."""

    modes: ClassVar[tuple[str, ...]] = ("preproduction", "production", "edit")
    """
    En qué modos existe esta tool. Es la restricción estructural: las tools de
    generación simplemente no se montan en preproducción.
    """

    _ctx: ToolContext | None = None

    # -- registro ---------------------------------------------------------- #

    registry: ClassVar[dict[str, type["XframeTool"]]] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """
        Registro por herencia.

        Tiene que ser `__pydantic_init_subclass__` y no `__init_subclass__`: en pydantic v2
        el segundo se ejecuta ANTES de que se construya `model_fields`, así que leer de ahí
        el nombre de la tool devuelve siempre vacío y el registro queda mudo. Pydantic
        expone este gancho justo para esto — corre una vez el modelo ya está completo.
        """
        super().__pydantic_init_subclass__(**kwargs)
        if getattr(cls, "__abstract__", False):
            return
        field = cls.model_fields.get("name")
        default = getattr(field, "default", None) if field is not None else None
        if default and isinstance(default, str):
            XframeTool.registry[default] = cls

    # -- ejecución --------------------------------------------------------- #

    @abstractmethod
    async def _arun_impl(self, *args: Any, **kwargs: Any) -> tuple[str, Any]:
        """Devuelve `(content_para_el_LLM, ui_payload_para_el_frontend)`."""

    def _run(self, *args: Any, **kwargs: Any) -> tuple[str, Any]:
        raise NotImplementedError("Xframe tools are async-only")

    async def _arun(self, *args: Any, **kwargs: Any) -> tuple[str, Any]:
        """
        Cuatro capas de captura, como el ejecutor de PostHog. El orden importa:

        1. `XframeToolError` → el mensaje ya está escrito para el LLM; se le añade el
           `retry_hint` y se devuelve como resultado normal para que se autocorrija.
        2. `ValidationError` de Pydantic → se pasa **cruda**. Los LLMs se corrigen muy
           bien con ella; reescribirla la empeora.
        3. `Exception` → bug nuestro. Se registra con traza y se le prohíbe reintentar,
           porque reintentar un bug solo quema créditos.
        """
        try:
            return await self._arun_impl(*args, **kwargs)
        except XframeToolError as e:
            logger.info("tool_error", extra={"tool": self.name, "err": e.to_summary()})
            return f"{e.to_summary()}{e.retry_hint}", None
        except Exception as e:  # noqa: BLE001
            from pydantic import ValidationError

            if isinstance(e, ValidationError):
                return f"Invalid arguments:\n{e}", None
            logger.exception("tool_crashed", extra={"tool": self.name})
            return (
                f"The {self.name} tool failed with an internal error: {type(e).__name__}. "
                f"This is a bug on our side, not something you can fix by retrying. "
                f"Do not call this tool again with the same arguments — tell the user "
                f"what you were trying to do and that it failed.",
                None,
            )

    # -- contexto ---------------------------------------------------------- #

    def bind_context(self, ctx: ToolContext) -> "XframeTool":
        self._ctx = ctx
        return self

    @property
    def ctx(self) -> ToolContext:
        if self._ctx is None:
            raise RuntimeError(f"{self.name} used without a bound ToolContext")
        return self._ctx


class ToolFactory:
    """
    Construcción dinámica de herramientas.

    Es el patrón `create_tool_class()` de PostHog y en nuestro caso es el que sostiene
    todo el sistema: `description` y `args_schema` se reescriben en runtime a partir de
    la taxonomía en BD, de modo que los `Literal[...]` contienen exactamente los
    modelos, movimientos de cámara y elements que existen **hoy** y que este usuario
    puede usar.

    Consecuencia: el LLM no puede alucinar un modelo apagado ni un personaje inexistente,
    porque el enum está en el JSON Schema y no en una instrucción del prompt.
    """

    @staticmethod
    async def build_for_mode(ctx: ToolContext) -> list[XframeTool]:
        from app.taxonomy.builder import build_tools_for_mode

        return await build_tools_for_mode(ctx)
