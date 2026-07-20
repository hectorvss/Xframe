-- Xframe · esquema de Supabase
--
-- Ya aplicado en el proyecto Xframe (mlawipfdsbzqtryjkeiv) mediante migraciones.
-- Este fichero es la referencia completa: sirve para levantar un entorno nuevo
-- de cero ejecutándolo en el SQL editor.
--
-- Además del SQL, el proyecto necesita:
--   · bucket "assets" (público, 50 MB, imagen/vídeo/audio) — ver más abajo
--   · edge functions generate-assets, resolve-asset y delete-account
--   · Auth → desactivar "Confirm email" o configurar SMTP propio

-- ---------------------------------------------------------------- perfiles
-- Extiende auth.users con lo que la app necesita: plan, créditos y ajustes.

create table if not exists public.profiles (
  id          uuid primary key references auth.users on delete cascade,
  email       text        not null,
  name        text        not null default 'Usuario',
  avatar_url  text,
  plan        text        not null default 'free'
                check (plan in ('free', 'pro', 'business', 'enterprise')),
  credits     integer     not null default 200 check (credits >= 0),
  username    text,
  -- `settings` son los ajustes de generación; `preferences` la cuenta:
  -- idioma, tema, sonidos, visibilidad y avisos por correo.
  settings    jsonb       not null default '{}'::jsonb,
  preferences jsonb       not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

-- Handle público único, insensible a mayúsculas.
create unique index if not exists profiles_username_key
  on public.profiles (lower(username))
  where username is not null;

-- Alta automática del perfil al registrarse.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, name)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'name', split_part(new.email, '@', 1))
  );
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- -------------------------------------------------------------- proyectos

