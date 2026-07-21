-- Brief and canvas media must point at first-class assets.  Browser blob URLs and
-- expiring signed URLs are presentation details and must never be the durable link.
alter table public.brief_blocks
  add column if not exists asset_id uuid references public.assets(id) on delete set null;

alter table public.canvas_nodes
  add column if not exists asset_id uuid references public.assets(id) on delete set null;

create index if not exists brief_blocks_asset_idx
  on public.brief_blocks(project_id, asset_id)
  where asset_id is not null;

create index if not exists canvas_nodes_asset_idx
  on public.canvas_nodes(project_id, asset_id)
  where asset_id is not null;
