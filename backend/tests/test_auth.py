"""
La frontera de autenticación y de tenant.

Lo que se comprueba aquí no es que el JWT se decodifique —eso lo hace PyJWT— sino las
tres cosas que el backend hacía mal y que ninguna librería arregla sola:

1. La identidad **nunca** puede venir de una cabecera. `x-user-id` tiene que ser
   irrelevante incluso cuando llega bien formada.
2. Autenticarse no es autorizarse: un usuario válido con el uuid de un proyecto ajeno
   tiene que rebotar, y rebotar con 404, sin oráculo de existencia.
3. El SSE de reenganche es el endpoint más goloso del sistema —con `Last-Event-ID: 0-0`
   reproduce la transcripción entera— y tenía cero autenticación.
"""

from __future__ import annotations

import os
import time

import httpx
import jwt
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("SUPABASE_URL", "https://proyecto.supabase.co")

from app import db, main
from app.auth import _redis as auth_redis
from app.auth.supabase import AuthError, verify_token
from app.config import get_settings

SECRET = "secreto-de-pruebas-que-no-vive-en-el-repo"
ISSUER = "https://proyecto.supabase.co/auth/v1"

ALICE = "11111111-1111-4111-8111-111111111111"
BEATRIZ = "22222222-2222-4222-8222-222222222222"
PROYECTO_DE_ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROYECTO_DE_BEATRIZ = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CONV_DE_ALICE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CONV_DE_BEATRIZ = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


# --------------------------------------------------------------------------- #
# Andamiaje                                                                    #
# --------------------------------------------------------------------------- #


def token_for(
    sub: str = ALICE,
    *,
    aud: str = "authenticated",
    iss: str | None = ISSUER,
    exp_delta: int = 3_600,
    secret: str = SECRET,
    alg: str = "HS256",
) -> str:
    claims: dict[str, object] = {
        "sub": sub,
        "aud": aud,
        "exp": int(time.time()) + exp_delta,
        "iat": int(time.time()),
        "email": "alice@example.com",
    }
    if iss is not None:
        claims["iss"] = iss
    return jwt.encode(claims, secret, algorithm=alg)


class FakeRedis:
    """Lo justo para tickets y rate limit: `set`, `getdel`, `incr`, `expire`."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, ttl: int) -> None:
        return None


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """
    Ajustes de test sobre el singleton de config, y Redis y BD falsos.

    Se toca el objeto ya construido en vez de recargar la config: `get_settings` está
    cacheado y vaciar la caché afectaría a los otros módulos de test.
    """
    settings = get_settings()
    previos = {
        k: getattr(settings, k)
        for k in ("supabase_url", "supabase_jwt_secret", "supabase_jwt_audience", "chat_rate_limit")
    }
    settings.supabase_url = "https://proyecto.supabase.co"
    settings.supabase_jwt_secret = SECRET
    settings.supabase_jwt_audience = "authenticated"
    settings.chat_rate_limit = 100

    fake = FakeRedis()
    auth_redis.set_redis(fake)

    # El runner real levantaría el grafo. Este devuelve un turno vacío: casi todos estos
    # casos tienen que cortar antes de llegar aquí, y el del rate limit necesita que las
    # primeras peticiones pasen de verdad para que la tercera rebote.
    class RunnerFalso:
        async def run(self, **_):
            if False:  # pragma: no cover - solo para que sea un generador asíncrono
                yield {}

    monkeypatch.setattr(main, "_runner", RunnerFalso(), raising=False)

    yield fake

    auth_redis.set_redis(None)
    for k, v in previos.items():
        setattr(settings, k, v)


def base_de_datos(monkeypatch, *, proyectos: dict[str, str], conversaciones: dict[str, tuple[str, str]]):
    """
    BD falsa: `proyectos` es {project_id: owner_id} y `conversaciones` es
    {conversation_id: (owner_id, project_id)}.
    """

    async def fetchval(q: str, *args):
        if "from public.projects" in q:
            project_id, user_id = args
            return 1 if proyectos.get(project_id) == user_id else None
        if "from public.conversations c" in q:
            conversation_id, user_id = args
            fila = conversaciones.get(conversation_id)
            if fila is None:
                return None
            owner, project_id = fila
            return 1 if owner == user_id and proyectos.get(project_id) == user_id else None
        raise AssertionError(f"consulta inesperada: {q}")

    async def fetchrow(q: str, *args):
        if "from public.conversations where id" in q:
            fila = conversaciones.get(args[0])
            return None if fila is None else {"owner_id": fila[0], "project_id": fila[1]}
        raise AssertionError(f"consulta inesperada: {q}")

    monkeypatch.setattr(db, "fetchval", fetchval)
    monkeypatch.setattr(db, "fetchrow", fetchrow)


def cliente() -> httpx.AsyncClient:
    """Sin `TestClient` a propósito: no queremos que arranque el `lifespan` (BD y Redis)."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    )


