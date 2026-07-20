"""Configuración. Todo por entorno; ningún secreto en el repo."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- infraestructura ---
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_key: str = Field(default="", alias="SUPABASE_SERVICE_KEY")
    storage_bucket: str = Field(default="xframe-assets", alias="STORAGE_BUCKET")

    # --- LLM ---
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    # Sin router central de modelos: como en PostHog, cada tarea elige el suyo junto
    # a su código. Estos son solo los defectos.
    model_root: str = Field(default="claude-opus-4-8", alias="MODEL_ROOT")
    model_fast: str = Field(default="claude-haiku-4-5-20251001", alias="MODEL_FAST")
    model_summarize: str = Field(default="claude-haiku-4-5-20251001", alias="MODEL_SUMMARIZE")

    # --- proveedores de generación ---
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    kling_access_key: str = Field(default="", alias="KLING_ACCESS_KEY")
    kling_secret_key: str = Field(default="", alias="KLING_SECRET_KEY")
    minimax_api_key: str = Field(default="", alias="MINIMAX_API_KEY")
    bytedance_api_key: str = Field(default="", alias="BYTEDANCE_API_KEY")
    wan_api_key: str = Field(default="", alias="WAN_API_KEY")
    higgsfield_key_id: str = Field(default="", alias="HIGGSFIELD_KEY_ID")
    higgsfield_key_secret: str = Field(default="", alias="HIGGSFIELD_KEY_SECRET")
    bfl_api_key: str = Field(default="", alias="BFL_API_KEY")

    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")
    """Base para los webhooks de proveedor. Debe ser accesible desde fuera."""

    # --- límites ---
    job_poll_interval_s: float = 5.0
    job_timeout_s: float = 900.0
    max_concurrent_jobs_per_project: int = 6

    # --- economía ---
    credits_per_usd: int = Field(default=100, alias="CREDITS_PER_USD")
    """
    Conversión coste de API → créditos al cliente. El precio de cada modelo se deriva
    de aquí en `credits_per_unit`, así que subir el margen es cambiar una constante.
    """
    credit_margin: float = Field(default=1.6, alias="CREDIT_MARGIN")

    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
