-- ===========================================================================
-- 003. Storage privado y políticas alineadas con las rutas reales
--
-- NO APLICADA. Requiere el cambio de código que se describe abajo; aplicarla
-- antes rompe la continuidad de personaje en producción.
--
-- Tres problemas, y los tres había que arreglarlos a la vez:
--
-- 1. El bucket es `public = true`. Cualquiera con el uuid de un asset ve el
--    material del proyecto sin sesión. Los uuids se filtran en logs, en el
--    Referer y en los payloads que mandamos a los proveedores.
--
-- 2. Las políticas exigen que la primera carpeta sea `auth.uid()`, pero el
--    worker escribe en `{project_id}/{job_id}/{fichero}`. Hoy no se nota
--    porque el worker usa la clave de servicio (salta RLS) y la lectura va por
--    la URL pública (tampoco pasa por RLS). En cuanto el bucket sea privado,
--    esas políticas no darían acceso a nada: ninguna ruta empieza por un uuid
--    de usuario. Se reescriben contra la propiedad del PROYECTO, que es lo que
--    la ruta realmente codifica.
--
-- 3. No hay ni una URL firmada en el backend. Está resuelto en `app/storage.py`
--    (`SignedUrls`), pero falta conectarlo donde se construye el payload del
--    proveedor. Ver la nota del final.
-- ===========================================================================

-- --------------------------------------------------------------- bucket
-- Privado. El límite de tamaño y los mime permitidos se mantienen: son la
-- primera línea contra una subida hostil, y no dependen de la visibilidad.

update storage.buckets set public = false where id = 'assets';


-- ------------------------------------------------------------ políticas
-- Se sustituyen las cuatro por prefijo de usuario. `storage.foldername(name)[1]`
-- es el project_id en todo lo que escribe el worker; se admite además el
-- prefijo por usuario para no invalidar lo ya subido desde el cliente antes de
-- esta migración.

drop policy if exists "assets listado propio"       on storage.objects;
drop policy if exists "assets subida propia"        on storage.objects;
drop policy if exists "assets actualizacion propia" on storage.objects;
drop policy if exists "assets borrado propio"       on storage.objects;

-- Un `uuid` inválido en la primera carpeta reventaría el cast y con él la
-- política entera. Se filtra por forma antes de castear.
create or replace function public.storage_prefix_is_mine(object_name text)
returns boolean
language sql stable security definer set search_path = public, storage
as $$
  select coalesce(
    case
      -- Sin carpeta (un fichero suelto en la raíz del bucket) `foldername` devuelve un
      -- array vacío y `[1]` es NULL. El regex sobre NULL da NULL, y una política que
      -- evalúa a NULL deniega — pero deniega por accidente. Se hace explícito con el
      -- `coalesce` de fuera: nada en la raíz pertenece a nadie.
      when (storage.foldername(object_name))[1] !~
           '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        then false
      -- Ruta que escribe el worker HOY, verificada contra el código y no supuesta:
      --   `SupabaseStorage.put` → f"{project_id}/{job_id}/{filename}"
      --   `_persist_cut`        → f"{project_id}/cut-v{n}/cut.mp4"
      -- Las dos empiezan por el project_id, así que la propiedad se comprueba contra el
      -- PROYECTO. Esto es lo que las políticas originales de `schema.sql` no hacían: ellas
      -- exigían `auth.uid()` en la primera carpeta, y ninguna ruta del worker la tiene.
      when exists (
        select 1 from public.projects p
         where p.id = ((storage.foldername(object_name))[1])::uuid
           and p.owner_id = auth.uid())
        then true
      -- Ruta legacy: {user_id}/{project_id}/... — es la que escribe `uploadAsset()` en
      -- `src/lib/supabase.js`. Sigue admitida para no invalidar lo ya subido.
      else ((storage.foldername(object_name))[1])::uuid = auth.uid()
    end,
    false);
$$;

