-- Canonical scene timeline and scene-to-shot membership.
-- A shot belongs to exactly one scene; manifests and cuts must not infer this relation
-- from dialogue lines or from a caller-provided list.

alter table public.script_scenes
  add column if not exists timeline_start_ms integer not null default 0
  check (timeline_start_ms >= 0);

create index if not exists script_scenes_project_timeline_idx
  on public.script_scenes(project_id, timeline_start_ms, position);

create table if not exists public.scene_shots (
  project_id uuid not null references public.projects on delete cascade,
  scene_id uuid not null references public.script_scenes on delete cascade,
  shot_id uuid not null references public.canvas_nodes on delete cascade,
  position integer not null check (position >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (scene_id, shot_id),
  unique (project_id, shot_id),
  unique (scene_id, position)
);

create index if not exists scene_shots_project_order_idx
  on public.scene_shots(project_id, scene_id, position);

drop trigger if exists scene_shots_touch_updated_at on public.scene_shots;
create trigger scene_shots_touch_updated_at
  before update on public.scene_shots
  for each row execute function public.touch_updated_at();

alter table public.scene_shots enable row level security;
drop policy if exists "scene shots belong to owned project" on public.scene_shots;
create policy "scene shots belong to owned project"
  on public.scene_shots for all
  using (exists (
    select 1 from public.projects p
     where p.id = scene_shots.project_id and p.owner_id = auth.uid()
  ))
  with check (exists (
    select 1 from public.projects p
     where p.id = scene_shots.project_id and p.owner_id = auth.uid()
  ));

grant select, insert, update, delete on public.scene_shots to authenticated;

-- Preserve existing explicit line-to-shot relations. If a shot was accidentally used
-- by lines in several scenes, the earliest line wins and the ambiguity becomes visible
-- instead of creating contradictory canonical memberships.
with candidates as (
  select distinct on (l.shot_id)
         l.project_id, l.scene_id, l.shot_id, l.position as line_position
    from public.script_lines l
   where l.shot_id is not null
   order by l.shot_id, l.scene_id, l.position
), ranked as (
  select project_id, scene_id, shot_id,
         row_number() over (partition by scene_id order by line_position, shot_id) - 1 as position
    from candidates
)
insert into public.scene_shots(project_id, scene_id, shot_id, position)
select project_id, scene_id, shot_id, position from ranked
on conflict do nothing;
