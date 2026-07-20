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

import { supabase, hasSupabase } from "./supabase";

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
      const { data: auth } = await supabase.auth.getUser();
      if (!auth?.user) return null;

      const [profile] = await DRIVER.select("profiles", { id: auth.user.id });
      if (!profile) return null;

      if (!profile.settings || !Object.keys(profile.settings).length) {
        return DRIVER.update("profiles", profile.id, {
          settings: { ...defaultGenSettings },
        });
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

  async signInWithProvider(provider) {
    const { error } = await supabase.auth.signInWithOAuth({
      provider,
      options: { redirectTo: `${location.origin}/dashboard` },
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

  /** Consumo de créditos de los últimos N días. */
  async listCreditUsage(ownerId, days = 30) {
    const rows = await DRIVER.select("credit_usage", { owner_id: ownerId });
    const since = Date.now() - days * 86400000;
    return rows
      .filter((row) => new Date(row.created_at).getTime() >= since)
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
  },

  /* --- espacio de trabajo --- */

  async getWorkspace(ownerId) {
    const [workspace] = await DRIVER.select("workspaces", { owner_id: ownerId });
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

  /**
   * Descuenta créditos. En Supabase usa la función atómica spend_credits(),
   * de modo que dos generaciones simultáneas no puedan dejar saldo negativo.
   * Devuelve null si no hay saldo suficiente.
   */
  async spendCredits(profile, amount, { projectId = null, kind = "build" } = {}) {
    if (hasSupabase) {
      const { data, error } = await supabase.rpc("spend_credits", {
        amount,
        project_id: projectId,
        kind,
      });
      if (error) return null;
      return { ...profile, credits: data };
    }
    // En local guardamos también el histórico, para que la pantalla de uso
    // funcione sin backend.
    if (profile.credits >= amount) {
      await DRIVER.insert("credit_usage", {
        id: uid(),
        owner_id: profile.id,
        project_id: projectId,
        kind,
        amount,
        created_at: nowISO(),
      });
    }
    if (profile.credits < amount) return null;
    return DRIVER.update("profiles", profile.id, {
      credits: profile.credits - amount,
    });
  },

  /* --- proyectos --- */

  async listProjects(ownerId) {
    const rows = await DRIVER.select("projects", { owner_id: ownerId });
    return rows.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  },

  async getProject(id) {
    const [project] = await DRIVER.select("projects", { id });
    return project ?? null;
  },

  async createProject({ ownerId, title, prompt = "", settings = {} }) {
    const project = {
      ...(hasSupabase ? {} : { id: uid(), created_at: nowISO(), updated_at: nowISO() }),
      owner_id: ownerId,
      title,
      prompt,
      cover_url: null,
      settings,
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

  async listAssets(projectId) {
    return DRIVER.select("assets", { project_id: projectId });
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

  /* --- brief, canvas y mensajes --- */

  async getBrief(projectId) {
    const rows = await DRIVER.select("brief_blocks", { project_id: projectId });
    return rows.sort((a, b) => a.position - b.position);
  },

  async saveBrief(projectId, blocks) {
    return DRIVER.replaceFor(
      "brief_blocks",
      projectId,
      blocks.map((block, position) => ({ ...block, project_id: projectId, position })),
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

  async reset() {
    return DRIVER.reset();
  },
};
