/**
 * Cliente de Supabase.
 *
 * Si no hay credenciales en el entorno, `supabase` es null y la app cae al
 * driver local — así el proyecto sigue arrancando sin configuración.
 */
import { createClient } from "@supabase/supabase-js";

// Valores por defecto del proyecto. Las variables de entorno mandan cuando están
// definidas; sin ellas se usan estos.
//
// Por qué van en el código y no dependen solo de Vercel: cuando `VITE_SUPABASE_URL` y
// `VITE_SUPABASE_ANON_KEY` no están configuradas en el build, `hasSupabase` era `false`,
// el cliente de Supabase quedaba en `null` y la app entera caía al driver de localStorage.
// El resultado en producción: nadie estaba realmente autenticado —el perfil, los créditos
// y el nombre eran datos locales de mentira— y el chat devolvía 401 ("sesión caducada")
// porque no había ningún token que mandar. Con estos defaults la app funciona aunque el
// build no traiga las variables.
//
// La `anon`/`publishable` de Supabase está PENSADA para ser pública: solo permite lo que
// las políticas RLS dejan, y de todas formas viaja al navegador de cada visitante. No es
// un secreto. El secreto es la `service_role`, que vive solo en el backend.
const DEFAULT_SUPABASE_URL = "https://mlawipfdsbzqtryjkeiv.supabase.co";
const DEFAULT_SUPABASE_ANON_KEY =
  "sb_publishable_B47PqXvyxEXKtidKft_45A_-KoV7-OJ";

const url = import.meta.env.VITE_SUPABASE_URL || DEFAULT_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || DEFAULT_SUPABASE_ANON_KEY;

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

/** Operaciones de consentimiento del servidor OAuth 2.1 de Supabase. */
export async function oauthAuthorizationDetails(authorizationId) {
  if (!supabase) throw new Error("Supabase no está configurado");
  const { data, error } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId);
  if (error) throw error;
  return data;
}

export async function oauthAuthorizationDecision(authorizationId, approved) {
  if (!supabase) throw new Error("Supabase no está configurado");
  const { data, error } = approved
    ? await supabase.auth.oauth.approveAuthorization(authorizationId)
    : await supabase.auth.oauth.denyAuthorization(authorizationId);
  if (error) throw error;
  return data;
}

export const ASSETS_BUCKET = "assets";

/**
 * Vida de las URLs firmadas que se piden desde el navegador.
 *
 * Una hora, no un día: estas URLs acaban en el DOM, en el historial y en
 * cualquier captura que el usuario comparta. Una hora cubre de sobra una sesión
 * de edición —y si no la cubre, al recargar se vuelven a firmar—, mientras que
 * una URL de 24 h compartida por accidente es acceso al material del proyecto
 * durante 24 h para quien la reciba.
 */
export const SIGNED_URL_TTL_S = 3600;

/**
 * Sube un archivo al bucket `assets` y devuelve la **ruta** del objeto.
 *
 * Devuelve la ruta y no una URL a propósito: el bucket es privado, así que lo
 * único que se podría devolver sería una URL firmada, y esa URL acabaría
 * guardada en `assets.url` y caducaría dentro de la fila. El proyecto se vería
 * bien hoy y con las imágenes rotas dentro de una semana, que es el fallo más
 * caro de diagnosticar de todos. Lo que se persiste no caduca; lo que caduca no
 * se persiste.
 *
 * La ruta empieza por el proyecto —igual que la que escribe el worker— para que
 * una sola política de storage cubra todo lo que hay en el bucket.
 */
export async function uploadAsset({ userId, projectId, file }) {
  if (!supabase) return URL.createObjectURL(file);

  const safeName = file.name.replace(/[^\w.-]+/g, "_");
  const path = `${projectId}/uploads/${Date.now()}-${safeName}`;

  const { error } = await supabase.storage
    .from(ASSETS_BUCKET)
    .upload(path, file, { cacheControl: "3600", upsert: false });
  if (error) throw error;

  return path;
}

/**
 * Convierte lo que haya en `assets.url` en una ruta del bucket.
 *
 * Acepta las URLs públicas que todavía hay en producción además de las rutas que
 * se escriben ahora, y por eso la migración de datos (005) no tiene que ser
 * atómica con el despliegue. Es el gemelo de `object_path()` del backend.
 */
export function objectPath(value) {
  if (!value) return null;
  for (const marker of [
    `/storage/v1/object/public/${ASSETS_BUCKET}/`,
    `/storage/v1/object/${ASSETS_BUCKET}/`,
  ]) {
    const at = value.indexOf(marker);
    if (at >= 0) return value.slice(at + marker.length).split("?")[0];
  }
  // Una URL externa (o un blob: local, sin Supabase) se deja tal cual: no es
  // nuestra y firmarla no significa nada.
  if (value.includes("://")) return null;

  // Ruta absoluta del propio sitio (`/assets/scene-3.webp`): la sirve Vite desde
  // `public/`, no el bucket. Distinguirla importa porque las rutas de storage que
  // escribe el worker son siempre `{project_id}/{job_id}/{fichero}` — relativas y
  // con al menos dos segmentos— así que una barra inicial es señal inequívoca de
  // fichero estático. Sin este corte, los assets de ejemplo del prototipo se
  // intentaban firmar contra el bucket, la firma fallaba y desaparecían de la UI
  // sin ningún error visible.
  if (value.startsWith("/")) return null;

  return value;
}

/**
 * Firma varias rutas de una vez y devuelve un mapa ruta → URL.
 *
 * Firma desde el navegador con la sesión del usuario, sin pasar por nuestro
 * backend. La alternativa —un endpoint propio que firmara con la clave de
 * servicio— obligaría a reimplementar en él el control de acceso que las
 * políticas de storage ya hacen, y ese es exactamente el tipo de comprobación
 * duplicada que acaba divergiendo. Aquí la autorización la decide Postgres
 * contra `projects.owner_id`, en un único sitio, y un token robado no sirve para
 * firmar assets de otro.
 *
 * `createSignedUrls` en lote y no una llamada por asset: una galería de treinta
 * planos son treinta peticiones que llegan a la vez.
 */
export async function signedUrls(values, ttl = SIGNED_URL_TTL_S) {
  if (!supabase) return new Map();
  const paths = [...new Set(values.map(objectPath).filter(Boolean))];
  if (!paths.length) return new Map();

  const { data, error } = await supabase.storage
    .from(ASSETS_BUCKET)
    .createSignedUrls(paths, ttl);
  // Que falle la firma no puede tumbar la vista: se pinta el placeholder, que es
  // lo mismo que ve un asset todavía generándose.
  if (error) return new Map();

  return new Map(
    (data ?? [])
      .filter((row) => row.signedUrl && !row.error)
      .map((row) => [row.path, row.signedUrl]),
  );
}
