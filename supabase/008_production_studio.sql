-- Xframe · production studio
--
-- Structured screenplay, cast/voice identities, multitrack audio, asset lineage,
-- frame-aware annotations, deterministic generated transitions and quality gates.
-- Every mutable creative decision is either versioned (artifacts) or append-only
-- (operations/reports); generated media is never overwritten.

-- ---------------------------------------------------------------- artifacts

alter table public.artifacts drop constraint if exists artifacts_kind_check;
alter table public.artifacts
  add constraint artifacts_kind_check check (kind in (
    'script', 'screenplay', 'timeline', 'audio_plan', 'cut', 'plan'
  ));

-- Provider/model capabilities evolve faster than the schema. These values drive both
-- the UI action dock and the agent schemas, so an unsupported action is not offered.
alter table public.gen_models
  add column if not exists capabilities text[] not null default '{}'::text[];

create index if not exists gen_models_capabilities_idx
  on public.gen_models using gin (capabilities);

-- ----------------------------------------------------------- cast and voices

create table if not exists public.voice_profiles (
  id                    uuid primary key default gen_random_uuid(),
  project_id            uuid not null references public.projects on delete cascade,
  name                  text not null,
  provider              text not null,
  provider_voice_id     text,
  source                text not null default 'library'
                        check (source in ('library','designed','cloned','uploaded')),
  language              text not null default 'es',
  accent                text,
  description           text not null default '',
  settings              jsonb not null default '{}'::jsonb,
  pronunciation_rules   jsonb not null default '[]'::jsonb,
  consent_status        text not null default 'not_required'
                        check (consent_status in
                          ('not_required','pending','verified','rejected')),
  consent_evidence      jsonb not null default '{}'::jsonb,
  status                text not null default 'draft'
                        check (status in ('draft','ready','disabled')),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (project_id, name)
);

create table if not exists public.character_voices (
  project_id          uuid not null references public.projects on delete cascade,
  element_id          uuid not null references public.assets on delete cascade,
  voice_profile_id    uuid not null references public.voice_profiles on delete cascade,
  is_default          boolean not null default true,
  performance_defaults jsonb not null default '{}'::jsonb,
  created_at          timestamptz not null default now(),
  primary key (element_id, voice_profile_id)
);

create unique index if not exists character_voices_one_default_idx
  on public.character_voices (element_id) where is_default;

-- --------------------------------------------------------------- screenplay

