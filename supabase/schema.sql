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
  -- Identificador estable del nodo dentro del canvas. `canvas_edges.from_node` y
  -- `to_node` son `text` y apuntan aqui, no al uuid. Estaba en la base de datos
  -- real y no en este fichero: la deriva hacia que los tests, que aplican este
  -- esquema, pasaran en verde mientras produccion rechazaba cada insercion.
  node_key    text    not null,
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

-- ------------------------------------------------- consumo de créditos
-- Histórico que alimenta la pantalla de uso. El descuento y el registro van
-- juntos en spend_credits(): sin saldo no se apunta nada.

create table if not exists public.credit_usage (
  id         uuid primary key default gen_random_uuid(),
  owner_id   uuid        not null references public.profiles on delete cascade,
  project_id uuid        references public.projects on delete set null,
  kind       text        not null default 'build' check (kind in ('build', 'run')),
  amount     integer     not null check (amount > 0),
  created_at timestamptz not null default now()
);

create index if not exists credit_usage_owner_idx
  on public.credit_usage (owner_id, created_at desc);

alter table public.credit_usage enable row level security;
create policy "consumo propio" on public.credit_usage
  for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);

-- --------------------------------------------- personas del espacio
-- Miembros, invitaciones por correo y solicitudes de acceso.

create table if not exists public.workspace_members (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid        not null references public.workspaces on delete cascade,
  user_id       uuid        not null references public.profiles on delete cascade,
  role          text        not null default 'member'
                  check (role in ('owner', 'admin', 'member', 'viewer')),
  credit_limit  integer     check (credit_limit is null or credit_limit >= 0),
  joined_at     timestamptz not null default now(),
  unique (workspace_id, user_id)
);

create table if not exists public.workspace_invites (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid        not null references public.workspaces on delete cascade,
  email         text        not null,
  role          text        not null default 'member'
                  check (role in ('admin', 'member', 'viewer')),
  status        text        not null default 'pending'
                  check (status in ('pending', 'accepted', 'revoked', 'expired')),
  token         text        not null unique default encode(gen_random_bytes(16), 'hex'),
  invited_by    uuid        references public.profiles on delete set null,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null default now() + interval '14 days'
);

-- Solo una invitación viva por correo y espacio.
create unique index if not exists invites_pending_key
  on public.workspace_invites (workspace_id, lower(email))
  where status = 'pending';

create table if not exists public.workspace_join_requests (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid        not null references public.workspaces on delete cascade,
  user_id       uuid        not null references public.profiles on delete cascade,
  message       text        not null default '',
  status        text        not null default 'pending'
                  check (status in ('pending', 'approved', 'rejected')),
  created_at    timestamptz not null default now(),
  unique (workspace_id, user_id)
);

alter table public.workspace_members       enable row level security;
alter table public.workspace_invites       enable row level security;
alter table public.workspace_join_requests enable row level security;

-- Evita repetir la subconsulta de propiedad en cada política.
create or replace function public.owns_workspace(ws uuid)
returns boolean language sql stable security definer set search_path = public
as $fn$
  select exists (
    select 1 from public.workspaces w
    where w.id = ws and w.owner_id = auth.uid()
  );
$fn$;

revoke all on function public.owns_workspace(uuid) from public, anon;
grant execute on function public.owns_workspace(uuid) to authenticated;

create policy "miembros del espacio" on public.workspace_members
  for all to authenticated
  using (public.owns_workspace(workspace_id) or user_id = (select auth.uid()))
  with check (public.owns_workspace(workspace_id));

create policy "invitaciones del espacio" on public.workspace_invites
  for all to authenticated
  using (public.owns_workspace(workspace_id))
  with check (public.owns_workspace(workspace_id));

create policy "solicitudes del espacio" on public.workspace_join_requests
  for all to authenticated
  using (public.owns_workspace(workspace_id) or user_id = (select auth.uid()))
  with check (public.owns_workspace(workspace_id) or user_id = (select auth.uid()));

-- El dueño es miembro desde el primer momento.
create or replace function public.handle_new_workspace()
returns trigger language plpgsql security definer set search_path = public
as $fn$
begin
  insert into public.workspace_members (workspace_id, user_id, role)
  values (new.id, new.owner_id, 'owner')
  on conflict do nothing;
  return new;
