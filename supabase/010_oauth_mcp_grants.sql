-- ConcesiÃ³n explÃ­cita de capacidades MCP por usuario y cliente OAuth.
-- Los scopes estÃ¡ndar de OAuth prueban identidad; esta tabla decide quÃ© puede
-- hacer realmente cada cliente dentro de Xframe.

create table if not exists public.oauth_mcp_grants (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles on delete cascade,
  client_id text not null,
  scopes text[] not null,
  project_ids uuid[] not null default '{}'::uuid[],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  revoked_at timestamptz,
  unique (owner_id, client_id)
);

alter table public.oauth_mcp_grants enable row level security;
create policy "concesiones OAuth propias" on public.oauth_mcp_grants
  for select to authenticated using ((select auth.uid()) = owner_id);
revoke insert, update, delete on public.oauth_mcp_grants from anon, authenticated;

create index if not exists oauth_mcp_grants_active_client_idx
  on public.oauth_mcp_grants (owner_id, client_id)
  where revoked_at is null;
