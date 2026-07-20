/**
 * Cliente de Supabase.
 *
 * Si no hay credenciales en el entorno, `supabase` es null y la app cae al
 * driver local — así el proyecto sigue arrancando sin configuración.
 */
import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const hasSupabase = Boolean(url && anonKey);

export const supabase = hasSupabase
  ? createClient(url, anonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;

/** Sube un archivo al bucket `assets` bajo <user>/<proyecto>/ y devuelve su URL. */
export async function uploadAsset({ userId, projectId, file }) {
  if (!supabase) return URL.createObjectURL(file);

  const safeName = file.name.replace(/[^\w.-]+/g, "_");
  const path = `${userId}/${projectId}/${Date.now()}-${safeName}`;

  const { error } = await supabase.storage
    .from("assets")
    .upload(path, file, { cacheControl: "3600", upsert: false });
  if (error) throw error;

  const { data } = supabase.storage.from("assets").getPublicUrl(path);
  return data.publicUrl;
}
