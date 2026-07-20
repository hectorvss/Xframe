-- ===========================================================================
-- 005. URLs públicas guardadas → rutas de objeto
--
-- NO APLICADA. Va DESPUÉS de desplegar el código que firma y ANTES de
-- 003_storage.sql (el que cierra el bucket). Ese orden no es una preferencia:
--
--   · Antes del código nuevo → el backend viejo compone payloads con lo que
--     haya en `assets.url`, y una ruta pelada no es descargable por nadie.
--   · Después de cerrar el bucket → hay una ventana en la que las filas siguen
--     con URL pública contra un bucket que ya no la sirve. `object_path()`
--     tolera las dos formas, así que la ventana no es fatal, pero no hay
--     ninguna razón para abrirla.
--
-- Con el código nuevo desplegado y el bucket todavía público, esta migración es
-- invisible para el usuario: `object_path()` ya devuelve lo mismo para la URL
-- pública y para la ruta, así que convertir las filas no cambia ningún
-- comportamiento. Es exactamente por eso que se puede hacer en un paso aparte.
--
-- Producción tiene 3 filas con URL pública. El SQL está escrito para N y es
-- idempotente: una fila que ya sea ruta no la toca (no contiene '://').
-- ===========================================================================


-- --------------------------------------------------------------- función
-- La conversión, en un solo sitio. Es el gemelo SQL de
-- `backend/app/storage.py:object_path()`; si una de las dos cambia, cambian las
-- dos, porque durante la transición conviven y tienen que coincidir.
--
-- Se contemplan las dos formas que Supabase Storage produce:
--   .../storage/v1/object/public/<bucket>/<ruta>
--   .../storage/v1/object/<bucket>/<ruta>
-- y se recorta la query string: una URL pública puede llevar `?t=` de
-- cache-busting, y ese sufijo pegado a la ruta daría un objeto inexistente.

create or replace function public.storage_url_to_path(value text, bucket text default 'assets')
returns text
language sql immutable
as $$
  select case
    when value is null or value = '' then value
    -- Ya es una ruta: se devuelve intacta. Esto es lo que hace la migración
    -- reejecutable sin daño.
    when position('://' in value) = 0 then ltrim(value, '/')
    when position('/storage/v1/object/public/' || bucket || '/' in value) > 0
      then split_part(
             split_part(value, '/storage/v1/object/public/' || bucket || '/', 2), '?', 1)
    when position('/storage/v1/object/' || bucket || '/' in value) > 0
      then split_part(
             split_part(value, '/storage/v1/object/' || bucket || '/', 2), '?', 1)
    -- URL externa (alguien pegó una referencia de fuera). No es nuestra y no se
    -- toca: convertirla la rompería, y dejarla es el comportamiento que ya
    -- tiene `object_path()`, que la deja pasar sin firmar.
    else value
  end;
$$;


-- ------------------------------------------------------------ inventario
-- EJECUTAR ESTO PRIMERO, a solas, y mirar el resultado antes de seguir. Si la
-- cuenta no es 3, el supuesto de esta migración ya no es cierto y hay que
-- entender por qué antes de escribir nada.

-- select id, project_id, url, public.storage_url_to_path(url) as nueva_ruta
--   from public.assets
--  where url like '%/storage/v1/object/%'
--  order by created_at;


-- ------------------------------------------------------------- migración

begin;

update public.assets
   set url = public.storage_url_to_path(url)
 where url like '%/storage/v1/object/%';

-- `projects.cover_url` sale de `assets.url` (`main.jsx` lo copia del primer
-- asset generado). Si se migra uno y no el otro, las portadas del dashboard se
-- quedan en negro y nadie relaciona la causa con esta migración.
update public.projects
   set cover_url = public.storage_url_to_path(cover_url)
 where cover_url like '%/storage/v1/object/%';

commit;


-- ------------------------------------------------------------ verificación
-- Después del commit no debe quedar ninguna fila con URL de nuestro storage.
-- Las URLs externas sí pueden quedar, y es correcto.

-- select count(*) as pendientes from public.assets
--  where url like '%/storage/v1/object/%';
-- select count(*) as pendientes from public.projects
--  where cover_url like '%/storage/v1/object/%';


-- ------------------------------------------------------------------ vuelta
-- No hay rollback y conviene decirlo en voz alta en vez de fingir que lo hay:
-- la ruta no contiene el host ni el bucket, así que reconstruir la URL pública
-- exige conocer los dos. Si hace falta deshacer, es un UPDATE con el prefijo
-- literal del proyecto:
--
--   update public.assets
--      set url = 'https://<ref>.supabase.co/storage/v1/object/public/assets/' || url
--    where url not like '%://%';
--
-- Y solo tiene sentido si el bucket sigue siendo público.
-- ===========================================================================
