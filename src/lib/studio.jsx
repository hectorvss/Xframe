/**
 * Estado global de Xframe: cuenta, créditos, ajustes y proyectos.
 *
 * El provider mantiene una copia en memoria y escribe a `db` en cada cambio.
 * Los componentes leen y escriben de forma síncrona; la persistencia (hoy
 * localStorage, mañana Supabase) queda detrás y no les afecta.
 */
import React, {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  db,
  defaultGenSettings,
  defaultPreferences,
  isRemote,
  uid,
} from "./db";

const StudioContext = createContext(null);

/** Coste en créditos de una generación, según ajustes. */
export const creditCost = ({ mode, res, dur, count }) => {
  const base = mode === "video" ? 10 : 2;
  const byRes = { "480p": 0.5, "720p": 0.75, "1080p": 1, "4K": 2 }[res] ?? 1;
  const seconds = parseInt(dur, 10) || 8;
  const byDur = mode === "video" ? seconds / 8 : 1;
  return Math.max(1, Math.round(base * byRes * byDur * (count || 1)));
};

export function StudioProvider({ children }) {
  const [profile, setProfile] = useState(null);
  const [projects, setProjects] = useState([]);
  const [workspace, setWorkspace] = useState(null);
  const [ready, setReady] = useState(false);

  /** Carga perfil y proyectos de la sesión actual (o los limpia al salir). */
  const load = useCallback(async () => {
    let loadedProfile = null;
    try {
      loadedProfile = await db.getProfile();
    } catch (error) {
      // Si ni el perfil se puede leer, se deja la sesión como no cargada pero lista,
      // para que la UI muestre su estado de "sin sesión" en vez de un spinner eterno.
      console.warn("No se pudo cargar el perfil", error);
    }
    if (!loadedProfile) {
      setProfile(null);
      setProjects([]);
      setWorkspace(null);
      setReady(true);
      return null;
    }

    // Cada dato accesorio se captura por separado: que falle la lista de proyectos, el
    // espacio de trabajo o el saldo NO puede impedir que el perfil se muestre. Antes un
    // `Promise.all` sin protección en `listProjects` tumbaba toda la carga —y el perfil
    // quedaba en null— por un fallo secundario como firmar la portada de un proyecto.
    const [list, ws, balance] = await Promise.all([
      db.listProjects(loadedProfile.id).catch(() => []),
      db.getWorkspace(loadedProfile.id).catch(() => null),
      db.getCreditBalance(loadedProfile).catch(() => loadedProfile.credits),
    ]);
    // El saldo que ve el usuario sale del libro mayor, no de profiles.credits,
    // que es un espejo derivado y puede ir por detrás de una reserva en curso.
    setProfile({ ...loadedProfile, credits: balance });
    setProjects(list);
    setWorkspace(ws);
    setReady(true);
    return loadedProfile;
  }, []);

  useEffect(() => {
    let alive = true;
    load();
    // El trigger de Supabase crea el perfil justo después del alta, así que
    // recargamos en cada cambio de sesión (login, logout, refresh de token).
    const unsubscribe = db.onAuthChange(() => alive && load());
    return () => {
      alive = false;
      unsubscribe();
    };
  }, [load]);

  const signUp = useCallback(
    async ({ email, password, name }) => {
      const result = await db.signUp({ email, password, name });
      await load();
      return result;
    },
    [load],
  );

  const signIn = useCallback(
    async ({ email, password }) => {
      const result = await db.signIn({ email, password });
      await load();
      return result;
    },
    [load],
  );

  const signInWithProvider = useCallback(
    (provider) => db.signInWithProvider(provider),
    [],
  );

  const signOut = useCallback(async () => {
    await db.signOut();
    setProfile(null);
    setProjects([]);
  }, []);

  /* ------------------------------------------------------------ cuenta */

  const updateProfile = useCallback(
    async (patch) => {
      const next = await db.updateProfile(profile.id, patch);
      setProfile(next);
      return next;
    },
    [profile],
  );

  /** Ajustes de generación por defecto de la cuenta. */
  const genSettings = profile?.settings ?? defaultGenSettings;
  const setGenSettings = useCallback(
    (patch) =>
      updateProfile({
        settings: { ...genSettings, ...patch },
      }),
    [genSettings, updateProfile],
  );

  /** Preferencias de cuenta: idioma, tema, sonidos, visibilidad. */
  const preferences = { ...defaultPreferences, ...(profile?.preferences ?? {}) };
  const setPreferences = useCallback(
    (patch) => updateProfile({ preferences: { ...preferences, ...patch } }),
    [preferences, updateProfile],
  );

  // Las preferencias no son solo datos: se aplican al documento.
  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");

    const applyTheme = () => {
      const dark =
        preferences.theme === "dark" ||
        (preferences.theme === "system" && media.matches);
      root.classList.toggle("dark", dark);
    };

    applyTheme();
    media.addEventListener("change", applyTheme);

    root.lang = preferences.language;
    root.classList.toggle("reduce-motion", preferences.reducedMotion);

    return () => media.removeEventListener("change", applyTheme);
  }, [preferences.theme, preferences.language, preferences.reducedMotion]);

  /**
   * Relee el saldo del libro mayor. Lo llama el editor cuando el agente
   * termina un turno: quien cobra es el backend, así que el frontend no puede
   * deducir el saldo nuevo, solo volver a preguntarlo.
   */
  const refreshCredits = useCallback(async () => {
    if (!profile) return null;
    const credits = await db.getCreditBalance(profile).catch(() => null);
    if (credits === null) return null;
    setProfile((current) => (current ? { ...current, credits } : current));
    return credits;
  }, [profile]);

  /* --------------------------------------------------------- proyectos */

  const refreshProjects = useCallback(async () => {
    const list = await db.listProjects(profile.id);
    setProjects(list);
    return list;
  }, [profile]);

  /**
   * Crea un proyecto a partir de un prompt. Es el atajo de mínima fricción:
   * el usuario escribe en el panel y aterriza dentro de su proyecto nuevo.
   */
  const createProject = useCallback(
    async ({ title, prompt = "", settings = {} } = {}) => {
      const project = await db.createProject({
        ownerId: profile.id,
        title: title || titleFromPrompt(prompt),
        prompt,
        settings: { ...genSettings, ...settings },
      });
      await refreshProjects();
      return project;
    },
    [profile, genSettings, refreshProjects],
  );

  const updateProject = useCallback(
    async (id, patch) => {
      const next = await db.updateProject(id, patch);
      setProjects((list) =>
        list
          .map((p) => (p.id === id ? next : p))
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      );
      return next;
    },
    [],
  );

  const deleteProject = useCallback(async (id) => {
    await db.deleteProject(id);
    setProjects((list) => list.filter((p) => p.id !== id));
  }, []);

  const value = useMemo(
    () => ({
      ready,
      profile,
      projects,
      workspace,
      genSettings,
      setGenSettings,
      preferences,
      setPreferences,
      updateProfile,
      refreshCredits,
      createProject,
      updateProject,
      deleteProject,
      refreshProjects,
      signUp,
      signIn,
      signInWithProvider,
      signOut,
      isRemote,
    }),
    [
      ready,
      profile,
      projects,
      workspace,
      genSettings,
      setGenSettings,
      preferences,
      setPreferences,
      updateProfile,
      refreshCredits,
      createProject,
      updateProject,
      deleteProject,
      refreshProjects,
      signUp,
      signIn,
      signInWithProvider,
      signOut,
    ],
  );

  return (
    <StudioContext.Provider value={value}>{children}</StudioContext.Provider>
  );
}

