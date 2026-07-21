-- Music, ambience and SFX often belong to a scene without belonging to one
-- dialogue line or shot. Timings remain absolute on the project mix timeline;
-- scene_id is the semantic production scope used by manifests and the agent.
alter table public.audio_cues
  add column if not exists scene_id uuid references public.script_scenes(id) on delete set null;

create index if not exists audio_cues_scene_timeline_idx
  on public.audio_cues(project_id, scene_id, start_ms);
