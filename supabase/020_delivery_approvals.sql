create table if not exists public.delivery_approvals (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  asset_id uuid not null references public.assets(id) on delete cascade,
  manifest_id uuid references public.production_manifests(id) on delete set null,
  approved_by uuid references auth.users(id) on delete set null,
  quality_report_ids uuid[] not null default '{}',
  evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(project_id, asset_id)
);

alter table public.delivery_approvals enable row level security;
drop policy if exists "delivery approvals belong to owned project" on public.delivery_approvals;
create policy "delivery approvals belong to owned project"
  on public.delivery_approvals for all
  using (exists (select 1 from public.projects p
    where p.id=delivery_approvals.project_id and p.owner_id=auth.uid()))
  with check (exists (select 1 from public.projects p
    where p.id=delivery_approvals.project_id and p.owner_id=auth.uid()));
grant select, insert, update, delete on public.delivery_approvals to authenticated;
