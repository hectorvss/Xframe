-- 006. Chat de equipo y saldo de créditos en tiempo real.
--
-- Esta migración es para instalaciones que ya aplicaron schema.sql y 002_agent.sql.
-- Es idempotente: puede ejecutarse una vez por entorno sin recrear tablas ni políticas.

create table if not exists public.project_chat (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid        not null references public.projects on delete cascade,
  sender_id     uuid        not null references public.profiles on delete cascade,
  sender_name   text        not null default 'Alguien',
  sender_avatar text,
  body          text        not null check (char_length(body) between 1 and 4000),
  created_at    timestamptz not null default now()
);

create index if not exists project_chat_idx on public.project_chat (project_id, created_at);

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
           join public.workspace_members m on m.workspace_id in (
             select w.id from public.workspaces w where w.owner_id = p.owner_id
           )
          where p.id = pid and m.user_id = auth.uid()
       );
$fn$;

revoke all on function public.can_access_project(uuid) from public, anon;
grant execute on function public.can_access_project(uuid) to authenticated;

alter table public.project_chat enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'project_chat' and policyname = 'chat del proyecto: leer') then
    create policy "chat del proyecto: leer" on public.project_chat
      for select to authenticated using (public.can_access_project(project_id));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'project_chat' and policyname = 'chat del proyecto: escribir') then
    create policy "chat del proyecto: escribir" on public.project_chat
      for insert to authenticated
      with check (sender_id = auth.uid() and public.can_access_project(project_id));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'project_chat' and policyname = 'chat del proyecto: borrar el propio') then
    create policy "chat del proyecto: borrar el propio" on public.project_chat
      for delete to authenticated using (sender_id = auth.uid());
  end if;
end;
$$;

create or replace function public.project_participants(pid uuid)
returns table (user_id uuid, name text, avatar_url text, email text, kind text, pending boolean)
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

do $$
begin
  alter publication supabase_realtime add table public.project_chat;
exception when duplicate_object then null;
end;
$$;

do $$
begin
  alter publication supabase_realtime add table public.profiles;
exception when duplicate_object then null;
end;
$$;
