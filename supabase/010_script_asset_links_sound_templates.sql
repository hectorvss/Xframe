-- Xframe · screenplay references and reusable sound templates

create table if not exists public.script_asset_links (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.projects on delete cascade,
  scene_id        uuid not null references public.script_scenes on delete cascade,
  script_line_id  uuid references public.script_lines on delete cascade,
  asset_id        uuid not null references public.assets on delete cascade,
  role            text not null default 'reference'
                  check (role in (
                    'reference','source','character','product','background',
                    'style','first_frame','last_frame'
                  )),
  instructions    text not null default '',
  start_offset_ms integer check (start_offset_ms is null or start_offset_ms >= 0),
  end_offset_ms   integer check (
                    end_offset_ms is null or
                    (end_offset_ms >= 0 and
                     (start_offset_ms is null or end_offset_ms > start_offset_ms))
                  ),
  locked          boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create unique index if not exists script_asset_links_scene_unique_idx
  on public.script_asset_links (scene_id, asset_id, role)
  where script_line_id is null;
create unique index if not exists script_asset_links_line_unique_idx
  on public.script_asset_links (script_line_id, asset_id, role)
  where script_line_id is not null;
create index if not exists script_asset_links_project_idx
  on public.script_asset_links (project_id, scene_id, script_line_id);

create table if not exists public.audio_templates (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.projects on delete cascade,
  name              text not null,
  kind              text not null default 'sfx'
                    check (kind in ('music','sfx','ambience')),
  prompt            text not null,
  duration_ms       integer check (duration_ms is null or duration_ms > 0),
  loop              boolean not null default false,
  intensity         numeric(4,3) not null default 0.5
                    check (intensity between 0 and 1),
  composition_plan  jsonb not null default '{}'::jsonb,
  tags              text[] not null default '{}'::text[],
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (project_id, name)
);

drop trigger if exists script_asset_links_touch_updated_at on public.script_asset_links;
create trigger script_asset_links_touch_updated_at
  before update on public.script_asset_links
  for each row execute function public.touch_updated_at();

drop trigger if exists audio_templates_touch_updated_at on public.audio_templates;
create trigger audio_templates_touch_updated_at
  before update on public.audio_templates
  for each row execute function public.touch_updated_at();

do $$
declare table_name text;
begin
  foreach table_name in array array['script_asset_links','audio_templates'] loop
    execute format('alter table public.%I enable row level security', table_name);
    begin
      execute format($policy$
        create policy "production rows belong to owned project" on public.%I
          for all using (exists (
            select 1 from public.projects p
             where p.id = %I.project_id and p.owner_id = auth.uid()
          )) with check (exists (
            select 1 from public.projects p
             where p.id = %I.project_id and p.owner_id = auth.uid()
          ))
      $policy$, table_name, table_name, table_name);
    exception when duplicate_object then null;
    end;
  end loop;
end $$;

do $$ begin
  alter publication supabase_realtime add table
    public.script_asset_links,
    public.audio_templates;
exception when duplicate_object then null;
end $$;
