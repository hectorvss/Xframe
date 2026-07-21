/**
 * Cliente del agente de Xframe.
 *
 * El backend (backend/app/main.py) expone tres rutas:
 *
 *   POST /chat                          → ejecuta un turno y emite sus eventos (SSE)
 *   POST /auth/stream-ticket            → ticket de un solo uso para el reenganche
 *   GET  /conversations/{id}/stream     → se reengancha a un turno en curso (SSE)
 *
 * Autenticación: `Authorization: Bearer <access_token>` de Supabase. La cabecera
 * `x-user-id` que se mandaba antes ya no la lee nadie — era una declaración de
 * intenciones del cliente, no autenticación, y con ella cualquiera operaba como
 * cualquiera. El `user_id` sale ahora del `sub` de un JWT firmado.
 *
 * No se usa `EventSource` a propósito: solo sabe hacer GET y el turno necesita
 * mandar el mensaje y el contexto de UI en el cuerpo. Con `fetch` + el
 * `ReadableStream` de la respuesta se parsea SSE a mano, que son veinte líneas,
 * y a cambio se gana POST, cabeceras propias (el Bearer, sin ir más lejos) y
 * cancelación con `AbortController`.
 *
 * La reconexión es la razón de que el backend tenga un Redis Stream detrás: si
 * se corta el POST, se reengancha por GET con `Last-Event-ID` y no se pierde lo
 * que ocurrió mientras tanto. Un render de doce planos dura minutos y el
 * usuario cierra el portátil; el worker sigue y los assets aterrizan igual.
 *
 * Protocolo de eventos (backend/app/agent/runner.py::_to_event y
 * backend/app/stream/bus.py::EventType):
 *
 *   message_delta     { node, content }        texto incremental
 *   tool_start        { tools: [nombre] }      empieza a ejecutar herramientas
 *   tool_result       { tool_call_id, content, ui_payload }
 *   tool_progress     { ... }                  progreso de una herramienta larga
 *   asset_ready       { asset }                un render ha terminado
 *   job_status        { status, ... }          estado de un job de generación
 *   interrupt_request { ... }                  el grafo pide confirmación
 *   error             { message }
 *   done                                       fin del turno (lo pone /chat)
 */

import { supabase } from "./supabase";

// El backend por defecto según dónde corra el frontend:
// - `VITE_AGENT_URL` manda siempre; es lo que se pondrá el día que haya dominio propio.
// - Sin ella, en desarrollo (localhost) se habla con el backend local; en cualquier otro
//   host —Vercel— con la instancia de producción. Así el despliegue funciona sin
//   configurar nada en Vercel, y basta cambiar la variable cuando el dominio cambie.
const DEFAULT_AGENT_URL =
  typeof window !== "undefined" &&
  window.location.hostname !== "localhost" &&
  window.location.hostname !== "127.0.0.1"
    ? "https://80.225.185.31.sslip.io"
    : "http://localhost:8000";

export const AGENT_URL = (
  import.meta.env.VITE_AGENT_URL || DEFAULT_AGENT_URL
).replace(/\/+$/, "");

/** Mensaje único de degradado: si el backend no está, se dice y no se rompe nada. */
export const AGENT_DOWN_MESSAGE =
  "No consigo conectar con el agente. Comprueba que el backend está en marcha " +
  "en " +
  AGENT_URL +
  " y vuelve a intentarlo: tus mensajes y tus assets siguen guardados.";

/** Sesión caducada o ausente: hay que volver a entrar, no reintentar en bucle. */
export const AUTH_REQUIRED_MESSAGE =
  "Tu sesión ha caducado. Vuelve a iniciar sesión para seguir trabajando con el agente.";

/**
 * Propiedad. El backend contesta 404 tanto si el recurso no existe como si es de
 * otro (a propósito: distinguirlos sería un oráculo para enumerar uuids ajenos),
 * así que aquí tampoco se afina más de lo que nos dicen.
 */
