-- A completed manifest must point at immutable selections, never at "the latest"
-- project state. The specification is the approved intent; the execution snapshot
-- freezes the exact takes, reviews, audio cues and transitions used by assembly.
alter table public.production_manifests
  add column if not exists execution_snapshot jsonb,
  add column if not exists execution_fingerprint text,
  add column if not exists completed_at timestamptz;

alter table public.production_manifests
  drop constraint if exists production_manifests_complete_snapshot_check;
alter table public.production_manifests
  add constraint production_manifests_complete_snapshot_check check (
    status <> 'complete' or (
      execution_snapshot is not null
      and execution_fingerprint is not null
      and completed_at is not null
    )
  );