end;
$fn$;

revoke all on function public.handle_new_workspace() from public, anon, authenticated;

create trigger on_workspace_created
  after insert on public.workspaces
  for each row execute function public.handle_new_workspace();

-- ------------------------------------------------------ colaboradores
-- Acceso a un proyecto suelto, sin ocupar plaza en el espacio de trabajo.
-- Es lo que reparte el botón Compartir de cada proyecto.

create table if not exists public.project_collaborators (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid        not null references public.projects on delete cascade,
  user_id     uuid        references public.profiles on delete cascade,
  email       text        not null,
  role        text        not null default 'editor'
                check (role in ('editor', 'commenter', 'viewer')),
  status      text        not null default 'pending'
                check (status in ('pending', 'active')),
  invited_by  uuid        references public.profiles on delete set null,
  created_at  timestamptz not null default now(),
  unique (project_id, email)
);

alter table public.project_collaborators enable row level security;

create or replace function public.owns_project(pid uuid)
returns boolean language sql stable security definer set search_path = public
as $fn$
  select exists (
    select 1 from public.projects p
    where p.id = pid and p.owner_id = auth.uid()
  );
$fn$;

revoke all on function public.owns_project(uuid) from public, anon;
grant execute on function public.owns_project(uuid) to authenticated;

create policy "colaboradores del proyecto" on public.project_collaborators
  for all to authenticated
  using (public.owns_project(project_id) or user_id = (select auth.uid()))
  with check (public.owns_project(project_id));

-- Ojo al consultar: hay dos claves ajenas a profiles (user_id e invited_by),
-- así que el embed debe nombrar la relación:
--   select=*,profile:profiles!project_collaborators_user_id_fkey(...)

-- ------------------------------------------ conocimiento y habilidades
-- Conocimiento: instrucciones permanentes. Ámbito de espacio (project_id
-- null) o de un proyecto concreto.

create table if not exists public.knowledge (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid        not null references public.workspaces on delete cascade,
  project_id   uuid        references public.projects on delete cascade,
  content      text        not null default '',
  updated_at   timestamptz not null default now()
);

create unique index if not exists knowledge_workspace_key
  on public.knowledge (workspace_id) where project_id is null;
create unique index if not exists knowledge_project_key
  on public.knowledge (project_id) where project_id is not null;

