import React, { useEffect, useMemo, useState } from "react";
import {
  AudioLines,
  ChevronRight,
  Clock3,
  FileAudio,
  MessageSquareText,
  Mic2,
  Music2,
  Plus,
  RefreshCw,
  Sparkles,
  UserRound,
  Volume2,
  Waves,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { db } from "@/lib/db";

const EMPTY = {
  scenes: [], lines: [], voices: [], characterVoices: [], cues: [], annotations: [],
  operations: [], transitions: [],
};

function useProduction(projectId) {
  const [data, setData] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const reload = async () => {
    setLoading(true);
    try { setData(await db.getProduction(projectId)); }
    catch { setData(EMPTY); }
    finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, loading, reload };
}

const lineTone = {
  dialogue: "bg-blue-50 text-blue-700",
  voiceover: "bg-violet-50 text-violet-700",
  action: "bg-amber-50 text-amber-700",
  caption: "bg-slate-100 text-slate-700",
};

export function ScreenplayStudio({ projectId, assets = [], onSeedChat }) {
  const { data, loading, reload } = useProduction(projectId);
  const [draft, setDraft] = useState("");
  const characters = useMemo(() => assets.filter((a) => a.role), [assets]);
  const byId = useMemo(() => new Map(assets.map((a) => [String(a.id), a])), [assets]);
  const linesByScene = useMemo(() => {
    const map = new Map();
    data.lines.forEach((line) => {
      const key = String(line.scene_id);
      map.set(key, [...(map.get(key) ?? []), line]);
    });
    return map;
  }, [data.lines]);

  const designScript = () => {
    const text = draft.trim();
    if (!text) return;
    onSeedChat?.(
      `Convierte este texto en el guion estructurado y editable del proyecto. ` +
      `Separa escenas, acciones, diálogo, voz en off y captions; asigna cada réplica ` +
      `solo a personajes que ya existan, conserva literalmente el copy y añade intención, ` +
      `emoción, ritmo, pausas y duración objetivo. No generes audio todavía.\n\n${text}`,
    );
    setDraft("");
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_300px]">
      <section className="min-h-0 overflow-y-auto rounded-xl border bg-background">
        <header className="sticky top-0 z-10 flex items-center gap-3 border-b bg-background/95 px-5 py-4 backdrop-blur">
          <div>
            <h2 className="font-semibold">Guion de producción</h2>
            <p className="text-xs text-muted-foreground">La fuente de verdad para diálogo, voz, captions y lipsync.</p>
          </div>
          <Button variant="outline" size="sm" className="ml-auto" onClick={reload}>
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} /> Actualizar
          </Button>
        </header>

        <div className="space-y-4 p-5">
          {!data.scenes.length && !loading && (
            <div className="rounded-xl border border-dashed p-8 text-center">
              <MessageSquareText className="mx-auto size-7 text-muted-foreground" />
              <h3 className="mt-3 text-sm font-medium">Todavía no hay un guion estructurado</h3>
              <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
                Pega una idea, guion técnico o copy. El agente lo convertirá en escenas y líneas editables sin inventar texto aprobado.
              </p>
            </div>
          )}
          {data.scenes.map((scene, sceneIndex) => (
            <Card key={scene.id} className="overflow-hidden shadow-none">
              <div className="flex items-start gap-3 border-b bg-muted/25 px-4 py-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-background text-xs font-semibold">
                  {sceneIndex + 1}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{scene.title || `Escena ${sceneIndex + 1}`}</p>
                  <p className="text-xs text-muted-foreground">
                    {[scene.setting, scene.time_of_day].filter(Boolean).join(" · ") || "Localización por definir"}
                  </p>
                </div>
                {scene.target_duration_ms && (
                  <Badge variant="outline" className="ml-auto gap-1 font-normal"><Clock3 className="size-3" />{scene.target_duration_ms / 1000}s</Badge>
                )}
              </div>
              <div className="divide-y">
                {(linesByScene.get(String(scene.id)) ?? []).map((line) => {
                  const speaker = byId.get(String(line.speaker_element_id));
                  return (
                    <div key={line.id} className="grid grid-cols-[120px_minmax(0,1fr)_110px] gap-3 px-4 py-3">
                      <div>
                        <Badge className={cn("border-0 text-[10px]", lineTone[line.line_type])}>{line.line_type}</Badge>
                        {speaker && <p className="mt-1.5 truncate text-xs font-medium">{speaker.name}</p>}
                      </div>
                      <div>
                        <p className="text-sm leading-relaxed">{line.text}</p>
                        {(line.direction || line.emotion) && <p className="mt-1 text-xs text-muted-foreground">{[line.emotion, line.direction].filter(Boolean).join(" · ")}</p>}
                      </div>
                      <div className="text-right text-xs text-muted-foreground">
                        {line.target_duration_ms ? `${(line.target_duration_ms / 1000).toFixed(1)} s` : "Auto"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          ))}
        </div>
      </section>

      <aside className="min-h-0 overflow-y-auto rounded-xl border bg-background p-4">
        <h3 className="text-sm font-semibold">Diseñar el guion</h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">Describe exactamente qué ocurre y qué dice cada personaje.</p>
        <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} className="mt-3 min-h-40 resize-y" placeholder={'ESCENA 1 — Oficina, noche\nMARTA: “El producto ya está listo.”\nVOZ EN OFF: “Del concepto al lanzamiento.”'} />
        <Button className="mt-2 w-full" disabled={!draft.trim()} onClick={designScript}><Sparkles /> Estructurar con el agente</Button>

        <div className="mt-6 border-t pt-4">
          <p className="text-xs font-medium text-muted-foreground">REPARTO Y VOCES</p>
          <div className="mt-2 space-y-2">
            {characters.map((character) => {
              const assignment = data.characterVoices.find((v) => String(v.element_id) === String(character.id) && v.is_default);
              const voice = data.voices.find((v) => String(v.id) === String(assignment?.voice_profile_id));
              return <div key={character.id} className="flex items-center gap-2 rounded-lg border p-2.5">
                <span className="flex size-8 items-center justify-center rounded-full bg-muted"><UserRound className="size-4" /></span>
                <div className="min-w-0 flex-1"><p className="truncate text-xs font-medium">{character.name}</p><p className="truncate text-[11px] text-muted-foreground">{voice?.name || "Voz sin asignar"}</p></div>
                <ChevronRight className="size-3.5 text-muted-foreground" />
              </div>;
            })}
            {!characters.length && <p className="text-xs text-muted-foreground">Crea personajes en Elements para asignar voces.</p>}
          </div>
        </div>
      </aside>
    </div>
  );
}

const trackMeta = {
  dialogue: [Mic2, "Diálogo", "bg-blue-500"],
  voiceover: [AudioLines, "Voz en off", "bg-violet-500"],
  music: [Music2, "Música", "bg-emerald-500"],
  sfx: [Waves, "Efectos", "bg-amber-500"],
  ambience: [Volume2, "Ambiente", "bg-cyan-500"],
  native: [FileAudio, "Audio nativo", "bg-slate-500"],
};

export function AudioStudio({ projectId, assets = [], onSeedChat }) {
  const { data, loading, reload } = useProduction(projectId);
  const [brief, setBrief] = useState("");
  const audioAssets = assets.filter((a) => /audio/i.test(String(a.type)) && a.status === "ready");
  const totalMs = Math.max(1000, ...data.cues.map((c) => c.end_ms || 0));

  const generate = () => {
    if (!brief.trim()) return;
    onSeedChat?.(
      `Diseña el audio del proyecto a partir de este brief: ${brief.trim()}\n` +
      `Usa el guion estructurado para cualquier voz. Decide si hace falta una sola pieza ` +
      `musical o varias por contexto, define secciones, intensidad, entradas, salidas, ` +
      `ducking bajo diálogo y transiciones. Primero explica el plan y estima créditos; ` +
      `después genera solo con mi aprobación.`,
    );
    setBrief("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-background">
      <header className="flex items-center gap-3 border-b px-5 py-4">
        <div><h2 className="font-semibold">Audio y voces</h2><p className="text-xs text-muted-foreground">Assets reutilizables, música contextual y mezcla determinista.</p></div>
        <Button variant="outline" size="sm" className="ml-auto" onClick={reload}><RefreshCw className={cn("size-3.5", loading && "animate-spin")} /> Actualizar</Button>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="overflow-y-auto border-r p-4">
          <p className="text-xs font-medium text-muted-foreground">BIBLIOTECA DE AUDIO</p>
          <div className="mt-2 space-y-2">
            {audioAssets.map((asset) => <div key={asset.id} className="rounded-lg border p-3"><div className="flex items-center gap-2"><FileAudio className="size-4 text-muted-foreground" /><p className="min-w-0 flex-1 truncate text-xs font-medium">{asset.name}</p></div>{asset.url && <audio src={asset.url} controls className="mt-2 h-7 w-full" />}</div>)}
            {!audioAssets.length && <div className="rounded-lg border border-dashed p-5 text-center text-xs text-muted-foreground">Aún no hay voces, música o efectos generados.</div>}
          </div>
          <p className="mt-5 text-xs font-medium text-muted-foreground">NUEVO AUDIO</p>
          <Textarea value={brief} onChange={(e) => setBrief(e.target.value)} className="mt-2 min-h-28" placeholder="Música sobria y tecnológica; tensión gradual en la demo, silencio antes del claim final…" />
          <Button className="mt-2 w-full" disabled={!brief.trim()} onClick={generate}><Plus /> Diseñar con el agente</Button>
        </aside>

        <section className="min-h-0 overflow-y-auto p-5">
          <div className="flex items-center justify-between"><div><h3 className="text-sm font-semibold">Plan de mezcla</h3><p className="text-xs text-muted-foreground">Cada cue tiene tiempo, ganancia, fundidos y función narrativa.</p></div><Badge variant="outline">{(totalMs / 1000).toFixed(1)} s</Badge></div>
          <div className="mt-5 space-y-2">
            {Object.entries(trackMeta).map(([kind, [Icon, label, color]]) => {
              const cues = data.cues.filter((cue) => cue.track_kind === kind);
              return <div key={kind} className="grid grid-cols-[120px_minmax(0,1fr)] items-stretch gap-2">
                <div className="flex items-center gap-2 rounded-lg border px-3"><Icon className="size-3.5 text-muted-foreground" /><span className="text-xs font-medium">{label}</span></div>
                <div className="relative h-14 overflow-hidden rounded-lg border bg-muted/20">
                  <div className="absolute inset-x-3 top-1/2 border-t border-dashed" />
                  {cues.map((cue) => <button key={cue.id} className={cn("absolute top-2 h-9 min-w-8 rounded-md px-2 text-left text-[10px] text-white shadow-sm", color)} style={{ left: `${(cue.start_ms / totalMs) * 100}%`, width: `${Math.max(3, ((cue.end_ms - cue.start_ms) / totalMs) * 100)}%` }} title={`${cue.start_ms}–${cue.end_ms} ms · ${cue.gain_db ?? 0} dB`}><span className="block truncate">{assets.find((a) => String(a.id) === String(cue.asset_id))?.name || label}</span><span className="opacity-75">{cue.gain_db ?? 0} dB</span></button>)}
                </div>
              </div>;
            })}
          </div>
          {!data.cues.length && <div className="mt-5 rounded-xl border border-dashed p-8 text-center"><Music2 className="mx-auto size-7 text-muted-foreground" /><p className="mt-2 text-sm font-medium">No hay cues colocados</p><p className="mt-1 text-xs text-muted-foreground">Genera o sube audio y pide al agente un plan de mezcla contextual.</p></div>}
        </section>
      </div>
    </div>
  );
}