# --------------------------------------------------------------------------- #
# Verificación del token                                                       #
# --------------------------------------------------------------------------- #


async def test_un_token_bien_formado_da_el_sub_como_identidad():
    user = await verify_token(token_for(ALICE))
    assert user.id == ALICE
    assert user.email == "alice@example.com"


@pytest.mark.parametrize(
    "token_malo, motivo",
    [
        (lambda: token_for(secret="otro-secreto"), "firma de otra llave"),
        (lambda: token_for(exp_delta=-60), "caducado"),
        (lambda: token_for(aud="anon"), "audiencia equivocada"),
        (lambda: token_for(iss="https://atacante.example/auth/v1"), "emisor equivocado"),
        (lambda: "no.es.un.jwt", "basura"),
        (lambda: "", "vacío"),
    ],
)
async def test_los_tokens_invalidos_se_rechazan(token_malo, motivo):
    with pytest.raises(AuthError):
        await verify_token(token_malo())


async def test_un_token_sin_firma_no_cuela():
    """
    `alg: none` es el ataque de libro contra un verificador escrito a mano.
    """
    sin_firmar = jwt.encode(
        {"sub": ALICE, "aud": "authenticated", "exp": int(time.time()) + 60, "iss": ISSUER},
        key="",
        algorithm="none",
    )
    with pytest.raises(AuthError):
        await verify_token(sin_firmar)


async def test_hs256_sin_secreto_configurado_se_rechaza():
    """
    Sin secreto no se puede verificar HS256. Aceptarlo sería la confusión de algoritmo:
    un atacante firma con la clave PÚBLICA del JWKS, que conoce, y pasa.
    """
    settings = get_settings()
    settings.supabase_jwt_secret = ""
    try:
        with pytest.raises(AuthError):
            await verify_token(token_for(ALICE))
    finally:
        settings.supabase_jwt_secret = SECRET


# --------------------------------------------------------------------------- #
# /chat                                                                        #
# --------------------------------------------------------------------------- #


async def test_chat_sin_credenciales_es_401(monkeypatch):
    base_de_datos(monkeypatch, proyectos={PROYECTO_DE_ALICE: ALICE}, conversaciones={})
    async with cliente() as c:
        r = await c.post(
            "/chat",
            json={"conversation_id": CONV_DE_ALICE, "project_id": PROYECTO_DE_ALICE, "message": "hola"},
        )
    assert r.status_code == 401


async def test_chat_con_token_invalido_es_401(monkeypatch):
    base_de_datos(monkeypatch, proyectos={PROYECTO_DE_ALICE: ALICE}, conversaciones={})
    async with cliente() as c:
        r = await c.post(
            "/chat",
            json={"conversation_id": CONV_DE_ALICE, "project_id": PROYECTO_DE_ALICE, "message": "hola"},
            headers={"authorization": f"Bearer {token_for(secret='otro')}"},
        )
    assert r.status_code == 401
    assert "otro" not in r.text  # el motivo del rechazo no viaja al cliente


