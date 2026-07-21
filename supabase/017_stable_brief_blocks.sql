-- The editor needs a stable, non-UUID key while production references keep the
-- immutable database UUID. Replacing every row on each keystroke invalidated
-- agent references and could race an older save over a newer one.
alter table public.brief_blocks
  add column if not exists block_key text;

update public.brief_blocks
   set block_key = id::text
 where block_key is null;

alter table public.brief_blocks
  alter column block_key set default gen_random_uuid()::text,
  alter column block_key set not null;

create unique index if not exists brief_blocks_project_key_uidx
  on public.brief_blocks(project_id, block_key);
