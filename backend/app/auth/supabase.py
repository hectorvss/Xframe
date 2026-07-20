"""
Verificación del JWT de Supabase.

El backend usaba la cabecera `x-user-id` y se fiaba. Eso no es autenticación: es una
declaración de intenciones del cliente. Cualquiera podía escribir el uuid de otro y
operar como él.

Aquí el `user_id` sale **siempre** de `claims["sub"]` de un token firmado y verificado.
No hay ninguna ruta por la que una cabecera pueda decidir quién eres.

Dos algoritmos, por dónde está Supabase hoy:

- **ES256 (asimétrico)** es el camino actual. Las claves públicas se publican en
  `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` y rotan. Se cachean con TTL y se
  refrescan cuando aparece un `kid` desconocido — que es exactamente la señal de una
  rotación — con un intervalo mínimo entre refrescos para que un token con un `kid`
  inventado no se convierta en un ariete contra el endpoint de JWKS.
- **HS256 (secreto compartido)** es el modo legacy. Se acepta solo si
  `SUPABASE_JWT_SECRET` está configurado. Si no lo está, un token HS256 se rechaza:
  la alternativa (aceptarlo sin llave) es el agujero clásico de confusión de algoritmo.

`aud`, `exp` e `iss` se comprueban siempre; `sub` es obligatorio. La lista de algoritmos
que se pasa a `jwt.decode` es la del algoritmo que ya hemos decidido aceptar, nunca la
que propone la cabecera del token.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)

ASYMMETRIC_ALGS = ("ES256", "RS256")
"""Los que se resuelven contra el JWKS. Supabase firma con ES256; RS256 se admite
porque el mismo endpoint puede publicar claves RSA y rechazarlas sería gratuito."""

MIN_REFRESH_INTERVAL_S = 30.0
"""Suelo entre refrescos forzados del JWKS. Sin esto, un atacante que mande tokens con
`kid` aleatorio nos convierte en una botnet contra nuestro propio Supabase."""


@dataclass(frozen=True, slots=True)
class AuthUser:
    """
    El usuario verificado del turno.

    `id` es `claims["sub"]`. Es el único origen de identidad del backend.
    """

    id: str
    email: str | None
    claims: dict[str, Any]


class AuthError(Exception):
    """Fallo de verificación. Se traduce a 401 sin detalle en la frontera HTTP."""


# --------------------------------------------------------------------------- #
# JWKS                                                                         #
# --------------------------------------------------------------------------- #


class JwksCache:
    """
    Caché del JWKS con TTL y refresco por `kid` desconocido.

    No usamos `jwt.PyJWKClient`: hace la petición con `urllib` de forma síncrona y
    bloquearía el bucle de eventos en cada expiración del TTL, justo en el camino
    caliente de todas las peticiones.
    """

    def __init__(
        self,
        url: str,
        *,
        ttl_s: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._ttl_s = ttl_s
        self._client = client
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0

    async def key_for(self, kid: str | None) -> Any:
        """Clave pública para un `kid`. Refresca si el TTL venció o si el `kid` es nuevo."""
        now = time.monotonic()
        stale = now - self._fetched_at > self._ttl_s
        unknown = kid is not None and kid not in self._keys

        if stale or unknown or not self._keys:
            can_refresh = stale or (now - self._fetched_at > MIN_REFRESH_INTERVAL_S)
            if can_refresh:
                await self._refresh()

        if kid is None:
            # Un JWKS con una sola clave y un token sin `kid` es válido; con varias, no
            # hay forma de elegir sin adivinar, y adivinar aquí es aceptar el token que
            # case con cualquiera.
            if len(self._keys) == 1:
                return next(iter(self._keys.values()))
            raise AuthError("token sin kid y el JWKS publica varias claves")

        key = self._keys.get(kid)
        if key is None:
            raise AuthError("kid desconocido")
        return key

    async def _refresh(self) -> None:
        try:
            client = self._client or httpx.AsyncClient(timeout=5.0)
            try:
                resp = await client.get(self._url)
                resp.raise_for_status()
                document = resp.json()
            finally:
                if self._client is None:
                    await client.aclose()
        except Exception as exc:
            logger.warning("jwks_fetch_failed", extra={"error": str(exc)})
            # No se vacía la caché: unas claves viejas que aún no han rotado sirven más
            # que un 401 a todo el mundo porque el JWKS tuvo un mal minuto.
            if not self._keys:
                raise AuthError("no se pudo obtener el JWKS") from exc
            return

        keys: dict[str, Any] = {}
        for entry in document.get("keys", []):
            try:
                keys[str(entry.get("kid"))] = jwt.PyJWK(entry).key
            except Exception:
                logger.warning("jwks_bad_key", extra={"kid": entry.get("kid")})
        if keys:
            self._keys = keys
            self._fetched_at = time.monotonic()


_jwks: JwksCache | None = None


def get_jwks_cache() -> JwksCache:
    global _jwks
    if _jwks is None:
        settings = get_settings()
        _jwks = JwksCache(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
            ttl_s=settings.jwks_cache_ttl_s,
        )
    return _jwks


def reset_jwks_cache(cache: JwksCache | None = None) -> None:
    """Punto de inyección para los tests. En producción no lo llama nadie."""
    global _jwks
    _jwks = cache


# --------------------------------------------------------------------------- #
# Verificación                                                                 #
# --------------------------------------------------------------------------- #


async def verify_token(token: str) -> AuthUser:
    """
    Verifica firma y claims. Levanta `AuthError` con un motivo interno; el motivo se
    registra pero no viaja al cliente.
    """
    settings = get_settings()

    if not token or token.count(".") != 2:
        raise AuthError("token malformado")

    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise AuthError("cabecera ilegible") from exc

    alg = header.get("alg")
    if alg in ASYMMETRIC_ALGS:
        key = await get_jwks_cache().key_for(header.get("kid"))
        algorithms = [alg]
    elif alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise AuthError("HS256 recibido sin secreto legacy configurado")
        key = settings.supabase_jwt_secret
        algorithms = ["HS256"]
    else:
        raise AuthError(f"algoritmo no admitido: {alg}")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=settings.supabase_jwt_audience,
            issuer=settings.jwt_issuer or None,
            options={
                "require": ["exp", "sub", "aud"],
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": bool(settings.jwt_issuer),
            },
            leeway=settings.jwt_leeway_s,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"jwt rechazado: {type(exc).__name__}") from exc

    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise AuthError("sub ausente")

    return AuthUser(id=sub, email=claims.get("email"), claims=claims)


def bearer_token(request: Request) -> str | None:
    """Extrae el token del `Authorization: Bearer`. Case-insensitive en el esquema."""
    raw = request.headers.get("authorization") or ""
    scheme, _, value = raw.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def current_user(request: Request) -> AuthUser:
    """
    Dependencia de FastAPI. 401 sin detalle: el motivo va al log, no a la respuesta.
    """
    token = bearer_token(request)
    if token is None:
        raise HTTPException(401, "credenciales ausentes")
    try:
        return await verify_token(token)
    except AuthError as exc:
        logger.info("auth_rejected", extra={"reason": str(exc)})
        raise HTTPException(401, "credenciales inválidas") from exc
