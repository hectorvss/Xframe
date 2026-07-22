"""Configuración. Todo por entorno; ningún secreto en el repo."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- infraestructura ---
    database_url: str = Field(alias="DATABASE_URL")

    db_pool_min: int = Field(default=1, alias="DB_POOL_MIN")
    db_pool_max: int = Field(default=4, alias="DB_POOL_MAX")
    """
    Tamaño del pool de asyncpg POR PROCESO. El defecto es deliberadamente pequeño: el
    pooler de Supabase en modo sesión admite 15 clientes EN TOTAL, y de ahí comen la API,
    cada réplica del worker y el checkpointer de LangGraph. Con el antiguo max_size=16
    por proceso, el segundo worker agotaba el cupo y moría en bucle con EMAXCONNSESSION,
    y las tools del agente fallaban a mitad de turno "por un error interno". La suma de
    todos los procesos debe quedar por debajo de 15; se reparte por entorno en compose.
    """
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_key: str = Field(default="", alias="SUPABASE_SERVICE_KEY")
    # El bucket real del proyecto se llama `assets`. El default anterior
    # (`xframe-assets`) no existía en Supabase, así que toda subida habría dado 404
    # y el job habría acabado en `failed` con reembolso, sin pista del motivo.
    storage_bucket: str = Field(default="assets", alias="STORAGE_BUCKET")

    # --- autenticación ---
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    """
    Secreto HS256 legacy. Vacío es lo correcto en un proyecto con claves asimétricas:
    si está vacío, un token HS256 se **rechaza** en vez de intentar verificarse sin
    llave, que es la confusión de algoritmo de manual.
    """

    supabase_jwt_issuer: str = Field(default="", alias="SUPABASE_JWT_ISSUER")
    """Vacío = se deriva de `SUPABASE_URL`. Solo hace falta con un gateway por delante."""

    supabase_jwt_audience: str = Field(default="authenticated", alias="SUPABASE_JWT_AUDIENCE")

    jwks_cache_ttl_s: float = Field(default=600.0, alias="JWKS_CACHE_TTL_S")
    """Diez minutos. Una rotación no espera al TTL: un `kid` desconocido fuerza refresco."""

    jwt_leeway_s: float = Field(default=10.0, alias="JWT_LEEWAY_S")
    """Tolerancia de reloj entre Supabase y nosotros. Diez segundos, no más."""

    sse_ticket_ttl_s: int = Field(default=60, alias="SSE_TICKET_TTL_S")
    """Vida del ticket de reenganche SSE. Lo justo para abrir el `EventSource`."""

    signed_url_ttl_s: int = Field(default=3600, alias="SIGNED_URL_TTL_S")
    """
    TTL de las URLs firmadas del bucket. Debe cubrir la cola del proveedor además del
    render: se le pasa la URL al enviar el job y él la descarga cuando le toca.
    """

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")
    """
    Orígenes permitidos, separados por comas. Vacío = los de desarrollo.

    Estaba fijado a `localhost:5173` en el código, y eso se rompe solo: Vite salta al
    5174, 5175… en cuanto el puerto está ocupado, y entonces el navegador bloquea toda
    llamada al agente con un `TypeError: Failed to fetch` que no menciona CORS por
    ninguna parte. En producción esto tiene que apuntar al dominio real.
    """

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip():
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        # Desarrollo: el rango que Vite usa al ir buscando puerto libre.
        return [
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in range(5173, 5183)
        ]

    # --- límites de petición ---
    chat_rate_limit: int = Field(default=20, alias="CHAT_RATE_LIMIT")
    """Turnos por ventana y usuario en `/chat`. 0 desactiva el limitador."""

    chat_rate_limit_window_s: int = Field(default=60, alias="CHAT_RATE_LIMIT_WINDOW_S")

    # --- LLM ---
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    """
    Quién razona: 'openai' o 'anthropic'. Se construye en `app/llm.py`, un único sitio.

    Aviso que conviene no perder: los prompts de `agent/prompts/base.py` se escribieron y
    se afinaron contra Claude. Funcionan con GPT, pero el comportamiento de las
    herramientas y la verbosidad **no están revalidados** en OpenAI.
    """

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Sin router central de modelos: como en PostHog, cada tarea elige el suyo junto
    # a su código. Estos son solo los defectos, y dependen del proveedor activo.
    #
    # Verificados contra developers.openai.com/api/docs/models el 2026-07-20. Sol es
    # el de frontera; luna, el barato. `gpt-5` a secas nunca existió como id.
    model_root: str = Field(default="gpt-5.6-sol", alias="MODEL_ROOT")
    model_fast: str = Field(default="gpt-5.6-luna", alias="MODEL_FAST")
    model_summarize: str = Field(default="gpt-5.6-luna", alias="MODEL_SUMMARIZE")

    # Precio por defecto de tokens del agente, para modelos que no estén en la tabla de
    # `app/agent/metering.py`. En USD por millón de tokens. Existen para que un modelo
    # nuevo NUNCA se mida a 0 (sería razonar gratis contra una API de pago): si no lo
    # reconocemos, se cobra a este precio conservador. Los modelos conocidos (Claude,
    # y el gpt-5.6 actual) llevan su precio real en la tabla. Ajusta esto —o añade una
    # fila a la tabla— cuando cambies el modelo de razonamiento.
    llm_price_input_per_mtok: float = Field(default=10.0, alias="LLM_PRICE_INPUT_PER_MTOK")
    llm_price_output_per_mtok: float = Field(default=30.0, alias="LLM_PRICE_OUTPUT_PER_MTOK")

    # --- proveedores de generación ---
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    # `openai_api_key` se declara arriba, en la sección de LLM: la misma clave sirve para
    # el modelo que razona y para los dos proveedores de generación de OpenAI (Sora y
    # GPT Image). Declararla dos veces hacía que la segunda pisara a la primera.
    kling_access_key: str = Field(default="", alias="KLING_ACCESS_KEY")
    kling_secret_key: str = Field(default="", alias="KLING_SECRET_KEY")
    minimax_api_key: str = Field(default="", alias="MINIMAX_API_KEY")
    bytedance_api_key: str = Field(default="", alias="BYTEDANCE_API_KEY")
    wan_api_key: str = Field(default="", alias="WAN_API_KEY")
    higgsfield_key_id: str = Field(default="", alias="HIGGSFIELD_KEY_ID")
    higgsfield_key_secret: str = Field(default="", alias="HIGGSFIELD_KEY_SECRET")
    bfl_api_key: str = Field(default="", alias="BFL_API_KEY")
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    sync_api_key: str = Field(default="", alias="SYNC_API_KEY")

    def provider_is_configured(self, provider_id: str) -> bool:
        """Return whether a generation provider has every credential it needs.

        The catalogue is user-facing. Advertising a model whose adapter can only fail
        with "API key missing" is not graceful degradation; it is a broken affordance.
        Keep this mapping beside the credentials so adding a provider cannot silently
        forget the readiness rule.
        """
        ready = {
            "openai": bool(self.openai_api_key),
            "openai_image": bool(self.openai_api_key),
            "google": bool(self.google_api_key),
            "kling": bool(self.kling_access_key and self.kling_secret_key),
            "minimax": bool(self.minimax_api_key),
            "bytedance": bool(self.bytedance_api_key),
            "wan": bool(self.wan_api_key),
            "higgsfield": bool(self.higgsfield_key_id and self.higgsfield_key_secret),
            "bfl": bool(self.bfl_api_key),
            "elevenlabs": bool(self.elevenlabs_api_key),
            "sync": bool(self.sync_api_key),
        }
        # Unknown providers are intentionally closed. A row typo must not become a
        # model the agent offers and then cannot resolve.
        return ready.get(provider_id, False)

    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")
    """Base para los webhooks de proveedor. Debe ser accesible desde fuera."""

    # --- webhooks de proveedor ---
    webhook_secrets: str = Field(default="", alias="WEBHOOK_SECRETS")
    """
    Secretos de firma por proveedor: `proveedor=secreto,proveedor=secreto`.

    Es un mapa y no un campo por proveedor porque los ocho adaptadores no firman igual ni
    documentan el mismo nombre de cabecera, y dar de alta uno nuevo no debe obligar a
    tocar esta clase. Los dos que ya tienen credencial propia —Higgsfield y Kling— se
    resuelven desde ella y no hace falta repetirlos aquí.

    Un proveedor **sin** secreto configurado no queda "sin verificar": queda sin
    autoridad. Su cuerpo no decide nada y el estado real se reconsulta con `poll()`.
    """

    bfl_webhook_secret: str = Field(default="", alias="BFL_WEBHOOK_SECRET")
    """
    Secreto que se le manda a BFL en el propio `submit` (`webhook_secret`) y con el que
    firmará la entrega. Campo propio porque es el único proveedor donde el secreto es
    nuestro y va por petición, no una credencial suya que ya tengamos.
    """

    webhook_path_token: str = Field(default="", alias="WEBHOOK_PATH_TOKEN")
    """
    Token opaco que viaja en la URL de callback (`?t=...`) y que el endpoint exige si
    está configurado.

    No sustituye a la firma —una URL se filtra en logs y en cabeceras `Referer`— pero
    cierra lo que la firma no cubre en los proveedores que no firman: sin él, la ruta
    `/webhooks/{provider}` es un endpoint público donde cualquiera puede pedir que
    releamos el estado de un job ajeno a base de probar identificadores.
    """

    output_host_allowlist: str = Field(default="", alias="OUTPUT_HOST_ALLOWLIST")
    """
    Dominios extra desde los que se acepta descargar una salida, separados por comas.

    La lista normal la declara cada adaptador en `output_domains`. Esto es la válvula de
    escape para el domingo en que un proveedor rota su CDN: sin ella, la única forma de
    volver a entregar los renders sería un despliegue.
    """

    # --- límites ---
    job_poll_interval_s: float = 5.0
    job_timeout_s: float = 900.0
    max_concurrent_jobs_per_project: int = 6

    # --- economía ---
    #
    # K = credits_per_usd * credit_margin es el ÚNICO número que fija el precio: cuántos
    # créditos cuesta 1 USD de coste real de API. Hoy K = 40.
    #
    # El margen de la SUSCRIPCIÓN no vive aquí, vive en la relación créditos-por-euro que
    # se conceden: con 200 créditos por 20 € (0,10 €/crédito) y K = 40 (coste real de
    # 1/40 $ ≈ 0,023 € por crédito), el peor caso —el usuario quema los 200— deja
    #   margen = 1 − (0,92 · 200/40) / 20 ≈ 77 %.
    # Para reapuntar a otro margen M en ese plan: K = 9,2 / (1 − M).
    credits_per_usd: int = Field(default=40, alias="CREDITS_PER_USD")
    """
    Conversión coste de API → créditos al cliente (la parte entera de K). El precio de
    cada modelo se deriva de aquí en `credits_per_unit`; cambiar K exige regenerar el
    seed (`python -m app.providers.seed --emit-sql > backend/seeds/taxonomy.sql`), o el
    menú que ve el agente y el cobro real divergen.
    """
    credit_margin: float = Field(default=1.0, alias="CREDIT_MARGIN")

    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")

    @property
    def jwt_issuer(self) -> str:
        """Emisor esperado. Se deriva de `SUPABASE_URL` salvo que se fije a mano."""
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1"
        return ""

    @property
    def provider_signed_url_ttl_s(self) -> int:
        """
        TTL con el que se firman las referencias que viajan a un proveedor.

        No es `signed_url_ttl_s` a secas, y la diferencia es el fallo caro que este
        cálculo existe para impedir. Cuando firmamos, el proveedor todavía **no** ha
        descargado nada: primero encola. Nuestro reloj de paciencia es `job_timeout_s`
        (900 s), así que una URL con menos vida que ese timeout puede caducar mientras el
        trabajo sigue vivo en la cola ajena. El síntoma sería un 400 al descargar la
        referencia — o peor, un render que sale sin la cara del personaje — de forma
        intermitente y solo en hora punta, que es la clase de fallo que nadie diagnostica.

        Por eso se toma el máximo entre lo configurado y 4x el timeout: el factor 4 cubre
        el timeout completo más el margen de cola del proveedor. Con los valores por
        defecto (3600 y 900) los dos términos coinciden, así que subir `SIGNED_URL_TTL_S`
        funciona y bajarlo por debajo del suelo seguro, no.

        Lo que este número **no** puede arreglar es un job que espere en NUESTRA cola más
        que el TTL: por eso la firma no ocurre al encolar sino en el worker, justo antes
        del `submit`. Ver `JobWorker._process`.
        """
        return max(self.signed_url_ttl_s, int(4 * self.job_timeout_s))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