export const OWNERSHIP_MESSAGE =
  "Este proyecto o esta conversación no están disponibles para tu cuenta.";

/** 429. El backend manda `Retry-After` en segundos; se la enseñamos tal cual. */
export const rateLimitMessage = (seconds) =>
  seconds > 0
    ? `Demasiadas peticiones. Espera ${seconds} segundo${seconds === 1 ? "" : "s"} y vuelve a intentarlo.`
    : "Demasiadas peticiones. Espera unos segundos y vuelve a intentarlo.";

/* ------------------------------------------------------------------ *
 * Autenticación                                                       *
 * ------------------------------------------------------------------ */

/**
 * Error de una respuesta HTTP que no es de red. Se distingue de un fallo de
 * conexión porque un 401 o un 404 no se arreglan reintentando: reenganchar
 * cuatro veces contra un 404 solo retrasa el mensaje que el usuario necesita.
 */
class AgentHttpError extends Error {
  constructor(status, retryAfter = 0) {
    super(`El agente respondió ${status}`);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

function httpError(response) {
  const raw = response.headers.get("Retry-After");
  const retryAfter = Number.parseInt(raw ?? "", 10);
  return new AgentHttpError(
    response.status,
    Number.isFinite(retryAfter) ? retryAfter : 0,
  );
}

/**
 * Access token de la sesión actual.
 *
 * `getSession()` ya renueva por su cuenta cuando el token está caducado, pero
 * no cuando el backend lo rechaza por otro motivo (rotación de claves, reloj
 * desfasado). Por eso existe `forceRefresh`: es lo que se usa en el reintento
 * único tras un 401.
 */
async function accessToken({ forceRefresh = false } = {}) {
  if (!supabase) return null;
  try {
    const { data, error } = forceRefresh
      ? await supabase.auth.refreshSession()
      : await supabase.auth.getSession();
    if (error) return null;
    return data?.session?.access_token ?? null;
  } catch {
    return null;
  }
}

/**
 * `fetch` con el Bearer puesto y un reintento ante 401.
 *
 * El reintento es uno y solo uno: si el token recién refrescado también se
 * rechaza, el problema no es el token y hay que mandar al usuario a la pantalla
 * de acceso en vez de girar sobre un 401 eterno.
 */
async function authorizedFetch(url, init = {}) {
  const attempt = async (forceRefresh) => {
    const token = await accessToken({ forceRefresh });
    if (!token) return null;
    return fetch(url, {
      ...init,
      headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
    });
  };

  const first = await attempt(false);
  if (!first) throw new AgentHttpError(401);
  if (first.status !== 401) return first;

  // El cuerpo del 401 no interesa, pero hay que consumirlo para no dejar la
  // conexión colgando mientras se renueva la sesión.
  first.body?.cancel?.().catch(() => {});
  const second = await attempt(true);
  if (!second) throw new AgentHttpError(401);
  return second;
}

/** API de administración del servidor MCP (no el protocolo MCP en sí). */
export async function mcpApi(path, init = {}) {
  const response = await authorizedFetch(`${AGENT_URL}/mcp${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) throw httpError(response);
  if (response.status === 204) return null;
  return response.json();
}

/**
 * Ticket de un solo uso para el SSE de reenganche.
 *
 * Se pide uno **en cada** reconexión: dura unos 60 s y el backend lo consume con
 * `GETDEL`, así que guardarlo para el siguiente intento garantiza un 401.
 */
async function requestStreamTicket(conversationId, signal) {
  const url =
    `${AGENT_URL}/auth/stream-ticket` +
    `?conversation_id=${encodeURIComponent(conversationId)}`;
  const response = await authorizedFetch(url, { method: "POST", signal });
  if (!response.ok) throw httpError(response);
  const { ticket } = await response.json();
  if (!ticket) throw new AgentHttpError(401);
  return ticket;
}

/**
 * Id de conversación por proyecto.
 *
 * El backend lo usa como `thread_id` del checkpointer de LangGraph, así que
 * tiene que sobrevivir a una recarga: si cambia, el agente pierde el hilo y
 * empieza de cero. Se guarda en localStorage y es un uuid porque la tabla
 * `conversations` lo declara así.
 */
export function conversationIdFor(projectId) {
  const key = `xframe.conversation.${projectId}`;
  try {
    const saved = localStorage.getItem(key);
    if (saved) return saved;
    const fresh =
      crypto.randomUUID?.() ??
      "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
        (
          c ^
          (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))
        ).toString(16),
      );
    localStorage.setItem(key, fresh);
    return fresh;
  } catch {
    return projectId;
  }
}

/** ¿Responde el backend? Se usa para degradar antes de montar la UI del turno. */
export async function agentReachable(timeoutMs = 2500) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const res = await fetch(`${AGENT_URL}/health`, { signal: abort.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/* ------------------------------------------------------------------ *
 * Parser SSE                                                          *
 * ------------------------------------------------------------------ */

/**
 * Trocea un `ReadableStream` de bytes en eventos SSE.
 *
 * El buffer es imprescindible: un chunk de red no respeta los límites del
 * protocolo y parte los eventos por cualquier byte. Se acumula y solo se emite
 * lo que va hasta un `\n\n` completo.
 */
async function* parseSSE(body, signal) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let cut;
      while ((cut = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const frame = readFrame(raw);
        if (frame) yield frame;
      }
    }
  } finally {
    // Cancelar el lector cierra la conexión de verdad. Sin esto, abortar un
    // turno deja el socket abierto hasta que caduque.
    if (signal?.aborted) reader.cancel().catch(() => {});
  }
}

/** Convierte un bloque de líneas `id:` / `event:` / `data:` en un evento normalizado. */
function readFrame(raw) {
  let id = null;
  const dataLines = [];

  for (const line of raw.split("\n")) {
    if (line.startsWith("id:")) id = line.slice(3).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    // `event:` se ignora: el tipo real viaja dentro del JSON, y así las dos
    // rutas (POST /chat y el reattach del bus) se leen con el mismo código.
  }

  if (!dataLines.length) return null;

  try {
    const payload = JSON.parse(dataLines.join("\n"));
    // El bus envuelve el evento en { type, data, ts }; /chat lo manda plano.
    const event =
      payload.data && typeof payload.data === "object"
        ? { type: payload.type, ...payload.data }
        : payload;
    return { id, event };
  } catch {
    // Un evento corrupto se descarta: perder progreso es tolerable, cortarle
    // el stream al usuario no.
    return null;
  }
}

/* ------------------------------------------------------------------ *
 * Turno de conversación                                               *
 * ------------------------------------------------------------------ */

const RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 1200;

/**
 * Ejecuta un turno y va llamando a los manejadores conforme llegan eventos.
 *
 * `handlers` acepta una función por tipo de evento más `onEvent` (todos) y
 * `onDone`. Todos son opcionales: lo que no se maneja, se ignora.
 *
 * Devuelve una promesa que resuelve al terminar el turno. No lanza por fallo de
 * red: llama a `onError` con un mensaje en castellano y resuelve. Un chat que
 * revienta la app por un backend caído es peor que un chat que no responde.
 */
export function sendMessage({
  conversationId,
  projectId,
  message,
  uiContext = null,
  resume = null,
  signal,
  ...handlers
}) {
  const abort = new AbortController();
  if (signal) signal.addEventListener("abort", () => abort.abort());

  const promise = run();
  return { promise, cancel: () => abort.abort() };

  async function run() {
    let lastEventId = null;
    let finished = false;

    const emit = (event) => {
      handlers.onEvent?.(event);
      const fn = handlers[handlerName(event.type)];
      if (typeof fn === "function") fn(event);
      if (event.type === "done") finished = true;
    };

    // Primer intento: el POST que arranca el turno. Los siguientes son
    // reenganches por GET, que no vuelven a ejecutar nada — solo releen.
    for (let attempt = 0; attempt <= RECONNECT_ATTEMPTS; attempt += 1) {
      try {
        let response;
        if (attempt === 0) {
          response = await authorizedFetch(`${AGENT_URL}/chat`, {
            method: "POST",
            signal: abort.signal,
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
            },
            body: JSON.stringify({
              conversation_id: conversationId,
              project_id: projectId,
              message,
              ui_context: uiContext,
              resume,
            }),
          });
        } else {
          // Reenganche. El ticket se pide aquí dentro, no fuera del bucle: es de
          // un solo uso y de vida corta, así que cada reconexión necesita el suyo.
          const ticket = await requestStreamTicket(conversationId, abort.signal);
          response = await fetch(
            `${AGENT_URL}/conversations/${conversationId}/stream` +
              `?ticket=${encodeURIComponent(ticket)}`,
            {
              signal: abort.signal,
              headers: {
                Accept: "text/event-stream",
                ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
              },
            },
          );
        }

        if (!response.ok) throw httpError(response);
        if (!response.body) throw new Error("respuesta sin cuerpo");

        for await (const { id, event } of parseSSE(response.body, abort.signal)) {
          if (id) lastEventId = id;
          emit(event);
          if (finished) return;
        }

        // El stream se cerró sin `done`. Si el turno seguía vivo, el worker
        // sigue trabajando: reenganchar es lo correcto, no dar por terminado.
        if (abort.signal.aborted) return;
      } catch (error) {
        if (abort.signal.aborted) return;

        // Los errores de credenciales, de propiedad y de límite no se arreglan
        // reintentando: se explican y se corta el turno. El 401 que sí tenía
        // arreglo (token caducado) ya se reintentó dentro de `authorizedFetch`.
        const fatal = fatalMessage(error);
        if (fatal) {
          emit({ type: "error", message: fatal, status: error.status });
          emit({ type: "done", aborted: false });
          return;
        }

        if (attempt === RECONNECT_ATTEMPTS) {
          emit({ type: "error", message: AGENT_DOWN_MESSAGE, cause: String(error) });
          emit({ type: "done", aborted: false });
          return;
        }
      }

      if (attempt < RECONNECT_ATTEMPTS) {
        await wait(RECONNECT_DELAY_MS * (attempt + 1), abort.signal);
        if (abort.signal.aborted) return;
      }
    }

    emit({ type: "done", aborted: false });
  }
}

/**
 * Mensaje definitivo para los errores que no se reintentan, o `null` si el
 * error es de red y el bucle de reconexión todavía tiene algo que hacer.
 */
function fatalMessage(error) {
  if (!(error instanceof AgentHttpError)) return null;
  if (error.status === 401) return AUTH_REQUIRED_MESSAGE;
  if (error.status === 403 || error.status === 404) return OWNERSHIP_MESSAGE;
  if (error.status === 429) return rateLimitMessage(error.retryAfter);
  return null;
}

/** `message_delta` → `onMessageDelta`. */
function handlerName(type) {
  return (
    "on" +
    String(type || "")
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join("")
  );
}

const wait = (ms, signal) =>
  new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });

/** Nombres legibles de las herramientas, para el indicador del chat. */
export const toolLabels = {
  generate_image: "Generando imagen",
  generate_video: "Generando vídeo",
  generate_audio: "Generando audio",
  edit_brief: "Editando el brief",
  read_brief: "Leyendo el brief",
  create_shot: "Creando plano",
  update_shot: "Ajustando plano",
  read_timeline: "Leyendo la timeline",
  search_assets: "Buscando entre los assets",
  create_element: "Creando element",
  assemble_cut: "Montando el corte",
};

export const labelForTool = (name) =>
  toolLabels[name] ?? `Ejecutando ${String(name || "herramienta").replace(/_/g, " ")}`;