revoke all on function public.storage_prefix_is_mine(text) from public, anon;
grant execute on function public.storage_prefix_is_mine(text) to authenticated;

create policy "assets lectura del proyecto propio" on storage.objects
  for select to authenticated
  using (bucket_id = 'assets' and public.storage_prefix_is_mine(name));

create policy "assets subida al proyecto propio" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'assets' and public.storage_prefix_is_mine(name));

create policy "assets actualizacion del proyecto propio" on storage.objects
  for update to authenticated
  using (bucket_id = 'assets' and public.storage_prefix_is_mine(name))
  with check (bucket_id = 'assets' and public.storage_prefix_is_mine(name));

create policy "assets borrado del proyecto propio" on storage.objects
  for delete to authenticated
  using (bucket_id = 'assets' and public.storage_prefix_is_mine(name));


-- ===========================================================================
-- AVISO DE CONFIGURACIÓN, antes que nada
--
-- Este fichero opera sobre el bucket con id 'assets', que es el que crea
-- `schema.sql`. Pero `backend/app/config.py` trae `STORAGE_BUCKET` con valor
-- por defecto 'xframe-assets'. Si el entorno de producción no fija
-- STORAGE_BUCKET=assets, el backend está firmando y subiendo contra un bucket
-- distinto del que estas políticas protegen: las subidas irían a un bucket sin
-- políticas y las firmas devolverían 404. Comprobar la variable ANTES de
-- aplicar; no es algo que el SQL pueda arreglar por su cuenta.
-- ===========================================================================


-- ===========================================================================
-- ESTADO DEL CAMBIO DE CÓDIGO (ya hecho — se conserva el porqué)
--
-- El bucket privado rompe la continuidad de personaje si no se hace primero el
-- cambio de código. La cadena hoy es:
--
--   taxonomy/repo.py  →  ElementRef.image_url  =  assets.url  (URL pública cruda)
--        ↓
--   tools/generation.py  →  payload del proveedor
--        ↓
--   el proveedor DESCARGA esa URL desde su infraestructura, sin credenciales
--   nuestras. Funciona hoy única y exclusivamente porque el bucket es público.
--
-- Con el bucket privado, esa descarga devuelve 400: se paga el submit y no sale
-- nada. Lo que había que cambiar, y YA ESTÁ ESCRITO:
--
--   - `app/taxonomy/builder.py` — `_reference_path()`: `ElementRef.image_url`
--     lleva la RUTA, no la URL. Firmar aquí sería firmar dentro de una caché
--     (`PROJECT_TTL_S`) y dentro de `generation_jobs.request`.
--   - `app/jobs/worker.py` — `_process()` llama a `sign_request_references()`
--     inmediatamente antes del `submit`, con
--     `settings.provider_signed_url_ttl_s` (= max(SIGNED_URL_TTL_S,
--     4x job_timeout_s) = 3600 s por defecto). Ahí y no en los ocho adaptadores:
--     uno que se olvide da el fallo silencioso de "sale con otra cara".
--   - `app/jobs/worker.py` — `SupabaseStorage.put` devuelve la ruta;
--     `_upsert_asset` la guarda tal cual en `assets.url`. Ninguna URL firmada
--     toca la base de datos.
--   - `app/tools/generation.py` — el montaje firma los `src` antes de ffmpeg,
--     que también descarga por HTTP.
--   - Frontend — `src/lib/supabase.js:signedUrl()` y `db.listAssets()` firman
--     con la sesión del usuario; las políticas de arriba son lo que autoriza
--     esa firma.
--
-- Orden de despliegue seguro: (1) backend + frontend que firman, sobre el
-- bucket todavía PÚBLICO — no rompe nada, porque una URL firmada funciona igual
-- en un bucket público y `object_path()` acepta las URLs públicas viejas;
-- (2) 005_migrate_asset_paths.sql, que convierte las filas existentes a rutas;
-- (3) esta migración, que es la que cierra la puerta.
-- ===========================================================================
