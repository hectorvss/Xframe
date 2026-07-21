-- Xframe · credenciales para API/MCP
--
-- Las claves existentes se conservan: una migración no puede convertir una
-- integración que ya funciona en una rotura. Las claves antiguas reciben solo
-- permisos de lectura; para generar o editar se crea una nueva clave con scopes
-- explícitos desde Ajustes > Servidor MCP.

alter table public.api_keys
  add column if not exists scopes text[] not null default array[
    'projects:read', 'assets:read', 'context:read'
  ]::text[],
  add column if not exists project_ids uuid[] not null default '{}'::uuid[],
  add column if not exists expires_at timestamptz,
  add column if not exists last_used_ip inet;

alter table public.api_keys
  add constraint api_keys_scopes_nonempty
  check (cardinality(scopes) > 0) not valid;

create index if not exists api_keys_active_hash_idx
  on public.api_keys (token_hash)
  where revoked_at is null;

-- Auditoría separada del request log: permite responder "qué agente creó este
-- plano" sin guardar prompts ni secretos en logs de infraestructura.
create table if not exists public.agent_audit_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles on delete cascade,
  api_key_id uuid references public.api_keys on delete set null,
  project_id uuid references public.projects on delete set null,
  action text not null,
  outcome text not null check (outcome in ('ok', 'denied', 'error')),
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists agent_audit_owner_idx
  on public.agent_audit_events (owner_id, created_at desc);
create index if not exists agent_audit_project_idx
  on public.agent_audit_events (project_id, created_at desc);

alter table public.agent_audit_events enable row level security;
create policy "auditoría propia" on public.agent_audit_events
  for select to authenticated
  using ((select auth.uid()) = owner_id);

-- El backend escribe con service role; ningún cliente inserta o modifica la
-- auditoría directamente.
revoke insert, update, delete on public.agent_audit_events from anon, authenticated;
