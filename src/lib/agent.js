/**
 * Cliente del agente de Xframe.
 *
 * El backend (backend/app/main.py) expone dos rutas y las dos hablan SSE:
 *
 *   POST /chat                          → ejecuta un turno y emite sus eventos
 *   GET  /conversations/{id}/stream     → se reengancha a un turno en curso
 *
 * No se usa `EventSource` a propósito: solo sabe hacer GET y el turno necesita
 * mandar el mensaje y el contexto de UI en el cuerpo. Con `fetch` + el
 * `ReadableStream` de la respuesta se parsea SSE a mano, que son veinte líneas,
 * y a cambio se gana POST, cabeceras propias (`x-user-id`) y cancelación con
 * `AbortController`.
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

export const AGENT_URL = (
  import.meta.env.VITE_AGENT_URL || "http://localhost:8000"
).replace(/\/+$/, "");

/** Mensaje único de degradado: si el backend no está, se dice y no se rompe nada. */
export const AGENT_DOWN_MESSAGE =
  "No consigo conectar con el agente. Comprueba que el backend está en marcha " +
  "en " +
  AGENT_URL +
  " y vuelve a intentarlo: tus mensajes y tus assets siguen guardados.";

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
  userId,
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
        const response =
          attempt === 0
            ? await fetch(`${AGENT_URL}/chat`, {
                method: "POST",
                signal: abort.signal,
                headers: {
                  "Content-Type": "application/json",
                  Accept: "text/event-stream",
                  "x-user-id": userId,
                },
                body: JSON.stringify({
                  conversation_id: conversationId,
                  project_id: projectId,
                  message,
                  ui_context: uiContext,
                  resume,
                }),
              })
            : await fetch(
                `${AGENT_URL}/conversations/${conversationId}/stream`,
                {
                  signal: abort.signal,
                  headers: {
                    Accept: "text/event-stream",
                    "x-user-id": userId,
                    ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
                  },
                },
              );

        if (!response.ok || !response.body) {
          throw new Error(`El agente respondió ${response.status}`);
        }

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