create table if not exists public.script_scenes (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.projects on delete cascade,
  position        integer not null,
  title           text not null default '',
  setting         text not null default '',
  time_of_day     text not null default '',
  summary         text not null default '',
  dramatic_intent text not null default '',
  timeline_start_ms integer not null default 0 check (timeline_start_ms >= 0),
  target_duration_ms integer,
  status          text not null default 'draft'
                  check (status in ('draft','approved','locked')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (project_id, position)
);

create table if not exists public.script_lines (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.projects on delete cascade,
  scene_id          uuid not null references public.script_scenes on delete cascade,
  position          integer not null,
  line_type         text not null default 'dialogue'
                    check (line_type in ('dialogue','voiceover','action','caption')),
  speaker_element_id uuid references public.assets on delete set null,
  voice_profile_id  uuid references public.voice_profiles on delete set null,
  shot_id           uuid references public.canvas_nodes on delete set null,
  text              text not null,
  language          text not null default 'es',
  emotion           text not null default 'neutral',
  direction         text not null default '',
  pronunciation     jsonb not null default '{}'::jsonb,
  pace              numeric(4,2) not null default 1.0 check (pace between 0.5 and 2.0),
  intensity         numeric(4,3) not null default 0.5 check (intensity between 0 and 1),
  pause_before_ms   integer not null default 0 check (pause_before_ms >= 0),
  pause_after_ms    integer not null default 0 check (pause_after_ms >= 0),
  target_duration_ms integer check (target_duration_ms is null or target_duration_ms > 0),
  audio_asset_id    uuid references public.assets on delete set null,
  selected_take     integer,
  status            text not null default 'draft'
                    check (status in ('draft','ready','generating','review','approved','failed')),
  metadata          jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (scene_id, position)
);

create index if not exists script_scenes_project_idx
  on public.script_scenes (project_id, position);
create index if not exists script_lines_project_idx
  on public.script_lines (project_id, scene_id, position);
create index if not exists script_lines_shot_idx
  on public.script_lines (shot_id) where shot_id is not null;

-- ------------------------------------------------------------ asset lineage

create table if not exists public.asset_operations (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.projects on delete cascade,
  operation       text not null check (operation in (
                    'edit','extend','remix','variation','character','lipsync',
                    'transition','upscale','voice','music','sfx','mix'
                  )),
  status          text not null default 'planned'
                  check (status in ('planned','queued','running','succeeded','failed','cancelled')),
  provider        text,
  model_id        text,
  prompt          text not null default '',
  params          jsonb not null default '{}'::jsonb,
  prompt_fingerprint text,
  output_asset_id uuid references public.assets on delete set null,
  job_id          uuid references public.generation_jobs on delete set null,
  created_by      text not null default 'agent' check (created_by in ('agent','user')),
  created_at      timestamptz not null default now(),
  completed_at    timestamptz
);

create table if not exists public.asset_operation_inputs (
  operation_id uuid not null references public.asset_operations on delete cascade,
  project_id   uuid not null references public.projects on delete cascade,
  asset_id     uuid not null references public.assets on delete cascade,
  role         text not null default 'source',
  position     integer not null default 0,
  time_range   int8range,
  metadata     jsonb not null default '{}'::jsonb,
  primary key (operation_id, asset_id, role)
);

create index if not exists asset_operations_project_idx
  on public.asset_operations (project_id, created_at desc);
create index if not exists asset_operations_output_idx
  on public.asset_operations (output_asset_id) where output_asset_id is not null;

-- --------------------------------------------------------- annotations/QC

create table if not exists public.asset_annotations (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects on delete cascade,
  asset_id    uuid not null references public.assets on delete cascade,
  author_id   uuid references public.profiles on delete set null,
  kind        text not null check (kind in ('region','drawing','text','comment')),
  body        text not null default '',
  time_ms     integer check (time_ms is null or time_ms >= 0),
  geometry    jsonb not null default '{}'::jsonb,
  color       text not null default '#2563eb',
  status      text not null default 'open' check (status in ('open','resolved','dismissed')),
  created_at  timestamptz not null default now(),
  resolved_at timestamptz
);

create table if not exists public.quality_reports (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects on delete cascade,
  asset_id    uuid not null references public.assets on delete cascade,
  operation_id uuid references public.asset_operations on delete set null,
  check_type  text not null check (check_type in
                ('lipsync','identity','continuity','audio','transition','render')),
  status      text not null default 'queued' check (status in
                ('queued','running','passed','failed','needs_review')),
  score       numeric(5,4) check (score is null or score between 0 and 1),
  passed      boolean,
  metrics     jsonb not null default '{}'::jsonb,
  issues      jsonb not null default '[]'::jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists asset_annotations_asset_idx
  on public.asset_annotations (asset_id, created_at);
create index if not exists quality_reports_asset_idx
  on public.quality_reports (asset_id, created_at desc);

-- ------------------------------------------------------------ audio timeline

create table if not exists public.audio_cues (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.projects on delete cascade,
  asset_id        uuid not null references public.assets on delete cascade,
  shot_id         uuid references public.canvas_nodes on delete set null,
  script_line_id  uuid references public.script_lines on delete set null,
  track_kind      text not null check (track_kind in
                    ('dialogue','voiceover','music','sfx','ambience','native')),
  start_ms        integer not null check (start_ms >= 0),
  end_ms          integer not null check (end_ms > start_ms),
  source_in_ms    integer not null default 0 check (source_in_ms >= 0),
  source_out_ms   integer check (source_out_ms is null or source_out_ms > source_in_ms),
  gain_db         numeric(6,2) not null default 0,
  fade_in_ms      integer not null default 0 check (fade_in_ms >= 0),
  fade_out_ms     integer not null default 0 check (fade_out_ms >= 0),
  pan             numeric(4,3) not null default 0 check (pan between -1 and 1),
  loop            boolean not null default false,
  locked          boolean not null default false,
  approved        boolean not null default false,
  ducking_group   text,
  ducking_db      numeric(6,2),
  priority        integer not null default 0,
  narrative_role  text not null default '',
  context_tags    text[] not null default '{}'::text[],
  metadata        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists public.audio_asset_profiles (
  asset_id        uuid primary key references public.assets on delete cascade,
  project_id      uuid not null references public.projects on delete cascade,
  bpm             numeric(7,3),
  musical_key     text,
  mood            text[] not null default '{}'::text[],
  instrumentation text[] not null default '{}'::text[],
  energy_curve    jsonb not null default '[]'::jsonb,
  sections        jsonb not null default '[]'::jsonb,
  loop_points     jsonb not null default '[]'::jsonb,
  stems           jsonb not null default '{}'::jsonb,
  rights          jsonb not null default '{}'::jsonb,
  analysis        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists audio_cues_project_time_idx
  on public.audio_cues (project_id, start_ms, end_ms);
create index if not exists audio_cues_context_tags_idx
  on public.audio_cues using gin (context_tags);

-- ------------------------------------------------------------ lip sync data

create table if not exists public.lipsync_segments (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.projects on delete cascade,
  operation_id      uuid not null references public.asset_operations on delete cascade,
  speaker_element_id uuid references public.assets on delete set null,
  face_track_id     text,
  audio_asset_id    uuid references public.assets on delete restrict,
  script_line_id    uuid references public.script_lines on delete set null,
  start_ms          integer not null check (start_ms >= 0),
  end_ms            integer not null check (end_ms > start_ms),
  source_in_ms      integer not null default 0 check (source_in_ms >= 0),
  source_out_ms     integer,
  options           jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now()
);

create index if not exists lipsync_segments_operation_idx
  on public.lipsync_segments (operation_id, start_ms);

-- ------------------------------------------------------ deterministic joins

create table if not exists public.timeline_transitions (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.projects on delete cascade,
  from_asset_id     uuid not null references public.assets on delete cascade,
  to_asset_id       uuid not null references public.assets on delete cascade,
  kind              text not null check (kind in ('cut','crossfade','generated')),
  duration_ms       integer not null default 0 check (duration_ms >= 0),
  generated_asset_id uuid references public.assets on delete set null,
  operation_id      uuid references public.asset_operations on delete set null,
  model_id          text,
  seed              bigint,
  parameters        jsonb not null default '{}'::jsonb,
  signature         text not null,
  status            text not null default 'planned'
                    check (status in ('planned','queued','running','ready','failed')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (project_id, signature)
);

create index if not exists timeline_transitions_pair_idx
  on public.timeline_transitions (project_id, from_asset_id, to_asset_id);

-- --------------------------------------------------------------- timestamps

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'voice_profiles','script_scenes','script_lines','audio_cues',
    'audio_asset_profiles','timeline_transitions'
  ] loop
    execute format('drop trigger if exists %I_touch_updated_at on public.%I', table_name, table_name);
    execute format(
      'create trigger %I_touch_updated_at before update on public.%I '
      'for each row execute function public.touch_updated_at()', table_name, table_name
    );
  end loop;
end $$;

-- --------------------------------------------------------------------- RLS

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'voice_profiles','character_voices','script_scenes','script_lines',
    'asset_operations','asset_operation_inputs','asset_annotations','quality_reports',
    'audio_cues','audio_asset_profiles','lipsync_segments','timeline_transitions'
  ] loop
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

-- Realtime updates make generated takes, QC and collaborative annotations appear
-- without polling. Ignore duplicate publication membership on repeated migrations.
do $$ begin
  alter publication supabase_realtime add table
    public.script_scenes,
    public.script_lines,
    public.audio_cues,
    public.asset_annotations,
    public.timeline_transitions;
exception when duplicate_object then null;
end $$;
