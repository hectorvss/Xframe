alter table public.production_manifests
  add column if not exists approved_by uuid references auth.users(id) on delete set null,
  add column if not exists approval_evidence jsonb not null default '{}'::jsonb;
