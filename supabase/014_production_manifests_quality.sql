create table if not exists public.production_manifests (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.projects on delete cascade,
  scene_id        uuid references public.script_scenes on delete cascade,
  version         integer not null,
  title           text not null,
  status          text not null default 'draft'
                  check (status in ('draft','validated','approved','executing','complete','invalid')),
  specification   jsonb not null default '{}'::jsonb,
  validation      jsonb not null default '{}'::jsonb,
  fingerprint     text not null,
  approved_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (project_id, scene_id, version)
);

create index if not exists production_manifests_project_idx
  on public.production_manifests (project_id, scene_id, version desc);
create unique index if not exists production_manifests_approved_scene_idx
  on public.production_manifests (project_id, scene_id) where status='approved';

drop trigger if exists production_manifests_touch_updated_at on public.production_manifests;
create trigger production_manifests_touch_updated_at
  before update on public.production_manifests
  for each row execute function public.touch_updated_at();

alter table public.production_manifests enable row level security;
drop policy if exists "production manifests belong to owned project" on public.production_manifests;
create policy "production manifests belong to owned project"
  on public.production_manifests for all
  using (exists (
    select 1 from public.projects p
     where p.id=production_manifests.project_id and p.owner_id=auth.uid()
  ))
  with check (exists (
    select 1 from public.projects p
     where p.id=production_manifests.project_id and p.owner_id=auth.uid()
  ));
grant select, insert, update, delete on public.production_manifests to authenticated;

-- Quality is broader than lipsync/render. These are the gates required before a
-- production manifest or final cut can be called approved.
alter table public.quality_reports drop constraint if exists quality_reports_check_type_check;
alter table public.quality_reports add constraint quality_reports_check_type_check check (
  check_type in (
    'lipsync','identity','continuity','audio','transition','render','technical',
    'prompt_adherence','script_fidelity','product_fidelity','text_logo','final_cut'
  )
);
