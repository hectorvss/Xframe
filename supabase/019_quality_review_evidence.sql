-- A quality decision must be attributable and carry the observation that led
-- to it. Existing automated reports are retained and explicitly classified.
alter table public.quality_reports
  add column if not exists review_source text not null default 'automated'
    check (review_source in ('human','automated','provider')),
  add column if not exists reviewed_by uuid default auth.uid() references auth.users(id) on delete set null,
  add column if not exists review_evidence jsonb not null default '{}'::jsonb;

create index if not exists quality_reports_reviewed_by_idx
  on public.quality_reports(project_id, reviewed_by, created_at desc);

alter table public.quality_reports alter column reviewed_by set default auth.uid();