-- Habilidades: instrucciones reutilizables que se activan por contexto.
create table if not exists public.skills (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid        not null references public.workspaces on delete cascade,
  name         text        not null check (char_length(name) between 1 and 60),
  description  text        not null default '',
  instructions text        not null default '',
  triggers     text[]      not null default '{}',
  enabled      boolean     not null default true,
  -- Las de fábrica no se borran, solo se desactivan.
  is_builtin   boolean     not null default false,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table public.knowledge enable row level security;
alter table public.skills    enable row level security;

create policy "conocimiento del espacio" on public.knowledge
  for all to authenticated
  using (public.owns_workspace(workspace_id))
  with check (public.owns_workspace(workspace_id));

create policy "habilidades del espacio" on public.skills
  for all to authenticated
  using (public.owns_workspace(workspace_id))
  with check (public.owns_workspace(workspace_id));

-- Cada espacio nuevo estrena conocimiento vacío y las habilidades de fábrica
-- (continuidad, ritmo de tráiler, fotografía y guion a planos). Ver
-- seed_workspace_skills() y el trigger handle_new_workspace().

-- ------------------------------------------- fuentes de conocimiento
-- Además del texto general, el agente puede tirar de notas, archivos y
-- páginas web. La extracción la hace la edge function extract-url, porque
-- el navegador no puede pedir a otros dominios.

create table if not exists public.knowledge_sources (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid        not null references public.workspaces on delete cascade,
  project_id   uuid        references public.projects on delete cascade,
  kind         text        not null default 'note'
                 check (kind in ('note', 'url', 'file')),
  title        text        not null default 'Sin título',
  url          text,
  content      text        not null default '',
  excerpt      text        not null default '',
  status       text        not null default 'ready'
                 check (status in ('pending', 'ready', 'failed')),
  error        text,
  enabled      boolean     not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table public.knowledge_sources enable row level security;
create policy "fuentes del espacio" on public.knowledge_sources
  for all to authenticated
  using (public.owns_workspace(workspace_id))
  with check (public.owns_workspace(workspace_id));

-- ------------------------------------------------------- chat de equipo
-- Chat humano ↔ humano del proyecto (distinto de `messages`, que es con el
-- agente). Habla quien tiene acceso: el dueño, los colaboradores y los
-- miembros del espacio. Los mensajes llegan por Supabase Realtime.

create table if not exists public.project_chat (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid        not null references public.projects on delete cascade,
  sender_id     uuid        not null references public.profiles on delete cascade,
  -- Identidad congelada: la RLS de profiles solo expone el perfil propio, así
  -- que unir profiles al leer daría nombres nulos para los demás.
  sender_name   text        not null default 'Alguien',
  sender_avatar text,
  body          text        not null check (char_length(body) between 1 and 4000),
  created_at    timestamptz not null default now()
);

create index if not exists project_chat_idx on public.project_chat (project_id, created_at);

-- ¿Tiene acceso al proyecto? Dueño, colaborador o miembro del espacio del dueño.
create or replace function public.can_access_project(pid uuid)
returns boolean language sql stable security definer set search_path = public
as $fn$
  select
    exists (select 1 from public.projects p
             where p.id = pid and p.owner_id = auth.uid())
    or exists (select 1 from public.project_collaborators c
                where c.project_id = pid and c.user_id = auth.uid())
    or exists (
         select 1 from public.projects p
           join public.workspace_members m
             on m.workspace_id in (
                  select w.id from public.workspaces w where w.owner_id = p.owner_id)
          where p.id = pid and m.user_id = auth.uid());
$fn$;

revoke all on function public.can_access_project(uuid) from public, anon;
grant execute on function public.can_access_project(uuid) to authenticated;

alter table public.project_chat enable row level security;
create policy "chat del proyecto: leer" on public.project_chat
  for select to authenticated using (public.can_access_project(project_id));
create policy "chat del proyecto: escribir" on public.project_chat
  for insert to authenticated
  with check (sender_id = auth.uid() and public.can_access_project(project_id));
create policy "chat del proyecto: borrar el propio" on public.project_chat
  for delete to authenticated using (sender_id = auth.uid());

alter publication supabase_realtime add table public.project_chat;

-- project_participants(pid): quién puede estar en el chat, con nombre y avatar.
-- SECURITY DEFINER para leer los perfiles ajenos, cerrado por can_access_project.
create or replace function public.project_participants(pid uuid)
returns table (user_id uuid, name text, avatar_url text, email text,
               kind text, pending boolean)
language sql stable security definer set search_path = public
as $fn$
  select * from (
    select p.id, p.name, p.avatar_url, p.email, 'owner'::text, false
      from public.projects pr join public.profiles p on p.id = pr.owner_id
     where pr.id = pid
    union
    select p.id, p.name, p.avatar_url, p.email, 'member'::text, false
      from public.projects pr
      join public.workspaces w on w.owner_id = pr.owner_id
      join public.workspace_members m on m.workspace_id = w.id
      join public.profiles p on p.id = m.user_id
     where pr.id = pid and p.id <> pr.owner_id
    union
    select c.user_id, coalesce(p.name, c.email), p.avatar_url, c.email,
           'collaborator'::text, (c.status = 'pending')
      from public.project_collaborators c
      left join public.profiles p on p.id = c.user_id
     where c.project_id = pid
  ) parts
  where public.can_access_project(pid);
$fn$;

revoke all on function public.project_participants(uuid) from public, anon;
grant execute on function public.project_participants(uuid) to authenticated;

-- ------------------------------------------------------------ realtime
-- profiles en la publicación de realtime: el contador de créditos del frontend
-- se actualiza en vivo cuando el backend gasta al generar (reescribe
-- profiles.credits desde el credit_ledger).
alter publication supabase_realtime add table public.profiles;
