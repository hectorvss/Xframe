import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  AudioLines,
  Bookmark,
  Check,
  ChevronRight,
  CopyPlus,
  FileAudio,
  GripVertical,
  LoaderCircle,
  Lock,
  MessageSquareText,
  Mic2,
  MoreHorizontal,
  Music2,
  Pause,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Settings2,
  Trash2,
  UserRound,
  Volume2,
  WandSparkles,
  Waves,
  Zap,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { db } from "@/lib/db";

const EMPTY = {
  scenes: [],
  lines: [],
  voices: [],
  characterVoices: [],
  cues: [],
  annotations: [],
  operations: [],
  transitions: [],
  assetLinks: [],
  audioTemplates: [],
};

const visualRoles = {
  reference: "Referencia visual",
  source: "Fuente obligatoria",
  character: "Personaje",
  product: "Producto",
  background: "Fondo / localización",
  style: "Estilo",
  first_frame: "Primer fotograma",
  last_frame: "Último fotograma",
};

const builtInSoundTemplates = [
  {
    id: "impact",
    name: "Impacto de producto",
    kind: "sfx",
    duration_ms: 1800,
    intensity: 0.8,
    loop: false,
    tags: ["reveal", "producto"],
    prompt:
      "Impacto cinematográfico premium, grave contenido, ataque limpio y cola corta; sin distorsión ni carácter épico excesivo.",
  },
  {
    id: "ui",
    name: "Interfaz tecnológica",
    kind: "sfx",
    duration_ms: 1200,
    intensity: 0.35,
    loop: false,
    tags: ["ui", "demo"],
    prompt:
      "Secuencia precisa de microclics digitales y confirmación tonal suave para una interacción de producto profesional.",
  },
  {
    id: "room",
    name: "Ambiente de estudio",
    kind: "ambience",
    duration_ms: 12000,
    intensity: 0.2,
    loop: true,
    tags: ["interior", "neutral"],
    prompt:
      "Room tone de estudio moderno y silencioso, ventilación muy distante, sin voces ni eventos reconocibles, bucle imperceptible.",
  },
  {
    id: "tension",
    name: "Tensión para demo",
    kind: "music",
    duration_ms: 20000,
    intensity: 0.55,
    loop: false,
    tags: ["tecnología", "progresión"],
    prompt:
      "Cama musical tecnológica sobria, pulso mínimo y crecimiento gradual; deja espacio al diálogo y resuelve con una nota cálida tras el reveal.",
  },
  {
    id: "transition",
    name: "Transición limpia",
    kind: "sfx",
    duration_ms: 900,
    intensity: 0.45,
    loop: false,
    tags: ["transición", "whoosh"],
    prompt:
      "Whoosh corto, elegante y aireado para una transición de interfaz; ataque suave, centro definido y final sin resonancia.",
  },
  {
    id: "outro",
    name: "Cierre de marca",
    kind: "music",
    duration_ms: 6000,
    intensity: 0.5,
    loop: false,
    tags: ["marca", "cierre"],
    prompt:
      "Resolución musical contemporánea y confiable, dos acordes limpios y una textura cálida para acompañar el logotipo final.",
  },
];

const lineMeta = {
  dialogue: ["Diálogo", "bg-blue-50 text-blue-700 border-blue-100"],
  voiceover: ["Voz en off", "bg-violet-50 text-violet-700 border-violet-100"],
  action: ["Acción", "bg-amber-50 text-amber-700 border-amber-100"],
  caption: ["Rótulo", "bg-slate-100 text-slate-700 border-slate-200"],
};

const trackMeta = {
  dialogue: [Mic2, "Diálogo", "bg-blue-600"],
  voiceover: [AudioLines, "Voz en off", "bg-violet-600"],
  music: [Music2, "Música", "bg-emerald-600"],
  sfx: [Waves, "Efectos", "bg-amber-600"],
  ambience: [Volume2, "Ambiente", "bg-cyan-600"],
  native: [FileAudio, "Audio nativo", "bg-slate-600"],
};

function useProduction(projectId) {
  const [data, setData] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const reload = async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      setData(await db.getProduction(projectId));
      setError("");
    } catch (reason) {
      setError(reason?.message || "No se pudo cargar la producción.");
    } finally {
      if (showLoader) setLoading(false);
    }
  };

  const run = async (operation) => {
    setSaving(true);
    try {
      await operation();
      await reload(false);
      setError("");
      return true;
    } catch (reason) {
      setError(reason?.message || "No se pudo guardar el cambio.");
      return false;
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    reload();
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, loading, saving, error, reload, run };
}

function useStoredVisibility(key, initial = true) {
  const [visible, setVisible] = useState(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? initial : stored === "true";
    } catch {
      return initial;
    }
  });
  const update = (next) => {
    setVisible(next);
    try {
      window.localStorage.setItem(key, String(next));
    } catch {
      // La preferencia es opcional; la UI sigue funcionando sin almacenamiento.
    }
  };
  return [visible, update];
}

function Field({ label, hint, children, className }) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <label className="text-xs font-medium text-foreground">{label}</label>
        {hint && (
          <span className="text-[10px] text-muted-foreground">{hint}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function DraftInput({
  value,
  onCommit,
  multiline = false,
  number = false,
  nullable = false,
  ...props
}) {
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => setDraft(value ?? ""), [value]);
  const commit = () => {
    let next = draft;
    if (number) next = draft === "" && nullable ? null : Number(draft || 0);
    if (next !== value) onCommit(next);
  };
  const Component = multiline ? Textarea : Input;
  return (
    <Component
      {...props}
      type={number && !multiline ? "number" : props.type}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (!multiline && event.key === "Enter") event.currentTarget.blur();
      }}
    />
  );
}

function SaveState({ saving, error }) {
  if (error)
    return (
      <Badge variant="destructive" className="max-w-72 truncate">
        {error}
      </Badge>
    );
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {saving ? (
        <LoaderCircle className="size-3.5 animate-spin" />
      ) : (
        <Check className="size-3.5" />
      )}
      {saving ? "Guardando" : "Cambios guardados"}
    </span>
  );
}

function SidebarToggle({ side, expanded, onChange, label }) {
  const Icon =
    side === "left"
      ? expanded
        ? PanelLeftClose
        : PanelLeftOpen
      : expanded
        ? PanelRightClose
        : PanelRightOpen;
  const action = expanded ? "Ocultar" : "Mostrar";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-9 shrink-0"
          onClick={() => onChange(!expanded)}
          aria-label={`${action} ${label}`}
        >
          <Icon className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{`${action} ${label}`}</TooltipContent>
    </Tooltip>
  );
}

function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed bg-muted/10 p-8 text-center">
      <span className="flex size-11 items-center justify-center rounded-xl border bg-background shadow-sm">
        <Icon className="size-5 text-muted-foreground" />
      </span>
      <h3 className="mt-4 text-sm font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
        {description}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

function AgentBrief({
  title,
  description,
  placeholder,
  value,
  setValue,
  onSubmit,
  submitLabel,
}) {
  return (
    <Card className="shadow-none">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Sparkles className="size-4" />
          {title}
        </CardTitle>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {description}
        </p>
      </CardHeader>
      <CardContent className="space-y-2 p-4 pt-2">
        <Textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          className="min-h-32 resize-y"
          placeholder={placeholder}
        />
        <Button className="w-full" disabled={!value.trim()} onClick={onSubmit}>
          <WandSparkles />
          {submitLabel}
        </Button>
      </CardContent>
    </Card>
  );
}

