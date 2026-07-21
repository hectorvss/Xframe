-- Tipo creativo fijado al crear un proyecto. Los proyectos anteriores pasan a
-- Cinema, que conserva el flujo audiovisual que ya existía.
alter table public.projects
  add column if not exists project_type text not null default 'cinema';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'projects_project_type_check'
      and conrelid = 'public.projects'::regclass
  ) then
    alter table public.projects
      add constraint projects_project_type_check
      check (project_type in ('cinema', 'marketing', 'demo'));
  end if;
end
$$;
