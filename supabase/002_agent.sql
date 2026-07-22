-- Xframe · esquema del agente
-- Se aplica sobre schema.sql (profiles, projects, assets, brief_blocks,
-- canvas_nodes, canvas_edges, messages).
--
-- Tres bloques:
--   1. Taxonomía  — el catálogo de modelos y lenguaje cinematográfico. Es DATOS,
--                   no código: de aquí salen los Literal[...] de las herramientas.
--   2. Jobs       — generación asíncrona, créditos e idempotencia.
--   3. Agente     — conversaciones, checkpoints y memoria del proyecto.

-- ===========================================================================
-- 1. TAXONOMÍA
-- ===========================================================================

-- Modelos de generación. `status` + `sunset_at` es lo que nos permite apagar un
-- proveedor con un UPDATE en vez de un despliegue. Runway Gen-3/Gen-4 se apagan el
-- 2026-07-30 y Sora 2 el 2026-09-24: esto se va a usar de verdad.
create table if not exists public.gen_models (
  id              text primary key,              -- "kling-3.0-turbo"
  family          text        not null,          -- "Kling"
  provider        text        not null,          -- adaptador que lo sirve
  modality        text        not null check (modality in ('image','video','audio','lipsync')),

  label           text        not null,          -- lo que ve el usuario
  description_llm text        not null,          -- lo que lee el modelo (distinto a propósito)

  min_duration_s  numeric,
  max_duration_s  numeric,
  resolutions     text[]      not null default '{}',
  aspects         text[]      not null default '{}',

  supports_i2v          boolean not null default false,
  supports_last_frame   boolean not null default false,
  supports_char_ref     boolean not null default false,
  supports_audio        boolean not null default false,

  -- Base de la facturación. Rango real entre modelos: 30x ($0.05/s a $1.50/s).
  cost_per_second   numeric(10,4) not null,
  cost_per_image    numeric(10,4),
  credits_per_unit  integer       not null,      -- lo que se le cobra al cliente

  min_plan  text not null default 'free'
            check (min_plan in ('free','pro','business','enterprise')),

  status    text not null default 'active'
            check (status in ('active','deprecated','retired')),
  sunset_at timestamptz,

  sort      integer not null default 100,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists gen_models_active_idx
  on public.gen_models (modality, status) where status = 'active';

-- Movimientos de cámara. Higgsfield los identifica por UUID vía getMotions(), así que
-- el mapeo a cada proveedor vive en jsonb y no en el id.
create table if not exists public.camera_motions (
  id              text primary key,              -- "dolly-zoom"
  label           text not null,                 -- "Dolly Zoom"
  description_llm text not null,                 -- cuándo usarlo narrativamente
  provider_ref    jsonb not null default '{}',   -- {"higgsfield": "<uuid>", ...}
  supports_strength boolean not null default true,
  category        text,                          -- push | orbit | crane | handheld | fx
  status          text not null default 'active'
                  check (status in ('active','retired')),
  sort            integer not null default 100
);

-- Estilos visuales: paleta, iluminación, film stock, lentes.
create table if not exists public.visual_styles (
  id              text primary key,
  dimension       text not null,                 -- palette | lighting | film_stock | lens
  label           text not null,
  description_llm text not null,
  prompt_fragment text not null,                 -- lo que se inyecta en el prompt final
  status          text not null default 'active'
                  check (status in ('active','retired')),
  sort            integer not null default 100
);

-- La taxonomía es catálogo global de solo lectura para los clientes.
alter table public.gen_models     enable row level security;
alter table public.camera_motions enable row level security;
alter table public.visual_styles  enable row level security;

do $$ begin
  create policy "catálogo legible" on public.gen_models     for select using (true);
  create policy "catálogo legible" on public.camera_motions for select using (true);
  create policy "catálogo legible" on public.visual_styles  for select using (true);
exception when duplicate_object then null; end $$;


-- ===========================================================================
-- 2. JOBS Y CRÉDITOS
-- ===========================================================================

create table if not exists public.generation_jobs (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects on delete cascade,
  asset_id    uuid references public.assets on delete set null,
  shot_id     text,                              -- canvas_nodes.id del plano

  provider    text not null,
  model_id    text not null references public.gen_models,
  request     jsonb not null,                    -- GenerationRequest serializada

  -- hash(provider, model, params, seed). Un reintento idéntico no vuelve a pagar:
  -- los webhooks de fal reintentan hasta 10 veces en 2h.
  idempotency_key text not null unique,

  status      text not null default 'queued'
              check (status in ('queued','submitted','running','succeeded',
                                'failed','cancelled','nsfw')),
  provider_ref jsonb,
  progress    numeric,

  credits_reserved integer not null default 0,
  credits_charged  integer not null default 0,
  cost_usd         numeric(10,4),

  attempts    integer not null default 0,
  error       jsonb,

  conversation_id uuid,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

create index if not exists generation_jobs_pending_idx
  on public.generation_jobs (status, updated_at)
  where status in ('queued','submitted','running');

create index if not exists generation_jobs_project_idx
  on public.generation_jobs (project_id, created_at desc);

-- Libro mayor de créditos. Reservar → confirmar → reembolsar.
-- Append-only: el saldo es la suma, nunca un UPDATE sobre un contador.
create table if not exists public.credit_ledger (
  id          uuid primary key default gen_random_uuid(),
  profile_id  uuid not null references public.profiles on delete cascade,
  project_id  uuid references public.projects on delete set null,
  job_id      uuid references public.generation_jobs on delete set null,
  kind        text not null check (kind in ('grant','reserve','charge','refund','expire','tokens')),
  amount      integer not null,                  -- con signo: reserve/charge/tokens negativos
  balance_after integer not null,
  note        text,
  created_at  timestamptz not null default now()
);

create index if not exists credit_ledger_profile_idx
  on public.credit_ledger (profile_id, created_at desc);


-- ===========================================================================
-- 3. AGENTE
-- ===========================================================================

create table if not exists public.conversations (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects on delete cascade,
  owner_id    uuid not null references public.profiles on delete cascade,
  title       text,
  mode        text not null default 'preproduction'
              check (mode in ('preproduction','production','edit')),
  supermode   text check (supermode in ('plan')),
  status      text not null default 'idle'
              check (status in ('idle','running','interrupted','failed')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Checkpointer de LangGraph (AsyncPostgresSaver crea lo suyo; esto es el índice
-- que nos permite listar y reanudar por conversación).
create table if not exists public.agent_checkpoints (
  thread_id   text not null,
  checkpoint_ns text not null default '',
  checkpoint_id text not null,
  parent_id   text,
  type        text,
  checkpoint  bytea not null,
  metadata    jsonb not null default '{}',
  created_at  timestamptz not null default now(),
  primary key (thread_id, checkpoint_ns, checkpoint_id)
);

-- Memoria del proyecto: la biblia. Un blob por proyecto y tipo.
--
-- Esto es lo que hay que reinyectar tras compactar el historial. Si no se reinyecta,
-- se rompe la continuidad visual entre planos, y el fallo se paga en créditos.
create table if not exists public.project_memory (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects on delete cascade,
  kind        text not null check (kind in
              ('style_bible','character_sheet','continuity_rules','director_prefs')),
  element_id  uuid references public.assets on delete cascade,  -- para character_sheet
  content     text not null,
  updated_at  timestamptz not null default now(),
  unique (project_id, kind, element_id)
);

-- Artefactos por referencia (guion, timeline, montaje). Nunca copias: refs.
-- Así, regenerar un plano actualiza todo lo que lo referencia.
create table if not exists public.artifacts (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects on delete cascade,
  kind        text not null check (kind in ('script','timeline','cut','plan')),
  version     integer not null default 1,
  content     jsonb not null,                    -- bloques con ShotRefBlock
  created_by  text not null default 'agent' check (created_by in ('agent','user')),
  created_at  timestamptz not null default now(),
  unique (project_id, kind, version)
);

-- --- RLS: todo cuelga del proyecto propio ---------------------------------

alter table public.generation_jobs enable row level security;
alter table public.credit_ledger   enable row level security;
alter table public.conversations   enable row level security;
alter table public.project_memory  enable row level security;
alter table public.artifacts       enable row level security;

do $$
declare t text;
begin
  foreach t in array array['generation_jobs','conversations','project_memory','artifacts']
  loop
    execute format($f$
      create policy "hijos del proyecto propio" on public.%I
        for all using (exists (
          select 1 from public.projects p
          where p.id = %I.project_id and p.owner_id = auth.uid()))
        with check (exists (
          select 1 from public.projects p
          where p.id = %I.project_id and p.owner_id = auth.uid()));
    $f$, t, t, t);
  end loop;
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "libro propio" on public.credit_ledger
    for select using (profile_id = auth.uid());
exception when duplicate_object then null; end $$;


-- --- Extensiones a tablas existentes --------------------------------------

alter table public.assets
  add column if not exists shot_id     text,
  add column if not exists job_id      uuid references public.generation_jobs on delete set null,
  add column if not exists model_id    text references public.gen_models,
  add column if not exists prompt      text,
  add column if not exists params      jsonb not null default '{}',
  add column if not exists parent_id   uuid references public.assets on delete set null,
  add column if not exists credits_spent integer not null default 0;

alter table public.canvas_nodes
  add column if not exists position    integer,     -- orden narrativo del timeline
  add column if not exists spec        jsonb not null default '{}',
  add column if not exists shot_status text not null default 'pending'
              check (shot_status in ('pending','generating','ready','failed','approved'));

comment on column public.canvas_nodes.position is
  'Orden narrativo. Es la señal que le dice al modelo qué plano va antes de cuál, '
  'y por tanto qué continuidad debe respetar. Equivale al orden por layout (y,x) '
  'con el que PostHog serializa los insights de un dashboard.';