async def test_la_cabecera_x_user_id_ya_no_autentica_nada(monkeypatch):
    """
    La regresión que hay que impedir para siempre: antes, esto era acceso completo.
    """
    base_de_datos(monkeypatch, proyectos={PROYECTO_DE_ALICE: ALICE}, conversaciones={})
    async with cliente() as c:
        r = await c.post(
            "/chat",
            json={"conversation_id": CONV_DE_ALICE, "project_id": PROYECTO_DE_ALICE, "message": "hola"},
            headers={"x-user-id": ALICE},
        )
    assert r.status_code == 401


async def test_chat_contra_un_proyecto_ajeno_es_404(monkeypatch):
    """
    Beatriz está autenticada de verdad. Lo que no puede es tocar el proyecto de Alice:
    ahí es donde se leía, se borraba el brief y se gastaban los créditos de la víctima.

    404 y no 403: distinguir "no existe" de "existe y no es tuyo" es un oráculo para
    enumerar uuids ajenos.
    """
    base_de_datos(
        monkeypatch,
        proyectos={PROYECTO_DE_ALICE: ALICE, PROYECTO_DE_BEATRIZ: BEATRIZ},
        conversaciones={},
    )
    async with cliente() as c:
        r = await c.post(
            "/chat",
            json={"conversation_id": CONV_DE_BEATRIZ, "project_id": PROYECTO_DE_ALICE, "message": "borra el brief"},
            headers={"authorization": f"Bearer {token_for(BEATRIZ)}"},
        )
    assert r.status_code == 404


async def test_no_se_puede_continuar_la_conversacion_de_otro_en_el_proyecto_propio(monkeypatch):
    """
    Segundo salto: proyecto propio, conversación ajena. Sin esta comprobación se
    inyectan turnos en el hilo de otro y se lee su historial por el camino.
    """
    base_de_datos(
        monkeypatch,
        proyectos={PROYECTO_DE_BEATRIZ: BEATRIZ},
        conversaciones={CONV_DE_ALICE: (ALICE, PROYECTO_DE_ALICE)},
    )
    async with cliente() as c:
        r = await c.post(
            "/chat",
            json={"conversation_id": CONV_DE_ALICE, "project_id": PROYECTO_DE_BEATRIZ, "message": "hola"},
            headers={"authorization": f"Bearer {token_for(BEATRIZ)}"},
        )
    assert r.status_code == 404


async def test_el_rate_limit_corta_el_bucle(monkeypatch):
    base_de_datos(monkeypatch, proyectos={PROYECTO_DE_ALICE: ALICE}, conversaciones={})
    get_settings().chat_rate_limit = 2

    cuerpo = {"conversation_id": CONV_DE_ALICE, "project_id": PROYECTO_DE_ALICE, "message": "hola"}
    cabeceras = {"authorization": f"Bearer {token_for(ALICE)}"}
    codigos = []
    async with cliente() as c:
        for _ in range(3):
            r = await c.post("/chat", json=cuerpo, headers=cabeceras)
            codigos.append(r.status_code)
            if r.status_code == 429:
                assert r.headers.get("retry-after")

    assert codigos[-1] == 429


# --------------------------------------------------------------------------- #
# /conversations/{id}/stream                                                   #
# --------------------------------------------------------------------------- #


async def test_el_stream_sin_credenciales_es_401(monkeypatch):
    """
    El caso del informe: `Last-Event-ID: 0-0` reproducía la transcripción entera.
    """
    base_de_datos(
        monkeypatch,
        proyectos={PROYECTO_DE_ALICE: ALICE},
        conversaciones={CONV_DE_ALICE: (ALICE, PROYECTO_DE_ALICE)},
    )
    async with cliente() as c:
        r = await c.get(
            f"/conversations/{CONV_DE_ALICE}/stream", headers={"last-event-id": "0-0"}
        )
    assert r.status_code == 401


