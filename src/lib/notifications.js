/**
 * Centro de notificaciones de Xframe.
 *
 * Un store global (fuera de React, con useSyncExternalStore) para que CUALQUIER acción de
 * la app —termine una generación, te inviten a colaborar, se cree un proyecto— pueda
 * empujar una notificación al Inbox sin pasar por props. Se persiste en localStorage.
 *
 * Dos pestañas, como la referencia:
 *  - Inbox: notificaciones del usuario, algunas con acciones (aceptar/rechazar).
 *  - What's new: novedades que añaden los desarrolladores (la constante WHATS_NEW).
 */

import React from "react";

const KEY = "xf-notifications";
const SEEN_KEY = "xf-whatsnew-seen";

// ---------------------------------------------------------------------------
// What's new — LOS DESARROLLADORES AÑADEN AQUÍ las novedades (la más reciente arriba).
// `date` en ISO. `image` es opcional (ruta en /public). Cada entrada nueva aparece con
// un punto rojo hasta que el usuario abre la pestaña.
// ---------------------------------------------------------------------------
export const WHATS_NEW = [
  {
    id: "wn-speech-to-speech",
    title: "Convierte una grabación a otra voz",
    body: "Usa un audio que ya tengas como referencia y el agente lo reinterpreta con la voz que elijas, conservando ritmo e intención.",
    image: "/gradients/grad-7.jpg",
    date: "2026-07-22",
  },
  {
    id: "wn-audio-studio",
    title: "Nuevo estudio de audio",
    body: "Biblioteca de sonidos y voces por categoría, arrastra a la mezcla multipista y un reproductor con control de velocidad y volumen.",
    image: "/gradients/grad-19.jpg",
    date: "2026-07-21",
  },
  {
    id: "wn-project-pages",
    title: "Páginas de proyectos",
    body: "Todos, Destacados, Creados por mí y Compartido conmigo, con búsqueda, filtros y vista de cuadrícula o lista.",
    image: "/gradients/grad-31.jpg",
    date: "2026-07-22",
  },
];

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------
function seed() {
  // Una invitación de ejemplo, como en la referencia: el Inbox nace con un elemento
  // accionable (Aceptar/Rechazar) y el badge muestra 1.
  return [
    {
      id: "seed-invite",
      type: "invite",
      actor: "Equipo de Xframe",
      project: "Isla encantada",
      body: 'Te ha invitado a colaborar en "Isla encantada"',
      read: false,
      created_at: "2026-07-22T09:00:00.000Z",
    },
  ];
}

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return seed();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : seed();
  } catch {
    return seed();
  }
}

let notifications = load();
const listeners = new Set();

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify(notifications));
  } catch {
    // Sin persistencia (modo privado/cuota): las notificaciones duran la sesión.
  }
}

function set(next) {
  notifications = next;
  persist();
  for (const fn of listeners) fn();
}

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const snapshot = () => notifications;

const newId = () =>
  globalThis.crypto?.randomUUID?.() ?? `n-${Date.now()}-${Math.round(performance.now())}`;

/**
 * Empuja una notificación al Inbox. Es idempotente por `id` (útil para eventos que se
 * reintentan, como un job). `actions` es una lista de {id,label,variant} y el componente
 * la resuelve con el handler que se le pase.
 */
export function pushNotification(input) {
  const item = {
    id: input.id || newId(),
    type: input.type || "system",
    read: false,
    created_at: input.created_at || new Date().toISOString(),
    ...input,
  };
  if (notifications.some((n) => n.id === item.id)) return item.id;
  set([item, ...notifications]);
  return item.id;
}

export function markAllRead() {
  if (!notifications.some((n) => !n.read)) return;
  set(notifications.map((n) => ({ ...n, read: true })));
}

export function dismissNotification(id) {
  set(notifications.filter((n) => n.id !== id));
}

export function clearNotifications() {
  set([]);
}

export function unreadCount() {
  return notifications.reduce((n, item) => n + (item.read ? 0 : 1), 0);
}

/** Hook reactivo: devuelve la lista viva de notificaciones. */
export function useNotifications() {
  return React.useSyncExternalStore(subscribe, snapshot, snapshot);
}

// --- What's new: seguimiento de "visto" para el punto rojo ------------------
export function whatsNewUnseenCount() {
  try {
    const seen = new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"));
    return WHATS_NEW.reduce((n, item) => n + (seen.has(item.id) ? 0 : 1), 0);
  } catch {
    return WHATS_NEW.length;
  }
}

export function isWhatsNewSeen(id) {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]")).has(id);
  } catch {
    return false;
  }
}

export function markWhatsNewSeen() {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(WHATS_NEW.map((w) => w.id)));
  } catch {
    // idem
  }
}
