# Desplegar Xframe junto a greeksdesk (misma instancia de Oracle)

El tier gratuito de Oracle da **una** instancia, y ya la ocupa greeksdesk. No hace falta
otra: las dos cosas caben en la misma máquina. greeksdesk ya tiene **Caddy en 80/443**
—comprobado: `Server: Caddy` y un 308 a HTTPS—, así que Xframe se mete **detrás de ese
Caddy** en vez de levantar uno propio, que chocaría por el puerto.

```
                         ┌─ greeksdesk           (lo que ya hay)
xframe-tau.vercel.app ──▶ Caddy (greeksdesk) ─┤
                         └─ Xframe api :8000    (lo nuevo, en 127.0.0.1)
                                 │
                             worker · redis ──▶ Supabase · OpenAI
```

Nada de greeksdesk se toca salvo **añadir un bloque a su Caddyfile**. Su Caddy, su TLS y
sus puertos siguen igual.

---

## 0. El acceso (lo único que falta)

Ninguna de las claves de `Descargas` abre la instancia: la que la creó no está ahí. Antes
de nada, una de estas dos:

**A. La clave con la que entras a greeksdesk.** Si usas PuTTY es un `.ppk`; si usas
terminal, mira en `C:\Users\usuario\.ssh\`. Con ella:

    ssh -i <clave> <usuario>@80.225.188.183     # usuario: opc en Oracle Linux, ubuntu en Ubuntu

**B. Añadir una clave nueva desde la consola de Oracle Cloud**, sin la original: Compute →
la instancia → *Console connection* → *Create local connection*, o pega una clave pública
nueva por Cloud Shell. Si eliges esta vía, dilo y te genero el par y te guío.

La instancia es **Oracle Linux** (OpenSSH 8.7), así que el usuario será casi seguro `opc`.

---

## 1. El nombre del backend

El navegador exige HTTPS con certificado válido, y Caddy lo saca solo, pero necesita un
**nombre**, no una IP. Dos caminos:

- **`sslip.io` sobre la IP** — cero configuración: `80.225.188.183.sslip.io` ya resuelve a
  la instancia, y Caddy le saca certificado de Let's Encrypt. Feo en la URL, pero solo lo
  ve el frontend.
- **Un subdominio de greeksdesk**, si tiene dominio propio: un registro A de
  `xframe-api.eldominio.com` a `80.225.188.183`.

Ese valor es `API_HOST` en todo lo que sigue.

---

## 2. Subir Xframe

En la instancia:

```bash
git clone https://github.com/hectorvss/Xframe.git
cd Xframe/backend
cp .env.example .env
nano .env       # ver el bloque de abajo
```

En `.env`, lo que cambia respecto a local:

```bash
CORS_ORIGINS=https://xframe-tau.vercel.app
PUBLIC_BASE_URL=https://API_HOST
REDIS_URL=redis://redis:6379/0
```

Lo que se mantiene: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (el JWT
`service_role`, no la `sb_secret_`), `OPENAI_API_KEY`, `LLM_PROVIDER`, `MODEL_*`.

Arrancar — **sin Caddy**, con el compose compartido:

```bash
docker compose -f docker-compose.shared.yml up -d --build
curl http://127.0.0.1:8000/health       # {"status":"ok"} desde la propia máquina
```

La API queda en `127.0.0.1:8000`, alcanzable solo desde la instancia. Aún no desde fuera:
falta el proxy.

---

## 3. Engancharla al Caddy de greeksdesk

Localiza el Caddyfile de greeksdesk (suele estar montado como volumen en su
`docker-compose`; búscalo con `docker inspect` del contenedor de Caddy, campo `Mounts`).
Añade **un bloque nuevo**, sin tocar los que ya hay:

```caddy
API_HOST {
	reverse_proxy 127.0.0.1:8000 {
		# Imprescindible para el chat: los eventos van por SSE y un proxy con buffer
		# los acumula y los entrega de golpe al final. Sin error, solo "no responde".
		flush_interval -1
		transport http {
			read_timeout 15m
			write_timeout 15m
		}
	}
}
```

Un matiz según cómo corra el Caddy de greeksdesk:

- **Caddy con `network_mode: host`** → `reverse_proxy 127.0.0.1:8000` funciona tal cual.
- **Caddy en red Docker normal** → `127.0.0.1` es el del contenedor, no el del host. Usa
  `reverse_proxy host.docker.internal:8000` y añade al servicio de Caddy
  `extra_hosts: ["host.docker.internal:host-gateway"]`. Si prefieres no tocar su compose,
  la alternativa es una red Docker externa compartida; dime cómo está montado y te doy el
  detalle exacto.

Recargar Caddy sin cortar nada de greeksdesk:

```bash
docker exec <contenedor-caddy> caddy reload --config /etc/caddy/Caddyfile
```

Comprobar desde fuera:

```bash
curl https://API_HOST/health     # {"status":"ok"}
curl -X POST https://API_HOST/chat   # 401  (la autenticación está puesta)
```

---

## 4. Conectar el frontend

En Vercel → proyecto `xframe` → Settings → Environment Variables:

```
VITE_AGENT_URL=https://API_HOST
```

Redeploy (o `git commit --allow-empty` y push). El chat pasa a hablar con la instancia.

Y en Supabase → Authentication → URL Configuration, añade
`https://xframe-tau.vercel.app` como Site URL y Redirect URL.

---

## 5. Verificación final, ya en producción

1. Entra en `xframe-tau.vercel.app`, inicia sesión, abre un proyecto.
2. Escribe en el chat: debe responder por streaming, escribir el brief y crear planos.
3. Pasa a producción y genera un plano: mira que el asset aparece y el saldo baja.

---

## Convivencia y recursos

greeksdesk y Xframe comparten CPU, RAM y disco de la instancia. En una A1 del tier
gratuito (4 OCPU / 24 GB) sobra, pero:

- El worker de Xframe arranca con `replicas: 2`. Si notas la máquina cargada, bájalo a 1:
  `docker compose -f docker-compose.shared.yml up -d --scale worker=1`.
- Los logs están topados a 100 MB por servicio, así que no se comen el disco.
- El montaje con ffmpeg es lo único que quema CPU, y dura segundos. Si coincide con carga
  de greeksdesk, se nota un pico corto, no sostenido.

## Antes de abrirlo

Rota las claves que pasaron por el chat, por orden de peligro: `SUPABASE_SERVICE_KEY`
(salta RLS), la contraseña de Postgres del `DATABASE_URL`, y `OPENAI_API_KEY`.
