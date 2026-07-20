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

const emptyState = () => ({
  profiles: [],
  projects: [],
  assets: [],
  brief_blocks: [],
  canvas_nodes: [],
  canvas_edges: [],
  messages: [],
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
 * Driver Supabase — pendiente                                         *
 * ------------------------------------------------------------------ *
 *
 * import { createClient } from "@supabase/supabase-js";
 *
 * function createSupabaseDriver() {
 *   const sb = createClient(
 *     import.meta.env.VITE_SUPABASE_URL,
 *     import.meta.env.VITE_SUPABASE_ANON_KEY,
 *   );
 *   return {
 *     async select(table, where = {}) {
 *       let q = sb.from(table).select("*");
 *       for (const [k, v] of Object.entries(where)) q = q.eq(k, v);
 *       const { data, error } = await q;
 *       if (error) throw error;
 *       return data;
 *     },
 *     async insert(table, row) {
 *       const { data, error } = await sb.from(table).insert(row).select().single();
 *       if (error) throw error;
 *       return data;
 *     },
 *     ...
 *   };
 * }
 *
 * Las políticas RLS del schema ya garantizan que cada usuario solo ve lo suyo,
 * así que los métodos de abajo no necesitan filtrar por owner_id a mano.
 */

const DRIVER = createLocalDriver();

/* ------------------------------------------------------------------ *
 * API de dominio                                                      *
 * ------------------------------------------------------------------ */

export const db = {
  /* --- perfil y créditos --- */

  async getProfile() {
    const [profile] = await DRIVER.select("profiles");
    if (profile) return profile;

    // Cuenta de arranque. Con Supabase esto lo crea el trigger on_auth_user_created.
    const fresh = {
      id: uid(),
      email: "hectorvidal0411@gmail.com",
      name: "Héctor",
      plan: "free",
      credits: 200,
      settings: { ...defaultGenSettings },
      created_at: nowISO(),
    };
    await DRIVER.insert("profiles", fresh);
    return fresh;
  },

  async updateProfile(id, patch) {
    return DRIVER.update("profiles", id, patch);
  },

  /** Descuenta créditos. Devuelve null si no hay saldo suficiente. */
  async spendCredits(profile, amount) {
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
      id: uid(),
      owner_id: ownerId,
      title,
      prompt,
      cover_url: null,
      settings,
      created_at: nowISO(),
      updated_at: nowISO(),
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

  async createAssets(projectId, assets) {
    // Respeta el id que traiga el llamante: la UI ya lo usa para seguir el
    // progreso de la generación, así que no puede cambiar al guardar.
    const rows = assets.map((asset) => ({
      id: asset.id ?? uid(),
      project_id: projectId,
      name: asset.name,
      type: asset.type,
      meta: asset.meta ?? "",
      url: asset.url ?? null,
      status: asset.status ?? "ready",
      role: asset.role ?? null,
      created_at: nowISO(),
    }));
    await DRIVER.insertMany("assets", rows);
    return rows;
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
      id: uid(),
      project_id: projectId,
      role,
      text,
      created_at: nowISO(),
    });
  },

  async reset() {
    return DRIVER.reset();
  },
};
