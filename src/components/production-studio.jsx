import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  AudioLines,
  Bookmark,
  BookOpen,
  Briefcase,
  Building2,
  Check,
  ChevronLeft,
  Clapperboard,
  CloudLightning,
  Cpu,
  Crosshair,
  Flame,
  GraduationCap,
  Leaf,
  MessageCircle,
  MousePointerClick,
  PawPrint,
  Rocket,
  Satellite,
  ShoppingBag,
  Smartphone,
  TrendingUp,
  Trophy,
  ChevronRight,
  CopyPlus,
  FileAudio,
  GripVertical,
  LoaderCircle,
  Lock,
  ListFilter,
  MessageSquareText,
  Mic2,
  Minus,
  MoreHorizontal,
  MoreVertical,
  Music2,
  Pause,
  SkipBack,
  SkipForward,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Settings2,
  Trash2,
  Type,
  UserRound,
  Volume2,
  WandSparkles,
  Waves,
  X,
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
  DropdownMenuLabel,
  DropdownMenuSeparator,
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
import { Skeleton } from "@/components/ui/skeleton";
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
import { agentApi } from "@/lib/agent";
import {
  gradientUrl,
  SFX_CATEGORIES,
  SFX_LIBRARY,
  VOICE_CATALOG,
  VOICE_CATEGORIES,
} from "@/lib/soundLibrary";

const EMPTY = {
  scenes: [],
  lines: [],
  sceneShots: [],
  shots: [],
  voices: [],
  characterVoices: [],
  cues: [],
  annotations: [],
  operations: [],
  transitions: [],
  assetLinks: [],
  audioTemplates: [],
  resourceBindings: [],
  productionManifests: [],
  qualityReports: [],
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

const systemSoundTemplates = builtInSoundTemplates.map((template) => ({
  ...template,
  builtIn: true,
}));

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
// Color por pista para los bloques del reproductor de la mezcla (mismo lenguaje que el
// del guion: cada tipo su color).
const TRACK_HEX = {
  dialogue: "#2563eb",
  voiceover: "#7c3aed",
  music: "#059669",
  sfx: "#d97706",
  ambience: "#0891b2",
  native: "#475569",
};

function useProduction(projectId, onChange, externalData = null) {
  const [data, setData] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const reload = async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const next = await db.getProduction(projectId);
      setData(next);
      onChange?.(next);
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
  useEffect(() => {
    if (!externalData || !Array.isArray(externalData.scenes)) return;
    setData(externalData);
    setLoading(false);
    setError("");
  }, [externalData]);
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
      // Las "esquinas" tenues que salen al escribir las pinta el corrector/predictor del
      // navegador (MS Editor en Edge). Se desactivan sus ganchos y el resize del textarea.
      spellCheck={false}
      autoCorrect="off"
      autoComplete="off"
      data-gramm="false"
      {...props}
      className={cn(multiline && "resize-none", props.className)}
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
          variant="outline"
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

function ProductionListSkeleton({ rows = 4 }) {
  return (
    <div className="space-y-2 p-3" aria-busy="true" aria-label="Cargando contenido">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-2.5 rounded-md p-2.5">
          <Skeleton className="size-7" />
          <div className="min-w-0 flex-1 space-y-1.5"><Skeleton className="h-3 w-3/4" /><Skeleton className="h-2.5 w-1/2" /></div>
        </div>
      ))}
    </div>
  );
}

function ScreenplayWorkspaceSkeleton() {
  return (
    <div className="space-y-5 p-5" aria-busy="true" aria-label="Cargando guion">
      <div className="grid grid-cols-3 gap-3"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
      {[0, 1, 2, 3].map((item) => <Card key={item} className="p-4"><Skeleton className="h-4 w-32" /><Skeleton className="mt-3 h-3 w-full" /><Skeleton className="mt-2 h-3 w-4/5" /></Card>)}
    </div>
  );
}

