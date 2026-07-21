/**
 * Capa de datos de Xframe.
 *
 * Toda la app habla con `db`, nunca con el almacenamiento directamente. Hoy los
 * datos viven en localStorage; el día que enchufemos Supabase solo hay que
 * escribir `createSupabaseDriver()` y cambiar la constante DRIVER — ni un solo
 * componente cambia.
 *
 * El modelo replica tabla a tabla el esquema de supabase/schema.sql:
 *
 *   profiles      id · email · name · plan · credits · settings
 *   projects      id · owner_id · title · prompt · cover_url · settings · timestamps
 *   assets        id · project_id · name · type · meta · url · status · role
 *   brief_blocks  id · project_id · position · type · text · checked · src
 *   canvas_nodes  id · project_id · type · x · y · title · text · thumb · media
 *   canvas_edges  id · project_id · from_node · to_node
 *   messages      id · project_id · role · text · created_at
 *
 * Todas las operaciones son asíncronas a propósito: así el salto a Supabase no
 * obliga a reescribir los llamantes.
 */

import { supabase, hasSupabase, objectPath, signedUrls } from "./supabase";

const STORAGE_KEY = "xframe.db.v1";

export const uid = () =>
  `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export const nowISO = () => new Date().toISOString();

// Ajustes de generación por defecto de una cuenta nueva.
export const defaultGenSettings = {
  mode: "video",
  model: "Cinema Studio 3.5",
  aspect: "Auto",
  res: "1080p",
  dur: "8s",
  count: 1,
  sound: true,
  genre: "General",
  style: {
    "Paleta de color": "Auto",
    Iluminación: "Auto",
    "Movimiento de cámara": "Auto",
  },
  camera: {
    Cámara: "Auto",
    Lente: "Auto",
    Focal: "50mm",
    Apertura: "f/2.8",
  },
};

// Preferencias de cuenta por defecto (distintas de los ajustes de generación).
export const defaultPreferences = {
  language: "es",
  theme: "system",
  profileVisibility: "public",
  chatSuggestions: true,
  autoAcceptInvites: true,
  generationSound: "first",
  emailProduct: true,
  emailTips: false,
  reducedMotion: false,
};

const emptyState = () => ({
  profiles: [],
  projects: [],
  assets: [],
  brief_blocks: [],
  canvas_nodes: [],
  canvas_edges: [],
  messages: [],
  script_scenes: [],
  script_lines: [],
  script_asset_links: [],
  voice_profiles: [],
  character_voices: [],
  audio_cues: [],
  audio_templates: [],
  asset_annotations: [],
  asset_operations: [],
  timeline_transitions: [],
  workspaces: [],
  api_keys: [],
  credit_usage: [],
});

/* ------------------------------------------------------------------ *
 * Driver local (localStorage)                                         *
 * ------------------------------------------------------------------ */

function createLocalDriver() {
  let cache = null;

  const read = () => {
    if (cache) return cache;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      cache = raw ? { ...emptyState(), ...JSON.parse(raw) } : emptyState();
    } catch {
      cache = emptyState();
    }
    return cache;
  };

  const write = () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
    } catch (error) {
      // Cuota llena: no rompemos la sesión en curso, solo avisamos.
      console.warn("Xframe: no se pudo persistir el estado", error);
    }
  };

  return {
    async select(table, where = {}) {
      const rows = read()[table] ?? [];
      return rows.filter((row) =>
        Object.entries(where).every(([k, v]) => row[k] === v),
      );
    },
    async insert(table, row) {
      const state = read();
      state[table] = [...(state[table] ?? []), row];
      write();
      return row;
    },
    async insertMany(table, rows) {
      const state = read();
      state[table] = [...(state[table] ?? []), ...rows];
      write();
      return rows;
    },
    async update(table, id, patch) {
      const state = read();
      let updated = null;
      state[table] = (state[table] ?? []).map((row) => {
        if (row.id !== id) return row;
        updated = { ...row, ...patch };
        return updated;
      });
      write();
      return updated;
    },
    async remove(table, where) {
      const state = read();
      state[table] = (state[table] ?? []).filter(
        (row) => !Object.entries(where).every(([k, v]) => row[k] === v),
      );
      write();
    },
    /** Reemplaza todas las filas de un proyecto (brief, canvas…) de una vez. */
    async replaceFor(table, projectId, rows) {
      const state = read();
      state[table] = [
        ...(state[table] ?? []).filter((row) => row.project_id !== projectId),
        ...rows,
      ];
      write();
      return rows;
    },
    async reset() {
      cache = emptyState();
      write();
    },
  };
}

/* ------------------------------------------------------------------ *
 * Driver Supabase                                                     *
 * ------------------------------------------------------------------ *
 * Las políticas RLS ya garantizan que cada usuario solo ve lo suyo, así
 * que la API de dominio no filtra por owner_id a mano.
 */

function createSupabaseDriver() {
  return {
    async select(table, where = {}) {
      let query = supabase.from(table).select("*");
      for (const [column, value] of Object.entries(where)) {
        query = query.eq(column, value);
      }
      const { data, error } = await query;
      if (error) throw error;
      return data ?? [];
    },
    async insert(table, row) {
      const { data, error } = await supabase
        .from(table)
        .insert(row)
        .select()
        .single();
      if (error) throw error;
      return data;
    },
    async insertMany(table, rows) {
      if (!rows.length) return [];
      const { data, error } = await supabase.from(table).insert(rows).select();
      if (error) throw error;
      return data;
    },
    async update(table, id, patch) {
      const { data, error } = await supabase
        .from(table)
        .update(patch)
        .eq("id", id)
        .select()
        .single();
      if (error) throw error;
      return data;
    },
    async remove(table, where) {
      let query = supabase.from(table).delete();
      for (const [column, value] of Object.entries(where)) {
        query = query.eq(column, value);
      }
      const { error } = await query;
      if (error) throw error;
    },
    async replaceFor(table, projectId, rows) {
      const { error: deleteError } = await supabase
        .from(table)
        .delete()
        .eq("project_id", projectId);
      if (deleteError) throw deleteError;
      if (!rows.length) return [];
      // Los ids locales no son uuid: dejamos que los genere Postgres.
      const { data, error } = await supabase
        .from(table)
        .insert(rows.map(({ id, ...rest }) => rest))
        .select();
      if (error) throw error;
      return data;
    },
    async reset() {
      await supabase.auth.signOut();
    },
  };
}

// Con credenciales configuradas manda Supabase; si no, el driver local
// mantiene la app usable sin backend.
const DRIVER = hasSupabase ? createSupabaseDriver() : createLocalDriver();

async function movePositionedRow(table, where, id, direction) {
  const rows = (await DRIVER.select(table, where)).sort(
    (left, right) => left.position - right.position,
  );
  const current = rows.findIndex((row) => String(row.id) === String(id));
  const target = current + direction;
  if (current < 0 || target < 0 || target >= rows.length) return rows;
  [rows[current], rows[target]] = [rows[target], rows[current]];

  // Las posiciones son únicas dentro de cada escena/proyecto. Se usa primero un
  // espacio temporal para que el reordenado sea válido también en Postgres.
  for (let index = 0; index < rows.length; index += 1) {
    await DRIVER.update(table, rows[index].id, { position: 10000 + index });
  }
  for (let index = 0; index < rows.length; index += 1) {
    await DRIVER.update(table, rows[index].id, {
      position: index,
      updated_at: nowISO(),
    });
  }
  return rows;
}

export const isRemote = hasSupabase;

/* ------------------------------------------------------------------ *
 * API de dominio                                                      *
 * ------------------------------------------------------------------ */

export const db = {
  /* --- perfil y créditos --- */

  /**
   * Perfil de la sesión actual. Con Supabase lo crea el trigger al registrarse;
   * si el usuario aún no tiene ajustes guardados, se le ponen los de fábrica.
   * Devuelve null si no hay sesión iniciada.
   */
  async getProfile() {
    if (hasSupabase) {
      // `getSession` lee la sesión del almacenamiento local: es instantáneo y no
      // depende de la red. `getUser`, que es lo que había antes, hace una petición al
      // servidor de Auth en CADA carga, y cuando tardaba o el token se estaba renovando
      // devolvía null — y entonces el perfil salía vacío de forma intermitente:
      // "Cargando…" que no termina, avatar "?", ajustes en blanco, y los selectores de
      // generación sin responder porque cuelgan del perfil.
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const user = session?.user;
      if (!user) return null;

      const [profile] = await DRIVER.select("profiles", { id: user.id });
      if (!profile) return null;

      // Los ajustes de fábrica se rellenan EN MEMORIA, no con un UPDATE. Escribir en la
      // base durante una simple lectura era un efecto colateral que, si fallaba (RLS o
      // el timing justo tras el alta), lanzaba y dejaba todo el perfil sin cargar. El
      // provider ya persiste los ajustes en cuanto el usuario toca un control.
      if (!profile.settings || !Object.keys(profile.settings).length) {
        return { ...profile, settings: { ...defaultGenSettings } };
      }
      return profile;
    }

    const [profile] = await DRIVER.select("profiles");
    if (profile) return profile;

    const fresh = {
      id: uid(),
      email: "invitado@xframe.app",
      name: "Invitado",
      plan: "free",
      credits: 200,
      settings: { ...defaultGenSettings },
      created_at: nowISO(),
    };
    await DRIVER.insert("profiles", fresh);
    return fresh;
  },

  /* --- sesión --- */

  async signUp({ email, password, name }) {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { name } },
    });
    if (error) throw error;
    return data;
  },

  async signIn({ email, password }) {
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) throw error;
    return data;
  },

  async signInWithProvider(
    provider,
    redirectTo = `${location.origin}/dashboard`,
  ) {
    const { error } = await supabase.auth.signInWithOAuth({
      provider,
      options: { redirectTo },
    });
    if (error) throw error;
  },

  async signOut() {
    if (hasSupabase) await supabase.auth.signOut();
  },

  /* --- seguridad de la cuenta --- */

  /** Cambia la contraseña del usuario en sesión. */
  async updatePassword(password) {
    if (!hasSupabase) return true;
    const { error } = await supabase.auth.updateUser({ password });
    if (error) throw error;
    return true;
  },

  /** Cambia el correo. Supabase envía confirmación a la dirección nueva. */
  async updateEmail(email) {
    if (!hasSupabase) return true;
    const { error } = await supabase.auth.updateUser({ email });
    if (error) throw error;
    return true;
  },

  /** Envía un correo para restablecer la contraseña. */
  async sendPasswordReset(email) {
    if (!hasSupabase) return true;
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${location.origin}/settings/account`,
    });
    if (error) throw error;
    return true;
  },

  /** Proveedores con los que el usuario puede iniciar sesión. */
  async listIdentities() {
    if (!hasSupabase) return [];
    const { data } = await supabase.auth.getUserIdentities();
    return data?.identities ?? [];
  },

  /** Vincula otro proveedor a la cuenta actual. */
  async linkIdentity(provider) {
    const { error } = await supabase.auth.linkIdentity({
      provider,
      options: { redirectTo: `${location.origin}/settings/account` },
    });
    if (error) throw error;
  },

  async unlinkIdentity(identity) {
    const { error } = await supabase.auth.unlinkIdentity(identity);
    if (error) throw error;
  },

  /** Cierra la sesión en todos los dispositivos. */
  async signOutEverywhere() {
    if (!hasSupabase) return;
    const { error } = await supabase.auth.signOut({ scope: "global" });
    if (error) throw error;
  },

  /** Comprueba si un nombre de usuario está libre. */
  async isUsernameAvailable(username, currentId) {
    if (!hasSupabase) return true;
    const { data } = await supabase
      .from("profiles")
      .select("id")
      .ilike("username", username)
      .neq("id", currentId);
    return !data?.length;
  },

  /**
   * Consumo de créditos de los últimos N días, desde el libro mayor real que
   * escribe el backend (`credit_ledger`). Cada generación reserva y ajusta ahí;
   * `profiles.credits` es solo su espejo. Se traduce a filas de "gasto" para los
   * gráficos: los `grant` (recargas) no son consumo; el resto sí, con el signo
   * invertido (una reserva de −10 son 10 créditos gastados).
   */
  async listCreditUsage(ownerId, days = 30) {
    if (!hasSupabase) {
      // Sin backend, cae al histórico local que escribía el driver antiguo.
      const rows = await DRIVER.select("credit_usage", { owner_id: ownerId });
      const since = Date.now() - days * 86400000;
      return rows
        .filter((row) => new Date(row.created_at).getTime() >= since)
        .sort((a, b) => a.created_at.localeCompare(b.created_at));
    }

    const since = new Date(Date.now() - days * 86400000).toISOString();
    const { data, error } = await supabase
      .from("credit_ledger")
      .select("created_at, kind, amount, project_id")
      .eq("profile_id", ownerId)
      .neq("kind", "grant")
      .gte("created_at", since)
      .order("created_at");
    if (error) throw error;
    return (data ?? []).map((row) => ({
      created_at: row.created_at,
      kind: "build",
      amount: -row.amount, // reserva negativa → gasto positivo
      project_id: row.project_id,
    }));
  },

  /* --- espacio de trabajo --- */

  /** Todos los espacios de trabajo del usuario (para el conmutador). */
  async listWorkspaces(ownerId) {
    const rows = await DRIVER.select("workspaces", { owner_id: ownerId });
    return rows.sort((a, b) =>
      (a.created_at ?? "").localeCompare(b.created_at ?? ""),
    );
  },

  async createWorkspace(ownerId, name) {
    return DRIVER.insert("workspaces", {
      ...(hasSupabase
        ? {}
        : { id: uid(), created_at: nowISO(), updated_at: nowISO() }),
      owner_id: ownerId,
      name: (name || "Nuevo espacio").slice(0, 50),
      avatar_color: "violet",
    });
  },

  async getWorkspace(ownerId) {
    const [workspace] = await DRIVER.select("workspaces", {
      owner_id: ownerId,
    });
    if (workspace) return workspace;
    if (hasSupabase) return null;
    return DRIVER.insert("workspaces", {
      id: uid(),
      owner_id: ownerId,
      name: "Mi espacio",
      slug: null,
      avatar_color: "pink",
      member_credit_limit: null,
      created_at: nowISO(),
      updated_at: nowISO(),
    });
  },

  /** Cuenta los miembros de un espacio. */
  async countMembers(workspaceId) {
    if (!hasSupabase) return 1;
    const { count } = await supabase
      .from("workspace_members")
      .select("id", { count: "exact", head: true })
      .eq("workspace_id", workspaceId);
    return count ?? 1;
  },

  /** Escucha cambios del perfil (créditos, plan) en tiempo real. */
  subscribeProfile(id, onChange) {
    if (!hasSupabase) return () => {};
    const channel = supabase
      .channel(`profile:${id}`)
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "profiles",
          filter: `id=eq.${id}`,
        },
        (payload) => onChange(payload.new),
      )
      .subscribe();
    return () => supabase.removeChannel(channel);
  },

  async updateWorkspace(id, patch) {
    return DRIVER.update("workspaces", id, patch);
  },

  async isWorkspaceSlugAvailable(slug, currentId) {
    if (!hasSupabase) return true;
    const { data } = await supabase
      .from("workspaces")
      .select("id")
      .ilike("slug", slug)
      .neq("id", currentId);
    return !data?.length;
  },

  async deleteWorkspace(id) {
    return DRIVER.remove("workspaces", { id });
  },

  /* --- personas del espacio de trabajo --- */

  /** Miembros con su perfil incorporado. */
  async listMembers(workspaceId) {
    if (!hasSupabase)
      return DRIVER.select("workspace_members", { workspace_id: workspaceId });
    const { data, error } = await supabase
      .from("workspace_members")
      .select("*, profile:profiles(id, name, email, avatar_url)")
      .eq("workspace_id", workspaceId)
      .order("joined_at");
    if (error) throw error;
    return data ?? [];
  },

  async updateMember(id, patch) {
    return DRIVER.update("workspace_members", id, patch);
  },

  async removeMember(id) {
    return DRIVER.remove("workspace_members", { id });
  },

  async listInvites(workspaceId) {
    const rows = await DRIVER.select("workspace_invites", {
      workspace_id: workspaceId,
    });
    return rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  async createInvite(workspaceId, { email, role, invitedBy }) {
    return DRIVER.insert("workspace_invites", {
      ...(hasSupabase
        ? {}
        : {
            id: uid(),
            token: uid() + uid(),
            status: "pending",
            created_at: nowISO(),
            expires_at: new Date(Date.now() + 14 * 86400000).toISOString(),
          }),
      workspace_id: workspaceId,
      email: email.trim().toLowerCase(),
      role,
      invited_by: invitedBy,
    });
  },

  async updateInvite(id, patch) {
    return DRIVER.update("workspace_invites", id, patch);
  },

  async listJoinRequests(workspaceId) {
    if (!hasSupabase)
      return DRIVER.select("workspace_join_requests", {
        workspace_id: workspaceId,
      });
    const { data, error } = await supabase
      .from("workspace_join_requests")
      .select("*, profile:profiles(id, name, email, avatar_url)")
      .eq("workspace_id", workspaceId)
      .order("created_at", { ascending: false });
    if (error) throw error;
    return data ?? [];
  },

  /** Aprueba una solicitud: la marca y da de alta a la persona. */
  async resolveJoinRequest(request, approve) {
    await DRIVER.update("workspace_join_requests", request.id, {
      status: approve ? "approved" : "rejected",
    });
    if (!approve) return null;
    return DRIVER.insert("workspace_members", {
      ...(hasSupabase ? {} : { id: uid(), joined_at: nowISO() }),
      workspace_id: request.workspace_id,
      user_id: request.user_id,
      role: "member",
    });
  },

  /** Colaboradores de todos los proyectos indicados, con su perfil. */
  async listCollaborators(projectIds) {
    if (!projectIds.length) return [];
    if (!hasSupabase) {
      const rows = await DRIVER.select("project_collaborators");
      return rows.filter((row) => projectIds.includes(row.project_id));
    }
    const { data, error } = await supabase
      .from("project_collaborators")
      .select(
        "*, profile:profiles!project_collaborators_user_id_fkey(id, name, email, avatar_url)",
      )
      .in("project_id", projectIds)
      .order("created_at", { ascending: false });
    if (error) throw error;
    return data ?? [];
  },

  async addCollaborator(projectId, { email, role, invitedBy }) {
    return DRIVER.insert("project_collaborators", {
      ...(hasSupabase
        ? {}
        : { id: uid(), status: "pending", created_at: nowISO() }),
      project_id: projectId,
      email: email.trim().toLowerCase(),
      role,
      invited_by: invitedBy,
    });
  },

  async updateCollaborator(id, patch) {
    return DRIVER.update("project_collaborators", id, patch);
  },

  async removeCollaborator(id) {
    return DRIVER.remove("project_collaborators", { id });
  },

  /* --- conocimiento y habilidades --- */

  /** Conocimiento del espacio (project_id null) o de un proyecto. */
  async getKnowledge(workspaceId, projectId = null) {
    const rows = await DRIVER.select("knowledge", {
      workspace_id: workspaceId,
    });
    const found = rows.find((row) => (row.project_id ?? null) === projectId);
    if (found) return found;
    return DRIVER.insert("knowledge", {
      ...(hasSupabase ? {} : { id: uid(), updated_at: nowISO() }),
      workspace_id: workspaceId,
      project_id: projectId,
      content: "",
    });
  },

  async saveKnowledge(id, content) {
    return DRIVER.update("knowledge", id, {
      content,
      ...(hasSupabase ? {} : { updated_at: nowISO() }),
    });
  },

  /* --- fuentes de conocimiento --- */

  async listKnowledgeSources(workspaceId) {
    const rows = await DRIVER.select("knowledge_sources", {
      workspace_id: workspaceId,
    });
    return rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  async createKnowledgeSource(workspaceId, source) {
    return DRIVER.insert("knowledge_sources", {
      ...(hasSupabase
        ? {}
        : { id: uid(), created_at: nowISO(), updated_at: nowISO() }),
      workspace_id: workspaceId,
      kind: source.kind ?? "note",
      title: source.title ?? "Sin título",
      url: source.url ?? null,
      content: source.content ?? "",
      excerpt: (source.content ?? "").slice(0, 240),
      status: source.status ?? "ready",
      enabled: true,
    });
  },

  async updateKnowledgeSource(id, patch) {
    return DRIVER.update("knowledge_sources", id, {
      ...patch,
      ...(patch.content !== undefined
        ? { excerpt: patch.content.slice(0, 240) }
        : {}),
    });
  },

  async deleteKnowledgeSource(id) {
    return DRIVER.remove("knowledge_sources", { id });
  },

  /**
   * Descarga una página y guarda su texto como fuente. La extracción va en el
   * servidor: el navegador no puede pedir a otros dominios.
   */
  async extractUrl(url, sourceId) {
    if (!hasSupabase) {
      throw new Error("La extracción web necesita el backend configurado");
    }
    const { data, error } = await supabase.functions.invoke("extract-url", {
      body: { url, sourceId },
    });
    if (error) {
      // El cuerpo del error trae el motivo real de la función.
      const detail = await error.context?.json?.().catch(() => null);
      throw new Error(detail?.error ?? error.message);
    }
    if (data?.error) throw new Error(data.error);
    return data;
  },

  async listSkills(workspaceId) {
    const rows = await DRIVER.select("skills", { workspace_id: workspaceId });
    return rows.sort(
      (a, b) =>
        Number(b.is_builtin) - Number(a.is_builtin) ||
        a.name.localeCompare(b.name),
    );
  },

  async createSkill(workspaceId, skill) {
    return DRIVER.insert("skills", {
      ...(hasSupabase
        ? {}
        : {
            id: uid(),
            is_builtin: false,
            created_at: nowISO(),
            updated_at: nowISO(),
          }),
      workspace_id: workspaceId,
      name: skill.name,
      description: skill.description ?? "",
      instructions: skill.instructions ?? "",
      triggers: skill.triggers ?? [],
      enabled: true,
    });
  },

  async updateSkill(id, patch) {
    return DRIVER.update("skills", id, patch);
  },

  async deleteSkill(id) {
    return DRIVER.remove("skills", { id });
  },

  /* --- dispositivos y claves de API --- */

  /** Sesiones abiertas del usuario, con navegador, sistema e IP. */
  async listSessions() {
    if (!hasSupabase) return [];
    const { data, error } = await supabase.rpc("my_sessions");
    if (error) throw error;
    return data ?? [];
  },

  async revokeSession(sessionId) {
    const { error } = await supabase.rpc("revoke_session", {
      session_id: sessionId,
    });
    if (error) throw error;
  },

  /** Id de la sesión en curso, para marcarla como «este dispositivo». */
  async currentSessionId() {
    if (!hasSupabase) return null;
    const { data } = await supabase.auth.getSession();
    const token = data?.session?.access_token;
    if (!token) return null;
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      return payload.session_id ?? null;
    } catch {
      return null;
    }
  },

  async listApiKeys(ownerId) {
    if (!hasSupabase) return [];
    const rows = await DRIVER.select("api_keys", { owner_id: ownerId });
    return rows
      .filter((row) => !row.revoked_at)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  /**
   * Crea una clave de API. Devuelve el token completo una única vez: en la
   * base solo queda su hash SHA-256.
   */
  async createApiKey(ownerId, name) {
    const random = crypto.getRandomValues(new Uint8Array(24));
    const body = [...random]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const token = `xfr_${body}`;

    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(token),
    );
    const tokenHash = [...new Uint8Array(digest)]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");

    const row = await DRIVER.insert("api_keys", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      owner_id: ownerId,
      name: name || "Clave sin nombre",
      prefix: token.slice(0, 12),
      token_hash: tokenHash,
    });
    return { key: row, token };
  },

  async revokeApiKey(id) {
    return DRIVER.update("api_keys", id, { revoked_at: nowISO() });
  },

  /** Borra la cuenta y todo su contenido (edge function con rol de servicio). */
  async deleteAccount() {
    if (!hasSupabase) return true;
    const { error } = await supabase.functions.invoke("delete-account", {
      body: { confirm: "ELIMINAR" },
    });
    if (error) throw error;
    await supabase.auth.signOut();
    return true;
  },

  onAuthChange(callback) {
    if (!hasSupabase) return () => {};
    const { data } = supabase.auth.onAuthStateChange((_event, session) =>
      callback(session),
    );
    return () => data.subscription.unsubscribe();
  },

  async updateProfile(id, patch) {
    return DRIVER.update("profiles", id, patch);
  },

  /**
   * Saldo real de créditos: la SUMA del libro mayor.
   *
   * `credit_ledger` es append-only y el saldo es su suma, nunca un contador que
   * se actualiza. `profiles.credits` ha quedado como espejo derivado — lo
   * mantiene el backend por comodidad de lectura, pero puede ir por detrás de
   * una reserva en curso, y cobrar dos veces por creer un contador desfasado
   * es exactamente lo que el libro existe para evitar.
   *
   * Sin Supabase no hay libro: se devuelve el contador local, que ahí sí es la
   * única verdad que hay.
   */
  async getCreditBalance(profile) {
    if (!hasSupabase) return profile?.credits ?? 0;

    const { data, error } = await supabase
      .from("credit_ledger")
      .select("amount")
      .eq("profile_id", profile.id);

    // Con el libro vacío o ilegible se cae al espejo: es preferible enseñar un
    // saldo aproximado a enseñar cero y asustar al usuario.
    if (error || !data?.length) return profile?.credits ?? 0;
    return data.reduce((total, row) => total + (row.amount ?? 0), 0);
  },

  /*
   * Aquí vivía `spendCredits()`, que llamaba a la función `spend_credits()`.
   * Está revocada: cobrar desde el navegador era pedirle al cliente que dijera
   * cuánto vale lo que acaba de pedir. Quien cobra ahora es el backend, contra
   * el libro mayor y dentro de la misma transacción que encola el trabajo; el
   * frontend solo vuelve a leer el saldo con `getCreditBalance()` cuando el
   * turno termina.
   */

  /* --- proyectos --- */

  async listProjects(ownerId) {
    const rows = await DRIVER.select("projects", { owner_id: ownerId });
    const signed = await this.withSignedCovers(rows);
    return signed.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  },

  async getProject(id) {
    const [project] = await DRIVER.select("projects", { id });
    if (!project) return null;
    const [signed] = await this.withSignedCovers([project]);
    return signed;
  },

  /**
   * Firma `cover_url`, que también guarda una ruta desde que el bucket es
   * privado. Va aquí y no en la vista por el mismo motivo que en `listAssets`:
   * la portada se pinta en dos sitios distintos del dashboard y uno de los dos
   * se habría quedado en negro.
   */
  async withSignedCovers(rows) {
    if (!hasSupabase || !rows?.length) return rows;
    const signed = await signedUrls(rows.map((row) => row.cover_url));
    return rows.map((row) => {
      const path = objectPath(row.cover_url);
      return {
        ...row,
        cover_path: path,
        cover_url: (path && signed.get(path)) || row.cover_url,
      };
    });
  },

  async createProject({
    ownerId,
    title,
    prompt = "",
    settings = {},
    projectType = "cinema",
  }) {
    const project = {
      ...(hasSupabase
        ? {}
        : { id: uid(), created_at: nowISO(), updated_at: nowISO() }),
      owner_id: ownerId,
      title,
      prompt,
      cover_url: null,
      settings,
      project_type: ["cinema", "marketing", "demo"].includes(projectType)
        ? projectType
        : "cinema",
    };
    return DRIVER.insert("projects", project);
  },

  async updateProject(id, patch) {
    return DRIVER.update("projects", id, { ...patch, updated_at: nowISO() });
  },

  async deleteProject(id) {
    for (const table of [
      "assets",
      "brief_blocks",
      "canvas_nodes",
      "canvas_edges",
      "messages",
    ]) {
      await DRIVER.remove(table, { project_id: id });
    }
    await DRIVER.remove("projects", { id });
  },

  /* --- assets --- */

  /**
   * Assets del proyecto, con `url` ya firmada y lista para pintar.
   *
   * El bucket es privado, así que lo que hay en la columna `url` es una RUTA y
   * no sirve para un `<img src>`. La firma se hace aquí, en la capa de datos, y
   * no en cada componente: hay una docena de sitios en `main.jsx` que hacen
   * `url(${a.url})`, y dejar que cada uno se acuerde de firmar garantiza que
   * alguno no lo haga. Ese alguno enseñaría un hueco en blanco sin ningún error
   * en consola.
   *
   * La ruta original se conserva en `path`: es lo que hay que volver a firmar
   * cuando la URL caduque, y lo que se guarda si esta fila se copia a otro sitio
   * (una portada de proyecto, por ejemplo). Nunca se persiste `url`.
   */
  async listAssets(projectId) {
    const rows = await DRIVER.select("assets", { project_id: projectId });
    return this.withSignedUrls(rows);
  },

  /**
   * Añade `url` firmada (y `path`) a filas que traen una ruta en `url`.
   *
   * Sirve para cualquier colección con esa forma —assets, y la portada de un
   * proyecto—, y es un no-op sin Supabase: en el driver local las urls son
   * `blob:` y ya son utilizables tal cual.
   */
  async withSignedUrls(rows) {
    if (!hasSupabase || !rows?.length) return rows;
    const signed = await signedUrls(rows.map((row) => row.url));
    return rows.map((row) => {
      const path = objectPath(row.url);
      return { ...row, path, url: (path && signed.get(path)) || row.url };
    });
  },

  /**
   * Inserta assets y devuelve las filas guardadas. Respeta el id que traiga el
   * llamante en local (la UI lo usa para seguir el progreso); con Supabase los
   * uuid los pone Postgres, así que el llamante debe usar el id devuelto.
   */
  async createAssets(projectId, assets) {
    const rows = assets.map((asset) => ({
      ...(hasSupabase ? {} : { id: asset.id ?? uid(), created_at: nowISO() }),
      project_id: projectId,
      name: asset.name,
      type: asset.type,
      meta: asset.meta ?? "",
      url: asset.url ?? null,
      status: asset.status ?? "ready",
      role: asset.role ?? null,
    }));
    const saved = await DRIVER.insertMany("assets", rows);
    return saved?.length ? saved : rows;
  },

  async updateAsset(id, patch) {
    return DRIVER.update("assets", id, patch);
  },

  async deleteAsset(id) {
    return DRIVER.remove("assets", { id });
  },

  /* --- production studio: screenplay, voices, audio and review --- */

  async getProduction(projectId) {
    const [
      scenes,
      lines,
      voices,
      characterVoices,
      cues,
      annotations,
      operations,
      transitions,
      assetLinks,
      audioTemplates,
    ] = await Promise.all([
      DRIVER.select("script_scenes", { project_id: projectId }),
      DRIVER.select("script_lines", { project_id: projectId }),
      DRIVER.select("voice_profiles", { project_id: projectId }),
      DRIVER.select("character_voices", { project_id: projectId }),
      DRIVER.select("audio_cues", { project_id: projectId }),
      DRIVER.select("asset_annotations", { project_id: projectId }),
      DRIVER.select("asset_operations", { project_id: projectId }),
      DRIVER.select("timeline_transitions", { project_id: projectId }),
      DRIVER.select("script_asset_links", { project_id: projectId }),
      DRIVER.select("audio_templates", { project_id: projectId }),
    ]);
    return {
      scenes: scenes.sort((a, b) => a.position - b.position),
      lines: lines.sort((a, b) => a.position - b.position),
      voices,
      characterVoices,
      cues: cues.sort((a, b) => a.start_ms - b.start_ms),
      annotations,
      operations,
      transitions,
      assetLinks,
      audioTemplates,
    };
  },

  async createScriptScene(projectId, input = {}) {
    const scenes = await DRIVER.select("script_scenes", {
      project_id: projectId,
    });
    const position =
      input.position ??
      Math.max(-1, ...scenes.map((scene) => scene.position ?? -1)) + 1;
    return DRIVER.insert("script_scenes", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      position,
      title: "Nueva escena",
      setting: "",
      time_of_day: "",
      summary: "",
      dramatic_intent: "",
      target_duration_ms: null,
      status: "draft",
      ...input,
      updated_at: nowISO(),
    });
  },

  async updateScriptScene(id, patch) {
    return DRIVER.update("script_scenes", id, {
      ...patch,
      updated_at: nowISO(),
    });
  },

  async deleteScriptScene(id) {
    await DRIVER.remove("script_lines", { scene_id: id });
    return DRIVER.remove("script_scenes", { id });
  },

  async moveScriptScene(projectId, id, direction) {
    return movePositionedRow(
      "script_scenes",
      { project_id: projectId },
      id,
      direction,
    );
  },

  async createScriptLine(projectId, sceneId, input = {}) {
    const lines = await DRIVER.select("script_lines", { scene_id: sceneId });
    const position =
      input.position ??
      Math.max(-1, ...lines.map((line) => line.position ?? -1)) + 1;
    return DRIVER.insert("script_lines", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      scene_id: sceneId,
      position,
      line_type: "dialogue",
      speaker_element_id: null,
      voice_profile_id: null,
      shot_id: null,
      text: "",
      language: "es",
      emotion: "neutral",
      direction: "",
      pronunciation: {},
      pace: 1,
      intensity: 0.5,
      pause_before_ms: 0,
      pause_after_ms: 0,
      target_duration_ms: null,
      audio_asset_id: null,
      selected_take: null,
      status: "draft",
      metadata: {},
      ...input,
      updated_at: nowISO(),
    });
  },

  async updateScriptLine(id, patch) {
    return DRIVER.update("script_lines", id, {
      ...patch,
      updated_at: nowISO(),
    });
  },

  async deleteScriptLine(id) {
    return DRIVER.remove("script_lines", { id });
  },

  async moveScriptLine(sceneId, id, direction) {
    return movePositionedRow(
      "script_lines",
      { scene_id: sceneId },
      id,
      direction,
    );
  },

  async linkScriptAsset(projectId, sceneId, scriptLineId, assetId, input = {}) {
    return DRIVER.insert("script_asset_links", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      scene_id: sceneId,
      script_line_id: scriptLineId || null,
      asset_id: assetId,
      role: "reference",
      instructions: "",
      start_offset_ms: null,
      end_offset_ms: null,
      locked: true,
      ...input,
      updated_at: nowISO(),
    });
  },

  async updateScriptAssetLink(id, patch) {
    return DRIVER.update("script_asset_links", id, {
      ...patch,
      updated_at: nowISO(),
    });
  },

  async unlinkScriptAsset(id) {
    return DRIVER.remove("script_asset_links", { id });
  },

  async createVoiceProfile(projectId, input = {}) {
    return DRIVER.insert("voice_profiles", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      name: "Nueva voz",
      provider: "elevenlabs",
      provider_voice_id: null,
      source: "library",
      language: "es",
      accent: "",
      description: "",
      settings: {},
      pronunciation_rules: [],
      consent_status: "not_required",
      consent_evidence: {},
      status: "draft",
      ...input,
      updated_at: nowISO(),
    });
  },

  async updateVoiceProfile(id, patch) {
    return DRIVER.update("voice_profiles", id, {
      ...patch,
      updated_at: nowISO(),
    });
  },

  async deleteVoiceProfile(id) {
    await DRIVER.remove("character_voices", { voice_profile_id: id });
    return DRIVER.remove("voice_profiles", { id });
  },

  async assignCharacterVoice(projectId, elementId, voiceProfileId) {
    await DRIVER.remove("character_voices", { element_id: elementId });
    if (!voiceProfileId) return null;
    return DRIVER.insert("character_voices", {
      project_id: projectId,
      element_id: elementId,
      voice_profile_id: voiceProfileId,
      is_default: true,
      performance_defaults: {},
      created_at: nowISO(),
    });
  },

  async createAudioCue(projectId, input) {
    return DRIVER.insert("audio_cues", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      asset_id: input.asset_id,
      shot_id: null,
      script_line_id: null,
      track_kind: "music",
      start_ms: 0,
      end_ms: 5000,
      source_in_ms: 0,
      source_out_ms: null,
      gain_db: 0,
      fade_in_ms: 0,
      fade_out_ms: 0,
      pan: 0,
      loop: false,
      locked: false,
      approved: false,
      ducking_group: null,
      ducking_db: null,
      priority: 0,
      narrative_role: "",
      context_tags: [],
      metadata: {},
      ...input,
      updated_at: nowISO(),
    });
  },

  async updateAudioCue(id, patch) {
    return DRIVER.update("audio_cues", id, { ...patch, updated_at: nowISO() });
  },

  async deleteAudioCue(id) {
    return DRIVER.remove("audio_cues", { id });
  },

  async createAudioTemplate(projectId, input) {
    return DRIVER.insert("audio_templates", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      name: input.name,
      kind: input.kind || "sfx",
      prompt: input.prompt || "",
      duration_ms: input.duration_ms ?? null,
      loop: Boolean(input.loop),
      intensity: input.intensity ?? 0.5,
      composition_plan: input.composition_plan || {},
      tags: input.tags || [],
      updated_at: nowISO(),
    });
  },

  async updateAudioTemplate(id, patch) {
    return DRIVER.update("audio_templates", id, {
      ...patch,
      updated_at: nowISO(),
    });
  },

  async deleteAudioTemplate(id) {
    return DRIVER.remove("audio_templates", { id });
  },

  async addAnnotation(projectId, annotation) {
    return DRIVER.insert("asset_annotations", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      kind: "comment",
      body: "",
      geometry: {},
      color: "#2563eb",
      ...annotation,
    });
  },

  async deleteAnnotation(id) {
    return DRIVER.remove("asset_annotations", { id });
  },

  /* --- brief, canvas y mensajes --- */

  async getBrief(projectId) {
    const rows = await DRIVER.select("brief_blocks", { project_id: projectId });
    return rows.sort((a, b) => a.position - b.position);
  },

  async saveBrief(projectId, blocks) {
    return DRIVER.replaceFor(
      "brief_blocks",
      projectId,
      blocks.map((block, position) => ({
        ...block,
        project_id: projectId,
        position,
      })),
    );
  },

  async getCanvas(projectId) {
    const [nodes, edges] = await Promise.all([
      DRIVER.select("canvas_nodes", { project_id: projectId }),
      DRIVER.select("canvas_edges", { project_id: projectId }),
    ]);
    return { nodes, edges };
  },

  async saveCanvas(projectId, { nodes, edges }) {
    await DRIVER.replaceFor(
      "canvas_nodes",
      projectId,
      nodes.map((node) => ({ ...node, project_id: projectId })),
    );
    await DRIVER.replaceFor(
      "canvas_edges",
      projectId,
      edges.map((edge) => ({ ...edge, project_id: projectId })),
    );
  },

  async listMessages(projectId) {
    return DRIVER.select("messages", { project_id: projectId });
  },

  async addMessage(projectId, { role, text }) {
    return DRIVER.insert("messages", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      role,
      text,
    });
  },

  /* --- chat de equipo (humano ↔ humano) --- */

  /** Participantes del proyecto: dueño, miembros del espacio y colaboradores. */
  async listChatParticipants(projectId) {
    if (!hasSupabase) return [];
    const { data, error } = await supabase.rpc("project_participants", {
      pid: projectId,
    });
    if (error) throw error;
    return data ?? [];
  },

  async listChatMessages(projectId) {
    const rows = await DRIVER.select("project_chat", { project_id: projectId });
    return rows.sort((a, b) => a.created_at.localeCompare(b.created_at));
  },

  async sendChatMessage(
    projectId,
    { senderId, senderName, senderAvatar, body },
  ) {
    return DRIVER.insert("project_chat", {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO() }),
      project_id: projectId,
      sender_id: senderId,
      sender_name: senderName || "Alguien",
      sender_avatar: senderAvatar ?? null,
      body,
    });
  },

  /**
   * Escucha los mensajes nuevos del chat en tiempo real. Devuelve una función
   * para cancelar la suscripción. Sin Supabase no hay realtime: no-op.
   */
  subscribeChat(projectId, onInsert) {
    if (!hasSupabase) return () => {};
    const channel = supabase
      .channel(`project_chat:${projectId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "project_chat",
          filter: `project_id=eq.${projectId}`,
        },
        (payload) => onInsert(payload.new),
      )
      .subscribe();
    return () => supabase.removeChannel(channel);
  },

  async reset() {
    return DRIVER.reset();
  },
};
