# Cómo verlo funcionando

Un `git push` **no despliega nada**. Esto es un repositorio, no un servidor: para ver el
agente en marcha hay que levantar cuatro cosas en tu máquina (o desplegarlas).

Y hay una pieza que no está —ni puede estar— en git: `backend/.env`, con las claves. Está
en `.gitignore` a propósito. En esta máquina ya existe y está relleno; en cualquier otra
hay que recrearlo desde `backend/.env.example`.

---

## Lo que hace falta instalado

| | Comprobar con | Si falta |
|---|---|---|
| Python 3.11+ | `python --version` | — |
| Docker Desktop | `docker info` | solo para el Postgres de los tests |
| ffmpeg | `ffmpeg -version` | `winget install Gyan.FFmpeg` |
| Node 18+ | `node --version` | — |

Redis es opcional para verlo funcionar: el bus de eventos se traga sus fallos a
propósito, porque transporta *progreso*, no *estado* — la verdad de un job vive en
Postgres. Sin Redis el chat funciona; lo que se pierde es el reenganche al stream si
cierras la pestaña a media generación.

---

## Arrancar (tres terminales)

```bash
# 1. dependencias, solo la primera vez
cd backend
pip install -e ".[dev]"

# 2. API
python run_api.py --port 8000

# 3. worker  (otra terminal)
cd backend && python -m app.jobs

# 4. frontend  (otra terminal, desde la raíz)
npm run dev
```

Abre la URL que imprima Vite. **Ojo con el puerto**: si el 5173 está ocupado salta al
5174, 5175… y el backend solo acepta los orígenes de `CORS_ORIGINS` (por defecto el rango
5173-5182). Si usas otro, ponlo ahí.

`python run_api.py` y no `uvicorn app.main:app`: uvicorn instala su propio bucle de
eventos en Windows y elige uno que el driver de Postgres no soporta, así que el proceso
muere al arrancar. El entrypoint existe para evitar exactamente eso.

---

## Comprobar que está vivo, sin tocar la interfaz

```bash
curl http://127.0.0.1:8000/health          # {"status":"ok"}
curl -X POST http://127.0.0.1:8000/chat    # 401: la autenticación funciona
```

Y los tres guiones de humo, que ejercitan el sistema entero contra infraestructura real:

```bash
cd backend
python -m scripts.smoke_agent      # el agente razona y escribe en la BD (céntimos)
python -m scripts.smoke_generate   # genera una imagen de verdad (~0,02 €)
python -m scripts.smoke_assemble   # monta un corte con ffmpeg (gratis)
```

`smoke_generate --video` genera un clip con Sora. Cuesta del orden de 0,80 €, así que se
deja fuera del camino habitual.

---

## Qué esperar en la interfaz

Entra, inicia sesión y abre un proyecto. En el editor, el chat habla con el agente real:
te escribirá el tratamiento, definirá elementos y creará planos, y lo verás aparecer en
las pestañas de Brief y Canvas conforme lo hace.

**En preproducción no puede generar nada**, y no es una restricción del prompt: las
herramientas de generación literalmente no se le montan. Para que genere hay que pasar a
producción, y entonces cada plano cuesta créditos de verdad.

---

## Antes de enseñárselo a nadie

Las claves que hay hoy en `backend/.env` han pasado por una conversación de chat:
**considéralas comprometidas y rótalas**. Por orden de peligro:

1. `SUPABASE_SERVICE_KEY` — salta RLS, da acceso a todos los datos de todos los usuarios.
2. La contraseña de Postgres (dentro de `DATABASE_URL`).
3. `OPENAI_API_KEY` — como mucho, gasto.

Nada del sistema depende de que sean estas: se cambian en el `.env` y sigue funcionando.

Y esto sigue siendo desarrollo local. Para que otra persona lo vea hace falta desplegar el
backend y el worker en algún sitio con `PUBLIC_BASE_URL` y `CORS_ORIGINS` apuntando al
dominio real.