create table if not exists public.projects (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid        not null references public.profiles on delete cascade,
  title       text        not null default 'Proyecto sin título',
  prompt      text        not null default '',
  cover_url   text,
  settings    jsonb       not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists projects_owner_idx on public.projects (owner_id, updated_at desc);

-- ----------------------------------------------------------------- assets

create table if not exists public.assets (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid        not null references public.projects on delete cascade,
  name        text        not null,
  type        text        not null,
  meta        text        not null default '',
  url         text,
  status      text        not null default 'ready'
                check (status in ('generating', 'ready', 'failed')),
  -- Un asset se convierte en Element cuando tiene rol. El rol es texto libre:
  -- Personaje, Localización, Objeto o el que escriba el usuario.
  role        text,
  created_at  timestamptz not null default now()
);

create index if not exists assets_project_idx on public.assets (project_id, created_at desc);

-- ------------------------------------------------------------------ brief

create table if not exists public.brief_blocks (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid    not null references public.projects on delete cascade,
  position    integer not null,
  type        text    not null default 'text',
  text        text    not null default '',
  checked     boolean not null default false,
  src         text
);

create index if not exists brief_project_idx on public.brief_blocks (project_id, position);

-- ----------------------------------------------------------------- canvas

create table if not exists public.canvas_nodes (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid    not null references public.projects on delete cascade,
  type        text    not null default 'concept',
  x           real    not null default 0,
  y           real    not null default 0,
  title       text    not null default '',
  text        text    not null default '',
  thumb       text,
  media       text
);

create table if not exists public.canvas_edges (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects on delete cascade,
  from_node   text not null,
  to_node     text not null
);

create index if not exists canvas_nodes_project_idx on public.canvas_nodes (project_id);
create index if not exists canvas_edges_project_idx on public.canvas_edges (project_id);

-- --------------------------------------------------------------- mensajes

create table if not exists public.messages (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid        not null references public.projects on delete cascade,
  role        text        not null check (role in ('user', 'agent')),
  text        text        not null,
  created_at  timestamptz not null default now()
);

create index if not exists messages_project_idx on public.messages (project_id, created_at);

-- ---------------------------------------------------------- updated_at

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists projects_touch_updated_at on public.projects;
create trigger projects_touch_updated_at
  before update on public.projects
  for each row execute function public.touch_updated_at();

-- ------------------------------------------------------------------- RLS
-- Cada usuario solo ve y toca lo suyo. Las tablas hijas heredan el permiso
-- del proyecto al que pertenecen.

alter table public.profiles     enable row level security;
alter table public.projects     enable row level security;
alter table public.assets       enable row level security;
alter table public.brief_blocks enable row level security;
alter table public.canvas_nodes enable row level security;
alter table public.canvas_edges enable row level security;
alter table public.messages     enable row level security;

create policy "perfil propio" on public.profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

create policy "proyectos propios" on public.projects
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

do $$
declare child text;
begin
  foreach child in array array[
    'assets', 'brief_blocks', 'canvas_nodes', 'canvas_edges', 'messages'
  ]
  loop
    execute format($f$
      create policy "hijos del proyecto propio" on public.%I
        for all
        using (exists (
          select 1 from public.projects p
          where p.id = %I.project_id and p.owner_id = auth.uid()
        ))
        with check (exists (
          select 1 from public.projects p
          where p.id = %I.project_id and p.owner_id = auth.uid()
        ));
    $f$, child, child, child);
  end loop;
end;
$$;

-- ------------------------------------------------------------- créditos
-- Descuento atómico: evita que dos generaciones simultáneas gasten de más.

create or replace function public.spend_credits(amount integer)
returns integer
language plpgsql security definer set search_path = public
as $$
declare remaining integer;
begin
  update public.profiles
     set credits = credits - amount
   where id = auth.uid() and credits >= amount
  returning credits into remaining;

  if remaining is null then
    raise exception 'Créditos insuficientes';
  end if;

  return remaining;
end;
$$;


-- ------------------------------------------------------------ storage
-- Bucket del material del proyecto. Las rutas son <user>/<proyecto>/<archivo>
-- y las políticas exigen que la primera carpeta sea la del propio usuario.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'assets', 'assets', true, 52428800,
  array['image/png','image/jpeg','image/webp','image/gif','video/mp4','video/webm','video/quicktime','audio/mpeg','audio/wav','audio/ogg']
)
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- Público para servir las URLs, pero cada usuario solo lista su carpeta.
create policy "assets listado propio" on storage.objects
  for select to authenticated
  using (bucket_id = 'assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy "assets subida propia" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy "assets actualizacion propia" on storage.objects
  for update to authenticated
  using (bucket_id = 'assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy "assets borrado propio" on storage.objects
  for delete to authenticated
  using (bucket_id = 'assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

-- ------------------------------------------------------- endurecimiento
-- handle_new_user() solo la invoca el trigger; spend_credits() solo el usuario
-- autenticado. Ninguna debe quedar expuesta en /rest/v1/rpc para anon.

revoke all on function public.handle_new_user() from public, anon, authenticated;
revoke all on function public.spend_credits(integer) from public, anon;
grant execute on function public.spend_credits(integer) to authenticated;

-- --------------------------------------------------- espacio de trabajo
-- Uno personal por usuario; la tabla ya admite equipos (owner + miembros).

create table if not exists public.workspaces (
  id            uuid primary key default gen_random_uuid(),
  owner_id      uuid        not null references public.profiles on delete cascade,
  name          text        not null default 'Mi espacio'
                  check (char_length(name) between 1 and 50),
  slug          text,
  avatar_color  text        not null default 'pink',
  member_credit_limit integer
                  check (member_credit_limit is null or member_credit_limit >= 0),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create unique index if not exists workspaces_slug_key
  on public.workspaces (lower(slug)) where slug is not null;

alter table public.workspaces enable row level security;
create policy "espacios propios" on public.workspaces
  for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);

-- Cada perfil nuevo estrena su espacio personal.
create or replace function public.handle_new_profile()
returns trigger language plpgsql security definer set search_path = public
as $fn$
begin
  insert into public.workspaces (owner_id, name, slug)
  values (
    new.id,
    coalesce(nullif(new.name, ''), 'Mi') || '''s Xframe',
    regexp_replace(lower(split_part(new.email, '@', 1)), '[^a-z0-9]', '', 'g')
  )
  on conflict do nothing;
  return new;
end;
$fn$;

revoke all on function public.handle_new_profile() from public, anon, authenticated;

create trigger on_profile_created
  after insert on public.profiles
  for each row execute function public.handle_new_profile();

-- ------------------------------------------------------ claves de API
-- Solo se guarda el hash: el token completo se muestra una única vez.

create table if not exists public.api_keys (
  id           uuid primary key default gen_random_uuid(),
  owner_id     uuid        not null references public.profiles on delete cascade,
  name         text        not null default 'Clave sin nombre',
  prefix       text        not null,
  token_hash   text        not null unique,
  last_used_at timestamptz,
  created_at   timestamptz not null default now(),
  revoked_at   timestamptz
);

alter table public.api_keys enable row level security;
create policy "claves propias" on public.api_keys
  for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);

-- ---------------------------------------------------------- sesiones
-- auth.sessions no admite RLS, así que se expone acotada al propio usuario.

create or replace function public.my_sessions()
returns table (
  id uuid, created_at timestamptz, refreshed_at timestamp,
  user_agent text, ip text
)
language sql security definer set search_path = auth, public
as $fn$
  select s.id, s.created_at, s.refreshed_at, s.user_agent, host(s.ip)
    from auth.sessions s
   where s.user_id = auth.uid()
   order by coalesce(s.refreshed_at, s.created_at::timestamp) desc;
$fn$;

create or replace function public.revoke_session(session_id uuid)
returns boolean language plpgsql security definer set search_path = auth, public
as $fn$
begin
  delete from auth.sessions where id = session_id and user_id = auth.uid();
  return found;
end;
$fn$;

revoke all on function public.my_sessions() from public, anon;
grant execute on function public.my_sessions() to authenticated;
revoke all on function public.revoke_session(uuid) from public, anon;
grant execute on function public.revoke_session(uuid) to authenticated;