async def test_el_stream_de_una_conversacion_ajena_es_404(monkeypatch):
    base_de_datos(
        monkeypatch,
        proyectos={PROYECTO_DE_ALICE: ALICE, PROYECTO_DE_BEATRIZ: BEATRIZ},
        conversaciones={CONV_DE_ALICE: (ALICE, PROYECTO_DE_ALICE)},
    )
    async with cliente() as c:
        r = await c.get(
            f"/conversations/{CONV_DE_ALICE}/stream",
            headers={"authorization": f"Bearer {token_for(BEATRIZ)}", "last-event-id": "0-0"},
        )
    assert r.status_code == 404


async def test_un_ticket_inventado_no_abre_el_stream(monkeypatch):
    base_de_datos(
        monkeypatch,
        proyectos={PROYECTO_DE_ALICE: ALICE},
        conversaciones={CONV_DE_ALICE: (ALICE, PROYECTO_DE_ALICE)},
    )
    async with cliente() as c:
        r = await c.get(f"/conversations/{CONV_DE_ALICE}/stream?ticket=inventado")
    assert r.status_code == 401


async def test_el_ticket_es_de_un_solo_uso(monkeypatch):
    """
    Un ticket que se pudiera reutilizar sería un token de sesión en la query, que es
    justo lo que se quería evitar.
    """
    base_de_datos(
        monkeypatch,
        proyectos={PROYECTO_DE_ALICE: ALICE},
        conversaciones={CONV_DE_ALICE: (ALICE, PROYECTO_DE_ALICE)},
    )
    from app.auth.tickets import consume_stream_ticket, issue_stream_ticket

    ticket, _ = await issue_stream_ticket(user_id=ALICE, conversation_id=CONV_DE_ALICE)
    assert await consume_stream_ticket(ticket, conversation_id=CONV_DE_ALICE) == ALICE
    assert await consume_stream_ticket(ticket, conversation_id=CONV_DE_ALICE) is None


async def test_un_ticket_no_sirve_para_otra_conversacion(monkeypatch):
    from app.auth.tickets import consume_stream_ticket, issue_stream_ticket

    ticket, _ = await issue_stream_ticket(user_id=ALICE, conversation_id=CONV_DE_ALICE)
    assert await consume_stream_ticket(ticket, conversation_id=CONV_DE_BEATRIZ) is None
    # Y queda gastado: presentarlo contra la conversación equivocada es un intento de
    # reutilización, no un despiste que merezca un segundo intento.
    assert await consume_stream_ticket(ticket, conversation_id=CONV_DE_ALICE) is None


async def test_no_se_emiten_tickets_para_conversaciones_ajenas(monkeypatch):
    base_de_datos(
        monkeypatch,
        proyectos={PROYECTO_DE_ALICE: ALICE, PROYECTO_DE_BEATRIZ: BEATRIZ},
        conversaciones={CONV_DE_ALICE: (ALICE, PROYECTO_DE_ALICE)},
    )
    async with cliente() as c:
        r = await c.post(
            f"/auth/stream-ticket?conversation_id={CONV_DE_ALICE}",
            headers={"authorization": f"Bearer {token_for(BEATRIZ)}"},
        )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Fugas por el mensaje de error                                                #
# --------------------------------------------------------------------------- #


def test_los_errores_del_agente_no_llevan_detalle_al_cliente():
    """
    `str(e)` de asyncpg lleva fragmentos de la consulta y nombres de columna: un mapa
    del esquema servido a quien sepa provocar un error.
    """
    fuga = {
        "type": "error",
        "message": 'relation "public.credit_ledger" does not exist\nLINE 1: select * from ...',
    }
    limpio = main._sanitize(fuga)

    assert limpio["message"] == main.GENERIC_ERROR
    assert "credit_ledger" not in limpio["message"]
    # Lo que no es un error pasa intacto: el filtro no puede comerse el contenido útil.
    assert main._sanitize({"type": "message_delta", "text": "hola"})["text"] == "hola"
