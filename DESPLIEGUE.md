# Despliegue

Backend y worker en tu instancia de Oracle Cloud. Frontend en Vercel. Base de datos y
storage siguen en Supabase.

```
xframe-tau.vercel.app  ──HTTPS──▶  $API_HOST  ──▶  Caddy ──▶ api ──┐
      (Vercel)                     (Oracle Cloud)        worker ───┤──▶ Supabase
                                                         redis     │   (Postgres + storage)
                                                                   └──▶ OpenAI
```

## 0. El nombre del backend

El frontend ya tiene dominio: `xframe-tau.vercel.app`, que lo da Vercel. **El backend
necesita uno propio, y no puede ser un subdominio de ese**: `vercel.app` es de Vercel y no
puedes crear registros ahí.

Dos opciones, y la primera no cuesta nada ni requiere comprar dominio:

**Sin dominio propio — `sslip.io`.** Es un DNS público que resuelve cualquier nombre que
contenga una IP a esa IP. Si tu instancia es `130.61.20.5`:

    export API_HOST=130.61.20.5.sslip.io

Caddy consigue certificado de Let's Encrypt para ese nombre sin que configures ningún DNS,
porque ya resuelve. Es feo en una URL, pero para el backend nadie lo ve: solo lo consume
el frontend.

**Con dominio propio.** Un registro A de `api.tudominio.com` a la IP de la instancia:

    export API_HOST=api.tudominio.com

Elijas la que elijas, ese valor es el que va en `XFRAME_DOMAIN`, en `PUBLIC_BASE_URL` y en
`VITE_AGENT_URL` de Vercel. Cambiarlo el día que tengas dominio es tocar esas tres cosas y
volver a desplegar.

---

## 1. La instancia de Oracle

Si es una **Ampere A1** (ARM), perfecto: el `Dockerfile` parte de `python:3.12-slim`, que
tiene imagen arm64, y ffmpeg entra por apt. No hay que tocar nada. Con 4 OCPU y 24 GB del
tier gratuito vas holgado para varios workers.

**Los dos cortafuegos.** Esto es lo que más tiempo hace perder en Oracle: hay que abrir
los puertos en la *security list* de la VCN **y además** en el iptables de la instancia,
que viene cerrado en las imágenes de Oracle Linux y Ubuntu. Si solo abres uno, el DNS
resuelve, el navegador se queda colgado y no hay ningún error que lo explique.

```bash
# En la instancia
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save     # Ubuntu
# En Oracle Linux: sudo firewall-cmd --permanent --add-service={http,https} && sudo firewall-cmd --reload
```

Docker y compose:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # cierra sesión y vuelve a entrar
```

## 2. DNS

Un registro **A** de `$API_HOST` a la IP pública de la instancia. Caddy pide el
certificado solo la primera vez que arranca, así que el DNS tiene que estar propagado
antes de levantarlo o el primer intento falla y hay que reiniciarlo.

## 3. Backend

```bash
git clone https://github.com/hectorvss/Xframe.git && cd Xframe/backend
cp .env.example .env
```

Rellena `.env`. Lo que **cambia** respecto a desarrollo:

```bash
CORS_ORIGINS=https://xframe-tau.vercel.app            # el de Vercel; sin esto el navegador bloquea todo
PUBLIC_BASE_URL=https://$API_HOST     # base de los webhooks de proveedor
REDIS_URL=redis://redis:6379/0             # el del compose, no localhost
```

Y lo que se mantiene: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`OPENAI_API_KEY`, `LLM_PROVIDER`, `MODEL_*`.

```bash
export XFRAME_DOMAIN=$API_HOST
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f api
```

Comprobación:

```bash
curl https://$API_HOST/health                    # {"status":"ok"}
curl -X POST https://$API_HOST/chat              # 401
```

Un 401 ahí es la respuesta correcta: significa que la frontera de autenticación está
puesta.

## 4. Frontend en Vercel

Variables del proyecto:

```
VITE_SUPABASE_URL=https://mlawipfdsbzqtryjkeiv.supabase.co
VITE_SUPABASE_ANON_KEY=sb_publishable_...
VITE_AGENT_URL=https://$API_HOST
```

`vercel.json` ya trae el build, el fallback de SPA y las cabeceras. Con el repositorio
conectado, cada push a la rama despliega.

## 5. Supabase

En **Authentication → URL Configuration**, añade `https://xframe-tau.vercel.app` como Site URL y
como Redirect URL. Sin eso el inicio de sesión redirige a `localhost` y no vuelve.

---

## Escalar

El único eje que importa es el worker:

```bash
docker compose -f docker-compose.prod.yml up -d --scale worker=6
```

Los jobs son de **espera**, no de cómputo: un worker pasa casi todo su tiempo haciendo
polling contra el proveedor. Por eso se escala en número y no en CPU, y por eso seis
workers en una máquina modesta rinden más que uno en una grande. El reparto lo hace
Postgres con `FOR UPDATE SKIP LOCKED`, así que no hay coordinación que configurar.

La excepción es el montaje, que sí quema CPU — pero dura segundos frente a los minutos
del render.

## Actualizar

```bash
git pull && docker compose -f docker-compose.prod.yml up -d --build
```

Los workers en vuelo terminan lo que tengan entre manos: el apagado espera diez segundos
y luego cancela, y un job cancelado se reembolsa. Nada queda a medias sin liquidar.

---

## Antes de abrirlo al mundo

**Rota las claves.** Las que hay hoy han pasado por una conversación de chat. Por orden
de peligro: `SUPABASE_SERVICE_KEY` (salta RLS, acceso a todo), la contraseña de Postgres
dentro de `DATABASE_URL`, y `OPENAI_API_KEY` (solo gasto).

**Los webhooks de proveedor no están configurados.** Funciona todo por polling, que es
correcto pero más lento y más caro en peticiones. Cuando quieras activarlos, los
proveedores llamarán a `https://$API_HOST/webhooks/{proveedor}` y hay que darles de
alta el secreto de firma en `.env`.

**El chat con sesión iniciada no se ha probado en un navegador real.** Verificado está
todo lo demás: la API responde, rechaza sin token, genera imagen y vídeo de verdad, y
monta el corte. Lo primero que haría tras desplegar es entrar, escribir en el chat, y
mirar la consola.