export const useStudio = () => {
  const ctx = useContext(StudioContext);
  if (!ctx) throw new Error("useStudio debe usarse dentro de <StudioProvider>");
  return ctx;
};

/** Título legible a partir del prompt: primera frase, recortada. */
export function titleFromPrompt(prompt) {
  const clean = prompt.trim().replace(/\s+/g, " ");
  if (!clean) return "Proyecto sin título";
  const first = clean.split(/[.!?\n]/)[0];
  const short = first.length > 48 ? `${first.slice(0, 48)}…` : first;
  return short.charAt(0).toUpperCase() + short.slice(1);
}

/**
 * Contenido de un proyecto (assets, brief, canvas, mensajes).
 * Se carga al abrir el proyecto y se guarda en cada cambio, así que ya no se
 * pierde nada al cambiar de pestaña dentro del editor.
 */
export function useProjectData(projectId) {
  const [assets, setAssets] = useState([]);
  const [messages, setMessages] = useState([]);
  const [brief, setBrief] = useState(null);
  const [canvas, setCanvas] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoaded(false);
    (async () => {
      const [a, m, b, c] = await Promise.all([
        db.listAssets(projectId),
        db.listMessages(projectId),
        db.getBrief(projectId),
        db.getCanvas(projectId),
      ]);
      if (!alive) return;
      setAssets(a);
      setMessages(m);
      setBrief(b.length ? b : null);
      setCanvas(c.nodes.length ? c : null);
      setLoaded(true);
    })();
    return () => {
      alive = false;
    };
  }, [projectId]);

  // Mientras haya algún asset generándose, se sondea la base cada pocos segundos.
  //
  // Por qué un sondeo y no solo el evento SSE: el worker termina el render MINUTOS
  // después de que el turno del chat cierre su stream, así que `asset_ready` llega cuando
  // el frontend ya dejó de escuchar y se perdía —la imagen solo aparecía al recargar—. La
  // base es la fuente de verdad (el worker escribe ahí el asset ya listo, con su ruta), y
  // `listAssets` firma las URLs, así que releerla es lo que hace aparecer la imagen sola.
  // El sondeo se apaga en cuanto no queda nada generándose, así que no hay tráfico ocioso.
  const anyGenerating = assets.some((a) => a.status === "generating");
  useEffect(() => {
    if (!anyGenerating) return undefined;
    let alive = true;
    const tick = async () => {
      let fresh;
      try {
        fresh = await db.listAssets(projectId);
      } catch {
        return;
      }
      if (!alive) return;
      const byId = new Map(fresh.map((a) => [String(a.id), a]));
      setAssets((list) =>
        list.map((a) => {
          if (a.status !== "generating") return a;
          const updated = byId.get(String(a.id));
          // Solo se adopta el estado de la base cuando el worker ya lo cerró
          // (ready o failed); mientras siga "generating" ahí, se deja el placeholder.
          return updated && updated.status !== "generating" ? { ...a, ...updated } : a;
        }),
      );
    };
    tick(); // una lectura inmediata, sin esperar al primer intervalo
    const interval = setInterval(tick, 3500);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, [anyGenerating, projectId]);

  /* ------------------------------------------------------------ assets */

  /**
   * Inserta assets y devuelve las filas guardadas. Es asíncrono porque con
   * Supabase el id lo genera Postgres, y quien llama lo necesita para seguir
   * el progreso de la generación.
   */
  const addAssets = useCallback(
    async (drafts) => {
      const rows = await db.createAssets(projectId, drafts);
      setAssets((list) => [...rows, ...list]);
      return rows;
    },
    [projectId],
  );

  const patchAsset = useCallback((id, patch) => {
    setAssets((list) => list.map((a) => (a.id === id ? { ...a, ...patch } : a)));
    db.updateAsset(id, patch);
  }, []);

  const removeAsset = useCallback((id) => {
    setAssets((list) => list.filter((a) => a.id !== id));
    db.deleteAsset(id);
  }, []);

  /* ---------------------------------------------------------- mensajes */

  const addMessage = useCallback(
    (role, text) => {
      const row = {
        id: uid(),
        project_id: projectId,
        role,
        text,
        created_at: new Date().toISOString(),
      };
      setMessages((list) => [...list, row]);
      db.addMessage(projectId, { role, text });
      return row;
    },
    [projectId],
  );

  /* ------------------------------------------------------ brief/canvas */

  const saveBrief = useCallback(
    (blocks) => {
      setBrief(blocks);
      db.saveBrief(projectId, blocks);
    },
    [projectId],
  );

  const saveCanvas = useCallback(
    (next) => {
      setCanvas(next);
      db.saveCanvas(projectId, next);
    },
    [projectId],
  );

  return {
    loaded,
    assets,
    addAssets,
    patchAsset,
    removeAsset,
    messages,
    addMessage,
    brief,
    saveBrief,
    canvas,
    saveCanvas,
  };
}
