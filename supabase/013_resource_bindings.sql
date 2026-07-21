-- Universal, typed references between a reusable project resource and the exact
-- narrative/timeline scope where the director requires it.

create table if not exists public.resource_bindings (
  id             uuid primary key default gen_random_uuid(),
  project_id     uuid not null references public.projects on delete cascade,
  resource_type  text not null check (resource_type in (
                   'asset','element','voice','sound_template','transition'
                 )),
  resource_id    uuid not null,
  scope_type     text not null check (scope_type in (
                   'project','scene','line','shot','timeline','canvas'
                 )),
  scope_id       uuid,
  role           text not null default 'reference',
  start_ms       integer check (start_ms is null or start_ms >= 0),
  end_ms         integer check (
                   end_ms is null or
                   (end_ms > 0 and (start_ms is null or end_ms > start_ms))
                 ),
  instructions   text not null default '',
  locked         boolean not null default true,
  priority       integer not null default 0,
  metadata       jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists resource_bindings_project_idx
  on public.resource_bindings (project_id, scope_type, scope_id);
create index if not exists resource_bindings_resource_idx
  on public.resource_bindings (project_id, resource_type, resource_id);
create unique index if not exists resource_bindings_unique_idx
  on public.resource_bindings (
    project_id, resource_type, resource_id, scope_type,
    coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid), role,
    coalesce(start_ms, -1), coalesce(end_ms, -1)
  );

drop trigger if exists resource_bindings_touch_updated_at on public.resource_bindings;
create trigger resource_bindings_touch_updated_at
  before update on public.resource_bindings
  for each row execute function public.touch_updated_at();

alter table public.resource_bindings enable row level security;
drop policy if exists "resource bindings belong to owned project" on public.resource_bindings;
create policy "resource bindings belong to owned project"
  on public.resource_bindings for all
  using (exists (
    select 1 from public.projects p
     where p.id = resource_bindings.project_id and p.owner_id = auth.uid()
  ))
  with check (exists (
    select 1 from public.projects p
     where p.id = resource_bindings.project_id and p.owner_id = auth.uid()
  ));

grant select, insert, update, delete on public.resource_bindings to authenticated;

-- Canvas keys are the stable UI identity. This also prevents two concurrent inserts
-- of the same local node while serialized browser writes are reconnecting.
create unique index if not exists canvas_nodes_project_node_key_idx
  on public.canvas_nodes (project_id, node_key);
create unique index if not exists canvas_edges_project_pair_idx
  on public.canvas_edges (project_id, from_node, to_node);