function AssetReferences({
  projectId,
  sceneId,
  lineId = null,
  assets,
  links,
  run,
  onSeedChat,
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const visualAssets = useMemo(
    () =>
      assets.filter(
        (asset) =>
          asset.status === "ready" &&
          !/audio/i.test(String(asset.type)) &&
          `${asset.name} ${asset.type}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [assets, query],
  );
  const scoped = links.filter(
    (link) =>
      String(link.scene_id) === String(sceneId) &&
      String(link.script_line_id || "") === String(lineId || ""),
  );
  const add = async (asset) => {
    const ok = await run(() =>
      db.linkScriptAsset(projectId, sceneId, lineId, asset.id),
    );
    if (ok) setOpen(false);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-xs font-medium">Assets vinculados</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            El agente los tratará como contexto explícito de esta{" "}
            {lineId ? "línea" : "escena"}.
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm">
              <Plus />
              Asignar
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-3xl">
            <DialogHeader>
              <DialogTitle>Asignar un asset al guion</DialogTitle>
              <DialogDescription>
                Elige una imagen o vídeo ya aprobado. Después podrás indicar su
                función exacta y el tramo donde debe utilizarse.
              </DialogDescription>
            </DialogHeader>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="pl-9"
                placeholder="Buscar en Assets…"
              />
            </div>
            <ScrollArea className="h-[390px]">
              <div className="grid grid-cols-3 gap-3 pr-3">
                {visualAssets.map((asset) => (
                  <Card key={asset.id} className="overflow-hidden shadow-none">
                    <div className="aspect-video bg-muted">
                      {asset.url ? (
                        /video/i.test(String(asset.type)) ? (
                          <video
                            src={asset.url}
                            className="size-full object-cover"
                          />
                        ) : (
                          <img
                            src={asset.url}
                            alt=""
                            className="size-full object-cover"
                          />
                        )
                      ) : (
                        <div className="flex size-full items-center justify-center text-xs text-muted-foreground">
                          Sin preview
                        </div>
                      )}
                    </div>
                    <CardContent className="flex items-center gap-2 p-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium">
                          {asset.name}
                        </p>
                        <p className="truncate text-[10px] text-muted-foreground">
                          {asset.type}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => add(asset)}
                      >
                        Usar
                      </Button>
                    </CardContent>
                  </Card>
                ))}
                {!visualAssets.length && (
                  <div className="col-span-3">
                    <EmptyState
                      icon={Search}
                      title="No hay coincidencias"
                      description="Genera o sube el asset en la sección Assets y después asígnalo aquí."
                    />
                  </div>
                )}
              </div>
            </ScrollArea>
          </DialogContent>
        </Dialog>
      </div>
      {scoped.map((link) => {
        const asset = assets.find(
          (item) => String(item.id) === String(link.asset_id),
        );
        return (
          <Card key={link.id} className="overflow-hidden shadow-none">
            <div className="flex gap-3 p-3">
              <div className="size-14 shrink-0 overflow-hidden rounded-md bg-muted">
                {asset?.url &&
                  (/video/i.test(String(asset.type)) ? (
                    <video src={asset.url} className="size-full object-cover" />
                  ) : (
                    <img
                      src={asset.url}
                      alt=""
                      className="size-full object-cover"
                    />
                  ))}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">
                  {asset?.name || "Asset"}
                </p>
                <p className="mt-0.5 text-[10px] text-muted-foreground">
                  {visualRoles[link.role]}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => run(() => db.unlinkScriptAsset(link.id))}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
            <div className="space-y-3 border-t bg-muted/10 p-3">
              <Field label="Función en la generación">
                <Select
                  value={link.role}
                  onValueChange={(role) =>
                    run(() => db.updateScriptAssetLink(link.id, { role }))
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(visualRoles).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Instrucción precisa">
                <DraftInput
                  multiline
                  className="min-h-16 text-xs"
                  value={link.instructions}
                  onCommit={(instructions) =>
                    run(() =>
                      db.updateScriptAssetLink(link.id, { instructions }),
                    )
                  }
                  placeholder="Usar exactamente el producto; conservar encuadre y color…"
                />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Desde" hint="ms">
                  <DraftInput
                    number
                    nullable
                    value={link.start_offset_ms ?? ""}
                    onCommit={(start_offset_ms) =>
                      run(() =>
                        db.updateScriptAssetLink(link.id, { start_offset_ms }),
                      )
                    }
                  />
                </Field>
                <Field label="Hasta" hint="ms">
                  <DraftInput
                    number
                    nullable
                    value={link.end_offset_ms ?? ""}
                    onCommit={(end_offset_ms) =>
                      run(() =>
                        db.updateScriptAssetLink(link.id, { end_offset_ms }),
                      )
                    }
                  />
                </Field>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium">Referencia obligatoria</p>
                  <p className="text-[10px] text-muted-foreground">
                    Impide sustituciones silenciosas
                  </p>
                </div>
                <Switch
                  checked={Boolean(link.locked)}
                  onCheckedChange={(locked) =>
                    run(() => db.updateScriptAssetLink(link.id, { locked }))
                  }
                />
              </div>
            </div>
          </Card>
        );
      })}
      {!scoped.length && (
        <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
          Sin referencias: el agente decidirá la imagen únicamente desde el
          texto.
        </p>
      )}
    </div>
  );
}

function SceneInspector({
  projectId,
  scene,
  characters,
  voices,
  assignments,
  assets,
  links,
  run,
}) {
  if (!scene) return null;
  return (
    <div className="space-y-4">
      <Field label="Estado">
        <Select
          value={scene.status || "draft"}
          onValueChange={(status) =>
            run(() => db.updateScriptScene(scene.id, { status }))
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="draft">Borrador</SelectItem>
            <SelectItem value="approved">Aprobada</SelectItem>
            <SelectItem value="locked">Bloqueada</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Duración objetivo" hint="segundos">
        <DraftInput
          number
          nullable
          min="0.1"
          step="0.1"
          value={
            scene.target_duration_ms ? scene.target_duration_ms / 1000 : ""
          }
          onCommit={(seconds) =>
            run(() =>
              db.updateScriptScene(scene.id, {
                target_duration_ms:
                  seconds === null ? null : Math.round(seconds * 1000),
              }),
            )
          }
        />
      </Field>
      <Field label="Resumen narrativo">
        <DraftInput
          multiline
          className="min-h-24"
          value={scene.summary}
          onCommit={(summary) =>
            run(() => db.updateScriptScene(scene.id, { summary }))
          }
          placeholder="Qué ocurre en la escena…"
        />
      </Field>
      <Field label="Intención dramática">
        <DraftInput
          multiline
          className="min-h-20"
          value={scene.dramatic_intent}
          onCommit={(dramatic_intent) =>
            run(() => db.updateScriptScene(scene.id, { dramatic_intent }))
          }
          placeholder="Qué debe sentir o comprender el espectador…"
        />
      </Field>
      <Separator />
      <AssetReferences
        projectId={projectId}
        sceneId={scene.id}
        assets={assets}
        links={links}
        run={run}
      />
      <Card className="border-blue-200 bg-blue-50/50 shadow-none">
        <CardContent className="p-3">
          <p className="text-xs font-medium">Producir esta escena</p>
          <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
            Texto, interpretación, referencias visuales y audio se enviarán como
            una única especificación.
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3 w-full bg-background"
            onClick={() =>
              onSeedChat?.(
                `Genera o rehace la escena de guion ${scene.id} como una secuencia de vídeo completa. ` +
                  `Respeta literalmente sus líneas aprobadas y usa todos sus asset links y los de cada línea según role, instructions, range_ms y locked. ` +
                  `Sincroniza tomas de voz, lipsync y cues asociados; no sustituyas referencias bloqueadas. ` +
                  `Presenta primero el plan de planos y el coste, y genera solo tras mi aprobación.`,
              )
            }
          >
            <WandSparkles />
            Generar o rehacer escena
          </Button>
        </CardContent>
      </Card>
      <Separator />
      <div>
        <p className="text-xs font-medium">Reparto y voces</p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          La voz asignada se usa como predeterminada en nuevas réplicas.
        </p>
        <div className="mt-3 space-y-2">
          {characters.map((character) => {
            const assignment = assignments.find(
              (item) =>
                String(item.element_id) === String(character.id) &&
                item.is_default,
            );
            return (
              <div key={character.id} className="rounded-lg border p-2.5">
                <div className="mb-2 flex items-center gap-2">
                  <span className="flex size-7 items-center justify-center rounded-full bg-muted">
                    <UserRound className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium">
                    {character.name}
                  </span>
                </div>
                <Select
                  value={assignment?.voice_profile_id || "__none__"}
                  onValueChange={(id) =>
                    run(() =>
                      db.assignCharacterVoice(
                        scene.project_id,
                        character.id,
                        id === "__none__" ? null : id,
                      ),
                    )
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="Sin voz" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Sin voz asignada</SelectItem>
                    {voices.map((voice) => (
                      <SelectItem key={voice.id} value={String(voice.id)}>
                        {voice.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            );
          })}
          {!characters.length && (
            <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              Crea personajes en Elements para asignar sus voces.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function LineInspector({
  projectId,
  line,
  assets,
  links,
  characters,
  voices,
  run,
  onSeedChat,
  onDelete,
  onMoveUp,
  onMoveDown,
}) {
  if (!line)
    return (
      <EmptyState
        icon={MessageSquareText}
        title="Selecciona una línea"
        description="Aquí podrás ajustar quién habla, la interpretación, el timing y el estado de aprobación."
      />
    );
  const update = (patch) => run(() => db.updateScriptLine(line.id, patch));
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold">Dirección de la línea</p>
          <p className="text-[11px] text-muted-foreground">
            Control fino para voz y lipsync
          </p>
        </div>
        <div className="flex items-center">
          <Button
            variant="ghost"
            size="icon"
            onClick={onMoveUp}
            aria-label="Mover línea arriba"
          >
            <ArrowUp className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onMoveDown}
            aria-label="Mover línea abajo"
          >
            <ArrowDown className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onDelete}
            aria-label="Eliminar línea"
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
      <Field label="Tipo">
        <Select
          value={line.line_type}
          onValueChange={(line_type) =>
            update({
              line_type,
              speaker_element_id:
                line_type === "dialogue" ? line.speaker_element_id : null,
            })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(lineMeta).map(([value, [label]]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      {line.line_type === "dialogue" && (
        <Field label="Personaje">
          <Select
            value={line.speaker_element_id || "__none__"}
            onValueChange={(id) =>
              update({ speaker_element_id: id === "__none__" ? null : id })
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">Sin asignar</SelectItem>
              {characters.map((character) => (
                <SelectItem key={character.id} value={String(character.id)}>
                  {character.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      )}
      {["dialogue", "voiceover"].includes(line.line_type) && (
        <Field label="Voz para esta toma">
          <Select
            value={line.voice_profile_id || "__default__"}
            onValueChange={(id) =>
              update({ voice_profile_id: id === "__default__" ? null : id })
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__default__">Voz predeterminada</SelectItem>
              {voices.map((voice) => (
                <SelectItem key={voice.id} value={String(voice.id)}>
                  {voice.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Emoción">
          <DraftInput
            value={line.emotion}
            onCommit={(emotion) => update({ emotion })}
          />
        </Field>
        <Field label="Idioma">
          <DraftInput
            value={line.language}
            onCommit={(language) => update({ language })}
          />
        </Field>
      </div>
      <Field label="Dirección interpretativa">
        <DraftInput
          multiline
          className="min-h-20"
          value={line.direction}
          onCommit={(direction) => update({ direction })}
          placeholder="Susurra, acelera al final…"
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Ritmo" hint="0.5–2">
          <DraftInput
            number
            min="0.5"
            max="2"
            step="0.05"
            value={line.pace}
            onCommit={(pace) => update({ pace })}
          />
        </Field>
        <Field label="Intensidad" hint="0–1">
          <DraftInput
            number
            min="0"
            max="1"
            step="0.05"
            value={line.intensity}
            onCommit={(intensity) => update({ intensity })}
          />
        </Field>
        <Field label="Pausa antes" hint="ms">
          <DraftInput
            number
            min="0"
            step="50"
            value={line.pause_before_ms}
            onCommit={(pause_before_ms) => update({ pause_before_ms })}
          />
        </Field>
        <Field label="Pausa después" hint="ms">
          <DraftInput
            number
            min="0"
            step="50"
            value={line.pause_after_ms}
            onCommit={(pause_after_ms) => update({ pause_after_ms })}
          />
        </Field>
        <Field label="Duración" hint="ms">
          <DraftInput
            number
            nullable
            min="1"
            value={line.target_duration_ms ?? ""}
            onCommit={(target_duration_ms) => update({ target_duration_ms })}
          />
        </Field>
        <Field label="Estado">
          <Select
            value={line.status || "draft"}
            onValueChange={(status) => update({ status })}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[
                "draft",
                "ready",
                "generating",
                "review",
                "approved",
                "failed",
              ].map((status) => (
                <SelectItem key={status} value={status}>
                  {status}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <Separator />
      {["dialogue", "voiceover"].includes(line.line_type) && (
        <Card className="border-violet-200 bg-violet-50/50 shadow-none">
          <CardContent className="p-3">
            <p className="text-xs font-medium">Generar una toma de voz</p>
            <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
              El modelo interpretará la voz asignada usando literalmente esta
              línea y sus parámetros de actuación.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3 w-full bg-background"
              onClick={() =>
                onSeedChat?.(
                  `Genera y guarda como asset una toma de audio para la línea de guion ${line.id}. ` +
                    `Usa exactamente su texto aprobado, personaje, emoción, dirección, ritmo, intensidad y pausas. ` +
                    `No me pidas escoger una voz concreta del modelo: usa el perfil asignado como intención y deja que el modelo produzca la interpretación. ` +
                    `Cuando esté lista, vincúlala a la línea y colócala en el plan de audio respetando su timing. Estima créditos antes de generar.`,
                )
              }
            >
              <Mic2 />
              Generar desde esta línea
            </Button>
          </CardContent>
        </Card>
      )}
      <AssetReferences
        projectId={projectId}
        sceneId={line.scene_id}
        lineId={line.id}
        assets={assets}
        links={links}
        run={run}
      />
    </div>
  );
}

export function ScreenplayStudio({ projectId, assets = [], onSeedChat }) {
  const { data, loading, saving, error, reload, run } =
    useProduction(projectId);
  const [sceneId, setSceneId] = useState(null);
  const [lineId, setLineId] = useState(null);
  const [draft, setDraft] = useState("");
  const [scenePanelVisible, setScenePanelVisible] = useStoredVisibility(
    "xframe.screenplay.scene-panel",
  );
  const [scriptInspectorVisible, setScriptInspectorVisible] =
    useStoredVisibility("xframe.screenplay.inspector");
  const characters = useMemo(
    () => assets.filter((asset) => asset.role),
    [assets],
  );
  const linesByScene = useMemo(
    () =>
      data.lines.filter((line) => String(line.scene_id) === String(sceneId)),
    [data.lines, sceneId],
  );
  const scene =
    data.scenes.find((item) => String(item.id) === String(sceneId)) ||
    data.scenes[0];
  const selectedLine =
    data.lines.find((item) => String(item.id) === String(lineId)) || null;
  const totalDuration = data.scenes.reduce(
    (total, item) => total + (item.target_duration_ms || 0),
    0,
  );

  useEffect(() => {
    if (!data.scenes.length) {
      setSceneId(null);
      setLineId(null);
      return;
    }
    if (!data.scenes.some((item) => String(item.id) === String(sceneId)))
      setSceneId(data.scenes[0].id);
  }, [data.scenes, sceneId]);
  useEffect(() => setLineId(null), [sceneId]);

  const addScene = async () => {
    let created;
    const ok = await run(async () => {
      created = await db.createScriptScene(projectId);
    });
    if (ok && created) setSceneId(created.id);
  };
  const addLine = async (line_type = "dialogue") => {
    if (!scene) return;
    let created;
    const ok = await run(async () => {
      created = await db.createScriptLine(projectId, scene.id, { line_type });
    });
    if (ok && created) setLineId(created.id);
  };
  const sendBrief = () => {
    if (!draft.trim()) return;
    onSeedChat?.(
      `Convierte este texto en el guion estructurado y editable del proyecto. Separa escenas, acciones, diálogo, voz en off y rótulos; conserva literalmente el copy aprobado y añade emoción, ritmo, pausas y duración objetivo. No generes audio todavía.\n\n${draft.trim()}`,
    );
    setDraft("");
  };

  return (
    <TooltipProvider>
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-background">
        <header className="flex h-16 shrink-0 items-center gap-4 border-b px-4">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">
              Guion de producción
            </h2>
            <p className="truncate text-xs text-muted-foreground">
              Documento vivo para narrativa, interpretación, timing y lipsync.
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <Badge variant="outline">
              {data.scenes.length} escenas · {data.lines.length} líneas ·{" "}
              {(totalDuration / 1000).toFixed(1)} s
            </Badge>
            <SaveState saving={saving} error={error} />
            <Button variant="outline" size="sm" onClick={() => reload()}>
              <RefreshCw
                className={cn("size-3.5", loading && "animate-spin")}
              />
              Actualizar
            </Button>
          </div>
        </header>
        <div
          className="grid min-h-0 flex-1"
          style={{
            gridTemplateColumns: `${scenePanelVisible ? "220px" : "0px"} minmax(420px, 1fr) ${scriptInspectorVisible ? "310px" : "0px"}`,
          }}
        >
          <aside
            className={cn(
              "relative flex min-h-0 flex-col",
              scenePanelVisible
                ? "overflow-hidden border-r bg-muted/10"
                : "overflow-visible",
            )}
          >
            <div
              className={cn(
                "flex shrink-0 items-center",
                scenePanelVisible
                  ? "h-14 justify-between border-b px-3"
                  : "absolute left-2 top-2 z-20",
              )}
            >
              {scenePanelVisible && (
                <div>
                  <p className="text-xs font-semibold">ESCENAS</p>
                  <p className="text-[10px] text-muted-foreground">
                    Orden narrativo
                  </p>
                </div>
              )}
              <div className="flex items-center gap-1">
                {scenePanelVisible && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="icon" onClick={addScene}>
                        <Plus className="size-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Nueva escena</TooltipContent>
                  </Tooltip>
                )}
                <SidebarToggle
                  side="left"
                  expanded={scenePanelVisible}
                  onChange={setScenePanelVisible}
                  label="escenas"
                />
              </div>
            </div>
            {scenePanelVisible && (
              <>
                <ScrollArea className="min-h-0 flex-1 px-2 pb-3">
                  <div className="space-y-1">
                    {data.scenes.map((item, index) => {
                      const count = data.lines.filter(
                        (line) => String(line.scene_id) === String(item.id),
                      ).length;
                      const referenceCount = data.assetLinks.filter(
                        (link) =>
                          String(link.scene_id) === String(item.id) &&
                          !link.script_line_id,
                      ).length;
                      return (
                        <Button
                          key={item.id}
                          variant="ghost"
                          className={cn(
                            "h-auto w-full justify-start gap-2.5 px-2.5 py-2.5 text-left",
                            String(scene?.id) === String(item.id) &&
                              "bg-accent",
                          )}
                          onClick={() => setSceneId(item.id)}
                        >
                          <span className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-background text-xs font-semibold">
                            {index + 1}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-xs font-medium">
                              {item.title || `Escena ${index + 1}`}
                            </span>
                            <span className="mt-0.5 block truncate text-[10px] font-normal text-muted-foreground">
                              {count} líneas ·{" "}
                              {item.target_duration_ms
                                ? `${item.target_duration_ms / 1000}s`
                                : "sin duración"}
                              {referenceCount
                                ? ` · ${referenceCount} refs`
                                : ""}
                            </span>
                          </span>
                          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                        </Button>
                      );
                    })}
                  </div>
                </ScrollArea>
                <div className="border-t p-3">
                  <Dialog>
                    <DialogTrigger asChild>
                      <Button variant="outline" className="w-full">
                        <Sparkles />
                        Importar con el agente
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Estructurar un guion</DialogTitle>
                        <DialogDescription>
                          Pega el texto aprobado. El agente propondrá escenas y
                          dirección sin generar audio.
                        </DialogDescription>
                      </DialogHeader>
                      <Textarea
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        className="min-h-52"
                        placeholder={
                          "ESCENA 1 — Estudio, noche\nMARTA: “La campaña está lista.”\nVOZ EN OFF: “Del concepto al lanzamiento.”"
                        }
                      />
                      <DialogFooter>
                        <Button disabled={!draft.trim()} onClick={sendBrief}>
                          <WandSparkles />
                          Llevar al chat
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </div>
              </>
            )}
          </aside>

          <main
            className={cn(
              "min-h-0 overflow-y-auto",
              !scenePanelVisible && "pl-14",
              !scriptInspectorVisible && "pr-14",
            )}
          >
            {!scene && !loading ? (
              <div className="p-6">
                <EmptyState
                  icon={MessageSquareText}
                  title="Empieza por la primera escena"
                  description="Crea una escena manualmente o importa un guion para convertirlo en una estructura completamente editable."
                  action={
                    <Button onClick={addScene}>
                      <Plus />
                      Crear escena
                    </Button>
                  }
                />
              </div>
            ) : (
              scene && (
                <div>
                  <div className="sticky top-0 z-10 border-b bg-background/95 px-5 py-4 backdrop-blur">
                    <div className="flex items-start gap-3">
                      <div className="grid min-w-0 flex-1 grid-cols-[minmax(180px,1fr)_minmax(130px,.55fr)_130px] gap-3">
                        <Field label="Título">
                          <DraftInput
                            value={scene.title}
                            onCommit={(title) =>
                              run(() =>
                                db.updateScriptScene(scene.id, { title }),
                              )
                            }
                          />
                        </Field>
                        <Field label="Localización">
                          <DraftInput
                            value={scene.setting}
                            onCommit={(setting) =>
                              run(() =>
                                db.updateScriptScene(scene.id, { setting }),
                              )
                            }
                            placeholder="Estudio"
                          />
                        </Field>
                        <Field label="Momento">
                          <DraftInput
                            value={scene.time_of_day}
                            onCommit={(time_of_day) =>
                              run(() =>
                                db.updateScriptScene(scene.id, { time_of_day }),
                              )
                            }
                            placeholder="Noche"
                          />
                        </Field>
                      </div>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon">
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={() =>
                              run(() =>
                                db.moveScriptScene(projectId, scene.id, -1),
                              )
                            }
                          >
                            <ArrowUp className="mr-2 size-4" />
                            Mover hacia arriba
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() =>
                              run(() =>
                                db.moveScriptScene(projectId, scene.id, 1),
                              )
                            }
                          >
                            <ArrowDown className="mr-2 size-4" />
                            Mover hacia abajo
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => addLine("action")}>
                            <CopyPlus className="mr-2 size-4" />
                            Añadir acción
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive"
                            onClick={() =>
                              run(() => db.deleteScriptScene(scene.id))
                            }
                          >
                            <Trash2 className="mr-2 size-4" />
                            Eliminar escena
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                  <div className="space-y-2 p-5">
                    {linesByScene.map((line) => {
                      const [label, tone] =
                        lineMeta[line.line_type] || lineMeta.dialogue;
                      const speaker = characters.find(
                        (item) =>
                          String(item.id) === String(line.speaker_element_id),
                      );
                      const referenceCount = data.assetLinks.filter(
                        (link) =>
                          String(link.script_line_id) === String(line.id),
                      ).length;
                      return (
                        <Card
                          key={line.id}
                          className={cn(
                            "cursor-pointer shadow-none transition-colors",
                            String(lineId) === String(line.id) &&
                              "border-foreground/35 ring-1 ring-foreground/10",
                          )}
                          onClick={() => setLineId(line.id)}
                        >
                          <CardContent className="grid grid-cols-[24px_108px_minmax(0,1fr)_74px] gap-3 p-3.5">
                            <GripVertical className="mt-2 size-4 text-muted-foreground/60" />
                            <div>
                              <Badge
                                variant="outline"
                                className={cn("text-[10px]", tone)}
                              >
                                {label}
                              </Badge>
                              <p className="mt-2 truncate text-[11px] font-medium">
                                {speaker?.name ||
                                  (line.line_type === "voiceover"
                                    ? "Narrador"
                                    : "—")}
                              </p>
                            </div>
                            <DraftInput
                              multiline
                              value={line.text}
                              className="min-h-16 resize-none border-0 bg-transparent p-1 text-sm shadow-none focus-visible:ring-1"
                              onCommit={(text) =>
                                run(() =>
                                  db.updateScriptLine(line.id, { text }),
                                )
                              }
                              placeholder="Escribe la línea…"
                            />
                            <div className="pt-1 text-right">
                              <p className="text-xs font-medium">
                                {line.target_duration_ms
                                  ? `${(line.target_duration_ms / 1000).toFixed(1)} s`
                                  : "Auto"}
                              </p>
                              <p className="mt-1 text-[10px] text-muted-foreground">
                                {line.status}
                              </p>
                              {referenceCount > 0 && (
                                <Badge
                                  variant="outline"
                                  className="mt-1 text-[9px]"
                                >
                                  {referenceCount} refs
                                </Badge>
                              )}
                            </div>
                          </CardContent>
                        </Card>
                      );
                    })}
                    {!linesByScene.length && (
                      <EmptyState
                        icon={MessageSquareText}
                        title="Escena vacía"
                        description="Añade diálogo, una acción, voz en off o un rótulo. Cada línea tendrá su propia dirección y timing."
                      />
                    )}
                    <div className="flex flex-wrap gap-2 pt-2">
                      <Button
                        variant="outline"
                        onClick={() => addLine("dialogue")}
                      >
                        <Plus />
                        Diálogo
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => addLine("action")}
                      >
                        <Plus />
                        Acción
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => addLine("voiceover")}
                      >
                        <Plus />
                        Voz en off
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => addLine("caption")}
                      >
                        <Plus />
                        Rótulo
                      </Button>
                    </div>
                  </div>
                </div>
              )
            )}
          </main>

          <aside
            className={cn(
              "relative flex min-h-0 flex-col",
              scriptInspectorVisible
                ? "overflow-hidden border-l bg-muted/10"
                : "overflow-visible",
            )}
          >
            <div
              className={cn(
                "flex shrink-0 items-center",
                scriptInspectorVisible
                  ? "h-14 justify-between border-b px-3"
                  : "absolute right-2 top-2 z-20",
              )}
            >
              {scriptInspectorVisible && (
                <span className="text-xs font-semibold">INSPECTOR</span>
              )}
              <SidebarToggle
                side="right"
                expanded={scriptInspectorVisible}
                onChange={setScriptInspectorVisible}
                label="inspector"
              />
            </div>
            {scriptInspectorVisible && (
              <Tabs
                defaultValue="line"
                className="flex min-h-0 flex-1 flex-col"
              >
                <TabsList className="m-3 mb-0 grid grid-cols-2">
                  <TabsTrigger value="line">Línea</TabsTrigger>
                  <TabsTrigger value="scene">Escena</TabsTrigger>
                </TabsList>
                <TabsContent value="line" className="min-h-0 flex-1">
                  <ScrollArea className="h-full">
                    <div className="p-4">
                      <LineInspector
                        projectId={projectId}
                        line={selectedLine}
                        assets={assets}
                        links={data.assetLinks}
                        characters={characters}
                        voices={data.voices}
                        run={run}
                        onSeedChat={onSeedChat}
                        onDelete={() =>
                          run(() => db.deleteScriptLine(selectedLine.id))
                        }
                        onMoveUp={() =>
                          run(() =>
                            db.moveScriptLine(
                              selectedLine.scene_id,
                              selectedLine.id,
                              -1,
                            ),
                          )
                        }
                        onMoveDown={() =>
                          run(() =>
                            db.moveScriptLine(
                              selectedLine.scene_id,
                              selectedLine.id,
                              1,
                            ),
                          )
                        }
                      />
                    </div>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="scene" className="min-h-0 flex-1">
                  <ScrollArea className="h-full">
                    <div className="p-4">
                      <SceneInspector
                        projectId={projectId}
                        scene={scene}
                        characters={characters}
                        voices={data.voices}
                        assignments={data.characterVoices}
                        assets={assets}
                        links={data.assetLinks}
                        run={run}
                        onSeedChat={onSeedChat}
                      />
                    </div>
                  </ScrollArea>
                </TabsContent>
              </Tabs>
            )}
          </aside>
        </div>
      </div>
    </TooltipProvider>
  );
}

function VoiceLibrary({ projectId, voices, run }) {
  const [name, setName] = useState("");
  const [providerId, setProviderId] = useState("");
  const [open, setOpen] = useState(false);
  const create = async () => {
    if (!name.trim()) return;
    const ok = await run(() =>
      db.createVoiceProfile(projectId, {
        name: name.trim(),
        provider_voice_id: providerId.trim() || null,
        status: providerId.trim() ? "ready" : "draft",
      }),
    );
    if (ok) {
      setName("");
      setProviderId("");
      setOpen(false);
    }
  };
  return (
    <div className="space-y-2">
      {voices.map((voice) => (
        <Card key={voice.id} className="shadow-none">
          <CardContent className="p-3">
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-lg bg-violet-50 text-violet-700">
                <Mic2 className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{voice.name}</p>
                <p className="truncate text-[10px] text-muted-foreground">
                  {voice.provider} · {voice.language} · {voice.status}
                </p>
              </div>
              <Dialog>
                <DialogTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Editar ${voice.name}`}
                  >
                    <Settings2 className="size-4" />
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Perfil de voz</DialogTitle>
                    <DialogDescription>
                      Configuración reutilizable para personajes, narración y
                      nuevas tomas.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid grid-cols-2 gap-4">
                    <Field label="Nombre" className="col-span-2">
                      <DraftInput
                        value={voice.name}
                        onCommit={(name) =>
                          run(() => db.updateVoiceProfile(voice.id, { name }))
                        }
                      />
                    </Field>
                    <Field label="Proveedor">
                      <Select
                        value={voice.provider}
                        onValueChange={(provider) =>
                          run(() =>
                            db.updateVoiceProfile(voice.id, { provider }),
                          )
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="elevenlabs">ElevenLabs</SelectItem>
                          <SelectItem value="openai">OpenAI</SelectItem>
                          <SelectItem value="uploaded">Audio subido</SelectItem>
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="Estado">
                      <Select
                        value={voice.status}
                        onValueChange={(status) =>
                          run(() => db.updateVoiceProfile(voice.id, { status }))
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="draft">Borrador</SelectItem>
                          <SelectItem value="ready">Lista</SelectItem>
                          <SelectItem value="disabled">Desactivada</SelectItem>
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="ID del proveedor" className="col-span-2">
                      <DraftInput
                        value={voice.provider_voice_id || ""}
                        onCommit={(provider_voice_id) =>
                          run(() =>
                            db.updateVoiceProfile(voice.id, {
                              provider_voice_id: provider_voice_id || null,
                            }),
                          )
                        }
                      />
                    </Field>
                    <Field label="Idioma">
                      <DraftInput
                        value={voice.language}
                        onCommit={(language) =>
                          run(() =>
                            db.updateVoiceProfile(voice.id, { language }),
                          )
                        }
                      />
                    </Field>
                    <Field label="Acento">
                      <DraftInput
                        value={voice.accent || ""}
                        onCommit={(accent) =>
                          run(() => db.updateVoiceProfile(voice.id, { accent }))
                        }
                        placeholder="Español neutro"
                      />
                    </Field>
                    <Field
                      label="Descripción interpretativa"
                      className="col-span-2"
                    >
                      <DraftInput
                        multiline
                        className="min-h-24"
                        value={voice.description}
                        onCommit={(description) =>
                          run(() =>
                            db.updateVoiceProfile(voice.id, { description }),
                          )
                        }
                        placeholder="Tono cálido, seguro y contenido…"
                      />
                    </Field>
                  </div>
                  <DialogFooter className="justify-between sm:justify-between">
                    <Button
                      variant="outline"
                      className="text-destructive"
                      onClick={() => run(() => db.deleteVoiceProfile(voice.id))}
                    >
                      <Trash2 />
                      Eliminar voz
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </CardContent>
        </Card>
      ))}
      {!voices.length && (
        <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
          No hay voces configuradas.
        </p>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button variant="outline" className="w-full">
            <Plus />
            Añadir voz
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nueva voz</DialogTitle>
            <DialogDescription>
              Crea un perfil reutilizable. El ID del proveedor puede añadirse
              ahora o más tarde.
            </DialogDescription>
          </DialogHeader>
          <Field label="Nombre">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Narradora principal"
            />
          </Field>
          <Field label="ID de ElevenLabs" hint="opcional">
            <Input
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
              placeholder="voice_id"
            />
          </Field>
          <DialogFooter>
            <Button disabled={!name.trim()} onClick={create}>
              Crear perfil
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SoundComposer({ projectId, scenes, lines, seed, onGenerate, run }) {
  const [prompt, setPrompt] = useState("");
  const [kind, setKind] = useState("sfx");
  const [duration, setDuration] = useState("5");
  const [intensity, setIntensity] = useState("0.5");
  const [loop, setLoop] = useState(false);
  const [sceneId, setSceneId] = useState("__none__");
  const [lineId, setLineId] = useState("__none__");
  const [start, setStart] = useState("0");
  const [templateName, setTemplateName] = useState("");

  useEffect(() => {
    if (!seed) return;
    setPrompt(seed.prompt || "");
    setKind(seed.kind || "sfx");
    setDuration(String((seed.duration_ms || 5000) / 1000));
    setIntensity(String(seed.intensity ?? 0.5));
    setLoop(Boolean(seed.loop));
  }, [seed]);

  const selectedSceneLines = lines.filter(
    (line) =>
      sceneId === "__none__" || String(line.scene_id) === String(sceneId),
  );
  const config = () => ({
    prompt: prompt.trim(),
    kind,
    duration_ms: Math.max(100, Math.round(Number(duration || 0) * 1000)),
    intensity: Math.min(1, Math.max(0, Number(intensity || 0))),
    loop,
    scene_id: sceneId === "__none__" ? null : sceneId,
    script_line_id: lineId === "__none__" ? null : lineId,
    start_ms: Math.max(0, Math.round(Number(start || 0) * 1000)),
  });
  const saveTemplate = async () => {
    if (!templateName.trim() || !prompt.trim()) return;
    const values = config();
    const ok = await run(() =>
      db.createAudioTemplate(projectId, {
        name: templateName.trim(),
        kind: values.kind,
        prompt: values.prompt,
        duration_ms: values.duration_ms,
        loop: values.loop,
        intensity: values.intensity,
      }),
    );
    if (ok) setTemplateName("");
  };

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold">CREAR SONIDO</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Describe el resultado; el modelo determina la interpretación sonora
          concreta.
        </p>
      </div>
      <Field label="Tipo">
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="sfx">Efecto de sonido</SelectItem>
            <SelectItem value="ambience">Ambiente</SelectItem>
            <SelectItem value="music">Música</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Descripción para el modelo">
        <Textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          className="min-h-36 resize-y"
          placeholder="Un dron grave y controlado que crece lentamente, sin melodía, con textura tecnológica limpia…"
        />
      </Field>
      <div className="flex flex-wrap gap-1.5">
        {[
          "Pasos sobre grava",
          "Lluvia sobre cristal",
          "Interfaz holográfica",
        ].map((suggestion) => (
          <Button
            key={suggestion}
            variant="outline"
            size="sm"
            className="h-7 text-[10px]"
            onClick={() => setPrompt(suggestion)}
          >
            {suggestion}
          </Button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Duración" hint="seg">
          <Input
            type="number"
            min="0.1"
            step="0.1"
            value={duration}
            onChange={(event) => setDuration(event.target.value)}
          />
        </Field>
        <Field label="Intensidad" hint="0–1">
          <Input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={intensity}
            onChange={(event) => setIntensity(event.target.value)}
          />
        </Field>
      </div>
      <div className="flex items-center justify-between rounded-lg border p-3">
        <div>
          <p className="text-xs font-medium">Bucle continuo</p>
          <p className="text-[10px] text-muted-foreground">
            Para ambientes y camas
          </p>
        </div>
        <Switch checked={loop} onCheckedChange={setLoop} />
      </div>
      <Separator />
      <div>
        <p className="text-xs font-medium">Contexto y colocación</p>
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          Opcional: el agente usará la escena completa y lo colocará en el
          segundo indicado.
        </p>
      </div>
      <Field label="Escena">
        <Select
          value={sceneId}
          onValueChange={(value) => {
            setSceneId(value);
            setLineId("__none__");
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Todo el proyecto</SelectItem>
            {scenes.map((scene, index) => (
              <SelectItem key={scene.id} value={String(scene.id)}>
                {index + 1}. {scene.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Línea del guion">
        <Select value={lineId} onValueChange={setLineId}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Contexto general de escena</SelectItem>
            {selectedSceneLines.map((line) => (
              <SelectItem key={line.id} value={String(line.id)}>
                {line.text.slice(0, 48) || line.line_type}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Empieza en" hint="segundos">
        <Input
          type="number"
          min="0"
          step="0.1"
          value={start}
          onChange={(event) => setStart(event.target.value)}
        />
      </Field>
      <Button
        className="w-full"
        disabled={!prompt.trim()}
        onClick={() => onGenerate(config())}
      >
        <Zap />
        Generar y guardar en Assets
      </Button>
      <div className="rounded-lg border bg-muted/10 p-3">
        <p className="text-xs font-medium">Guardar como plantilla</p>
        <div className="mt-2 flex gap-2">
          <Input
            value={templateName}
            onChange={(event) => setTemplateName(event.target.value)}
            placeholder="Nombre de plantilla"
          />
          <Button
            variant="outline"
            size="icon"
            disabled={!templateName.trim() || !prompt.trim()}
            onClick={saveTemplate}
          >
            <Bookmark className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function SoundTemplates({ templates, onUse, run }) {
  const all = [...builtInSoundTemplates, ...templates];
  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-semibold">PLANTILLAS</p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Puntos de partida editables, no resultados cerrados.
        </p>
      </div>
      {all.map((template) => (
        <Card key={template.id} className="shadow-none">
          <CardContent className="p-3">
            <div className="flex items-start gap-2">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                <Waves className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium">{template.name}</p>
                <p className="mt-0.5 line-clamp-2 text-[10px] leading-relaxed text-muted-foreground">
                  {template.prompt}
                </p>
              </div>
              {!builtInSoundTemplates.some(
                (item) => item.id === template.id,
              ) && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => run(() => db.deleteAudioTemplate(template.id))}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Badge variant="outline" className="text-[10px]">
                {template.kind}
              </Badge>
              <span className="text-[10px] text-muted-foreground">
                {template.duration_ms
                  ? `${template.duration_ms / 1000}s`
                  : "Auto"}
              </span>
              <Button
                variant="outline"
                size="sm"
                className="ml-auto h-7 text-[10px]"
                onClick={() => onUse(template)}
              >
                Usar plantilla
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function CueInspector({ cue, assets, scenes, lines, run }) {
  if (!cue)
    return (
      <EmptyState
        icon={AudioLines}
        title="Selecciona un clip"
        description="Edita aquí su posición, mezcla, fades, ducking y función narrativa."
      />
    );
  const asset = assets.find((item) => String(item.id) === String(cue.asset_id));
  const update = (patch) => run(() => db.updateAudioCue(cue.id, patch));
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <span className="flex size-9 items-center justify-center rounded-lg border bg-background">
          <FileAudio className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">
            {asset?.name || "Audio"}
          </p>
          <p className="text-[11px] text-muted-foreground">
            {trackMeta[cue.track_kind]?.[1] || cue.track_kind}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => run(() => db.deleteAudioCue(cue.id))}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
      <Field label="Pista">
        <Select
          value={cue.track_kind}
          onValueChange={(track_kind) => update({ track_kind })}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(trackMeta).map(([value, [, label]]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Inicio" hint="ms">
          <DraftInput
            number
            min="0"
            value={cue.start_ms}
            onCommit={(start_ms) =>
              update({ start_ms: Math.min(start_ms, cue.end_ms - 1) })
            }
          />
        </Field>
        <Field label="Final" hint="ms">
          <DraftInput
            number
            min="1"
            value={cue.end_ms}
            onCommit={(end_ms) =>
              update({ end_ms: Math.max(end_ms, cue.start_ms + 1) })
            }
          />
        </Field>
        <Field label="Entrada fuente" hint="ms">
          <DraftInput
            number
            min="0"
            value={cue.source_in_ms}
            onCommit={(source_in_ms) => update({ source_in_ms })}
          />
        </Field>
        <Field label="Salida fuente" hint="ms">
          <DraftInput
            number
            nullable
            min="1"
            value={cue.source_out_ms ?? ""}
            onCommit={(source_out_ms) => update({ source_out_ms })}
          />
        </Field>
      </div>
      <Separator />
      <div className="grid grid-cols-2 gap-3">
        <Field label="Ganancia" hint="dB">
          <DraftInput
            number
            step="0.5"
            value={cue.gain_db}
            onCommit={(gain_db) => update({ gain_db })}
          />
        </Field>
        <Field label="Paneo" hint="-1 a 1">
          <DraftInput
            number
            min="-1"
            max="1"
            step="0.1"
            value={cue.pan}
            onCommit={(pan) => update({ pan })}
          />
        </Field>
        <Field label="Fade in" hint="ms">
          <DraftInput
            number
            min="0"
            step="50"
            value={cue.fade_in_ms}
            onCommit={(fade_in_ms) => update({ fade_in_ms })}
          />
        </Field>
        <Field label="Fade out" hint="ms">
          <DraftInput
            number
            min="0"
            step="50"
            value={cue.fade_out_ms}
            onCommit={(fade_out_ms) => update({ fade_out_ms })}
          />
        </Field>
      </div>
      <Field label="Función narrativa">
        <DraftInput
          multiline
          className="min-h-20"
          value={cue.narrative_role}
          onCommit={(narrative_role) => update({ narrative_role })}
          placeholder="Sostiene la tensión antes del reveal…"
        />
      </Field>
      <Field label="Línea del guion">
        <Select
          value={cue.script_line_id || "__none__"}
          onValueChange={(script_line_id) =>
            update({
              script_line_id:
                script_line_id === "__none__" ? null : script_line_id,
            })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Sin vínculo</SelectItem>
            {scenes.flatMap((scene, sceneIndex) =>
              lines
                .filter((line) => String(line.scene_id) === String(scene.id))
                .map((line) => (
                  <SelectItem key={line.id} value={String(line.id)}>
                    {sceneIndex + 1}. {line.text.slice(0, 45) || line.line_type}
                  </SelectItem>
                )),
            )}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Etiquetas de contexto" hint="separadas por comas">
        <DraftInput
          value={(cue.context_tags || []).join(", ")}
          onCommit={(value) =>
            update({
              context_tags: value
                .split(",")
                .map((tag) => tag.trim())
                .filter(Boolean),
            })
          }
          placeholder="tecnología, tensión, reveal"
        />
      </Field>
      <div className="rounded-lg border bg-background">
        <div className="flex items-center justify-between p-3">
          <div>
            <p className="text-xs font-medium">Repetir clip</p>
            <p className="text-[10px] text-muted-foreground">
              Loop hasta el final del cue
            </p>
          </div>
          <Switch
            checked={Boolean(cue.loop)}
            onCheckedChange={(loop) => update({ loop })}
          />
        </div>
        <Separator />
        <div className="flex items-center justify-between p-3">
          <div>
            <p className="text-xs font-medium">Bloquear posición</p>
            <p className="text-[10px] text-muted-foreground">
              El agente no podrá moverlo
            </p>
          </div>
          <Switch
            checked={Boolean(cue.locked)}
            onCheckedChange={(locked) => update({ locked })}
          />
        </div>
        <Separator />
        <div className="flex items-center justify-between p-3">
          <div>
            <p className="text-xs font-medium">Aprobado</p>
            <p className="text-[10px] text-muted-foreground">
              Listo para el render final
            </p>
          </div>
          <Switch
            checked={Boolean(cue.approved)}
            onCheckedChange={(approved) => update({ approved })}
          />
        </div>
      </div>
      <Field label="Grupo de ducking">
        <DraftInput
          value={cue.ducking_group || ""}
          onCommit={(ducking_group) =>
            update({ ducking_group: ducking_group || null })
          }
          placeholder="dialogue"
        />
      </Field>
      <Field label="Reducción al hablar" hint="dB">
        <DraftInput
          number
          nullable
          step="0.5"
          value={cue.ducking_db ?? ""}
          onCommit={(ducking_db) => update({ ducking_db })}
        />
      </Field>
    </div>
  );
}

export function AudioStudio({ projectId, assets = [], onSeedChat }) {
  const { data, loading, saving, error, reload, run } =
    useProduction(projectId);
  const [cueId, setCueId] = useState(null);
  const [brief, setBrief] = useState("");
  const [briefOpen, setBriefOpen] = useState(false);
  const [libraryTab, setLibraryTab] = useState("library");
  const [composerSeed, setComposerSeed] = useState(null);
  const [audioLibraryVisible, setAudioLibraryVisible] = useStoredVisibility(
    "xframe.audio.library-panel",
  );
  const [audioInspectorVisible, setAudioInspectorVisible] = useStoredVisibility(
    "xframe.audio.inspector",
  );
  const audioAssets = useMemo(
    () =>
      assets.filter(
        (asset) =>
          /audio/i.test(String(asset.type)) && asset.status === "ready",
      ),
    [assets],
  );
  const totalMs = Math.max(10000, ...data.cues.map((cue) => cue.end_ms || 0));
  const cue =
    data.cues.find((item) => String(item.id) === String(cueId)) || null;
  const approved = data.cues.filter((item) => item.approved).length;

  useEffect(() => {
    if (cueId && !data.cues.some((item) => String(item.id) === String(cueId)))
      setCueId(null);
  }, [data.cues, cueId]);
  const addCue = async (asset, track_kind = "music") => {
    const lastEnd = Math.max(
      0,
      ...data.cues
        .filter((item) => item.track_kind === track_kind)
        .map((item) => item.end_ms || 0),
    );
    let created;
    const ok = await run(async () => {
      created = await db.createAudioCue(projectId, {
        asset_id: asset.id,
        track_kind,
        start_ms: lastEnd,
        end_ms: lastEnd + 5000,
      });
    });
    if (ok && created) setCueId(created.id);
  };
  const designAudio = () => {
    if (!brief.trim()) return;
    onSeedChat?.(
      `Diseña el audio del proyecto a partir de este brief: ${brief.trim()}\nUsa el guion estructurado para cualquier voz. Elige entre los assets existentes, define secciones, intensidad, entradas, salidas, ducking bajo diálogo y transiciones. Primero explica el plan y estima créditos; genera solo con mi aprobación.`,
    );
    setBrief("");
    setBriefOpen(false);
  };
  const generateSound = (config) => {
    const scene = data.scenes.find(
      (item) => String(item.id) === String(config.scene_id),
    );
    const line = data.lines.find(
      (item) => String(item.id) === String(config.script_line_id),
    );
    const endMs = config.start_ms + config.duration_ms;
    onSeedChat?.(
      `Genera un asset de audio reutilizable con generate_audio y guárdalo en Assets.\n` +
        `Tipo: ${config.kind}. Descripción aprobada: ${config.prompt}\n` +
        `Duración: ${config.duration_ms / 1000}s. Intensidad creativa: ${config.intensity}. Loop: ${config.loop}.\n` +
        (scene
          ? `Contexto obligatorio: escena ${scene.id} (“${scene.title}”), usando su guion completo y sus assets vinculados.\n`
          : "") +
        (line
          ? `Línea contextual exacta: ${line.id} — “${line.text}”. No cambies sus palabras.\n`
          : "") +
        `Colócalo automáticamente en el plan de audio desde ${config.start_ms} ms hasta ${endMs} ms usando placement_start_ms y placement_end_ms. ` +
        `No me pidas elegir una voz concreta: para sonidos, música y ambientes la interpretación final corresponde al modelo. ` +
        `Estima los créditos antes de encolar la generación.`,
    );
  };
  const useTemplate = (template) => {
    setComposerSeed({ ...template, selectedAt: Date.now() });
    setLibraryTab("create");
  };

  return (
    <TooltipProvider>
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-background">
        <header className="flex h-16 shrink-0 items-center gap-4 border-b px-4">
          <div>
            <h2 className="text-sm font-semibold">Diseño de audio</h2>
            <p className="text-xs text-muted-foreground">
              Biblioteca, voces y mezcla multipista determinista.
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <Badge variant="outline">
              {data.cues.length} clips · {approved} aprobados ·{" "}
              {(totalMs / 1000).toFixed(1)} s
            </Badge>
            <SaveState saving={saving} error={error} />
            <Dialog open={briefOpen} onOpenChange={setBriefOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Sparkles />
                  Diseñar con el agente
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Dirección de audio</DialogTitle>
                  <DialogDescription>
                    Describe el arco musical, silencios, intensidad y
                    referencias. El agente trabajará sobre el guion y tu
                    biblioteca.
                  </DialogDescription>
                </DialogHeader>
                <AgentBrief
                  title="Brief sonoro"
                  description="Puedes pedir una o varias piezas según el contexto de cada escena."
                  placeholder="Inicio mínimo y sobrio; tensión gradual durante la demo; silencio de 400 ms antes del claim; cierre cálido…"
                  value={brief}
                  setValue={setBrief}
                  onSubmit={designAudio}
                  submitLabel="Llevar al chat"
                />
              </DialogContent>
            </Dialog>
            <Button variant="outline" size="icon" onClick={() => reload()}>
              <RefreshCw className={cn("size-4", loading && "animate-spin")} />
            </Button>
          </div>
        </header>
        <div
          className="grid min-h-0 flex-1"
          style={{
            gridTemplateColumns: `${audioLibraryVisible ? "300px" : "0px"} minmax(500px, 1fr) ${audioInspectorVisible ? "310px" : "0px"}`,
          }}
        >
          <aside
            className={cn(
              "relative flex min-h-0 flex-col",
              audioLibraryVisible
                ? "overflow-hidden border-r bg-muted/10"
                : "overflow-visible",
            )}
          >
            <div
              className={cn(
                "flex shrink-0 items-center",
                audioLibraryVisible
                  ? "h-14 justify-between border-b px-3"
                  : "absolute left-2 top-2 z-20",
              )}
            >
              {audioLibraryVisible && (
                <span className="text-xs font-semibold">SONIDO</span>
              )}
              <SidebarToggle
                side="left"
                expanded={audioLibraryVisible}
                onChange={setAudioLibraryVisible}
                label="biblioteca de sonido"
              />
            </div>
            {audioLibraryVisible && (
              <Tabs
                value={libraryTab}
                onValueChange={setLibraryTab}
                className="flex min-h-0 flex-1 flex-col"
              >
                <TabsList className="m-3 mb-0 grid h-auto grid-cols-2">
                  <TabsTrigger value="library">Biblioteca</TabsTrigger>
                  <TabsTrigger value="create">Crear</TabsTrigger>
                  <TabsTrigger value="templates">Plantillas</TabsTrigger>
                  <TabsTrigger value="voices">Voces</TabsTrigger>
                </TabsList>
                <TabsContent value="library" className="min-h-0 flex-1">
                  <ScrollArea className="h-full">
                    <div className="space-y-2 p-3">
                      {audioAssets.map((asset) => (
                        <Card key={asset.id} className="shadow-none">
                          <CardContent className="p-3">
                            <div className="flex items-center gap-2">
                              <FileAudio className="size-4 text-muted-foreground" />
                              <div className="min-w-0 flex-1">
                                <p className="truncate text-xs font-medium">
                                  {asset.name}
                                </p>
                                <p className="text-[10px] text-muted-foreground">
                                  Listo para usar
                                </p>
                              </div>
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button variant="ghost" size="icon">
                                    <Plus className="size-4" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  {Object.entries(trackMeta).map(
                                    ([kind, [, label]]) => (
                                      <DropdownMenuItem
                                        key={kind}
                                        onClick={() => addCue(asset, kind)}
                                      >
                                        Añadir a {label.toLowerCase()}
                                      </DropdownMenuItem>
                                    ),
                                  )}
                                  <DropdownMenuItem
                                    onClick={() =>
                                      onSeedChat?.(
                                        `Edita o crea una variación del asset de audio @${asset.name} (id ${asset.id}). Conserva su función narrativa y pregúntame qué propiedad sonora quiero cambiar antes de generar. Guarda el resultado como un asset nuevo y mantén el linaje.`,
                                      )
                                    }
                                  >
                                    <WandSparkles className="mr-2 size-4" />
                                    Editar o variar
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                            {asset.url && (
                              <audio
                                src={asset.url}
                                controls
                                className="mt-2 h-8 w-full"
                              />
                            )}
                          </CardContent>
                        </Card>
                      ))}
                      {!audioAssets.length && (
                        <EmptyState
                          icon={FileAudio}
                          title="Biblioteca vacía"
                          description="Genera o sube voces, música y efectos desde Assets. Cuando estén listos aparecerán aquí."
                        />
                      )}
                    </div>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="create" className="min-h-0 flex-1">
                  <ScrollArea className="h-full">
                    <div className="p-3">
                      <SoundComposer
                        projectId={projectId}
                        scenes={data.scenes}
                        lines={data.lines}
                        seed={composerSeed}
                        onGenerate={generateSound}
                        run={run}
                      />
                    </div>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="templates" className="min-h-0 flex-1">
                  <ScrollArea className="h-full">
                    <div className="p-3">
                      <SoundTemplates
                        templates={data.audioTemplates}
                        onUse={useTemplate}
                        run={run}
                      />
                    </div>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="voices" className="min-h-0 flex-1">
                  <ScrollArea className="h-full">
                    <div className="p-3">
                      <VoiceLibrary
                        projectId={projectId}
                        voices={data.voices}
                        run={run}
                      />
                    </div>
                  </ScrollArea>
                </TabsContent>
              </Tabs>
            )}
          </aside>

          <main
            className={cn(
              "min-h-0 overflow-auto p-5",
              !audioLibraryVisible && "pl-14",
              !audioInspectorVisible && "pr-14",
            )}
          >
            <div className="min-w-[660px]">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold">Timeline de mezcla</h3>
                  <p className="text-xs text-muted-foreground">
                    Selecciona un clip para ajustar sus parámetros exactos.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="icon" disabled>
                    <Play className="size-4" />
                  </Button>
                  <Button variant="outline" size="icon" disabled>
                    <Pause className="size-4" />
                  </Button>
                </div>
              </div>
              <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2">
                <div />
                <div className="grid grid-cols-5 px-2 text-[10px] text-muted-foreground">
                  {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
                    <span
                      key={ratio}
                      className={cn(ratio === 1 && "text-right")}
                    >
                      {((totalMs * ratio) / 1000).toFixed(1)}s
                    </span>
                  ))}
                </div>
              </div>
              <div className="mt-1 space-y-2">
                {Object.entries(trackMeta).map(
                  ([kind, [Icon, label, color]]) => {
                    const cues = data.cues.filter(
                      (item) => item.track_kind === kind,
                    );
                    return (
                      <div
                        key={kind}
                        className="grid grid-cols-[112px_minmax(0,1fr)] gap-2"
                      >
                        <div className="flex h-16 items-center gap-2 rounded-lg border bg-background px-3">
                          <Icon className="size-4 text-muted-foreground" />
                          <div>
                            <p className="text-xs font-medium">{label}</p>
                            <p className="text-[10px] text-muted-foreground">
                              {cues.length} clips
                            </p>
                          </div>
                        </div>
                        <div className="relative h-16 overflow-hidden rounded-lg border bg-muted/15">
                          <div className="absolute inset-0 grid grid-cols-4 divide-x divide-dashed">
                            {[0, 1, 2, 3].map((i) => (
                              <span key={i} />
                            ))}
                          </div>
                          {cues.map((item) => {
                            const source = assets.find(
                              (asset) =>
                                String(asset.id) === String(item.asset_id),
                            );
                            return (
                              <Button
                                key={item.id}
                                variant="default"
                                className={cn(
                                  "absolute top-2 h-11 min-w-12 justify-start overflow-hidden rounded-md px-2 text-left shadow-sm",
                                  color,
                                  String(cueId) === String(item.id) &&
                                    "ring-2 ring-foreground ring-offset-2",
                                )}
                                style={{
                                  left: `${Math.min(97, (item.start_ms / totalMs) * 100)}%`,
                                  width: `${Math.max(4, Math.min(100 - (item.start_ms / totalMs) * 100, ((item.end_ms - item.start_ms) / totalMs) * 100))}%`,
                                }}
                                onClick={() => setCueId(item.id)}
                              >
                                <span className="min-w-0">
                                  <span className="block truncate text-[10px] font-medium">
                                    {source?.name || label}
                                  </span>
                                  <span className="block truncate text-[9px] opacity-75">
                                    {item.gain_db ?? 0} dB
                                    {item.locked ? " · locked" : ""}
                                  </span>
                                </span>
                              </Button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  },
                )}
              </div>
              {!data.cues.length && (
                <div className="mt-5">
                  <EmptyState
                    icon={Music2}
                    title="La mezcla aún está vacía"
                    description="Añade audio desde la biblioteca o pide al agente que proponga un plan contextual a partir del guion."
                    action={
                      <Button onClick={() => setBriefOpen(true)}>
                        <Sparkles />
                        Diseñar plan
                      </Button>
                    }
                  />
                </div>
              )}
              <Card className="mt-5 shadow-none">
                <CardContent className="flex items-center gap-3 p-4">
                  <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
                    <Lock className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">Mezcla reproducible</p>
                    <p className="text-[11px] text-muted-foreground">
                      Los tiempos, fades, ganancias, paneo y ducking se guardan
                      como parámetros exactos para FFmpeg.
                    </p>
                  </div>
                  <Badge variant="outline">−14 LUFS</Badge>
                </CardContent>
              </Card>
            </div>
          </main>

          <aside
            className={cn(
              "relative flex min-h-0 flex-col",
              audioInspectorVisible
                ? "overflow-hidden border-l bg-muted/10"
                : "overflow-visible",
            )}
          >
            <div
              className={cn(
                "flex shrink-0 items-center",
                audioInspectorVisible
                  ? "h-14 justify-between border-b px-3"
                  : "absolute right-2 top-2 z-20",
              )}
            >
              {audioInspectorVisible && (
                <span className="text-xs font-semibold">INSPECTOR</span>
              )}
              <SidebarToggle
                side="right"
                expanded={audioInspectorVisible}
                onChange={setAudioInspectorVisible}
                label="inspector de mezcla"
              />
            </div>
            {audioInspectorVisible && (
              <ScrollArea className="min-h-0 flex-1">
                <div className="p-4">
                  <CueInspector
                    cue={cue}
                    assets={assets}
                    scenes={data.scenes}
                    lines={data.lines}
                    run={run}
                  />
                </div>
              </ScrollArea>
            )}
          </aside>
        </div>
      </div>
    </TooltipProvider>
  );
}
