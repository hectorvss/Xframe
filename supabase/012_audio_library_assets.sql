-- A template can either be a reusable generation brief or point at an approved
-- project audio asset saved from the library. The source asset remains immutable.

alter table public.audio_templates
  add column if not exists asset_id uuid references public.assets on delete set null;

create index if not exists audio_templates_asset_idx
  on public.audio_templates (project_id, asset_id)
  where asset_id is not null;