function AudioWorkspaceSkeleton() {
  return (
    <div className="min-w-[660px] space-y-4" aria-busy="true" aria-label="Cargando mezcla de audio">
      <div className="flex items-center justify-between"><div className="space-y-2"><Skeleton className="h-4 w-36" /><Skeleton className="h-3 w-64" /></div><div className="flex gap-2"><Skeleton className="size-9" /><Skeleton className="size-9" /></div></div>
      <Skeleton className="h-3 w-full" />
      {[0, 1, 2, 3, 4, 5].map((item) => <div key={item} className="grid grid-cols-[112px_minmax(0,1fr)] gap-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>)}
      <Skeleton className="h-24 w-full" />
    </div>
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
    if (scoped.some((link) => String(link.asset_id) === String(asset.id))) {
      setOpen(false);
      return;
    }
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

// Solo los Elements con rol de Personaje pueden hablar y llevar voz; una localización o
// un objeto no.
function isPersonajeRole(role) {
  return /personaje|character/i.test(String(role || ""));
}

// Fila de ajuste compacta: etiqueta a la izquierda, control a la derecha. Da el aire de
// hoja de ajustes visual (como la de generación) en vez de un formulario plano.
function MetaRow({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b py-2.5 last:border-b-0">
      <span className="shrink-0 text-xs font-medium text-muted-foreground">
        {label}
      </span>
      <div className="min-w-0 flex-1 text-right">{children}</div>
    </div>
  );
}

// Grupo de pastillas seleccionables (estado, tipo…): un clic, sin desplegable.
function SegPills({ value, options, onChange }) {
  return (
    <div className="flex rounded-lg border bg-muted/40 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "flex-1 rounded-md px-2 py-1 text-[11px] font-semibold transition-colors",
            String(value) === String(option.value)
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// Deslizable segmentado por pasos, con puntos y un pomo en el paso activo. Igual que los
// controles de aspecto/resolución/duración de la hoja de generación.
function SegSlider({ label, value, options, onChange, formatValue }) {
  const index = Math.max(
    0,
    options.findIndex((option) => String(option.value) === String(value)),
  );
  const active = options[index] || options[0];
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">{label}</span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {formatValue ? formatValue(active) : active?.label}
        </span>
      </div>
      <div className="relative mt-2 flex items-center">
        {options.map((option, i) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            aria-label={option.label}
            className="group relative flex-1 py-2.5"
          >
            <span
              className={cn(
                "absolute top-1/2 h-1 -translate-y-1/2",
                i === 0 ? "left-1/2" : "left-0",
                i === options.length - 1 ? "right-1/2" : "right-0",
                i <= index ? "bg-foreground/70" : "bg-muted",
              )}
            />
            <span
              className={cn(
                "relative mx-auto block size-1.5 rounded-full",
                i < index ? "bg-foreground/70" : "bg-muted-foreground/40",
              )}
            />
            {i === index && (
              <span className="absolute left-1/2 top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-foreground bg-background" />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

const SCENE_DURATION_STEPS = [2, 4, 6, 8, 10, 12, 15].map((seconds) => ({
  value: seconds * 1000,
  label: `${seconds}s`,
}));

function SceneInspector({
  projectId,
  scene,
  characters,
  voices,
  assignments,
  assets,
  links,
  manifests,
  sceneShots,
  shots,
  run,
  onSeedChat,
  onSendAgent,
}) {
  if (!scene) return null;
  const manifest = [...(manifests || [])]
    .filter((item) => String(item.scene_id) === String(scene.id))
    .sort((a, b) => Number(b.version || 0) - Number(a.version || 0))[0];
  const manifestErrors = manifest?.validation?.errors || [];
  const manifestWarnings = manifest?.validation?.warnings || [];
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
          Título de la escena
        </label>
        <DraftInput
          className="text-base font-semibold"
          value={scene.title}
          onCommit={(title) =>
            run(() => db.updateScriptScene(scene.id, { title }))
          }
          placeholder="Nueva escena"
        />
      </div>

      <div className="rounded-xl border bg-muted/10 px-3">
        <MetaRow label="Localización">
          <DraftInput
            className="border-0 bg-transparent p-0 text-right text-xs shadow-none focus-visible:ring-0"
            value={scene.setting}
            onCommit={(setting) =>
              run(() => db.updateScriptScene(scene.id, { setting }))
            }
            placeholder="Estudio"
          />
        </MetaRow>
        <MetaRow label="Momento">
          <DraftInput
            className="border-0 bg-transparent p-0 text-right text-xs shadow-none focus-visible:ring-0"
            value={scene.time_of_day}
            onCommit={(time_of_day) =>
              run(() => db.updateScriptScene(scene.id, { time_of_day }))
            }
            placeholder="Noche"
          />
        </MetaRow>
        <MetaRow label="Inicio en el proyecto">
          <DraftInput
            number
            min="0"
            step="0.1"
            className="border-0 bg-transparent p-0 text-right text-xs tabular-nums shadow-none focus-visible:ring-0"
            value={(scene.timeline_start_ms || 0) / 1000}
            onCommit={(seconds) =>
              run(() =>
                db.updateScriptScene(scene.id, {
                  timeline_start_ms: Math.max(
                    0,
                    Math.round((seconds || 0) * 1000),
                  ),
                }),
              )
            }
          />
        </MetaRow>
      </div>

      <div className="space-y-2">
        <span className="text-xs font-medium">Estado</span>
        <SegPills
          value={scene.status || "draft"}
          onChange={(status) =>
            run(() => db.updateScriptScene(scene.id, { status }))
          }
          options={[
            { value: "draft", label: "Borrador" },
            { value: "approved", label: "Aprobada" },
            { value: "locked", label: "Bloqueada" },
          ]}
        />
      </div>

      <SegSlider
        label="Duración objetivo"
        value={scene.target_duration_ms}
        options={SCENE_DURATION_STEPS}
        onChange={(target_duration_ms) =>
          run(() => db.updateScriptScene(scene.id, { target_duration_ms }))
        }
      />

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
      <div className="space-y-2">
        <div>
          <p className="text-xs font-medium">Planos de la escena</p>
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            El agente, el manifiesto y el render usarán exactamente estos planos
            y este orden.
          </p>
        </div>
        <div className="space-y-1.5">
          {(shots || []).map((shot, index) => {
            const link = (sceneShots || []).find(
              (item) => String(item.shot_id) === String(shot.id),
            );
            const selected = String(link?.scene_id) === String(scene.id);
            return (
              <Button
                key={shot.id}
                type="button"
                variant={selected ? "secondary" : "outline"}
                size="sm"
                className="h-auto w-full justify-start py-2 text-left"
                onClick={() =>
                  run(() =>
                    selected
                      ? db.removeShotFromScene(projectId, scene.id, shot.id)
                      : db.assignShotToScene(projectId, scene.id, shot.id),
                  )
                }
              >
                {selected ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
                <span className="min-w-0 flex-1 truncate text-xs">
                  {shot.title || `Plano ${index + 1}`}
                </span>
                {link && !selected && (
                  <Badge variant="outline" className="text-[9px]">
                    reasignar
                  </Badge>
                )}
              </Button>
            );
          })}
          {!shots?.length && (
            <p className="rounded-md border border-dashed p-2 text-[10px] text-muted-foreground">
              Crea planos en el canvas para poder asignarlos a esta escena.
            </p>
          )}
        </div>
      </div>
      <Separator />
      <AssetReferences
        projectId={projectId}
        sceneId={scene.id}
        assets={assets}
        links={links}
        run={run}
      />
      <Card className="shadow-none">
        <CardContent className="space-y-2 p-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-xs font-medium">Manifiesto de producción</p>
              <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
                Congela guion, planos, recursos, voces, audio y entrega antes de renderizar.
              </p>
            </div>
            {manifest && (
              <Badge
                variant={manifest.status === "invalid" ? "destructive" : "outline"}
                className="shrink-0 text-[10px]"
              >
                v{manifest.version} · {manifest.status}
              </Badge>
            )}
          </div>
          {manifest ? (
            <div className="space-y-1 rounded-md border bg-muted/20 p-2 text-[10px]">
              <p>{manifestErrors.length} errores · {manifestWarnings.length} avisos</p>
              {manifestErrors.slice(0, 3).map((issue, index) => (
                <p key={`${issue.code}-${index}`} className="text-destructive">
                  {issue.code}{issue.shot_id ? ` · ${issue.shot_id}` : ""}
                </p>
              ))}
              <p className="truncate text-muted-foreground" title={manifest.fingerprint}>
                Huella: {manifest.fingerprint}
              </p>
            </div>
          ) : (
            <p className="rounded-md border border-dashed p-2 text-[10px] text-muted-foreground">
              Aún no existe una especificación ejecutable para esta escena.
            </p>
          )}
          <div className="grid grid-cols-1 gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                (onSendAgent || onSeedChat)?.(
                  `Construye un manifiesto de producción completo para la escena ${scene.id}. Identifica sus planos del canvas, valida guion, recursos @ bloqueados, voces, cues, continuidad y entrega. No generes todavía; muéstrame errores, avisos, coste y la versión para revisarla.`,
                )
              }
            >
              <Settings2 />
              {manifest ? "Crear nueva versión" : "Construir manifiesto"}
            </Button>
            {manifest?.status === "validated" && (
              <Button
                size="sm"
                onClick={() =>
                  (onSendAgent || onSeedChat)?.(
                    `Apruebo explícitamente el manifiesto ${manifest.id}, versión ${manifest.version}, para la escena ${scene.id}. Registra esta aprobación, conserva su huella ${manifest.fingerprint} y no cambies la especificación.`,
                  )
                }
              >
                <Check />
                Aprobar esta versión
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
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
              (onSendAgent || onSeedChat)?.(
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

// Color de cada categoría de etiqueta, alineado con las @menciones del chat.
const ASSET_PILL_HEX = {
  video: "#7c3aed",
  image: "#0284c7",
  audio: "#c026d3",
  character: "#d97706",
  background: "#059669",
  object: "#e11d48",
  other: "#64748b",
};
const SCENE_TAG_HEX = "#6366f1";

function assetTagCategory(asset) {
  const type = String(asset?.type || "").toLowerCase();
  const role = String(asset?.role || "").toLowerCase();
  if (/personaje|character/.test(role)) return "character";
  if (/localiz|fondo|background|location/.test(role)) return "background";
  if (/objeto|producto|object|product/.test(role)) return "object";
  if (/audio|sound|sonido|music|música|voz/.test(type)) return "audio";
  if (/video|cut|clip|vídeo/.test(type)) return "video";
  return "image";
}

// Etiqueta de una línea como pill de color, con el mismo lenguaje visual que las
// @menciones del chat: punto de color + texto y una X opcional para quitarla.
function TagPill({ hex, label, onRemove }) {
  return (
    <span
      className="inline-flex max-w-full items-center gap-1.5 rounded-full py-0.5 pl-2 pr-1 text-[11px] font-medium"
      style={{
        color: hex,
        backgroundColor: `color-mix(in srgb, ${hex} 13%, transparent)`,
        border: `1px solid color-mix(in srgb, ${hex} 26%, transparent)`,
      }}
    >
      <span
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: hex }}
      />
      <span className="truncate">{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="ml-0.5 shrink-0 rounded-full p-0.5 hover:bg-black/10"
          aria-label={`Quitar ${label}`}
        >
          <X className="size-3" />
        </button>
      )}
    </span>
  );
}

// Fila de etiquetas de una línea: escena, personaje que habla y assets/elements. Cada
// una se añade con un clic y sustituye a toda la opcionalidad de campos anterior.
function LineTags({
  projectId,
  line,
  sceneTitle,
  characters,
  assets,
  links,
  run,
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const speaker = characters.find(
    (item) => String(item.id) === String(line.speaker_element_id),
  );
  const scoped = (links || []).filter(
    (link) => String(link.script_line_id) === String(line.id),
  );
  const isDialogue = line.line_type === "dialogue";
  const linkable = assets.filter(
    (asset) =>
      asset.status === "ready" &&
      `${asset.name} ${asset.type}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {sceneTitle && <TagPill hex={SCENE_TAG_HEX} label={sceneTitle} />}
      {isDialogue && speaker && (
        <TagPill
          hex={characterColor(speaker.id).hex}
          label={speaker.name}
          onRemove={() =>
            run(() =>
              db.updateScriptLine(line.id, { speaker_element_id: null }),
            )
          }
        />
      )}
      {scoped.map((link) => {
        const asset = assets.find(
          (item) => String(item.id) === String(link.asset_id),
        );
        return (
          <TagPill
            key={link.id}
            hex={ASSET_PILL_HEX[assetTagCategory(asset)]}
            label={asset?.name || "Asset"}
            onRemove={() => run(() => db.unlinkScriptAsset(link.id))}
          />
        );
      })}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-full border border-dashed px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-foreground/50 hover:text-foreground"
          >
            <Plus className="size-3" /> Etiqueta
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-52">
          {isDialogue && (
            <>
              <DropdownMenuLabel>Personaje que habla</DropdownMenuLabel>
              {characters.length ? (
                characters.map((character) => (
                  <DropdownMenuItem
                    key={character.id}
                    onClick={() =>
                      run(() =>
                        db.updateScriptLine(line.id, {
                          speaker_element_id: character.id,
                        }),
                      )
                    }
                  >
                    <span
                      className="mr-2 size-2 rounded-full"
                      style={{
                        backgroundColor: characterColor(character.id).hex,
                      }}
                    />
                    {character.name}
                    {String(line.speaker_element_id) ===
                      String(character.id) && (
                      <Check className="ml-auto size-3.5" />
                    )}
                  </DropdownMenuItem>
                ))
              ) : (
                <DropdownMenuItem disabled>
                  Crea personajes en la pestaña Personajes
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuItem onSelect={() => setPickerOpen(true)}>
            <Bookmark className="mr-2 size-3.5" />
            Asset o element…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Etiquetar un asset o element</DialogTitle>
            <DialogDescription>
              Se enviará al agente como referencia @ de esta línea al generar.
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
              {linkable.map((asset) => {
                const already = scoped.some(
                  (link) => String(link.asset_id) === String(asset.id),
                );
                return (
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
                        variant={already ? "secondary" : "outline"}
                        disabled={already}
                        onClick={() =>
                          run(() =>
                            db.linkScriptAsset(
                              projectId,
                              line.scene_id,
                              line.id,
                              asset.id,
                            ),
                          )
                        }
                      >
                        {already ? "Añadido" : "Etiquetar"}
                      </Button>
                    </CardContent>
                  </Card>
                );
              })}
              {!linkable.length && (
                <div className="col-span-3">
                  <EmptyState
                    icon={Search}
                    title="No hay coincidencias"
                    description="Genera o sube el asset en Assets y después etiquétalo aquí."
                  />
                </div>
              )}
            </div>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const EMOTION_STEPS = [
  { value: "calmado", label: "Calmado" },
  { value: "neutral", label: "Neutral" },
  { value: "cálido", label: "Cálido" },
  { value: "alegre", label: "Alegre" },
  { value: "tenso", label: "Tenso" },
  { value: "épico", label: "Épico" },
];
const INTENSITY_STEPS = [
  { value: 0, label: "Muy baja" },
  { value: 0.25, label: "Baja" },
  { value: 0.5, label: "Media" },
  { value: 0.75, label: "Alta" },
  { value: 1, label: "Máxima" },
];
const PACE_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2].map((v) => ({
  value: v,
  label: `${v}×`,
}));
const VOLUME_STEPS = [0, 0.25, 0.5, 0.75, 1].map((v) => ({
  value: v,
  label: `${Math.round(v * 100)}%`,
}));

function nearestStep(value, steps) {
  const num = Number(value);
  if (!Number.isFinite(num)) return steps[0].value;
  let best = steps[0].value;
  let bestDiff = Infinity;
  for (const step of steps) {
    const diff = Math.abs(Number(step.value) - num);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = step.value;
    }
  }
  return best;
}

// Opciones avanzadas de una línea: solo deslizables de interpretación. Personaje, escena
// y assets se manejan como etiquetas en la propia tarjeta.
// Copiado tal cual del compositor de generación (SettingsSlider de main.jsx): el
// deslizable con pomo que se arrastra, el mismo de Aspecto/Resolución/Duración.
function SettingsSlider({ label, value, options, onChange }) {
  const trackRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const i = Math.max(0, options.indexOf(value));
  const last = options.length - 1;
  const pct = last ? (i / last) * 100 : 0;

  const pick = (clientX) => {
    const r = trackRef.current.getBoundingClientRect();
    const t = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    const next = options[Math.round(t * last)];
    if (next !== value) onChange(next);
  };
  const start = (e) => {
    e.preventDefault();
    setDragging(true);
    pick(e.clientX);
    const move = (ev) => pick(ev.clientX);
    const up = () => {
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.removeProperty("user-select");
    };
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const step = (d) => {
    const n = Math.min(last, Math.max(0, i + d));
    if (n !== i) onChange(options[n]);
  };

  return (
    <div className="px-2 py-1.5">
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="truncate font-medium">{value}</span>
      </div>
      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuetext={value}
        aria-valuemin={0}
        aria-valuemax={last}
        aria-valuenow={i}
        onPointerDown={start}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") (e.preventDefault(), step(-1));
          if (e.key === "ArrowRight") (e.preventDefault(), step(1));
        }}
        className="relative mt-2 flex h-7 cursor-pointer touch-none items-center rounded-full bg-muted px-1 outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <div
          className={cn(
            "pointer-events-none absolute left-1 top-1 h-5 w-9 rounded-full bg-background shadow-sm",
            !dragging && "transition-[left] duration-300 ease-out",
          )}
          style={{ left: `calc(0.25rem + ${pct}% - ${(pct / 100) * 2.25}rem)` }}
        />
        <div className="pointer-events-none relative flex w-full justify-between px-3">
          {options.map((o, n) => (
            <span
              key={o}
              title={o}
              className={cn(
                "size-1 rounded-full transition-colors",
                n === i ? "bg-transparent" : "bg-muted-foreground/35",
              )}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// Opciones de los deslizables de una línea, como texto (igual que las de generación).
const INTENSITY_OPTS = ["Muy baja", "Baja", "Media", "Alta", "Máxima"];
const PACE_OPTS = ["0.5×", "0.75×", "1×", "1.25×", "1.5×", "2×"];
const PACE_VALUES = [0.5, 0.75, 1, 1.25, 1.5, 2];
const EMOTION_OPTS = ["Calmado", "Neutral", "Cálido", "Alegre", "Tenso", "Épico"];
const VOLUME_OPTS = ["0%", "25%", "50%", "75%", "100%"];
const VOLUME_VALUES = [0, 0.25, 0.5, 0.75, 1];
// Opciones de los deslizables de generación de voz (misma UI segmentada).
const SPEED_OPTS = ["Más lento", "Lento", "Normal", "Rápido", "Más rápido"];
const SPEED_VALUES = [0.7, 0.85, 1.0, 1.05, 1.2];
const LEVEL_OPTS = ["Muy baja", "Baja", "Media", "Alta", "Muy alta"];
const LEVEL_VALUES = [0, 0.25, 0.5, 0.75, 1];

function nearestIndex(value, values) {
  const num = Number(value);
  let best = 0;
  let diff = Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const d = Math.abs(values[i] - num);
    if (d < diff) {
      diff = d;
      best = i;
    }
  }
  return best;
}

// Opciones avanzadas de una línea: solo los deslizables de interpretación, con el mismo
// componente exacto que la hoja de generación.
function LineInspector({ line, run, onSeedChat, onSendAgent }) {
  if (!line) return null;
  const update = (patch) => run(() => db.updateScriptLine(line.id, patch));
  const volume = Number(line.metadata?.volume ?? 0.75);
  const emotionValue =
    EMOTION_OPTS.find(
      (option) =>
        option.toLowerCase() === String(line.emotion || "").toLowerCase(),
    ) || "Neutral";
  const speaks = ["dialogue", "voiceover"].includes(line.line_type);
  return (
    <div className="space-y-1">
      <SettingsSlider
        label="Intensidad"
        value={
          INTENSITY_OPTS[
            Math.round(
              Math.min(1, Math.max(0, Number(line.intensity ?? 0.5))) * 4,
            )
          ]
        }
        options={INTENSITY_OPTS}
        onChange={(v) => update({ intensity: INTENSITY_OPTS.indexOf(v) / 4 })}
      />
      <SettingsSlider
        label="Velocidad"
        value={PACE_OPTS[nearestIndex(line.pace ?? 1, PACE_VALUES)]}
        options={PACE_OPTS}
        onChange={(v) => update({ pace: PACE_VALUES[PACE_OPTS.indexOf(v)] })}
      />
      <SettingsSlider
        label="Sentimiento"
        value={emotionValue}
        options={EMOTION_OPTS}
        onChange={(v) => update({ emotion: v })}
      />
      <SettingsSlider
        label="Volumen"
        value={VOLUME_OPTS[nearestIndex(volume, VOLUME_VALUES)]}
        options={VOLUME_OPTS}
        onChange={(v) =>
          update({
            metadata: {
              ...(line.metadata || {}),
              volume: VOLUME_VALUES[VOLUME_OPTS.indexOf(v)],
            },
          })
        }
      />
      {speaks && (
        <div className="px-2 pt-2">
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() =>
              (onSendAgent || onSeedChat)?.(
                `Genera y guarda como asset una toma de audio para la línea de guion ${line.id}. ` +
                  `Usa exactamente su texto, personaje, sentimiento, intensidad, velocidad y volumen, y sus etiquetas @ como referencias. ` +
                  `Vincúlala a la línea y colócala en el plan de audio respetando su timing. Estima créditos antes de generar.`,
              )
            }
          >
            <Mic2 /> Generar toma de voz
          </Button>
        </div>
      )}
    </div>
  );
}

// Cada personaje recibe un color estable derivado de su id, para que la barra lateral de
// cada línea, su pill de hablante y su clip en el timeline compartan identidad visual.
const CHARACTER_PALETTE = [
  { hex: "#f59e0b", text: "text-amber-600", tint: "bg-amber-500/12" },
  { hex: "#0ea5e9", text: "text-sky-600", tint: "bg-sky-500/12" },
  { hex: "#10b981", text: "text-emerald-600", tint: "bg-emerald-500/12" },
  { hex: "#d946ef", text: "text-fuchsia-600", tint: "bg-fuchsia-500/12" },
  { hex: "#f43f5e", text: "text-rose-600", tint: "bg-rose-500/12" },
  { hex: "#8b5cf6", text: "text-violet-600", tint: "bg-violet-500/12" },
  { hex: "#06b6d4", text: "text-cyan-600", tint: "bg-cyan-500/12" },
  { hex: "#f97316", text: "text-orange-600", tint: "bg-orange-500/12" },
];
const NEUTRAL_ACCENT = { hex: "#a1a1aa", text: "text-muted-foreground", tint: "bg-muted" };

// Estado de una línea como un punto de color discreto, en vez de la palabra suelta que
// añadía ruido sin jerarquía.
const STATUS_HEX = {
  draft: "#a1a1aa",
  ready: "#10b981",
  approved: "#10b981",
  generating: "#f59e0b",
  review: "#0ea5e9",
  failed: "#ef4444",
};

function characterColor(id) {
  const source = String(id ?? "");
  let hash = 0;
  for (let i = 0; i < source.length; i += 1)
    hash = (hash * 31 + source.charCodeAt(i)) >>> 0;
  return CHARACTER_PALETTE[hash % CHARACTER_PALETTE.length];
}

function lineAccent(line, speaker) {
  if (line.line_type === "dialogue" && speaker) return characterColor(speaker.id);
  if (line.line_type === "voiceover") return CHARACTER_PALETTE[2];
  if (line.line_type === "caption") return CHARACTER_PALETTE[1];
  return NEUTRAL_ACCENT;
}

// Reproduce una lista de tomas de audio una detrás de otra con un único <audio>. Sirve
// para escuchar solo el guion (las voces) sin música ni efectos.
// Línea de tiempo de reproducción reutilizable: una pista con los clips en orden,
// coloreados, con regla de tiempo, cabezal y transporte. La usa el Guion para escuchar el
// diálogo y es el mismo módulo que debe llevar el estudio de voces/audio.
function DialogueTimeline({ clips, emptyHint, caption }) {
  const durations = clips.map((clip) => Math.max(400, clip.durationMs || 1000));
  const total = Math.max(1000, durations.reduce((sum, d) => sum + d, 0));
  const offsets = [];
  {
    let acc = 0;
    for (const d of durations) {
      offsets.push(acc);
      acc += d;
    }
  }
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [speed, setSpeed] = useState(1);
  const rafRef = useRef(0);
  const audioRef = useRef(null);
  const activeRef = useRef(-1);
  const clockRef = useRef({ t0: 0, base: 0 });
  const speedRef = useRef(1);
  speedRef.current = speed;

  const stopAudio = () => {
    activeRef.current = -1;
    if (audioRef.current) audioRef.current.pause();
  };
  const halt = () => {
    cancelAnimationFrame(rafRef.current);
    stopAudio();
    setPlaying(false);
  };

  // Reinicia el cabezal cuando cambia la lista de clips (otra escena).
  const clipKey = clips.map((clip) => clip.id).join("|");
  useEffect(() => {
    halt();
    setPos(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipKey]);
  useEffect(() => () => cancelAnimationFrame(rafRef.current), []);

  const frame = () => {
    const now = performance.now();
    const p =
      clockRef.current.base +
      (now - clockRef.current.t0) * speedRef.current;
    if (p >= total) {
      setPos(total);
      halt();
      return;
    }
    setPos(p);
    let idx = -1;
    for (let i = 0; i < clips.length; i += 1) {
      if (p >= offsets[i] && p < offsets[i] + durations[i]) {
        idx = i;
        break;
      }
    }
    if (idx !== activeRef.current) {
      stopAudio();
      activeRef.current = idx;
      const clip = clips[idx];
      if (clip?.url) {
        let audio = audioRef.current;
        if (!audio) {
          audio = new Audio();
          audioRef.current = audio;
        }
        audio.src = clip.url;
        audio.playbackRate = speedRef.current;
        audio.play().catch(() => {});
      }
    }
    rafRef.current = requestAnimationFrame(frame);
  };

  const toggle = () => {
    if (!clips.length) return;
    if (playing) {
      cancelAnimationFrame(rafRef.current);
      stopAudio();
      clockRef.current.base = pos;
      setPlaying(false);
      return;
    }
    const start = pos >= total ? 0 : pos;
    clockRef.current = { t0: performance.now(), base: start };
    activeRef.current = -1;
    setPlaying(true);
    rafRef.current = requestAnimationFrame(frame);
  };

  const [pxPerSec, setPxPerSec] = useState(90);
  const clampZoom = (v) => Math.min(280, Math.max(28, v));

  const seekTo = (ms) => {
    const clamped = Math.min(total, Math.max(0, ms));
    setPos(clamped);
    clockRef.current = { t0: performance.now(), base: clamped };
    stopAudio();
  };

  const fmt = (ms) => {
    const s = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };

  const PAD = 10; // margen para que el primer bloque no quede pegado al borde.
  const contentSec = total / 1000;
  const displaySec = Math.max(Math.ceil(contentSec) + 3, 10);
  const trackWidth = displaySec * pxPerSec + PAD * 2;
  const px = (ms) => (ms / 1000) * pxPerSec;
  const at = (ms) => PAD + px(ms);
  const zoomPct = ((pxPerSec - 28) / (280 - 28)) * 100;

  // Arrastra el cabezal por toda la pista (scrubbing), no solo un clic.
  const startScrub = (event) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const toMs = (clientX) =>
      ((Math.max(0, clientX - rect.left) - PAD) / pxPerSec) * 1000;
    seekTo(toMs(event.clientX));
    const move = (moveEvent) => seekTo(toMs(moveEvent.clientX));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.removeProperty("user-select");
    };
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const SPEEDS = [1, 1.25, 1.5, 2, 0.5];
  const cycleSpeed = () => {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length] ?? 1;
    // Rebasa el reloj para que el cambio de velocidad no dé un salto en el cabezal.
    clockRef.current = { t0: performance.now(), base: pos };
    if (audioRef.current) audioRef.current.playbackRate = next;
    setSpeed(next);
  };

  // El control − ● + ajusta la escala de segundos (zoom) de la pista; se puede arrastrar.
  const startZoom = (event) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const apply = (clientX) => {
      const ratio = Math.min(
        1,
        Math.max(0, (clientX - rect.left) / rect.width),
      );
      setPxPerSec(clampZoom(28 + ratio * (280 - 28)));
    };
    apply(event.clientX);
    const move = (moveEvent) => apply(moveEvent.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const iconBtn =
    "flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40";

  return (
    <div className="shrink-0 border-t bg-background">
      {/* Transporte, idéntico al reproductor de referencia. */}
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <div className="flex flex-1 items-center justify-center gap-2">
          <button type="button" className={iconBtn} aria-label="Pistas">
            <ListFilter className="size-4" />
          </button>
          <button
            type="button"
            onClick={cycleSpeed}
            title="Velocidad de reproducción"
            className="rounded-md px-1.5 py-0.5 text-xs font-medium tabular-nums text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {speed}x
          </button>
          <button
            type="button"
            className={iconBtn}
            onClick={() => seekTo(0)}
            aria-label="Al inicio"
          >
            <SkipBack className="size-4" />
          </button>
          <button
            type="button"
            onClick={toggle}
            disabled={!clips.length}
            aria-label={playing ? "Pausar" : "Reproducir"}
            className="flex size-9 items-center justify-center rounded-full bg-foreground text-background transition-transform hover:scale-105 disabled:opacity-40"
          >
            {playing ? (
              <Pause className="size-4 fill-current" />
            ) : (
              <Play className="size-4 fill-current" />
            )}
          </button>
          <button
            type="button"
            className={iconBtn}
            onClick={() => seekTo(total)}
            aria-label="Al final"
          >
            <SkipForward className="size-4" />
          </button>
          <span className="text-xs tabular-nums text-muted-foreground">
            {fmt(pos)} / {fmt(total)}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className={iconBtn}
            onClick={() => setPxPerSec((v) => clampZoom(v * 0.8))}
            aria-label="Alejar"
          >
            <Minus className="size-4" />
          </button>
          <div
            className="relative h-4 w-16 cursor-pointer touch-none"
            onPointerDown={startZoom}
            title="Escala de segundos"
          >
            <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-muted" />
            <span
              className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground"
              style={{ left: `${zoomPct}%` }}
            />
          </div>
          <button
            type="button"
            className={iconBtn}
            onClick={() => setPxPerSec((v) => clampZoom(v * 1.25))}
            aria-label="Acercar"
          >
            <Plus className="size-4" />
          </button>
        </div>
      </div>

      {clips.length ? (
        <div className="flex items-stretch">
          <div className="flex w-8 shrink-0 items-center justify-center border-r text-muted-foreground">
            <Volume2 className="size-4" />
          </div>
          <div className="scrollbar-hidden min-w-0 flex-1 overflow-x-auto">
            <div style={{ width: `${trackWidth}px` }}>
              {/* Regla de tiempo con el badge de posición actual. */}
              <div className="relative h-5 border-b">
                {Array.from({ length: displaySec + 1 }).map((_, i) => (
                  <span
                    key={i}
                    className="absolute top-1 flex flex-col items-center text-[9px] tabular-nums text-muted-foreground/60"
                    style={{ left: `${PAD + i * pxPerSec}px` }}
                  >
                    {fmt(i * 1000)}
                  </span>
                ))}
                <span
                  className="absolute top-0 -translate-x-1/2 rounded bg-foreground px-1 text-[9px] font-medium tabular-nums text-background"
                  style={{ left: `${at(pos)}px` }}
                >
                  {fmt(pos)}
                </span>
              </div>
              {/* Pista con un bloque por línea: trama diagonal, borde de color y, en el
                  activo, asas redondeadas a los lados. */}
              <div
                className="relative h-12 cursor-pointer touch-none py-1.5"
                onPointerDown={startScrub}
              >
                {clips.map((clip, i) => {
                  const activeClip =
                    pos >= offsets[i] && pos < offsets[i] + durations[i];
                  return (
                    <div
                      key={clip.id}
                      className={cn(
                        "absolute inset-y-1.5 flex items-center overflow-hidden rounded-lg px-2.5 text-[11px] font-medium",
                        activeClip ? "border-2" : "border",
                      )}
                      style={{
                        left: `${at(offsets[i])}px`,
                        width: `${Math.max(28, px(durations[i]))}px`,
                        backgroundColor: `color-mix(in srgb, ${clip.hex} 9%, transparent)`,
                        backgroundImage: `repeating-linear-gradient(45deg, color-mix(in srgb, ${clip.hex} 24%, transparent) 0, color-mix(in srgb, ${clip.hex} 24%, transparent) 1px, transparent 1px, transparent 7px)`,
                        borderColor: `color-mix(in srgb, ${clip.hex} ${activeClip ? 95 : 42}%, transparent)`,
                        color: `color-mix(in srgb, ${clip.hex} 70%, #111)`,
                      }}
                      title={clip.label}
                    >
                      {activeClip && (
                        <>
                          <span
                            className="absolute inset-y-1 left-0.5 w-1.5 rounded-full"
                            style={{ backgroundColor: clip.hex }}
                          />
                          <span
                            className="absolute inset-y-1 right-0.5 w-1.5 rounded-full"
                            style={{ backgroundColor: clip.hex }}
                          />
                        </>
                      )}
                      <span className="relative truncate">{clip.label}</span>
                    </div>
                  );
                })}
                <div
                  className="pointer-events-none absolute inset-y-0 z-10 w-0.5 bg-foreground"
                  style={{ left: `${at(pos)}px` }}
                />
              </div>
            </div>
          </div>
        </div>
      ) : (
        <p className="px-4 py-3 text-[11px] text-muted-foreground">{emptyHint}</p>
      )}
    </div>
  );
}

// Reproductor multipista de la mezcla: mismo lenguaje que el del guion (transporte,
// zoom y bloques con trama de color), pero con una pista por tipo de sonido. La
// reproducción real la hace el motor Web Audio del estudio; aquí el cabezal se sincroniza
// con él y cada bloque se puede seleccionar para editarlo debajo.
function MixTimeline({
  tracks,
  totalMs,
  playing,
  onToggle,
  selectedCueId,
  onSelectCue,
  onDropTemplate,
  onMoveCue,
}) {
  const [pxPerSec, setPxPerSec] = useState(70);
  const clampZoom = (v) => Math.min(220, Math.max(24, v));
  const [pos, setPos] = useState(0);
  const rafRef = useRef(0);
  const startRef = useRef(0);

  useEffect(() => {
    if (!playing) {
      cancelAnimationFrame(rafRef.current);
      setPos(0);
      return undefined;
    }
    startRef.current = performance.now();
    setPos(0);
    const tick = () => {
      const p = performance.now() - startRef.current;
      if (p >= totalMs) {
        setPos(totalMs);
        return;
      }
      setPos(p);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [playing, totalMs]);

  const PAD = 12;
  const NAME_W = 140;
  const LANE_H = 76;

  // Mueve un cue a la posición y pista exactas donde se suelta (drag & drop nativo).
  const dropCue = (event, kind) => {
    const cueId = event.dataTransfer.getData("application/x-xframe-cue");
    if (!cueId || !onMoveCue) return;
    const source = tracks
      .flatMap((track) => track.cues)
      .find((cue) => String(cue.id) === String(cueId));
    if (!source) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const startMs = Math.max(
      0,
      Math.round((((event.clientX - rect.left - PAD) / pxPerSec) * 1000) / 50) *
        50,
    );
    const duration = Math.max(200, source.end_ms - source.start_ms);
    onMoveCue(cueId, startMs, startMs + duration, kind);
  };
  const contentSec = totalMs / 1000;
  const displaySec = Math.max(Math.ceil(contentSec) + 3, 10);
  const trackWidth = displaySec * pxPerSec + PAD * 2;
  const px = (ms) => (ms / 1000) * pxPerSec;
  const at = (ms) => PAD + px(ms);
  const zoomPct = ((pxPerSec - 24) / (220 - 24)) * 100;
  const fmt = (ms) => {
    const s = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  const ticks = Math.min(24, displaySec + 1);

  const startZoom = (event) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const apply = (clientX) => {
      const ratio = Math.min(
        1,
        Math.max(0, (clientX - rect.left) / rect.width),
      );
      setPxPerSec(clampZoom(24 + ratio * (220 - 24)));
    };
    apply(event.clientX);
    const move = (moveEvent) => apply(moveEvent.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const iconBtn =
    "flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40";

  return (
    <div className="overflow-hidden rounded-xl border bg-background">
      <div className="flex">
        {/* Columna fija de nombres de pista */}
        <div className="shrink-0 border-r" style={{ width: `${NAME_W}px` }}>
          <div className="h-5 border-b" />
          {tracks.map((track) => {
            const Icon = track.Icon;
            return (
              <div
                key={track.kind}
                className="flex items-center gap-2 border-b px-3"
                style={{ height: `${LANE_H}px` }}
              >
                <span
                  className="flex size-6 shrink-0 items-center justify-center rounded-md"
                  style={{
                    backgroundColor: `color-mix(in srgb, ${track.hex} 14%, transparent)`,
                    color: track.hex,
                  }}
                >
                  <Icon className="size-3.5" />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[11px] font-medium">
                    {track.label}
                  </p>
                  <p className="text-[9px] text-muted-foreground">
                    {track.cues.length} clips
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Pistas con scroll horizontal compartido */}
        <div className="scrollbar-hidden min-w-0 flex-1 overflow-x-auto">
          <div className="relative" style={{ width: `${trackWidth}px` }}>
            {/* Regla */}
            <div className="relative h-5 border-b">
              {Array.from({ length: ticks }).map((_, i) => (
                <span
                  key={i}
                  className="absolute top-1 -translate-x-1/2 text-[9px] tabular-nums text-muted-foreground/60"
                  style={{ left: `${PAD + i * pxPerSec}px` }}
                >
                  {fmt(i * 1000)}
                </span>
              ))}
            </div>
            {tracks.map((track) => (
              <div
                key={track.kind}
                className="relative border-b transition-colors"
                style={{ height: `${LANE_H}px` }}
                onDragOver={(event) => {
                  const types = event.dataTransfer.types;
                  if (
                    types.includes("application/x-xframe-audio-template") ||
                    types.includes("application/x-xframe-cue")
                  )
                    event.preventDefault();
                }}
                onDrop={(event) => {
                  if (
                    event.dataTransfer.types.includes(
                      "application/x-xframe-cue",
                    )
                  )
                    dropCue(event, track.kind);
                  else onDropTemplate(event, track.kind);
                }}
              >
                {track.cues.map((cue) => {
                  const selected = String(selectedCueId) === String(cue.id);
                  return (
                    <div
                      key={cue.id}
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData(
                          "application/x-xframe-cue",
                          String(cue.id),
                        );
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onClick={() => onSelectCue(cue.id)}
                      title={cue.label}
                      className={cn(
                        "absolute inset-y-2 flex cursor-grab items-center overflow-hidden rounded-lg px-2 text-[11px] font-medium active:cursor-grabbing",
                        selected ? "border-2" : "border",
                      )}
                      style={{
                        left: `${at(cue.start_ms)}px`,
                        width: `${Math.max(28, px(cue.end_ms - cue.start_ms))}px`,
                        backgroundColor: `color-mix(in srgb, ${track.hex} 10%, transparent)`,
                        backgroundImage: `repeating-linear-gradient(45deg, color-mix(in srgb, ${track.hex} 24%, transparent) 0, color-mix(in srgb, ${track.hex} 24%, transparent) 1px, transparent 1px, transparent 7px)`,
                        borderColor: `color-mix(in srgb, ${track.hex} ${selected ? 95 : 42}%, transparent)`,
                        color: `color-mix(in srgb, ${track.hex} 70%, #111)`,
                      }}
                    >
                      {selected && (
                        <>
                          <span
                            className="absolute inset-y-1 left-0.5 w-1.5 rounded-full"
                            style={{ backgroundColor: track.hex }}
                          />
                          <span
                            className="absolute inset-y-1 right-0.5 w-1.5 rounded-full"
                            style={{ backgroundColor: track.hex }}
                          />
                        </>
                      )}
                      <span className="relative truncate">
                        {cue.label}
                        {cue.locked ? " · 🔒" : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
            {/* Cabezal sobre todas las pistas */}
            <div
              className="pointer-events-none absolute z-10 w-0.5 bg-foreground"
              style={{ left: `${at(pos)}px`, top: "20px", bottom: 0 }}
            />
          </div>
        </div>
      </div>
      {/* Transporte, abajo como un reproductor. */}
      <div className="flex items-center gap-2 border-t px-3 py-2.5">
        <div className="flex flex-1 items-center justify-center gap-3">
          <button
            type="button"
            onClick={onToggle}
            aria-label={playing ? "Detener" : "Reproducir mezcla"}
            className="flex size-11 items-center justify-center rounded-full bg-foreground text-background transition-transform hover:scale-105"
          >
            {playing ? (
              <Pause className="size-5 fill-current" />
            ) : (
              <Play className="size-5 fill-current" />
            )}
          </button>
          <span className="text-sm tabular-nums text-muted-foreground">
            {fmt(pos)} / {fmt(totalMs)}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className={iconBtn}
            onClick={() => setPxPerSec((v) => clampZoom(v * 0.8))}
            aria-label="Alejar"
          >
            <Minus className="size-4" />
          </button>
          <div
            className="relative h-4 w-16 cursor-pointer touch-none"
            onPointerDown={startZoom}
            title="Escala de segundos"
          >
            <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-muted" />
            <span
              className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground"
              style={{ left: `${zoomPct}%` }}
            />
          </div>
          <button
            type="button"
            className={iconBtn}
            onClick={() => setPxPerSec((v) => clampZoom(v * 1.25))}
            aria-label="Acercar"
          >
            <Plus className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

// Reparto del proyecto: personajes (Elements con rol) con su color y su voz por defecto.
function CastPanel({
  projectId,
  characters,
  voices,
  assignments,
  run,
  onSendAgent,
  onSeedChat,
}) {
  return (
    <div className="space-y-2 p-2.5">
      {characters.map((character) => {
        const color = characterColor(character.id);
        const assignment = assignments.find(
          (item) =>
            String(item.element_id) === String(character.id) && item.is_default,
        );
        return (
          <div key={character.id} className="rounded-xl border bg-background p-2.5">
            <div className="flex items-center gap-2.5">
              <span
                className="relative size-8 shrink-0 rounded-lg bg-cover bg-center ring-1 ring-border"
                style={{
                  backgroundImage: character.url
                    ? `url(${character.url})`
                    : undefined,
                  backgroundColor: character.url ? undefined : color.hex,
                }}
              >
                <span
                  className="absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-background"
                  style={{ backgroundColor: color.hex }}
                />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-semibold">{character.name}</p>
                <p className="truncate text-[10px] text-muted-foreground">
                  {character.role}
                </p>
              </div>
            </div>
            <Select
              value={assignment?.voice_profile_id || "__none__"}
              onValueChange={(id) =>
                run(() =>
                  db.assignCharacterVoice(
                    projectId,
                    character.id,
                    id === "__none__" ? null : id,
                  ),
                )
              }
            >
              <SelectTrigger className="mt-2 h-8 text-xs">
                <SelectValue placeholder="Sin voz asignada" />
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
        <EmptyState
          icon={UserRound}
          title="Sin personajes"
          description="Los personajes son Elements con rol. Créalos en Assets o pídeselos al agente."
        />
      )}
      <Button
        variant="outline"
        className="w-full"
        onClick={() =>
          (onSendAgent || onSeedChat)?.(
            "Crea un personaje nuevo como Element con rol de Personaje: propón nombre, breve descripción física y una imagen de referencia, y déjalo listo para asignarle voz.",
          )
        }
      >
        <Plus /> Crear personaje
      </Button>
    </div>
  );
}

export function ScreenplayStudio({
  projectId,
  assets = [],
  onSeedChat,
  onSendAgent,
  onProductionChange,
  productionData,
}) {
  const { data, loading, saving, error, reload, run } =
    useProduction(projectId, onProductionChange, productionData);
  const [sceneId, setSceneId] = useState(null);
  const [draft, setDraft] = useState("");
  const [scenePanelVisible, setScenePanelVisible] = useStoredVisibility(
    "xframe.screenplay.scene-panel",
  );
  // Solo los personajes hablan y llevan voz. Localizaciones y objetos son Elements pero
  // no forman parte del reparto ni pueden ser el hablante de un diálogo.
  const characters = useMemo(
    () => assets.filter((asset) => isPersonajeRole(asset.role)),
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
  const totalDuration = data.scenes.reduce(
    (total, item) => total + (item.target_duration_ms || 0),
    0,
  );
  const [leftTab, setLeftTab] = useState("scenes");
  const [openLineId, setOpenLineId] = useState("");
  const [overLineId, setOverLineId] = useState(null);
  const dragLineId = useRef(null);
  // Clips de diálogo/voz de la escena para la línea de tiempo: cada línea es un bloque
  // coloreado por quien habla; si ya tiene toma generada, su audio suena al reproducir.
  const dialogueClips = useMemo(() => {
    return linesByScene
      .filter((line) => ["dialogue", "voiceover"].includes(line.line_type))
      .map((line) => {
        const speaker = characters.find(
          (item) => String(item.id) === String(line.speaker_element_id),
        );
        const cue = data.cues.find(
          (item) => String(item.script_line_id) === String(line.id),
        );
        const asset = cue
          ? assets.find(
              (item) => String(item.id) === String(cue.asset_id) && item.url,
            )
          : null;
        const accent = lineAccent(line, speaker);
        // Cada bloque siempre con color: si el diálogo aún no tiene personaje, se le da
        // uno estable por su id en vez del gris neutro.
        const hex =
          accent.hex === NEUTRAL_ACCENT.hex
            ? characterColor(line.id).hex
            : accent.hex;
        return {
          id: String(line.id),
          label:
            line.text ||
            (line.line_type === "voiceover" ? "Voz en off" : "Diálogo"),
          durationMs:
            line.target_duration_ms ||
            Math.max(1200, String(line.text || "").length * 55),
          hex,
          url: asset?.url || null,
        };
      });
  }, [linesByScene, characters, data.cues, assets]);

  useEffect(() => {
    if (!data.scenes.length) {
      setSceneId(null);
      setOpenLineId("");
      return;
    }
    if (!data.scenes.some((item) => String(item.id) === String(sceneId)))
      setSceneId(data.scenes[0].id);
  }, [data.scenes, sceneId]);
  useEffect(() => setOpenLineId(""), [sceneId]);

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
    if (ok && created) setOpenLineId(String(created.id));
  };
  const sendBrief = () => {
    if (!draft.trim()) return;
    (onSendAgent || onSeedChat)?.(
      `Convierte este texto en el guion estructurado y editable del proyecto. Separa escenas, acciones, diálogo, voz en off y rótulos; conserva literalmente el copy aprobado y añade emoción, ritmo, pausas y duración objetivo. No generes audio todavía.\n\n${draft.trim()}`,
    );
    setDraft("");
  };
  // Soltar una línea sobre otra la mueve hasta esa posición desplazando el resto. El
  // backend solo sabe intercambiar con el vecino, así que se encadenan pasos adyacentes
  // dentro de un único run() (una sola recarga).
  const dropLineOn = (targetIndex) => {
    const draggedId = dragLineId.current;
    dragLineId.current = null;
    setOverLineId(null);
    if (!draggedId || !scene) return;
    const from = linesByScene.findIndex(
      (line) => String(line.id) === draggedId,
    );
    if (from < 0 || from === targetIndex) return;
    const step = targetIndex > from ? 1 : -1;
    const steps = Math.abs(targetIndex - from);
    run(async () => {
      for (let i = 0; i < steps; i += 1)
        await db.moveScriptLine(scene.id, draggedId, step);
    });
  };

  return (
    <TooltipProvider>
      {/* Misma rejilla 2×2 que en Audio: el sidebar ocupa toda la altura de su columna
          y el encabezado solo existe sobre la principal. El toggle vive en el
          encabezado: fuera del sidebar al desplegarse, primero del grupo derecho al
          colapsar. */}
      <div
        className="grid h-full min-h-0 grid-rows-[3rem_minmax(0,1fr)] overflow-hidden rounded-xl border bg-background"
        style={{
          gridTemplateColumns: `${scenePanelVisible ? "272px" : "0px"} minmax(420px, 1fr)`,
        }}
      >
        {/* El toggle va SIEMPRE el primero a la izquierda del encabezado: pegado al
            sidebar cuando está abierto y en ese mismo hueco cuando está cerrado. */}
        <header className="col-start-2 row-start-1 flex min-w-0 items-center gap-3 px-4">
          <SidebarToggle
            side="left"
            expanded={scenePanelVisible}
            onChange={setScenePanelVisible}
            label="escenas"
          />
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
          <aside
            className={cn(
              "production-sidebar relative col-start-1 row-span-2 row-start-1 flex min-h-0 flex-col",
              scenePanelVisible
                ? "overflow-hidden border-r bg-muted/10"
                : "overflow-visible",
            )}
          >
            {scenePanelVisible && (
              <div className="flex shrink-0 items-center border-b p-3">
                <div className="grid w-full grid-cols-2 rounded-xl border bg-muted/40 p-1">
                  {[
                    ["scenes", "Escenas"],
                    ["cast", "Personajes"],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setLeftTab(value)}
                      className={cn(
                        "rounded-lg px-3.5 py-1.5 text-center text-xs font-semibold transition-colors",
                        leftTab === value
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {scenePanelVisible && leftTab === "cast" && (
              <div className="min-h-0 flex-1 overflow-y-auto">
                <CastPanel
                  projectId={projectId}
                  characters={characters}
                  voices={data.voices}
                  assignments={data.characterVoices}
                  run={run}
                  onSendAgent={onSendAgent}
                  onSeedChat={onSeedChat}
                />
              </div>
            )}
            {scenePanelVisible && leftTab === "scenes" && (
              <>
                {loading ? (
                  <ProductionListSkeleton />
                ) : (
                  <ScrollArea className="min-h-0 flex-1 px-3 pb-3 pt-2">
                    <div className="space-y-1.5">
                      {data.scenes.map((item, index) => {
                        const count = data.lines.filter(
                          (line) => String(line.scene_id) === String(item.id),
                        ).length;
                        const referenceCount = data.assetLinks.filter(
                          (link) =>
                            String(link.scene_id) === String(item.id) &&
                            !link.script_line_id,
                        ).length;
                        const active = String(scene?.id) === String(item.id);
                        return (
                          <div
                            key={item.id}
                            onClick={() => setSceneId(item.id)}
                            className={cn(
                              "flex w-full cursor-pointer items-center gap-2 rounded-lg border bg-background px-2 py-1.5 text-left transition-colors hover:bg-accent/50",
                              active && "border-foreground/25 bg-accent",
                            )}
                          >
                            <span className="flex size-6 shrink-0 items-center justify-center rounded-md border bg-background text-[11px] font-semibold">
                              {index + 1}
                            </span>
                            <span className="min-w-0 flex-1">
                              <DraftInput
                                value={item.title}
                                onCommit={(title) =>
                                  run(() =>
                                    db.updateScriptScene(item.id, { title }),
                                  )
                                }
                                placeholder={`Escena ${index + 1}`}
                                onClick={(event) => event.stopPropagation()}
                                className="h-auto w-full appearance-none truncate rounded-none border-0 bg-transparent p-0 text-xs font-medium text-foreground shadow-none outline-none ring-0 focus:border-0 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0"
                              />
                              <span className="block truncate text-[10px] font-normal text-muted-foreground">
                                {count} {count === 1 ? "línea" : "líneas"}
                                {" · "}
                                {item.target_duration_ms
                                  ? `${item.target_duration_ms / 1000}s`
                                  : "sin duración"}
                                {referenceCount ? ` · ${referenceCount} refs` : ""}
                              </span>
                            </span>
                            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                          </div>
                        );
                      })}
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={addScene}
                      >
                        <Plus className="size-3.5" /> Añadir escena
                      </Button>
                    </div>
                  </ScrollArea>
                )}
                <div className="px-3 pb-3">
                  <button
                    type="button"
                    onClick={() =>
                      (onSendAgent || onSeedChat)?.(
                        "Crea una escena nueva y completa para este proyecto usando el contexto que ya tienes (brief, personajes, tono y escenas existentes). Estructúrala con sus líneas de diálogo, voz en off y acción, con el personaje que habla y su dirección. Si te falta algo clave para que quede perfecta, pregúntame antes de crearla.",
                      )
                    }
                    className="flex w-full items-center gap-2.5 rounded-lg border border-dashed px-3 py-2.5 text-left transition-colors hover:border-primary/50 hover:bg-accent/40"
                  >
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Sparkles className="size-4" />
                    </span>
                    <span className="text-xs font-semibold">
                      Generar escena con IA
                    </span>
                  </button>
                </div>
              </>
            )}
          </aside>

          <main className="col-start-2 row-start-2 flex min-h-0 flex-col overflow-hidden">
            <div className="min-h-0 flex-1 overflow-y-auto">
            {loading ? <ScreenplayWorkspaceSkeleton /> : !scene ? (
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
                  <div className="space-y-3 p-5">
                    <div className="space-y-1.5">
                      {linesByScene.map((line, index) => {
                        const [label] =
                          lineMeta[line.line_type] || lineMeta.dialogue;
                        const speaker = characters.find(
                          (item) =>
                            String(item.id) === String(line.speaker_element_id),
                        );
                        const accent = lineAccent(line, speaker);
                        const speakerName =
                          speaker?.name ||
                          (line.line_type === "voiceover" ? "Narrador" : null);
                        const open = openLineId === String(line.id);
                        const isDropTarget =
                          overLineId === String(line.id) &&
                          dragLineId.current &&
                          dragLineId.current !== String(line.id);
                        return (
                          <div
                            key={line.id}
                            onDragOver={(event) => {
                              if (!dragLineId.current) return;
                              event.preventDefault();
                              if (overLineId !== String(line.id))
                                setOverLineId(String(line.id));
                            }}
                            onDrop={(event) => {
                              event.preventDefault();
                              dropLineOn(index);
                            }}
                            className={cn(
                              "flex overflow-hidden rounded-xl border transition-shadow",
                              open
                                ? "border-border bg-card shadow-lg"
                                : "border-transparent hover:border-border hover:bg-accent/30",
                              isDropTarget &&
                                "border-primary/60 ring-2 ring-primary/40",
                            )}
                          >
                            <span
                              className="w-1 shrink-0"
                              style={{ backgroundColor: accent.hex }}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="px-3 py-2.5">
                                <div className="flex items-center gap-2">
                                  <div
                                    draggable
                                    onDragStart={(event) => {
                                      dragLineId.current = String(line.id);
                                      event.dataTransfer.effectAllowed = "move";
                                    }}
                                    onDragEnd={() => {
                                      dragLineId.current = null;
                                      setOverLineId(null);
                                    }}
                                    className="cursor-grab text-muted-foreground/40 active:cursor-grabbing"
                                    aria-label="Reordenar línea"
                                  >
                                    <GripVertical className="size-4" />
                                  </div>
                                  {speakerName && (
                                    <span
                                      className="text-[11px] font-semibold"
                                      style={{ color: accent.hex }}
                                    >
                                      {speakerName}
                                    </span>
                                  )}
                                  <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground/70">
                                    {label}
                                  </span>
                                  <span className="ml-auto flex items-center gap-2.5 text-[10px] text-muted-foreground/70">
                                    {line.target_duration_ms ? (
                                      <span className="tabular-nums">
                                        {(line.target_duration_ms / 1000).toFixed(
                                          1,
                                        )}
                                        s
                                      </span>
                                    ) : null}
                                    <span
                                      className="size-1.5 rounded-full"
                                      style={{
                                        backgroundColor:
                                          STATUS_HEX[line.status] ||
                                          STATUS_HEX.draft,
                                      }}
                                      title={line.status}
                                    />
                                  </span>
                                  <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="size-7 shrink-0 text-muted-foreground"
                                      >
                                        <MoreHorizontal className="size-4" />
                                      </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                      <DropdownMenuItem
                                        onClick={() =>
                                          run(() =>
                                            db.moveScriptLine(
                                              line.scene_id,
                                              line.id,
                                              -1,
                                            ),
                                          )
                                        }
                                      >
                                        <ArrowUp className="mr-2 size-4" />
                                        Mover arriba
                                      </DropdownMenuItem>
                                      <DropdownMenuItem
                                        onClick={() =>
                                          run(() =>
                                            db.moveScriptLine(
                                              line.scene_id,
                                              line.id,
                                              1,
                                            ),
                                          )
                                        }
                                      >
                                        <ArrowDown className="mr-2 size-4" />
                                        Mover abajo
                                      </DropdownMenuItem>
                                      <DropdownMenuItem
                                        className="text-destructive"
                                        onClick={() =>
                                          run(() => db.deleteScriptLine(line.id))
                                        }
                                      >
                                        <Trash2 className="mr-2 size-4" />
                                        Eliminar línea
                                      </DropdownMenuItem>
                                    </DropdownMenuContent>
                                  </DropdownMenu>
                                  <button
                                    type="button"
                                    aria-label="Opciones avanzadas"
                                    onClick={() =>
                                      setOpenLineId(open ? "" : String(line.id))
                                    }
                                    className="shrink-0 p-0.5"
                                  >
                                    <ChevronRight
                                      className={cn(
                                        "size-4 text-muted-foreground transition-transform",
                                        open && "rotate-90",
                                      )}
                                    />
                                  </button>
                                </div>
                                <DraftInput
                                  multiline
                                  value={line.text}
                                  onCommit={(text) =>
                                    run(() =>
                                      db.updateScriptLine(line.id, { text }),
                                    )
                                  }
                                  placeholder="Escribe la línea…"
                                  className="mt-1.5 min-h-9 w-full resize-none appearance-none rounded-none border-0 bg-transparent p-0 text-[15px] font-medium leading-snug text-foreground shadow-none outline-none ring-0 focus:border-0 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0"
                                />
                                <div className="mt-2">
                                  <LineTags
                                    projectId={projectId}
                                    line={line}
                                    sceneTitle={scene?.title || "Escena"}
                                    characters={characters}
                                    assets={assets}
                                    links={data.assetLinks}
                                    run={run}
                                  />
                                </div>
                              </div>
                              {open && (
                                <div className="border-t bg-muted/10 px-4 pb-4 pt-3">
                                  <p className="mb-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                    Opciones avanzadas
                                  </p>
                                  <LineInspector
                                    line={line}
                                    run={run}
                                    onSeedChat={onSeedChat}
                                    onSendAgent={onSendAgent}
                                  />
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {!linesByScene.length && (
                      <EmptyState
                        icon={MessageSquareText}
                        title="Escena vacía"
                        description="Añade diálogo, una acción, voz en off o un rótulo. Cada línea tendrá su propia dirección y timing."
                      />
                    )}
                    <div className="pt-1">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" size="sm">
                            <Plus className="size-3.5" /> Añadir línea
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          <DropdownMenuItem onClick={() => addLine("dialogue")}>
                            <MessageSquareText
                              className="mr-2 size-4"
                              style={{ color: CHARACTER_PALETTE[0].hex }}
                            />
                            Diálogo
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => addLine("voiceover")}>
                            <Mic2
                              className="mr-2 size-4"
                              style={{ color: CHARACTER_PALETTE[2].hex }}
                            />
                            Voz en off
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => addLine("action")}>
                            <Waves
                              className="mr-2 size-4"
                              style={{ color: NEUTRAL_ACCENT.hex }}
                            />
                            Acción
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => addLine("caption")}>
                            <Type
                              className="mr-2 size-4"
                              style={{ color: CHARACTER_PALETTE[1].hex }}
                            />
                            Rótulo
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                </div>
              )
            )}
            </div>
            {scene && (
              <DialogueTimeline
                clips={dialogueClips}
                caption="Diálogo del guion"
                emptyHint="Añade diálogo o voz en off para ver aquí la línea de tiempo del guion."
              />
            )}
          </main>
      </div>
    </TooltipProvider>
  );
}

function VoiceLibrary({ projectId, voices, run, onAskAgent }) {
  const [name, setName] = useState("");
  const [providerId, setProviderId] = useState("");
  const [open, setOpen] = useState(false);
  const [providerSearch, setProviderSearch] = useState("");
  const [providerVoices, setProviderVoices] = useState([]);
  const [providerLoading, setProviderLoading] = useState(false);
  const [providerError, setProviderError] = useState("");
  useEffect(() => {
    let alive = true;
    const timer = setTimeout(async () => {
      setProviderLoading(true);
      setProviderError("");
      try {
        const query = new URLSearchParams({ page_size: "50" });
        if (providerSearch.trim()) query.set("search", providerSearch.trim());
        const result = await agentApi(
          `/projects/${projectId}/voices?${query.toString()}`,
        );
        if (alive) setProviderVoices(result.voices || []);
      } catch {
        if (alive) {
          setProviderVoices([]);
          setProviderError(
            "Conecta un proveedor de voz para explorar y previsualizar su catálogo real.",
          );
        }
      } finally {
        if (alive) setProviderLoading(false);
      }
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [projectId, providerSearch]);

  const importProviderVoice = (voice) =>
    run(() =>
      db.createVoiceProfile(projectId, {
        name: voice.name,
        provider: "elevenlabs",
        provider_voice_id: voice.voice_id,
        source: "library",
        language:
          voice.verified_languages?.[0]?.language ||
          voice.labels?.language ||
          "es",
        accent:
          voice.verified_languages?.[0]?.accent || voice.labels?.accent || "",
        description: voice.description || "",
        settings: voice.settings || {},
        status: "ready",
      }),
    );
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
      <div className="rounded-xl border p-3">
        <div className="flex items-center gap-2">
          <AudioLines className="size-4" />
          <p className="text-xs font-semibold">EXPLORAR VOCES</p>
          {providerLoading && <LoaderCircle className="ml-auto size-3.5 animate-spin" />}
        </div>
        <div className="relative mt-3">
          <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
          <Input
            value={providerSearch}
            onChange={(event) => setProviderSearch(event.target.value)}
            className="pl-8"
            placeholder="Nombre, acento, estilo o caso de uso…"
          />
        </div>
        {providerError && (
          <p className="mt-2 text-[11px] text-muted-foreground">{providerError}</p>
        )}
        {providerVoices.length > 0 && (
          <div className="mt-2 max-h-72 space-y-1 overflow-y-auto">
            {providerVoices.map((voice) => (
              <div
                key={voice.voice_id}
                className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-muted/60"
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
                  <Mic2 className="size-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium">{voice.name}</p>
                  <p className="truncate text-[10px] text-muted-foreground">
                    {[voice.labels?.accent, voice.labels?.age, voice.labels?.use_case]
                      .filter(Boolean)
                      .join(" · ") || voice.description}
                  </p>
                </div>
                {voice.preview_url && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => new Audio(voice.preview_url).play()}
                    aria-label={`Escuchar ${voice.name}`}
                  >
                    <Play className="size-3.5" />
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => importProviderVoice(voice)}
                >
                  Usar
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="rounded-xl border bg-muted/20 p-3">
        <p className="text-xs font-semibold">VOCES DEL PROYECTO</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Pide al agente narradores, personajes o voces de marca. Cada perfil
          conserva su nombre, proveedor e ID para reutilizarlo en diálogos,
          escenas y vídeos.
        </p>
        <Button className="mt-3 w-full" size="sm" onClick={onAskAgent}>
          <Sparkles /> Crear voces con el agente
        </Button>
      </div>
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
                          <SelectItem value="google">Google Cloud</SelectItem>
                          <SelectItem value="azure">Microsoft Azure</SelectItem>
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
          <Field label="ID del proveedor" hint="opcional">
            <Input
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
              placeholder="voice_id o clave de clonación"
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

function RangeSetting({
  label,
  low,
  high,
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.01,
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium underline decoration-dotted underline-offset-4">
        {label}
      </p>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{low}</span>
        <span>{high}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-foreground"
      />
    </div>
  );
}

function SoundComposer({
  projectId,
  scenes,
  lines,
  sceneShots,
  shots,
  voices,
  audioAssets,
  providerReady,
  seed,
  onGenerate,
  onVariant,
  onOpenVoices,
  run,
}) {
  const [panelTab, setPanelTab] = useState("settings");
  const [kind, setKind] = useState("voice");
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState("5");
  const [intensity, setIntensity] = useState(0.5);
  const [loop, setLoop] = useState(false);
  const [sceneId, setSceneId] = useState("__none__");
  const [lineId, setLineId] = useState("__none__");
  const [shotId, setShotId] = useState("__none__");
  const [start, setStart] = useState("0");
  const [voiceId, setVoiceId] = useState("");
  const [voicePickerOpen, setVoicePickerOpen] = useState(false);
  const [voiceSearch, setVoiceSearch] = useState("");
  const [voiceTab, setVoiceTab] = useState("explore");
  const [modelId, setModelId] = useState("eleven-multilingual-v2");
  const [speed, setSpeed] = useState(1);
  const [stability, setStability] = useState(0.5);
  const [similarity, setSimilarity] = useState(0.75);
  const [style, setStyle] = useState(0);
  const [languageOverride, setLanguageOverride] = useState(false);
  const [speakerBoost, setSpeakerBoost] = useState(true);
  const [outputFormat, setOutputFormat] = useState("mp3_44100_128");

  const selectedVoice = voices.find(
    (voice) => String(voice.id) === String(voiceId),
  );
  const selectedSceneLines = lines.filter(
    (line) =>
      sceneId === "__none__" || String(line.scene_id) === String(sceneId),
  );
  const selectedLine = lines.find((line) => String(line.id) === String(lineId));
  const selectedSceneShotIds = new Set(
    (sceneShots || [])
      .filter((item) => sceneId === "__none__" || String(item.scene_id) === String(sceneId))
      .map((item) => String(item.shot_id)),
  );
  const visibleShots = (shots || []).filter(
    (shot) => sceneId === "__none__" || selectedSceneShotIds.has(String(shot.id)),
  );
  const visibleVoices = voices.filter((voice) => {
    const text =
      `${voice.name} ${voice.description || ""} ${voice.accent || ""}`.toLowerCase();
    return text.includes(voiceSearch.trim().toLowerCase());
  });

  useEffect(() => {
    if (!seed) return;
    setPanelTab("settings");
    setKind(seed.kind || "sfx");
    setPrompt(seed.prompt || "");
    setDuration(String((seed.duration_ms || 5000) / 1000));
    setIntensity(Number(seed.intensity ?? 0.5));
    setLoop(Boolean(seed.loop));
  }, [seed]);

  useEffect(() => {
    if (!selectedVoice) return;
    const settings = selectedVoice.settings || {};
    setSpeed(Number(settings.speed ?? 1));
    setStability(Number(settings.stability ?? 0.5));
    setSimilarity(Number(settings.similarity_boost ?? 0.75));
    setStyle(Number(settings.style ?? 0));
    setSpeakerBoost(settings.use_speaker_boost !== false);
  }, [voiceId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const defaults = {
      voice: "eleven-multilingual-v2",
      music: "eleven-music-v2",
      sfx: "eleven-sfx-v2",
      ambience: "eleven-sfx-v2",
    };
    setModelId(defaults[kind]);
  }, [kind]);

  const config = () => ({
    prompt: kind === "voice" ? selectedLine?.text || "" : prompt.trim(),
    kind,
    model_id: modelId,
    voice_profile_id: voiceId || null,
    duration_ms: Math.max(100, Math.round(Number(duration || 0) * 1000)),
    intensity: Math.min(1, Math.max(0, Number(intensity || 0))),
    loop,
    scene_id: sceneId === "__none__" ? null : sceneId,
    script_line_id: lineId === "__none__" ? null : lineId,
    shot_id: shotId === "__none__" ? null : shotId,
    start_ms: Math.max(0, Math.round(Number(start || 0) * 1000)),
    placement_time_basis: sceneId === "__none__" ? "project" : "scene",
    output_format: outputFormat,
    settings: {
      speed,
      stability,
      similarity_boost: similarity,
      style,
      use_speaker_boost: speakerBoost,
      language_override: languageOverride,
    },
  });

  const submit = async () => {
    const values = config();
    if (kind === "voice" && selectedVoice) {
      const ok = await run(async () => {
        await db.updateVoiceProfile(selectedVoice.id, {
          settings: values.settings,
          status: selectedVoice.provider_voice_id ? "ready" : "draft",
        });
        if (selectedLine) {
          await db.updateScriptLine(selectedLine.id, {
            voice_profile_id: selectedVoice.id,
          });
        }
      });
      if (!ok) return;
    }
    onGenerate(values);
  };

  const canGenerate =
    providerReady &&
    (kind === "voice"
      ? Boolean(selectedVoice?.provider_voice_id && selectedLine?.text)
      : Boolean(prompt.trim()));

  return (
    <Tabs value={panelTab} onValueChange={setPanelTab} className="min-h-full">
      <TabsList className="grid h-10 w-full grid-cols-2 rounded-none border-b bg-transparent p-0">
        <TabsTrigger
          value="settings"
          className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none"
        >
          Configuración
        </TabsTrigger>
        <TabsTrigger
          value="history"
          className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none"
        >
          Historial
        </TabsTrigger>
      </TabsList>

      <TabsContent value="history" className="mt-0 space-y-2 p-4">
        {audioAssets.map((asset) => (
          <div key={asset.id} className="rounded-xl border p-3">
            <div className="flex items-center gap-2">
              <FileAudio className="size-4 text-muted-foreground" />
              <p className="min-w-0 flex-1 truncate text-xs font-medium">
                {asset.name}
              </p>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onVariant(asset)}
              >
                <WandSparkles className="size-3.5" />
              </Button>
            </div>
            {asset.url && (
              <audio controls src={asset.url} className="mt-2 h-8 w-full" />
            )}
          </div>
        ))}
        {!audioAssets.length && (
          <EmptyState
            icon={AudioLines}
            title="Aún no hay generaciones"
            description="Los audios creados aparecerán aquí para reproducirlos o generar una variante."
          />
        )}
      </TabsContent>

      <TabsContent value="settings" className="mt-0 space-y-5 p-4">
        <div className="flex items-center gap-3 rounded-xl border p-2.5">
          <span className="flex size-14 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 via-teal-500 to-cyan-900 text-white">
            <AudioLines className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium">Diseño de voz y sonido</p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              Ajusta la interpretación y genera una toma vinculada al guion.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-4 rounded-lg border bg-muted/30 p-1">
          {[
            ["voice", "Voz"],
            ["music", "Música"],
            ["sfx", "Efecto"],
            ["ambience", "Ambiente"],
          ].map(([value, label]) => (
            <Button
              key={value}
              variant={kind === value ? "secondary" : "ghost"}
              size="sm"
              className="h-8 px-1 text-[11px]"
              onClick={() => setKind(value)}
            >
              {label}
            </Button>
          ))}
        </div>

        {kind === "voice" ? (
          <>
            <Field label="Voz">
              <Dialog open={voicePickerOpen} onOpenChange={setVoicePickerOpen}>
                <DialogTrigger asChild>
                  <Button
                    variant="outline"
                    className="h-11 w-full justify-between px-3 font-normal"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="size-6 shrink-0 rounded-full bg-gradient-to-br from-slate-300 to-slate-700" />
                      <span className="truncate">
                        {selectedVoice?.name || "Selecciona una voz"}
                      </span>
                    </span>
                    <ChevronRight className="size-4" />
                  </Button>
                </DialogTrigger>
                <DialogContent className="production-sidebar flex max-h-[82vh] max-w-lg flex-col gap-0 overflow-hidden p-0">
                  <DialogHeader className="border-b p-4">
                    <DialogTitle className="flex items-center gap-2 text-base">
                      <ArrowLeft className="size-4" /> Selecciona una voz
                    </DialogTitle>
                  </DialogHeader>
                  <Tabs
                    value={voiceTab}
                    onValueChange={setVoiceTab}
                    className="flex min-h-0 flex-1 flex-col"
                  >
                    <TabsList className="mx-4 mt-3 grid h-11 grid-cols-2 rounded-none border-b bg-transparent p-0">
                      <TabsTrigger
                        value="explore"
                        className="h-11 rounded-none border-b-2 border-transparent data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none"
                      >
                        Explorar
                      </TabsTrigger>
                      <TabsTrigger
                        value="mine"
                        className="h-11 rounded-none border-b-2 border-transparent data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none"
                      >
                        Mis voces
                      </TabsTrigger>
                    </TabsList>
                    <div className="flex gap-2 p-4 pb-2">
                      <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                        <Input
                          value={voiceSearch}
                          onChange={(event) =>
                            setVoiceSearch(event.target.value)
                          }
                          placeholder="Empieza a escribir para buscar…"
                          className="h-10 pl-9"
                        />
                      </div>
                      <Button variant="outline" size="icon">
                        <ListFilter className="size-4" />
                      </Button>
                    </div>
                    <div className="flex gap-1.5 overflow-x-auto px-4 pb-2">
                      {["Idiomas", "Acento", "Categoría", "Género", "Edad"].map(
                        (filter) => (
                          <Badge
                            key={filter}
                            variant="outline"
                            className="whitespace-nowrap font-normal"
                          >
                            + {filter}
                          </Badge>
                        ),
                      )}
                    </div>
                    <ScrollArea className="min-h-0 flex-1 px-2 pb-3">
                      <div className="space-y-0.5">
                        {visibleVoices.map((voice, index) => (
                          <button
                            key={voice.id}
                            type="button"
                            onClick={() => {
                              setVoiceId(String(voice.id));
                              setVoicePickerOpen(false);
                            }}
                            className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-accent"
                          >
                            <span
                              className={cn(
                                "size-9 shrink-0 rounded-full",
                                index % 3 === 0
                                  ? "bg-gradient-to-br from-slate-300 to-slate-800"
                                  : index % 3 === 1
                                    ? "bg-gradient-to-br from-amber-200 to-rose-500"
                                    : "bg-gradient-to-br from-cyan-200 to-indigo-600",
                              )}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-xs font-semibold">
                                {voice.name}
                              </span>
                              <span className="block truncate text-[11px] text-muted-foreground">
                                {voice.description ||
                                  `${voice.language} · ${voice.accent || "Voz de proyecto"}`}
                              </span>
                            </span>
                            <Play className="size-3.5 fill-current" />
                            <MoreVertical className="size-4 text-muted-foreground" />
                          </button>
                        ))}
                        {!visibleVoices.length && (
                          <div className="p-6 text-center">
                            <p className="text-sm font-medium">
                              No hay voces configuradas
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              Añade una voz con su ID del proveedor para poder
                              generar.
                            </p>
                            <Button
                              className="mt-4"
                              onClick={() => {
                                setVoicePickerOpen(false);
                                onOpenVoices();
                              }}
                            >
                              <Plus /> Añadir voz
                            </Button>
                          </div>
                        )}
                      </div>
                    </ScrollArea>
                  </Tabs>
                </DialogContent>
              </Dialog>
            </Field>

            <Field label="Modelo">
              <Select value={modelId} onValueChange={setModelId}>
                <SelectTrigger className="h-11">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="eleven-multilingual-v2">
                    Multilingüe v2
                  </SelectItem>
                  <SelectItem value="eleven-v3-voice">Voz v3</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <SettingsSlider
              label="Velocidad"
              value={SPEED_OPTS[nearestIndex(speed, SPEED_VALUES)]}
              options={SPEED_OPTS}
              onChange={(v) => setSpeed(SPEED_VALUES[SPEED_OPTS.indexOf(v)])}
            />
            <SettingsSlider
              label="Estabilidad"
              value={LEVEL_OPTS[nearestIndex(stability, LEVEL_VALUES)]}
              options={LEVEL_OPTS}
              onChange={(v) => setStability(LEVEL_VALUES[LEVEL_OPTS.indexOf(v)])}
            />
            <SettingsSlider
              label="Similitud"
              value={LEVEL_OPTS[nearestIndex(similarity, LEVEL_VALUES)]}
              options={LEVEL_OPTS}
              onChange={(v) => setSimilarity(LEVEL_VALUES[LEVEL_OPTS.indexOf(v)])}
            />
            <SettingsSlider
              label="Estilo"
              value={LEVEL_OPTS[nearestIndex(style, LEVEL_VALUES)]}
              options={LEVEL_OPTS}
              onChange={(v) => setStyle(LEVEL_VALUES[LEVEL_OPTS.indexOf(v)])}
            />
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium underline decoration-dotted underline-offset-4">
                Anulación de idioma
              </p>
              <Switch
                checked={languageOverride}
                onCheckedChange={setLanguageOverride}
              />
            </div>
            <Field label="Formato de salida">
              <Select value={outputFormat} onValueChange={setOutputFormat}>
                <SelectTrigger className="h-11">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="mp3_44100_128">
                    MP3 44.1 kHz (128 kbps)
                  </SelectItem>
                  <SelectItem value="mp3_44100_192">
                    MP3 44.1 kHz (192 kbps)
                  </SelectItem>
                  <SelectItem value="pcm_44100">WAV PCM 44.1 kHz</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <div className="flex items-center justify-between border-y py-3">
              <p className="text-xs font-medium">Aumento de altavoz</p>
              <Switch
                checked={speakerBoost}
                onCheckedChange={setSpeakerBoost}
              />
            </div>
          </>
        ) : (
          <>
            <Field label="Modelo">
              <Select value={modelId} onValueChange={setModelId}>
                <SelectTrigger className="h-11">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {kind === "music" ? (
                    <SelectItem value="eleven-music-v2">Música</SelectItem>
                  ) : (
                    <SelectItem value="eleven-sfx-v2">
                      Efectos de sonido
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Descripción">
              <Textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                className="min-h-32 resize-y"
                placeholder="Describe con precisión el sonido, su evolución y lo que debe evitar…"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Duración" hint="seg">
                <Input
                  type="number"
                  min="0.5"
                  step="0.1"
                  value={duration}
                  onChange={(event) => setDuration(event.target.value)}
                />
              </Field>
              <Field label="Intensidad">
                <Input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={intensity}
                  onChange={(event) => setIntensity(Number(event.target.value))}
                />
              </Field>
            </div>
            <div className="flex items-center justify-between border-y py-3">
              <p className="text-xs font-medium">Bucle continuo</p>
              <Switch checked={loop} onCheckedChange={setLoop} />
            </div>
          </>
        )}

        <Separator />
        <Field label="Escena">
          <Select
            value={sceneId}
            onValueChange={(value) => {
              setSceneId(value);
              setLineId("__none__");
              setShotId("__none__");
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
        <Field label="Plano" hint="opcional">
          <Select value={shotId} onValueChange={setShotId}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">Sin plano específico</SelectItem>
              {visibleShots.map((shot, index) => (
                <SelectItem key={shot.id} value={String(shot.id)}>
                  {index + 1}. {shot.title || "Plano"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field
          label={kind === "voice" ? "Texto del guion" : "Línea contextual"}
        >
          <Select
            value={lineId}
            onValueChange={(value) => {
              setLineId(value);
              if (value === "__none__") return;
              const line = lines.find(
                (item) => String(item.id) === String(value),
              );
              if (!line) return;
              setSceneId(String(line.scene_id));
              setShotId(line.shot_id ? String(line.shot_id) : "__none__");
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {kind !== "voice" && (
                <SelectItem value="__none__">Contexto general</SelectItem>
              )}
              {selectedSceneLines.map((line) => (
                <SelectItem key={line.id} value={String(line.id)}>
                  {line.text.slice(0, 52) || line.line_type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field
          label="Empieza en"
          hint={sceneId === "__none__" ? "segundos del proyecto" : "segundos de la escena"}
        >
          <Input
            type="number"
            min="0"
            step="0.1"
            value={start}
            onChange={(event) => setStart(event.target.value)}
          />
        </Field>
        {kind === "voice" &&
          selectedVoice &&
          !selectedVoice.provider_voice_id && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              Esta voz todavía no tiene un ID de proveedor y no puede generar
              una toma.
            </p>
          )}
        {!providerReady && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            Conecta un proveedor de voz y sonido para habilitar la generación
            real de voz, música, efectos y ambientes. La edición de perfiles,
            plantillas y timeline sigue disponible.
          </p>
        )}
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="icon"
            title="Restablecer valores"
            onClick={() => {
              setSpeed(1);
              setStability(0.5);
              setSimilarity(0.75);
              setStyle(0);
              setSpeakerBoost(true);
            }}
          >
            <RotateCcw className="size-4" />
          </Button>
          <Button className="flex-1" disabled={!canGenerate} onClick={submit}>
            <Zap /> Generar y guardar
          </Button>
        </div>
      </TabsContent>
    </Tabs>
  );
}

function SoundTemplates({ templates, mediaAssets, onUse, onVariant, run }) {
  const startDrag = (event, asset) => {
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(
      "application/x-xframe-audio-template",
      JSON.stringify({
        assetId: String(asset.id),
        trackKind: asset.templateKind || "music",
      }),
    );
  };
  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold">RECURSOS GUARDADOS</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Guarda desde Biblioteca las generaciones que quieras reutilizar. El
          original nunca se modifica y el agente también puede encontrarlas.
        </p>
      </div>
      {mediaAssets.map((asset) => (
        <Card
          key={asset.id}
          draggable
          onDragStart={(event) => startDrag(event, asset)}
          className="cursor-grab shadow-none active:cursor-grabbing"
        >
          <CardContent className="p-3">
            <div className="flex items-center gap-2">
              <GripVertical className="size-4 shrink-0 text-muted-foreground" />
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
                <FileAudio className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{asset.name}</p>
                <p className="text-[10px] text-muted-foreground">
                  Archivo listo · arrastra a la timeline
                </p>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon">
                    <MoreVertical className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onVariant(asset)}>
                    <WandSparkles className="mr-2 size-4" />
                    Editar con el agente
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            {asset.url &&
              (/video/i.test(String(asset.type)) ? (
                <video
                  src={asset.url}
                  controls
                  className="mt-3 aspect-video w-full rounded-lg bg-black"
                />
              ) : (
                <audio src={asset.url} controls className="mt-3 h-8 w-full" />
              ))}
          </CardContent>
        </Card>
      ))}
      {!mediaAssets.length && (
        <EmptyState
          icon={FileAudio}
          title="No hay archivos de plantilla"
          description="Sube o genera un MP4/audio y aparecerá aquí listo para arrastrarlo a una pista."
        />
      )}
      {!!templates.length && (
        <>
          <Separator />
          <p className="text-xs font-semibold">PRESETS DE GENERACIÓN</p>
          {templates.map((template) => (
            <div key={template.id} className="rounded-xl border p-3">
              <div className="flex items-start gap-2">
                <Waves className="mt-0.5 size-4 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium">{template.name}</p>
                  <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                    {template.prompt}
                  </p>
                </div>
                {!template.builtIn && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() =>
                      run(() => db.deleteAudioTemplate(template.id))
                    }
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="mt-3 w-full"
                onClick={() => onUse(template)}
              >
                Abrir configuración
              </Button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function CueInspector({ cue, assets, scenes, lines, shots, sceneShots, run }) {
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
  const selectedScene = scenes.find((item) => String(item.id) === String(cue.scene_id));
  const sceneOffset = Number(selectedScene?.timeline_start_ms || 0);
  const availableShotIds = new Set(
    (sceneShots || [])
      .filter((item) => !cue.scene_id || String(item.scene_id) === String(cue.scene_id))
      .map((item) => String(item.shot_id)),
  );
  const availableShots = (shots || []).filter(
    (shot) => !cue.scene_id || availableShotIds.has(String(shot.id)),
  );
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
        <Field label="Inicio" hint={selectedScene ? "s de escena" : "s de proyecto"}>
          <DraftInput
            number
            min="0"
            step="0.1"
            value={Math.max(0, (cue.start_ms - sceneOffset) / 1000)}
            onCommit={(seconds) =>
              update({ start_ms: Math.min(sceneOffset + Math.round(seconds * 1000), cue.end_ms - 1) })
            }
          />
        </Field>
        <Field label="Final" hint={selectedScene ? "s de escena" : "s de proyecto"}>
          <DraftInput
            number
            min="0.001"
            step="0.1"
            value={Math.max(0, (cue.end_ms - sceneOffset) / 1000)}
            onCommit={(seconds) =>
              update({ end_ms: Math.max(sceneOffset + Math.round(seconds * 1000), cue.start_ms + 1) })
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
          onValueChange={(script_line_id) => {
            if (script_line_id === "__none__") {
              update({ script_line_id: null });
              return;
            }
            const line = lines.find(
              (item) => String(item.id) === String(script_line_id),
            );
            const nextScene = scenes.find(
              (item) => String(item.id) === String(line?.scene_id),
            );
            const duration = cue.end_ms - cue.start_ms;
            const currentRelativeStart = Math.max(0, cue.start_ms - sceneOffset);
            const nextStart =
              Number(nextScene?.timeline_start_ms || 0) + currentRelativeStart;
            update({
              script_line_id,
              scene_id: line?.scene_id || null,
              shot_id: line?.shot_id || null,
              start_ms: nextStart,
              end_ms: nextStart + duration,
            });
          }}
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
      <Field label="Escena" hint="contexto; tiempos globales">
        <Select
          value={cue.scene_id || "__none__"}
          onValueChange={(scene_id) => {
            const duration = cue.end_ms - cue.start_ms;
            if (scene_id === "__none__") {
              update({ scene_id: null, shot_id: null, script_line_id: null });
              return;
            }
            const nextScene = scenes.find(
              (item) => String(item.id) === String(scene_id),
            );
            const relativeStart = selectedScene
              ? Math.max(0, cue.start_ms - sceneOffset)
              : 0;
            const nextStart =
              Number(nextScene?.timeline_start_ms || 0) + relativeStart;
            update({
              scene_id,
              shot_id: null,
              script_line_id: null,
              start_ms: nextStart,
              end_ms: nextStart + duration,
            });
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Sin escena asignada</SelectItem>
            {scenes.map((scene, index) => (
              <SelectItem key={scene.id} value={String(scene.id)}>
                {index + 1}. {scene.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Plano" hint="contexto opcional">
        <Select
          value={cue.shot_id || "__none__"}
          onValueChange={(shot_id) =>
            update({ shot_id: shot_id === "__none__" ? null : shot_id })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Sin plano asignado</SelectItem>
            {availableShots.map((shot, index) => (
              <SelectItem key={shot.id} value={String(shot.id)}>
                {index + 1}. {shot.title || "Plano"}
              </SelectItem>
            ))}
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

// Icono minimalista por categoría (biblioteca de sonido + voces). Sustituye a los
// emojis: línea fina en blanco sobre la imagen de gradiente.
const CATEGORY_ICONS = {
  animales: PawPrint,
  armas: Crosshair,
  ascensos: TrendingUp,
  bajo: Volume2,
  braams: Clapperboard,
  "ciencia-ficcion": Rocket,
  clima: CloudLightning,
  cuerdas: Music2,
  deportes: Trophy,
  dispositivos: Cpu,
  drones: Satellite,
  ui: MousePointerClick,
  escuela: GraduationCap,
  explosiones: Flame,
  magia: Sparkles,
  humano: UserRound,
  naturaleza: Leaf,
  ambiente: Building2,
  narracion: BookOpen,
  social: Smartphone,
  educacion: GraduationCap,
  conversacion: MessageCircle,
  podcast: Mic2,
  corporativo: Briefcase,
  comercial: ShoppingBag,
};

// Carril horizontal de categorías: 3 tarjetas casi cuadradas visibles a la vez, con
// las imágenes de gradiente como fondo, icono minimalista y sin barra de scroll (se
// desplaza con rueda/arrastre y con las flechas laterales).
function CategoryGrid({ categories, active, onSelect }) {
  const railRef = useRef(null);
  const nudge = (dir) => {
    const rail = railRef.current;
    if (rail) rail.scrollBy({ left: dir * rail.clientWidth * 0.9, behavior: "smooth" });
  };
  return (
    <div className="group/rail relative">
      <div
        ref={railRef}
        className="no-scrollbar grid snap-x snap-mandatory grid-flow-col auto-cols-[calc((100%-1rem)/3)] gap-2 overflow-x-auto scroll-smooth"
      >
        {categories.map((cat) => {
          const Icon = CATEGORY_ICONS[cat.id] ?? Music2;
          return (
            <button
              key={cat.id}
              type="button"
              onClick={() => onSelect(active === cat.name ? null : cat.name)}
              className={cn(
                // El ring de selección va por dentro (inset): con offset hacia fuera lo
                // recortaba el overflow del carril en la primera y última tarjeta.
                "relative flex aspect-[5/4] min-w-0 snap-start flex-col justify-between overflow-hidden rounded-2xl p-2.5 text-left text-black shadow-sm transition-transform hover:scale-[1.02]",
                active === cat.name && "ring-2 ring-inset ring-black",
              )}
              style={{
                backgroundImage: `url(${gradientUrl(cat.id)})`,
                backgroundSize: "cover",
                backgroundPosition: "center",
              }}
            >
              <Icon className="size-4" strokeWidth={1.75} />
              <span className="line-clamp-2 text-[10px] font-semibold leading-tight">
                {cat.name}
              </span>
            </button>
          );
        })}
      </div>
      <button
        type="button"
        onClick={() => nudge(-1)}
        aria-label="Categorías anteriores"
        className="absolute -left-1.5 top-1/2 z-10 flex size-6 -translate-y-1/2 items-center justify-center rounded-full border bg-background/90 text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground group-hover/rail:opacity-100"
      >
        <ChevronLeft className="size-3.5" />
      </button>
      <button
        type="button"
        onClick={() => nudge(1)}
        aria-label="Más categorías"
        className="absolute -right-1.5 top-1/2 z-10 flex size-6 -translate-y-1/2 items-center justify-center rounded-full border bg-background/90 text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground group-hover/rail:opacity-100"
      >
        <ChevronRight className="size-3.5" />
      </button>
    </div>
  );
}

// Pestaña Biblioteca: catálogo de efectos por categoría (estilo librería de SFX) +
// los sonidos ya guardados del proyecto. Explorar pide al agente que genere el efecto y
// lo coloque; Guardados añade un asset existente a la pista elegida.
function SoundBrowser({ audioAssets, trackMeta, onUseEffect, onAddAsset }) {
  const [tab, setTab] = useState("explore");
  const [category, setCategory] = useState(null);
  const [query, setQuery] = useState("");
  const effects = SFX_LIBRARY.filter(
    (effect) =>
      (!category || effect.category === category) &&
      `${effect.title} ${effect.category} ${effect.sub}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex gap-2 border-b px-3 pt-2">
        {[
          ["explore", "Explorar"],
          ["saved", "Guardados"],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={cn(
              "border-b-2 px-1.5 pb-2 text-xs font-semibold transition-colors",
              tab === value
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "explore" ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-3 p-3">
            <CategoryGrid
              categories={SFX_CATEGORIES}
              active={category}
              onSelect={setCategory}
            />
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Buscar efectos de sonido…"
                className="h-9 pl-8 text-xs"
              />
            </div>
            {category && (
              <button
                type="button"
                onClick={() => setCategory(null)}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                ← Todas las categorías · {category}
              </button>
            )}
            <div className="space-y-1">
              {effects.map((effect) => (
                <div
                  key={effect.id}
                  className="flex items-center gap-2.5 rounded-lg border p-2"
                >
                  <button
                    type="button"
                    className="flex size-8 shrink-0 items-center justify-center rounded-full text-white shadow-sm"
                    style={{
                      backgroundImage: `url(${gradientUrl(effect.id)})`,
                      backgroundSize: "cover",
                      backgroundPosition: "center",
                    }}
                    aria-label="Previsualizar"
                  >
                    <Play className="size-3.5 fill-current drop-shadow-sm" />
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-[11px] font-medium leading-snug">
                      {effect.title}
                    </p>
                    <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                      {effect.category} › {effect.sub} · {effect.duration} ·{" "}
                      {effect.downloads} ↓
                    </p>
                  </div>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-7 shrink-0"
                    onClick={() => onUseEffect(effect)}
                    title="Generar y añadir a la mezcla"
                  >
                    <Plus className="size-4" />
                  </Button>
                </div>
              ))}
              {!effects.length && (
                <p className="px-1 py-4 text-center text-[11px] text-muted-foreground">
                  Sin resultados para esa búsqueda.
                </p>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-1 p-3">
            {audioAssets.map((asset) => (
              <div
                key={asset.id}
                className="flex items-center gap-2.5 rounded-lg border p-2"
              >
                <FileAudio className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium">{asset.name}</p>
                  <p className="text-[10px] text-muted-foreground">
                    Listo para usar
                  </p>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="size-7">
                      <Plus className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {Object.entries(trackMeta).map(([kind, [, label]]) => (
                      <DropdownMenuItem
                        key={kind}
                        onClick={() => onAddAsset(asset, kind)}
                      >
                        Añadir a {label.toLowerCase()}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))}
            {!audioAssets.length && (
              <EmptyState
                icon={FileAudio}
                title="Sin sonidos guardados"
                description="Genera o sube audio desde Assets y aparecerá aquí."
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Pestaña Voces: lista de voces del catálogo (Explorar) y las del proyecto (Mis Voces),
// con búsqueda y filtros, al estilo de una librería de voces.
function VoicesBrowser({ projectId, voices, run, onAskAgent }) {
  const [tab, setTab] = useState("explore");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(null);
  const catalog = VOICE_CATALOG.filter(
    (voice) =>
      (!category || voice.category === category) &&
      `${voice.name} ${voice.tagline} ${voice.description} ${voice.language} ${voice.gender} ${voice.category}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const importVoice = (voice) =>
    run(() =>
      db.createVoiceProfile(projectId, {
        name: voice.name,
        description: voice.tagline,
        language: voice.language === "Español" ? "es" : "en",
        accent: voice.accent || "",
        source: "library",
        status: "draft",
      }),
    );
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex gap-2 border-b px-3 pt-2">
        {[
          ["explore", "Explorar"],
          ["mine", "Mis Voces"],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={cn(
              "border-b-2 px-1.5 pb-2 text-xs font-semibold transition-colors",
              tab === value
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="space-y-2 border-b p-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Empieza a escribir para buscar…"
            className="h-9 pl-8 text-xs"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {["Idiomas", "Acento", "Categoría", "Género", "Edad"].map((filter) => (
            <button
              key={filter}
              type="button"
              className="rounded-full border border-dashed px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-foreground/50 hover:text-foreground"
            >
              + {filter}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="space-y-1 p-3">
          {tab === "explore" ? (
            <div className="space-y-2">
              <CategoryGrid
                categories={VOICE_CATEGORIES}
                active={category}
                onSelect={setCategory}
              />
              {category && (
                <button
                  type="button"
                  onClick={() => setCategory(null)}
                  className="text-[11px] text-muted-foreground hover:text-foreground"
                >
                  ← Todas las categorías · {category}
                </button>
              )}
              <div className="space-y-1">
                {catalog.map((voice) => (
                  <div
                    key={voice.id}
                    className="flex items-center gap-2.5 rounded-lg border p-2"
                  >
                    <span
                      className="size-9 shrink-0 rounded-full ring-1 ring-black/80"
                      style={{
                        backgroundImage: `url(${gradientUrl(voice.id)})`,
                        backgroundSize: "cover",
                        backgroundPosition: "center",
                      }}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold">
                        {voice.name}{" "}
                        <span className="font-normal text-muted-foreground">
                          — {voice.tagline}
                        </span>
                      </p>
                      <p className="truncate text-[10px] text-muted-foreground">
                        {voice.description}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="flex size-7 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted"
                      aria-label="Previsualizar"
                    >
                      <Play className="size-3.5" />
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="size-7">
                          <MoreVertical className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => importVoice(voice)}>
                          <Plus className="mr-2 size-4" />
                          Importar a Mis Voces
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                ))}
                {!catalog.length && (
                  <p className="px-1 py-4 text-center text-[11px] text-muted-foreground">
                    Sin voces para ese filtro.
                  </p>
                )}
              </div>
            </div>
          ) : (
                <>
                  {voices.map((voice) => {
                    return (
                      <div
                        key={voice.id}
                        className="flex items-center gap-2.5 rounded-lg border p-2"
                      >
                        <span
                          className="size-9 shrink-0 rounded-full ring-1 ring-black/80"
                          style={{
                            backgroundImage: `url(${gradientUrl(voice.id)})`,
                            backgroundSize: "cover",
                            backgroundPosition: "center",
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-semibold">
                            {voice.name}
                          </p>
                          <p className="truncate text-[10px] text-muted-foreground">
                            {voice.provider_voice_id
                              ? `Listo · ${voice.provider || "proveedor"}`
                              : "Borrador · sin ID de voz"}
                          </p>
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 text-destructive"
                          onClick={() =>
                            run(() => db.deleteVoiceProfile(voice.id))
                          }
                          aria-label="Eliminar voz"
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                    );
                  })}
                  {!voices.length && (
                    <EmptyState
                      icon={UserRound}
                      title="No hay voces configuradas"
                      description="Importa una voz del catálogo o pídeselas al agente."
                    />
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={onAskAgent}
                  >
                    <Sparkles /> Crear voces con el agente
                  </Button>
                </>
              )}
        </div>
      </div>
    </div>
  );
}

export function AudioStudio({
  projectId,
  assets = [],
  resources = [],
  onSeedChat,
  onSendAgent,
  onProductionChange,
  productionData,
}) {
  const { data, loading, saving, error, reload, run } =
    useProduction(projectId, onProductionChange, productionData);
  const [cueId, setCueId] = useState(null);
  const [brief, setBrief] = useState("");
  const [briefOpen, setBriefOpen] = useState(false);
  const [libraryTab, setLibraryTab] = useState("library");
  const [composerSeed, setComposerSeed] = useState(null);
  const [providerStatus, setProviderStatus] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const previewContextRef = useRef(null);
  const previewSourcesRef = useRef([]);
  const previewTimerRef = useRef(null);
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
          /audio|sound|sonido|music|música/i.test(String(asset.type)) &&
          asset.status === "ready",
      ),
    [assets],
  );
  const mentionAsset = useCallback(
    (asset) => {
      const ref = resources.find(
        (item) =>
          ["asset", "element"].includes(item.type) &&
          String(item.id) === String(asset?.id),
      );
      return ref ? `@${ref.mention}` : `asset ${asset?.id}`;
    },
    [resources],
  );
  const templateAssets = useMemo(
    () =>
      assets.filter(
        (asset) =>
          asset.status === "ready" &&
          /audio|video|mp4/i.test(
            `${asset.type || ""} ${asset.url || ""} ${asset.path || ""}`,
          ),
      ),
    [assets],
  );
  const templateAssetIds = useMemo(
    () =>
      new Set(
        data.audioTemplates
          .filter((template) => template.asset_id)
          .map((template) => String(template.asset_id)),
      ),
    [data.audioTemplates],
  );
  const savedTemplateAssets = useMemo(
    () =>
      templateAssets
        .filter((asset) => templateAssetIds.has(String(asset.id)))
        .map((asset) => ({
          ...asset,
          templateKind:
            data.audioTemplates.find(
              (template) => String(template.asset_id) === String(asset.id),
            )?.kind || "music",
        })),
    [data.audioTemplates, templateAssetIds, templateAssets],
  );
  const totalMs = Math.max(10000, ...data.cues.map((cue) => cue.end_ms || 0));
  const cue =
    data.cues.find((item) => String(item.id) === String(cueId)) || null;
  const approved = data.cues.filter((item) => item.approved).length;

  const stopPreview = async () => {
    if (previewTimerRef.current) clearTimeout(previewTimerRef.current);
    previewTimerRef.current = null;
    previewSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        // A source may already have reached its deterministic end.
      }
    });
    previewSourcesRef.current = [];
    const context = previewContextRef.current;
    previewContextRef.current = null;
    if (context && context.state !== "closed") await context.close();
    setPreviewing(false);
  };

  const playPreview = async () => {
    await stopPreview();
    setPreviewError("");
    if (!data.cues.length) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      setPreviewError("Este navegador no permite previsualizar una mezcla multipista.");
      return;
    }
    const context = new AudioContextClass();
    previewContextRef.current = context;
    try {
      await context.resume();
      const baseTime = context.currentTime + 0.08;
      const speechWindows = data.cues
        .filter((item) => ["dialogue", "voiceover"].includes(item.track_kind))
        .map((item) => [item.start_ms / 1000, item.end_ms / 1000]);
      const decoded = await Promise.all(
        data.cues.map(async (item) => {
          const asset = assets.find((candidate) => String(candidate.id) === String(item.asset_id));
          if (!asset?.url) throw new Error(`El clip ${item.id} no tiene una URL reproducible.`);
          const response = await fetch(asset.url);
          if (!response.ok) throw new Error(`No se pudo cargar ${asset.name || item.asset_id}.`);
          return [item, await context.decodeAudioData(await response.arrayBuffer())];
        }),
      );
      for (const [item, buffer] of decoded) {
        const source = context.createBufferSource();
        const gain = context.createGain();
        const panner = context.createStereoPanner?.();
        source.buffer = buffer;
        source.loop = Boolean(item.loop);
        const cueStart = baseTime + item.start_ms / 1000;
        const cueEnd = baseTime + item.end_ms / 1000;
        const duration = Math.max(0.001, (item.end_ms - item.start_ms) / 1000);
        const normalGain = Math.pow(10, Number(item.gain_db || 0) / 20);
        const fadeIn = Math.min(duration, Number(item.fade_in_ms || 0) / 1000);
        const fadeOut = Math.min(duration, Number(item.fade_out_ms || 0) / 1000);
        gain.gain.setValueAtTime(fadeIn ? 0.0001 : normalGain, cueStart);
        if (fadeIn) gain.gain.linearRampToValueAtTime(normalGain, cueStart + fadeIn);
        if (fadeOut) {
          gain.gain.setValueAtTime(normalGain, Math.max(cueStart, cueEnd - fadeOut));
          gain.gain.linearRampToValueAtTime(0.0001, cueEnd);
        }
        if (["music", "ambience"].includes(item.track_kind) && item.ducking_db != null) {
          const ducked = normalGain * Math.pow(10, Number(item.ducking_db) / 20);
          speechWindows.forEach(([start, end]) => {
            const overlapStart = Math.max(item.start_ms / 1000, start);
            const overlapEnd = Math.min(item.end_ms / 1000, end);
            if (overlapEnd > overlapStart) {
              gain.gain.setTargetAtTime(ducked, baseTime + overlapStart, 0.03);
              gain.gain.setTargetAtTime(normalGain, baseTime + overlapEnd, 0.08);
            }
          });
        }
        source.connect(gain);
        if (panner) {
          panner.pan.value = Number(item.pan || 0);
          gain.connect(panner).connect(context.destination);
        } else {
          gain.connect(context.destination);
        }
        const sourceOffset = Math.max(0, Number(item.source_in_ms || 0) / 1000);
        if (!source.loop && sourceOffset >= buffer.duration) {
          throw new Error(
            `La entrada de fuente de ${assets.find((candidate) => String(candidate.id) === String(item.asset_id))?.name || item.id} está fuera del archivo.`,
          );
        }
        const availableDuration = source.loop
          ? duration
          : Math.min(duration, Math.max(0.001, buffer.duration - sourceOffset));
        source.start(
          cueStart,
          source.loop ? sourceOffset % buffer.duration : sourceOffset,
          availableDuration,
        );
        previewSourcesRef.current.push(source);
      }
      setPreviewing(true);
      previewTimerRef.current = setTimeout(() => void stopPreview(), totalMs + 300);
    } catch (previewFailure) {
      await stopPreview();
      setPreviewError(previewFailure?.message || "No se pudo previsualizar la mezcla.");
    }
  };

  useEffect(() => {
    if (cueId && !data.cues.some((item) => String(item.id) === String(cueId)))
      setCueId(null);
  }, [data.cues, cueId]);
  useEffect(() => {
    let alive = true;
    agentApi(`/projects/${projectId}/provider-status`)
      .then((status) => alive && setProviderStatus(status))
      .catch(() => alive && setProviderStatus(null));
    return () => {
      alive = false;
    };
  }, [projectId]);
  useEffect(() => () => void stopPreview(), []); // eslint-disable-line react-hooks/exhaustive-deps
  const addCue = async (asset, track_kind = "music", requestedStart = null) => {
    const lastEnd = Math.max(
      0,
      ...data.cues
        .filter((item) => item.track_kind === track_kind)
        .map((item) => item.end_ms || 0),
    );
    const startMs =
      requestedStart === null ? lastEnd : Math.max(0, requestedStart);
    const durationMs = Math.max(
      500,
      Number(asset.duration_ms || asset.params?.duration_ms || 5000),
    );
    let created;
    const ok = await run(async () => {
      created = await db.createAudioCue(projectId, {
        asset_id: asset.id,
        track_kind,
        start_ms: startMs,
        end_ms: startMs + durationMs,
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
  const askForVoices = () =>
    (onSendAgent || onSeedChat)?.(
      "Crea los perfiles de voz que necesito para este proyecto. Para cada voz, define nombre, idioma, acento, tono y uso narrativo; guárdala con create_voice_profile en Audio > Voces con su proveedor e ID reutilizable. Si el proveedor no puede crear o devolver un ID de voz, guárdala honestamente como borrador y dime qué falta. No clones ni imites voces reales sin consentimiento verificable.",
    );
  const inferTemplateKind = (asset) => {
    const description =
      `${asset.name || ""} ${asset.meta || ""} ${asset.type || ""}`.toLowerCase();
    if (/music|música|song|track|score/.test(description)) return "music";
    if (/ambient|ambience|room tone|atmósfera/.test(description))
      return "ambience";
    return "sfx";
  };
  const saveAsVoice = (asset) => {
    const providerVoiceId =
      asset.provider_voice_id ||
      asset.voice_id ||
      asset.params?.voice_id ||
      null;
    return run(() =>
      db.createVoiceProfile(projectId, {
        name: asset.name || "Voz guardada",
        provider: asset.provider || "generated",
        provider_voice_id: providerVoiceId,
        source: "designed",
        description: `Guardada desde Biblioteca (asset ${asset.id}).`,
        status: providerVoiceId ? "ready" : "draft",
      }),
    );
  };
  const saveAsTemplate = (asset) =>
    run(() =>
      db.createAudioTemplate(projectId, {
        name: asset.name || "Audio guardado",
        asset_id: asset.id,
        kind: inferTemplateKind(asset),
        prompt: asset.meta || `Reutilizar el asset ${asset.id}.`,
        duration_ms: asset.duration_ms || asset.params?.duration_ms || null,
      }),
    );
  const generateSound = (config) => {
    const scene = data.scenes.find(
      (item) => String(item.id) === String(config.scene_id),
    );
    const line = data.lines.find(
      (item) => String(item.id) === String(config.script_line_id),
    );
    const endMs = config.start_ms + config.duration_ms;
    if (config.kind === "voice") {
      (onSendAgent || onSeedChat)?.(
        `Genera una toma de voz reutilizable con generate_audio y guárdala en Assets.\n` +
        `Modelo obligatorio: ${config.model_id}. Perfil de voz: ${config.voice_profile_id}. ` +
          `Usa script_line_ids=["${config.script_line_id}"] como única fuente verbal. ` +
          `Línea exacta del guion: ${config.script_line_id} — “${line?.text || config.prompt}”. No cambies ninguna palabra.\n` +
          `Formato: ${config.output_format}. Ajustes interpretativos guardados en el perfil: ${JSON.stringify(config.settings)}.\n` +
          `Colócala desde ${config.start_ms} ms hasta ${endMs} ms usando placement_start_ms y placement_end_ms. ` +
          `Usa scene_id=${config.scene_id || "null"}, shot_id=${config.shot_id || "null"} y placement_time_basis=${config.placement_time_basis}. ` +
          `Estima los créditos antes de generar.`,
      );
      return;
    }
    (onSendAgent || onSeedChat)?.(
      `Genera un asset de audio reutilizable con generate_audio y guárdalo en Assets.\n` +
        `Tipo: ${config.kind}. Descripción aprobada: ${config.prompt}\n` +
        `Modelo obligatorio: ${config.model_id}.\n` +
        `Duración: ${config.duration_ms / 1000}s. Usa prompt_influence=${config.intensity}. Loop: ${config.loop}.\n` +
        (scene
          ? `Contexto obligatorio: escena ${scene.id} (“${scene.title}”), usando su guion completo y sus assets vinculados.\n`
          : "") +
        (line
          ? `Línea contextual exacta: ${line.id} — “${line.text}”. No cambies sus palabras.\n`
          : "") +
        `Colócalo automáticamente en el plan de audio desde ${config.start_ms} ms hasta ${endMs} ms usando placement_start_ms y placement_end_ms. ` +
        `Usa scene_id=${config.scene_id || "null"}, shot_id=${config.shot_id || "null"} y placement_time_basis=${config.placement_time_basis}. ` +
        `No me pidas elegir una voz concreta: para sonidos, música y ambientes la interpretación final corresponde al modelo. ` +
        `Estima los créditos antes de encolar la generación.`,
    );
  };
  const useTemplate = (template) => {
    setComposerSeed({ ...template, selectedAt: Date.now() });
    setLibraryTab("create");
  };
  const varyAsset = (asset) =>
    onSeedChat?.(
      `Crea una variante del archivo ${mentionAsset(asset)} (id ${asset.id}) sin modificar el original. Conserva duración y función narrativa; pregúntame qué propiedad debo cambiar, registra el linaje y guarda el resultado como un asset nuevo.`,
    );
  const dropTemplate = (event, trackKind) => {
    event.preventDefault();
    const raw = event.dataTransfer.getData(
      "application/x-xframe-audio-template",
    );
    if (!raw) return;
    try {
      const payload = JSON.parse(raw);
      const asset = templateAssets.find(
        (item) => String(item.id) === String(payload.assetId),
      );
      if (!asset) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const ratio = Math.min(
        1,
        Math.max(0, (event.clientX - rect.left) / rect.width),
      );
      addCue(
        asset,
        trackKind || payload.trackKind || "music",
        Math.round(totalMs * ratio),
      );
    } catch {
      // Un payload externo o corrupto no debe afectar a la timeline.
    }
  };

  return (
    <TooltipProvider>
      {/* Rejilla 2×2: el sidebar ocupa toda la altura (las dos filas de su columna) y
          el encabezado solo existe sobre la columna principal. Así el panel no deja
          hueco arriba y el toggle queda fuera del sidebar, a la altura del resto de
          botones. */}
      <div
        className="grid h-full min-h-0 grid-rows-[3rem_minmax(0,1fr)] overflow-hidden rounded-xl border bg-background"
        style={{
          gridTemplateColumns: `${audioLibraryVisible ? "400px" : "0px"} minmax(440px, 1fr)`,
        }}
      >
        {/* El toggle va SIEMPRE el primero a la izquierda del encabezado: pegado al
            sidebar cuando está abierto y en ese mismo hueco cuando está cerrado. */}
        <header className="col-start-2 row-start-1 flex min-w-0 items-center gap-3 px-4">
          <SidebarToggle
            side="left"
            expanded={audioLibraryVisible}
            onChange={setAudioLibraryVisible}
            label="biblioteca de sonido"
          />
          <div className="ml-auto flex items-center gap-3">
            {providerStatus && (
              <div className="hidden items-center gap-1.5 xl:flex">
                <Badge variant="outline" className="gap-1 text-[10px]">
                  <span className={cn("size-1.5 rounded-full", providerStatus.audio ? "bg-emerald-500" : "bg-amber-500")} />
                  Voz y sonido {providerStatus.audio ? "listos" : "sin proveedor"}
                </Badge>
                <Badge variant="outline" className="gap-1 text-[10px]">
                  <span className={cn("size-1.5 rounded-full", providerStatus.lipsync ? "bg-emerald-500" : "bg-amber-500")} />
                  Lipsync {providerStatus.lipsync ? "listo" : "sin proveedor"}
                </Badge>
              </div>
            )}
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
          <aside
            className={cn(
              "production-sidebar relative col-start-1 row-span-2 row-start-1 flex min-h-0 flex-col",
              audioLibraryVisible
                ? "overflow-hidden border-r bg-muted/10"
                : "overflow-visible",
            )}
          >
            {audioLibraryVisible && (
              loading ? <ProductionListSkeleton rows={6} /> : <Tabs
                value={libraryTab}
                onValueChange={setLibraryTab}
                className="flex min-h-0 flex-1 flex-col"
              >
                <TabsList className="mx-3 mt-3 grid h-10 w-auto grid-cols-3 p-1">
                  <TabsTrigger value="library">Biblioteca</TabsTrigger>
                  <TabsTrigger value="create">Crear</TabsTrigger>
                  <TabsTrigger value="voices">Voces</TabsTrigger>
                </TabsList>
                <TabsContent value="library" className="min-h-0 flex-1">
                  <SoundBrowser
                    audioAssets={audioAssets}
                    trackMeta={trackMeta}
                    onAddAsset={addCue}
                    onUseEffect={(effect) =>
                      (onSendAgent || onSeedChat)?.(
                        `Genera un efecto de sonido con generate_audio y guárdalo en Assets: "${effect.title}". ` +
                          `Duración aproximada ${effect.duration}. Colócalo en la pista de ${effect.track === "ambience" ? "ambiente" : effect.track === "music" ? "música" : "efectos"} de la mezcla. Estima créditos antes de generar.`,
                      )
                    }
                  />
                </TabsContent>
                <TabsContent value="create" className="min-h-0 flex-1">
                  <ScrollArea className="h-full">
                    <div className="p-3">
                      <SoundComposer
                        projectId={projectId}
                        scenes={data.scenes}
                        lines={data.lines}
                        sceneShots={data.sceneShots}
                        shots={data.shots}
                        voices={data.voices}
                        audioAssets={audioAssets}
                        providerReady={Boolean(providerStatus?.audio)}
                        seed={composerSeed}
                        onGenerate={generateSound}
                        onVariant={varyAsset}
                        onOpenVoices={() => setLibraryTab("voices")}
                        run={run}
                      />
                    </div>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="voices" className="min-h-0 flex-1">
                  <VoicesBrowser
                    projectId={projectId}
                    voices={data.voices}
                    run={run}
                    onAskAgent={askForVoices}
                  />
                </TabsContent>
              </Tabs>
            )}
          </aside>

          <main className="col-start-2 row-start-2 flex min-h-0 flex-col overflow-hidden">
            <div className="min-h-0 flex-1 overflow-auto p-5">
              {loading ? (
                <AudioWorkspaceSkeleton />
              ) : (
                <div className="mx-auto max-w-none">
                  {previewError && (
                    <p className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
                      {previewError}
                    </p>
                  )}
                  <MixTimeline
                    tracks={Object.entries(trackMeta).map(
                      ([kind, [Icon, label]]) => ({
                        kind,
                        Icon,
                        label,
                        hex: TRACK_HEX[kind] || "#64748b",
                        cues: data.cues
                          .filter((item) => item.track_kind === kind)
                          .map((item) => ({
                            id: item.id,
                            start_ms: item.start_ms,
                            end_ms: item.end_ms,
                            gain_db: item.gain_db,
                            locked: item.locked,
                            label:
                              assets.find(
                                (asset) =>
                                  String(asset.id) === String(item.asset_id),
                              )?.name || label,
                          })),
                      }),
                    )}
                    totalMs={totalMs}
                    playing={previewing}
                    onToggle={() => {
                      if (previewing) void stopPreview();
                      else void playPreview();
                    }}
                    selectedCueId={cueId}
                    onSelectCue={setCueId}
                    onDropTemplate={dropTemplate}
                    onMoveCue={(id, start_ms, end_ms, track_kind) =>
                      run(() =>
                        db.updateAudioCue(id, { start_ms, end_ms, track_kind }),
                      )
                    }
                  />
                  {cue && (
                    <div className="mt-4 rounded-xl border bg-muted/10 p-4">
                      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Editar clip
                      </p>
                      <CueInspector
                        cue={cue}
                        assets={assets}
                        scenes={data.scenes}
                        lines={data.lines}
                        shots={data.shots}
                        sceneShots={data.sceneShots}
                        run={run}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          </main>
      </div>
    </TooltipProvider>
  );
}
