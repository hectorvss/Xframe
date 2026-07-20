import React, { useState, useRef, useEffect } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowLeft,
  ArrowRight,
  Search,
  LayoutDashboard,
  FolderKanban,
  Users,
  Settings,
  Plug,
  BookOpen,
  Sparkles,
  CreditCard,
  Shield,
  Code2,
  Globe,
  Plus,
  ChevronDown,
  Mic,
  ArrowUp,
  MoreHorizontal,
  ExternalLink,
  Check,
  Grid2X2,
  PanelLeft,
  Monitor,
  Share2,
  Undo2,
  Redo2,
  Paperclip,
  X,
  Ban,
  User,
  Palette,
  LifeBuoy,
  Home,
  LogOut,
  Gift,
  Zap,
  Bell,
  Pencil,
  Copy,
  Info,
  ChevronRight,
  Download,
  Link,
  UserPlus,
  ChevronsUpDown,
  Clock,
  History,
  RefreshCw,
  Layers,
  FileText,
  Cloud,
  ThumbsUp,
  ThumbsDown,
  BarChart3,
  Bookmark,
  Play,
  Image as ImageIcon,
  Video,
  Volume2,
  VolumeX,
  Minus,
  Camera as CameraIcon,
  Wand2,
  AtSign,
  MessageCircle,
  Frame,
  Maximize2,
  GripVertical,
  Heading1,
  Heading2,
  List,
  ListTodo,
  Quote,
  Type,
  Trash2,
  Upload,
  Lightbulb,
  Mail,
  Smartphone,
  Pause,
  SkipBack,
  SkipForward,
  Repeat,
} from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Button as UIButton } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { uploadAsset } from "@/lib/supabase";
import { db } from "@/lib/db";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
} from "@/components/ui/chart";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
} from "recharts";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  StudioProvider,
  useStudio,
  useProjectData,
  titleFromPrompt,
} from "@/lib/studio";
import {
  sendMessage,
  conversationIdFor,
  labelForTool,
  AGENT_DOWN_MESSAGE,
} from "@/lib/agent";
import { buildUIContext } from "@/lib/uiContext";
import "./index.css";
import "./styles.css";

const go = (p) => {
  history.pushState({}, "", p);
  dispatchEvent(new PopStateEvent("popstate"));
};
function useResizableWidth(key, initial, min, max) {
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem(key));
    return saved >= min && saved <= max ? saved : initial;
  });
  const onResize = (clientX) => {
    const next = Math.min(max, Math.max(min, Math.round(clientX)));
    setWidth(next);
    localStorage.setItem(key, String(next));
  };
  return [width, onResize];
}
function ResizeHandle({ onResize }) {
  const start = (e) => {
    e.preventDefault();
    const move = (ev) => onResize(ev.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div
      onPointerDown={start}
      title="Arrastra para redimensionar"
      className="absolute inset-y-0 -right-0.5 z-30 w-1.5 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50"
    />
  );
}
const XframeHeart = ({ size = 24, className = "" }) => (
  <img
    className={`heart-mark ${className}`}
    src="/lovable-logo.svg"
    width={size}
    height={size}
    alt=""
    aria-hidden="true"
  />
);
const Button = ({
  children,
  primary = false,
  onClick,
  className = "",
  fullWidth = false,
}) => (
  <UIButton
    variant={primary ? "default" : "outline"}
    onClick={onClick}
    className={`${fullWidth ? "w-full " : ""}${className}`.trim()}
  >
    {children}
  </UIButton>
);
const Logo = () => (
  <button
    className="flex items-center gap-2 text-lg font-semibold"
    onClick={() => go("/es")}
  >
    <XframeHeart size={22} />
    Xframe
  </button>
);

const NAV_LINKS = [
  "Soluciones",
  "Recursos",
  "Comunidad",
  "Precios",
  "Seguridad",
];

function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
    return () => removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header
      className={cn(
        "sticky top-0 z-30 border-b [transition:background-color_.25s,border-color_.25s]",
        scrolled
          ? "border-border bg-white/70 backdrop-blur-md"
          : "border-transparent",
      )}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-6">
        <Logo />
        <nav className="hidden flex-1 items-center gap-6 text-sm text-muted-foreground md:flex">
          {NAV_LINKS.map((l) => (
            <button
              key={l}
              className="transition-colors hover:text-foreground"
              onClick={() => l === "Precios" && go("/es/pricing")}
            >
              {l}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2 md:ml-0">
          <UIButton variant="ghost" onClick={() => go("/es?auth=login")}>
            Iniciar sesión
          </UIButton>
          <UIButton onClick={() => go("/dashboard")}>Empezar</UIButton>
        </div>
      </div>
    </header>
  );
}
const templates = [
  [
    "Tráiler cinematográfico",
    "Ritmo alto, cortes secos y música épica",
    "/assets/maison.webp",
  ],
  [
    "Videoclip musical",
    "Planos sincronizados al beat con color intenso",
    "/assets/inspo.jpg",
  ],
  [
    "Spot de producto",
    "Producto en primer plano con luz de estudio",
    "/assets/personal-blog.png",
  ],
  ["Moda editorial", "Cámara lenta, texturas y luz natural", "/assets/vesper.webp"],
  [
    "Documental",
    "Tono sobrio, planos largos y voz en off",
    "/assets/continuum.jpg",
  ],
  [
    "Anuncio vertical",
    "Formato 9:16 para redes, impacto en los primeros segundos",
    "/assets/lovable-slides.webp",
  ],
  [
    "Noir cinematográfico",
    "Alto contraste, sombras duras y ambiente nocturno",
    "/assets/prompt-frame.webp",
  ],
  [
    "Time-lapse aéreo",
    "Planos de dron y paisajes en movimiento",
    "/assets/ecommerce.webp",
  ],
];
const cinematicModels = [
  ["Cinema Studio 3.5", "Selección de cámara, presets de estilo y director IA", "NEW"],
  ["Cinema Studio 3.0", "Control avanzado de cámara y speed ramp"],
  ["Cinema Studio 2.5", "Movimientos de cámara con fotograma inicial"],
];
// [nombre, dominio (logo), resolución, duración, badge]
const featuredModels = [
  ["Seedance 2.0", "bytedance.com", "4K", "4s-15s"],
  ["Seedance 2.0 Mini", "bytedance.com", "720p", "4s-15s", "NEW"],
  ["Seedance 2.0 Fast", "bytedance.com", "720p", "4s-15s"],
  ["Gemini Omni Flash", "gemini.google.com", "720p", "4s-10s", "NEW"],
  ["Kling 3.0", "klingai.com", "4K", "3s-15s"],
  ["Kling 3.0 Turbo", "klingai.com", "1080p", "3s-15s", "NEW"],
  ["Kling 3.0 Motion Control", "klingai.com", "1080p", "3s-30s"],
  ["HappyHorse", null, "1080p", "3s-15s", "NEW"],
  ["Grok Imagine", "x.ai", "720p", "1s-15s"],
  ["Grok Imagine 1.5", "x.ai", "720p", "1s-15s", "NEW"],
  ["Google Veo 3.1 Lite", "deepmind.google", "1080p", "4s-8s", "NEW"],
  ["Wan 2.7", "wan.video", "1080p", "2s-15s", "NEW"],
];
// [familia, dominio, descripción, [variantes]]
const modelFamilies = [
  ["Minimax Hailuo", "minimax.io", "Alta dinámica, listo para VFX, el más rápido y asequible", [
    ["Minimax Hailuo 2.3 Fast", "1080p", "6s-10s"],
    ["Minimax Hailuo 2.3", "1080p", "6s-10s", "PREMIUM"],
    ["Minimax Hailuo 02 Fast", "512p", "6s-10s"],
    ["Minimax Hailuo 02", "1080p", "6s-10s", "PREMIUM"],
  ]],
  ["Kling", "klingai.com", "Movimiento perfecto con control de vídeo avanzado", [
    ["Kling 3.0", "4K", "3s-15s"],
    ["Kling 3.0 Turbo", "1080p", "3s-15s", "NEW"],
    ["Kling 3.0 Motion Control", "1080p", "3s-30s"],
    ["Kling 2.5 Turbo", "1080p", "5s-10s"],
    ["Kling 2.1 Master", "1080p", "5s-10s", "PREMIUM"],
  ]],
  ["OpenAI Sora", "openai.com", "Vídeo multiplano con generación de sonido", [
    ["OpenAI Sora 2 Pro", "1080p", "4s-12s", "PREMIUM"],
    ["OpenAI Sora 2", "1080p", "4s-12s"],
  ]],
  ["Google Veo", "deepmind.google", "Vídeo de precisión con control de sonido", [
    ["Google Veo 3.1", "4K", "4s-8s", "PREMIUM"],
    ["Google Veo 3.1 Lite", "1080p", "4s-8s", "NEW"],
    ["Google Veo 3 Fast", "1080p", "4s-8s"],
  ]],
  ["Gemini", "gemini.google.com", "Generación rápida multimodal", [
    ["Gemini Omni Flash", "720p", "4s-10s", "NEW"],
  ]],
  ["Wan", "wan.video", "Vídeo con control de cámara y sonido, más libertad", [
    ["Wan 2.7", "1080p", "2s-15s", "NEW"],
    ["Wan 2.5", "1080p", "5s-10s"],
    ["Wan 2.2 Turbo", "720p", "5s"],
  ]],
  ["Seedance", "bytedance.com", "Creación de vídeo cinematográfico multiplano", [
    ["Seedance 2.0", "4K", "4s-15s"],
    ["Seedance 2.0 Mini", "720p", "4s-15s", "NEW"],
    ["Seedance 2.0 Fast", "720p", "4s-15s"],
    ["Seedance 1.0 Pro", "1080p", "5s-10s"],
  ]],
  ["Grok Imagine", "x.ai", "Movimiento perfecto con control de vídeo avanzado", [
    ["Grok Imagine 1.5", "720p", "1s-15s", "NEW"],
    ["Grok Imagine", "720p", "1s-15s"],
  ]],
  ["Runway", "runwayml.com", "Control de movimiento y referencias de estilo", [
    ["Runway Gen-4 Turbo", "1080p", "5s-10s"],
    ["Runway Gen-4", "1080p", "5s-10s", "PREMIUM"],
  ]],
  ["Luma", "lumalabs.ai", "Dream Machine, movimiento natural y fluido", [
    ["Luma Ray 3", "1080p", "5s-9s", "NEW"],
    ["Luma Ray 2", "1080p", "5s-9s"],
  ]],
  ["Pika", "pika.art", "Efectos y transformaciones creativas", [
    ["Pika 2.2", "1080p", "5s-10s"],
    ["Pika Turbo", "720p", "3s-5s"],
  ]],
  ["HappyHorse", null, "Modelo con sonido nativo y alta consistencia", [
    ["HappyHorse", "1080p", "3s-15s", "NEW"],
  ]],
];
function ModelLogo({ domain, name, className = "size-5" }) {
  if (domain) {
    return (
      <img
        src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`}
        alt=""
        className={cn("shrink-0 rounded-sm object-contain", className)}
        onError={(e) => {
          e.currentTarget.style.display = "none";
        }}
      />
    );
  }
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-sm bg-muted text-[10px] font-semibold",
        className,
      )}
    >
      {name[0]}
    </span>
  );
}
const genreList = [
  "Noir",
  "Drama",
  "Epic",
  "General",
  "Action",
  "Horror",
  "Comedy",
];
const resolutionList = ["480p", "720p", "1080p", "4K"];
const durationList = ["4s", "6s", "8s", "10s", "15s"];
const aspectList = ["Auto", "16:9", "9:16", "1:1", "2.39:1"];
const cameraGroups = {
  Cámara: ["Auto", "Handheld", "Steadicam", "Dron", "Grúa", "Dolly"],
  Lente: ["Auto", "Extreme Macro", "Gran angular", "Estándar", "Teleobjetivo", "Anamórfica"],
  Focal: ["24mm", "35mm", "50mm", "75mm", "100mm"],
  Apertura: ["f/1.4 Shallow", "f/2.8", "f/5.6", "f/11 Deep Focus"],
};
const styleGroups = {
  "Paleta de color": ["Auto", "Teal & Orange", "Monocromo", "Pastel", "Neón", "Sepia"],
  Iluminación: ["Auto", "Hora dorada", "Low key", "High key", "Neón", "Contraluz"],
  "Movimiento de cámara": ["Auto", "Estático", "Push lento", "Órbita", "Handheld", "Crash zoom"],
};

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
      <div className="flex items-baseline justify-between gap-3 text-sm">
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

function SettingsRowSelect({ label, value, options, onChange }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <MiniSelect value={value} options={options} onChange={onChange} />
    </div>
  );
}
function MiniSelect({ icon: Icon, value, options, onChange }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent [&_svg]:size-3.5">
          {Icon && <Icon className="text-muted-foreground" />}
          {value}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-[9rem]">
        {options.map((o) => (
          <DropdownMenuItem key={o} onClick={() => onChange(o)}>
            {o}
            {o === value && <Check className="ml-auto size-3.5" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
function ModelPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [expanded, setExpanded] = useState(null);
  const match = (n) => n.toLowerCase().includes(q.toLowerCase());
  const pick = (n) => {
    onChange(n);
    setOpen(false);
    setQ("");
  };
  const rowCls =
    "flex w-full items-center gap-2 rounded-md p-2 text-left transition-colors hover:bg-accent";
  const meta = (res, dur) => (
    <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
      {res} · {dur}
    </span>
  );
  const badgeEl = (b) =>
    b && (
      <Badge
        className={cn(
          "rounded px-1 py-0 text-[9px]",
          b === "PREMIUM" && "bg-violet-600 hover:bg-violet-600",
        )}
      >
        {b}
      </Badge>
    );

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors hover:bg-accent"
      >
        <Wand2 className="size-3.5 text-violet-600" />
        {value}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full left-0 z-50 mb-2 w-[380px] overflow-hidden rounded-xl border bg-background shadow-2xl">
            <div className="flex items-center gap-2 border-b px-3">
              <Search className="size-4 shrink-0 text-muted-foreground" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Buscar modelo…"
                className="h-10 flex-1 bg-transparent text-sm outline-none"
              />
            </div>
            <div className="max-h-[380px] overflow-y-auto overscroll-contain p-2">
              {cinematicModels.filter(([n]) => match(n)).length > 0 && (
                <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                  Modelos cinematográficos
                </p>
              )}
              {cinematicModels
                .filter(([n]) => match(n))
                .map(([n, d, badge]) => (
                  <button key={n} onClick={() => pick(n)} className={rowCls}>
                    <img src="/lovable-logo.svg" alt="" className="size-5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium">{n}</span>
                        {badgeEl(badge)}
                      </div>
                      <p className="truncate text-xs text-muted-foreground">{d}</p>
                    </div>
                    {n === value && <Check className="size-4 shrink-0" />}
                  </button>
                ))}

              {featuredModels.filter(([n]) => match(n)).length > 0 && (
                <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                  Modelos destacados
                </p>
              )}
              {featuredModels
                .filter(([n]) => match(n))
                .map(([n, domain, res, dur, badge]) => (
                  <button key={n} onClick={() => pick(n)} className={rowCls}>
                    <ModelLogo domain={domain} name={n} />
                    <span className="truncate text-sm font-medium">{n}</span>
                    {badgeEl(badge)}
                    {meta(res, dur)}
                    {n === value && <Check className="size-4 shrink-0" />}
                  </button>
                ))}

              <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                Todos los modelos
              </p>
              {modelFamilies
                .filter(
                  ([fname, , , variants]) =>
                    match(fname) || variants.some(([n]) => match(n)),
                )
                .map(([fname, domain, desc, variants]) => {
                  const isOpen = expanded === fname || q.length > 0;
                  return (
                    <div key={fname}>
                      <button
                        onClick={() =>
                          setExpanded(expanded === fname ? null : fname)
                        }
                        className={rowCls}
                      >
                        <ModelLogo domain={domain} name={fname} />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium">{fname}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {desc}
                          </p>
                        </div>
                        <ChevronRight
                          className={cn(
                            "size-4 shrink-0 text-muted-foreground transition-transform",
                            isOpen && "rotate-90",
                          )}
                        />
                      </button>
                      {isOpen &&
                        variants
                          .filter(([n]) => match(n) || match(fname))
                          .map(([n, res, dur, badge]) => (
                            <button
                              key={n}
                              onClick={() => pick(n)}
                              className={cn(rowCls, "pl-9")}
                            >
                              <span className="truncate text-sm">{n}</span>
                              {badgeEl(badge)}
                              {meta(res, dur)}
                              {n === value && <Check className="size-4 shrink-0" />}
                            </button>
                          ))}
                    </div>
                  );
                })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Ajustes de generación. El estado vive en la cuenta (useStudio), así que lo
 * que elijas en el panel se mantiene al entrar en el editor y se persiste.
 * `onMention` engancha el botón @ con el compositor que lo aloja.
 */
function GenSettingsBar({ trailing, onMention, onAttach }) {
  const { genSettings: s, setGenSettings } = useStudio();
  const { mode, model, aspect, res, dur, count, sound, genre, style, camera } = s;
  const setMode = (v) => setGenSettings({ mode: v });
  const setModel = (v) => setGenSettings({ model: v });
  const setAspect = (v) => setGenSettings({ aspect: v });
  const setRes = (v) => setGenSettings({ res: v });
  const setDur = (v) => setGenSettings({ dur: v });
  const setCount = (v) => setGenSettings({ count: v });
  const setSound = (v) => setGenSettings({ sound: v });
  const setGenre = (v) => setGenSettings({ genre: v });
  const setStyle = (v) => setGenSettings({ style: v });
  const setCamera = (v) => setGenSettings({ camera: v });
  const [open, setOpen] = useState(false);
  const [flyout, setFlyout] = useState(null);
  const summarize = (o) =>
    Object.values(o).every((v) => v === "Auto")
      ? "Auto"
      : Object.values(o).filter((v) => v !== "Auto").join(", ");

  return (
    <>
      <div className="flex items-center gap-0.5 px-1 pb-1">
        <UIButton
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="Adjuntar archivo"
          disabled={!onAttach}
          onClick={onAttach}
        >
          <Plus />
        </UIButton>
        <UIButton
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="Mencionar un element"
          disabled={!onMention}
          onClick={onMention}
        >
          <span className="text-sm">@</span>
        </UIButton>
        <div className="flex items-center rounded-md border p-0.5">
          {[
            ["image", ImageIcon, "Imagen"],
            ["video", Video, "Vídeo"],
          ].map(([id, I, label]) => (
            <button
              key={id}
              onClick={() => setMode(id)}
              title={label}
              className={cn(
                "flex size-6 items-center justify-center rounded transition-colors [&_svg]:size-3.5",
                mode === id
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:bg-accent",
              )}
            >
              <I />
            </button>
          ))}
        </div>
        <ModelPicker value={model} onChange={setModel} />

        <div className="relative">
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Settings className="size-3.5" />
            {res} · {dur}
          </button>
          {open && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => {
                  setOpen(false);
                  setFlyout(null);
                }}
              />
              <div className="absolute bottom-full left-0 z-50 mb-2 w-[280px] rounded-xl border bg-background p-2 shadow-2xl">
                {[
                  ["Género", genre, Sparkles, "genre"],
                  ["Estilo", summarize(style), Palette, "style"],
                  ["Cámara", summarize(camera), CameraIcon, "camera"],
                ].map(([label, value, I, key]) => (
                  <button
                    key={label}
                    onClick={() => setFlyout(flyout === key ? null : key)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent",
                      flyout === key && "bg-accent",
                    )}
                  >
                    <I className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="text-muted-foreground">{label}</span>
                    <span className="ml-auto max-w-[120px] truncate">{value}</span>
                    <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                  </button>
                ))}
                <Separator className="my-1.5" />
                <SettingsSlider label="Aspecto" value={aspect} options={aspectList} onChange={setAspect} />
                <SettingsSlider label="Resolución" value={res} options={resolutionList} onChange={setRes} />
                <SettingsSlider label="Duración" value={dur} options={durationList} onChange={setDur} />
                <div className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm">
                  <span className="text-muted-foreground">Cantidad</span>
                  <div className="flex items-center gap-0.5">
                    <button
                      onClick={() => setCount(Math.max(1, count - 1))}
                      className="flex size-6 items-center justify-center rounded hover:bg-accent"
                    >
                      <Minus className="size-3" />
                    </button>
                    <span className="w-8 text-center tabular-nums">{count}/4</span>
                    <button
                      onClick={() => setCount(Math.min(4, count + 1))}
                      className="flex size-6 items-center justify-center rounded hover:bg-accent"
                    >
                      <Plus className="size-3" />
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm">
                  <span className="text-muted-foreground">Sonido</span>
                  <Switch checked={sound} onCheckedChange={setSound} />
                </div>

                {flyout && (
                  <div className="absolute left-full top-0 ml-2 w-[280px] rounded-xl border bg-background p-2 shadow-2xl">
                    {flyout === "genre" &&
                      genreList.map((g) => (
                        <button
                          key={g}
                          onClick={() => {
                            setGenre(g);
                            setFlyout(null);
                          }}
                          className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
                        >
                          {g}
                          {genre === g && <Check className="size-3.5" />}
                        </button>
                      ))}
                    {flyout === "style" &&
                      Object.entries(styleGroups).map(([k, opts]) => (
                        <SettingsSlider
                          key={k}
                          label={k}
                          value={style[k]}
                          options={opts}
                          onChange={(v) => setStyle({ ...style, [k]: v })}
                        />
                      ))}
                    {flyout === "camera" &&
                      Object.entries(cameraGroups).map(([k, opts]) => (
                        <SettingsSlider
                          key={k}
                          label={k}
                          value={camera[k]}
                          options={opts}
                          onChange={(v) => setCamera({ ...camera, [k]: v })}
                        />
                      ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="flex-1" />
        {trailing}
      </div>
    </>
  );
}

/**
 * Caja de prompt del panel. Mínima fricción: al generar se crea el proyecto
 * con esa idea y el usuario entra directamente en su editor, con el prompt
 * ya encolado para que el agente lo ejecute al llegar.
 */
function PromptBox() {
  const [t, setT] = useState("");
  const [creating, setCreating] = useState(false);
  const { createProject, genSettings, ready } = useStudio();

  const generate = async () => {
    const prompt = t.trim();
    if (!prompt || creating || !ready) return;
    setCreating(true);
    const project = await createProject({
      title: titleFromPrompt(prompt),
      prompt,
      settings: genSettings,
    });
    go(`/projects/${project.id}?run=1`);
  };

  return (
    <Card className="w-full max-w-2xl p-2 text-left shadow-lg">
      <Textarea
        value={t}
        onChange={(e) => setT(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            generate();
          }
        }}
        placeholder="Describe tu escena — usa @ para añadir personajes y localizaciones"
        className="min-h-[76px] resize-none border-0 text-base shadow-none focus-visible:ring-0"
      />
      <GenSettingsBar
        trailing={
          <UIButton
            size="sm"
            disabled={!t.trim() || creating}
            onClick={generate}
          >
            {creating ? <RefreshCw className="animate-spin" /> : null}
            {creating ? "Creando…" : "Generar"}
          </UIButton>
        }
      />
    </Card>
  );
}

// Proveedores ofrecidos en el acceso. El logo sale de authBrands.
const authProviders = ["google", "github", "apple"];

/**
 * Alta e inicio de sesión contra Supabase. Al registrarse, el trigger
 * on_auth_user_created crea el perfil con sus 200 créditos de bienvenida.
 */
function AuthModal() {
  const { signUp, signIn, signInWithProvider, isRemote } = useStudio();
  const [mode, setMode] = useState("signin");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e) => {
    e?.preventDefault();
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      if (!isRemote) return go("/dashboard");
      if (mode === "signup") {
        const result = await signUp(form);
        // Si el proyecto exige confirmar el correo, aún no hay sesión.
        if (!result?.session) {
          setStatus({
            kind: "info",
            text: "Te hemos enviado un correo para confirmar la cuenta.",
          });
          return;
        }
      } else {
        await signIn(form);
      }
      go("/dashboard");
    } catch (error) {
      setStatus({ kind: "error", text: translateAuthError(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && go("/es")}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader className="items-center">
          <XframeHeart size={36} />
          <DialogTitle className="text-2xl">Empieza a crear.</DialogTitle>
          <DialogDescription>
            {mode === "signup"
              ? "Crea tu cuenta — 200 créditos de regalo"
              : "Inicia sesión en tu cuenta"}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {authProviders.map((provider) => (
            <UIButton
              key={provider}
              variant="outline"
              className="w-full"
              disabled={busy}
              onClick={() =>
                isRemote ? signInWithProvider(provider) : go("/dashboard")
              }
            >
              <AuthBrandIcon provider={provider} className="size-4" />
              Continuar con {brandLabel(provider)}
            </UIButton>
          ))}

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Separator className="flex-1" />O<Separator className="flex-1" />
          </div>

          <form onSubmit={submit} className="flex flex-col gap-3">
            {mode === "signup" && (
              <Input
                value={form.name}
                onChange={set("name")}
                placeholder="Tu nombre"
                autoComplete="name"
              />
            )}
            <Input
              type="email"
              required
              value={form.email}
              onChange={set("email")}
              placeholder="Correo electrónico"
              autoComplete="email"
            />
            <Input
              type="password"
              required
              minLength={6}
              value={form.password}
              onChange={set("password")}
              placeholder="Contraseña"
              autoComplete={
                mode === "signup" ? "new-password" : "current-password"
              }
            />
            {status && (
              <p
                className={cn(
                  "text-xs",
                  status.kind === "error"
                    ? "text-destructive"
                    : "text-muted-foreground",
                )}
              >
                {status.text}
              </p>
            )}
            <UIButton type="submit" className="w-full" disabled={busy}>
              {busy && <RefreshCw className="animate-spin" />}
              {mode === "signup" ? "Crear cuenta" : "Continuar"}
            </UIButton>
          </form>

          <button
            type="button"
            onClick={() => {
              setMode(mode === "signup" ? "signin" : "signup");
              setStatus(null);
            }}
            className="text-center text-xs text-muted-foreground hover:text-foreground"
          >
            {mode === "signup"
              ? "¿Ya tienes cuenta? Inicia sesión"
              : "¿No tienes cuenta? Créala gratis"}
          </button>

          <Separator />
          <p className="flex items-center justify-center gap-2 text-center text-xs text-muted-foreground">
            <Shield className="size-4 shrink-0" />
            SSO disponible en los planes Business y Enterprise
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Mensajes de Supabase Auth en castellano. */
function translateAuthError(error) {
  const message = String(error?.message ?? error);
  if (/Invalid login credentials/i.test(message))
    return "Correo o contraseña incorrectos.";
  if (/User already registered/i.test(message))
    return "Ya existe una cuenta con ese correo. Inicia sesión.";
  if (/Password should be at least/i.test(message))
    return "La contraseña debe tener al menos 6 caracteres.";
  if (/Email not confirmed/i.test(message))
    return "Confirma tu correo antes de iniciar sesión.";
  if (/rate limit|too many/i.test(message))
    return "Demasiados intentos. Espera un momento.";
  return message;
}

function CookieConsent() {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <Card className="fixed bottom-5 right-5 z-40 w-[300px] p-4 shadow-lg">
      <p className="text-sm text-muted-foreground">
        We use cookies to enhance your development experience and keep your data
        secure.{" "}
        <a href="#" className="underline">
          Privacy Policy
        </a>
      </p>
      <div className="mt-3 flex flex-col gap-2">
        <UIButton className="w-full" onClick={() => setOpen(false)}>
          Accept all
        </UIButton>
        <UIButton
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => setOpen(false)}
        >
          Manage preferences
        </UIButton>
        <UIButton
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => setOpen(false)}
        >
          Reject all
        </UIButton>
      </div>
    </Card>
  );
}
const footerColumns = [
  [
    "Empresa",
    "Empleo",
    "Prensa y medios",
    "Seguridad",
    "Centro de confianza",
    "Colaboraciones",
  ],
  [
    "Producto",
    "Precios",
    "Descuento para estudiantes",
    "Fundadores",
    "Gerentes de producto",
    "Diseñadores",
    "Especialistas en marketing",
    "Operaciones",
    "Recursos humanos",
    "Creación de prototipos",
    "Herramientas internas",
    "Descargar aplicaciones",
    "Conexiones",
    "Registro de cambios",
    "Estado",
  ],
  [
    "Recursos",
    "Aprender",
    "Plantillas",
    "Guías",
    "Conectores",
    "Servidor MCP",
    "Vídeos",
    "Soporte",
    "Reseñas",
    "Mapa del sitio",
  ],
  [
    "Legal",
    "Política de privacidad",
    "No vender ni compartir mi información personal",
    "Configuración de cookies",
    "Términos para empresas",
    "Términos generales",
    "Reglas de la plataforma",
    "Denunciar abuso",
    "Reportar problemas de seguridad",
    "Acuerdo de tratamiento de datos",
  ],
  [
    "Comunidad",
    "Conviértete en socio",
    "Contrata a un experto de Xframe",
    "Afiliados",
    "Código de conducta",
    "Discord",
    "Reddit",
    "X / Twitter",
    "YouTube",
    "LinkedIn",
  ],
];
function MarketingFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto grid max-w-6xl grid-cols-2 gap-8 px-6 py-16 md:grid-cols-5">
        {footerColumns.map(([title, ...links]) => (
          <div
            key={title}
            className="flex flex-col gap-3 text-sm text-muted-foreground"
          >
            <span className="font-semibold text-foreground">{title}</span>
            {links.map((link) => (
              <a key={link} href="#" className="hover:text-foreground">
                {link}
              </a>
            ))}
          </div>
        ))}
      </div>
      <Separator />
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Logo />
        <span className="text-sm text-muted-foreground">ES</span>
      </div>
    </footer>
  );
}
const featureSteps = [
  [
    "Empieza con una idea",
    "Describe la escena o el vídeo que quieres rodar, o adjunta guiones e imágenes de referencia.",
  ],
  [
    "Velo cobrar vida",
    "Mira cómo tu visión se transforma en planos de vídeo en tiempo real.",
  ],
  [
    "Perfecciona y publica",
    "Ajusta la dirección con comentarios sencillos y exporta tu vídeo con un solo clic.",
  ],
];
const stats = [
  ["50M", "vídeos generados en Xframe"],
  ["1M", "planos nuevos generados cada semana"],
  ["100M", "reproducciones al mes de vídeos creados con Xframe"],
];
function Landing() {
  const auth = new URLSearchParams(location.search).has("auth");
  return (
    <main>
      <MarketingNav />
      <section className="relative isolate -mt-16 flex min-h-[calc(100vh+4rem)] flex-col items-center justify-center gap-6 overflow-hidden px-6 py-16 text-center">
        <div
          className="absolute inset-0 -z-10 bg-no-repeat"
          style={{
            backgroundImage: "url(/hero-aura.webp)",
            backgroundSize: "220%",
            backgroundPosition: "center 30%",
          }}
        />
        <Badge variant="secondary" className="rounded-full px-3 py-1">
          Vídeo con IA
        </Badge>
        <h1 className="max-w-3xl text-4xl font-bold tracking-tight sm:text-6xl">
          Crea algo con Xframe
        </h1>
        <p className="max-w-xl text-lg text-muted-foreground">
          Crea vídeos y películas conversando con la IA
        </p>
        <PromptBox />
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16 text-center">
        <p className="text-sm text-muted-foreground">
          Equipos de empresas líderes crean con Xframe
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-x-12 gap-y-6 text-lg font-semibold text-muted-foreground/60">
          {["NVIDIA", "HCA Healthcare", "HEARST", "UDACITY", "asana"].map((x) => (
            <span key={x}>{x}</span>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="grid gap-10 md:grid-cols-2 md:items-center">
          <div className="aspect-video overflow-hidden rounded-xl border bg-muted">
            <video
              autoPlay
              muted
              loop
              playsInline
              poster="/assets/scene-2.webp"
              className="h-full w-full object-cover"
            >
              <source src="/assets/scene-1.webm" type="video/webm" />
            </video>
          </div>
          <div className="divide-y">
            {featureSteps.map(([title, desc]) => (
              <div key={title} className="py-5 first:pt-0">
                <h3 className="text-xl font-semibold">{title}</h3>
                <p className="mt-1.5 text-muted-foreground">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="flex items-end justify-between">
          <div>
            <h2 className="text-3xl font-bold tracking-tight">Descubre</h2>
            <p className="mt-1 text-muted-foreground">
              Empieza tu próximo proyecto con una plantilla
            </p>
          </div>
          <UIButton variant="outline">Ver todo</UIButton>
        </div>
        <div className="mt-8 grid grid-cols-2 gap-5 md:grid-cols-4">
          {templates.map((x) => (
            <Card
              key={x[0]}
              className="cursor-pointer overflow-hidden transition-shadow hover:shadow-md"
              onClick={() => go("/dashboard")}
            >
              <div
                className="aspect-[4/3] bg-muted bg-cover bg-center"
                style={{ backgroundImage: `url(${x[2]})` }}
              />
              <div className="p-4">
                <h4 className="font-medium">{x[0]}</h4>
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                  {x[1]}
                </p>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="text-3xl font-bold tracking-tight">Xframe</h2>
        <p className="mt-1 text-muted-foreground">
          Millones de creadores ya están convirtiendo sus ideas en realidad
        </p>
        <div className="mt-8 grid gap-5 sm:grid-cols-3">
          {stats.map(([n, l]) => (
            <Card key={l}>
              <CardContent className="flex flex-col gap-2 p-6">
                <span className="text-5xl font-bold tracking-tight">{n}</span>
                <span className="text-sm text-muted-foreground">{l}</span>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-6 py-24 text-center">
        <h2 className="text-3xl font-bold tracking-tight">¿Listo para crear?</h2>
        <PromptBox />
      </section>

      <MarketingFooter />
      {auth && <AuthModal />}
      <CookieConsent />
    </main>
  );
}

const plans = [
  {
    name: "Free",
    desc: "Descubre lo que Xframe puede hacer por ti",
    price: "€0",
    cadence: "al mes",
    leads: [
      ["No se necesita tarjeta de crédito", CreditCard],
      ["Créditos gratuitos", Grid2X2, true],
    ],
    features: [
      "Proyectos privados del espacio de trabajo",
      "Colaboradores ilimitados",
      "5 dominios xframe.app",
      "Nube",
      "Soporte de la comunidad",
    ],
  },
  {
    name: "Pro",
    desc: "Diseñado para equipos ágiles que crean juntos en tiempo real.",
    price: "€25",
    cadence: "al mes IVA incl.",
    leads: [
      ["Usuarios ilimitados", Users],
      ["Créditos gratuitos", Grid2X2, true],
    ],
    features: [
      "Todas las funciones del plan Gratis",
      "100 créditos Pro",
      "Acumulación de créditos",
      "Recargas de créditos a demanda",
      "Dominios xframe.app ilimitados",
      "Dominios personalizados",
      "Roles y permisos de usuario",
      "Per-member credit limits",
    ],
  },
  {
    name: "Business",
    desc: "Controles avanzados y funciones potentes para departamentos en crecimiento",
    price: "€50",
    cadence: "al mes IVA incl.",
    leads: [
      ["Usuarios ilimitados", Users],
      ["Créditos gratuitos", Grid2X2, true],
    ],
    features: [
      "Todas las funciones de Pro",
      "100 créditos Business",
      "Espacio de trabajo en equipo",
      "Acceso basado en roles",
      "Publicación interna",
      "Proyectos personales",
      "SSO",
      "Centro de seguridad",
    ],
  },
  {
    name: "Enterprise",
    desc: "Diseñado para grandes organizaciones que necesitan flexibilidad, escala y gobernanza.",
    price: "Tarifa de plataforma",
    cadence: "Precios por volumen",
    leads: [
      ["Precios por volumen", CreditCard],
      ["Usuarios ilimitados", Users],
    ],
    features: [
      "Todas las funciones de Business",
      "Precios de créditos por volumen",
      "Soporte dedicado",
      "Servicios de incorporación",
      "Sistemas de diseño",
      "SCIM",
      "Compatibilidad con conectores personalizados",
      "Controles de publicación",
    ],
    note: "Para funcionalidades empresariales adicionales o personalizadas, contacta directamente con nuestro equipo.",
  },
];
const pricingFaqs = [
  "¿Qué es Xframe y cómo funciona?",
  "¿Qué es un crédito?",
  "¿Cómo uso los créditos en Xframe?",
  "¿Caducan los créditos?",
  "¿Qué pasa con mis créditos si finaliza mi suscripción?",
  "¿Son reembolsables los créditos?",
  "¿Qué incluyen los planes gratuitos y de pago?",
  "How do I buy credits for a team, class, or community?",
  "Do you charge per seat or per user?",
  "How much does it cost to run my app on Xframe?",
  "Why is the Business plan more expensive?",
  "¿Quién es propietario de los proyectos y el código?",
  "¿Ofrecen un descuento para estudiantes?",
  "¿Dónde puedo obtener más información?",
];
function PricingCard({ p, i, annual = false }) {
  const isPro = p.name === "Pro";
  const isEnterprise = p.name === "Enterprise";
  const hasSelect = i === 1 || i === 2;
  const basePrice = isPro ? 25 : 50;
  const [credits, setCredits] = useState(100);
  const price = tierPrice(basePrice, credits, annual);
  return (
    <Card className="flex flex-col p-6">
      <h3 className="text-xl font-semibold">{p.name}</h3>
      <p className="mt-2 min-h-[56px] text-sm text-muted-foreground">{p.desc}</p>
      <div className="mt-4 flex min-h-[44px] items-end">
        <span
          className={cn(
            "font-bold tracking-tight",
            isEnterprise ? "text-xl text-muted-foreground" : "text-4xl",
          )}
        >
          {hasSelect ? `€${price.toLocaleString("es-ES")}` : p.price}
        </span>
      </div>
      <p className="mt-1 min-h-[20px] text-sm text-muted-foreground">
        {isEnterprise
          ? "Precios por volumen"
          : hasSelect
            ? `al mes IVA incl.${annual ? " · facturado anual" : ""}`
            : p.cadence}
      </p>
      {hasSelect ? (
        <CreditTierSelect
          basePrice={basePrice}
          annual={annual}
          value={credits}
          onChange={setCredits}
        />
      ) : (
        <div className="mt-4 h-9" />
      )}
      <UIButton
        variant={isPro ? "default" : "outline"}
        className={cn(
          "mt-4 w-full",
          isPro && "bg-violet-600 text-white hover:bg-violet-700",
        )}
        onClick={() => go(isEnterprise ? "/es?auth=login" : "/dashboard")}
      >
        {isEnterprise ? "Reservar una demo" : "Empezar"}
      </UIButton>
      <div className="mt-6 space-y-3 border-t pt-5">
        {p.leads.map(([label, Icon, expandable]) => (
          <div key={label} className="flex items-center gap-2 text-sm">
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <span className="flex-1">{label}</span>
            {expandable && (
              <ChevronDown className="size-3.5 text-muted-foreground" />
            )}
          </div>
        ))}
      </div>
      <ul className="mt-5 space-y-2.5">
        {p.features.map((f) => (
          <li key={f} className="flex gap-2 text-sm text-muted-foreground">
            <Check className="size-4 shrink-0 text-foreground" />
            {f}
          </li>
        ))}
      </ul>
      {p.note && (
        <p className="mt-3 flex gap-2 text-sm text-muted-foreground">
          <Check className="size-4 shrink-0 text-foreground" />
          {p.note}
        </p>
      )}
    </Card>
  );
}
const pricingEdu = [
  [
    "Xframe para estudiantes",
    "Verifica tu condición de estudiante y obtén hasta un 50 % de descuento en Xframe Pro.",
    "Empezar",
  ],
  [
    "Xframe para campus",
    "Controles de facturación y administración para universidades y centros de educación superior.",
    "Contactar con ventas",
  ],
  [
    "Xframe para niños",
    "Acceso conforme a la normativa y plan de estudios para colegios, en colaboración con imagi.",
    "Más información",
  ],
];
function Pricing() {
  const [billing, setBilling] = useState("monthly");
  return (
    <main>
      <MarketingNav />
      <section className="mx-auto max-w-3xl px-6 pb-6 pt-20 text-center">
        <div className="flex items-center justify-center gap-2.5">
          <XframeHeart size={32} />
          <h1 className="text-3xl font-bold tracking-tight">Precios</h1>
        </div>
        <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
          Empieza gratis. Mejora tu plan para obtener la capacidad que se ajusta
          exactamente a las necesidades de tu equipo.
        </p>
        <div className="mt-6 inline-flex rounded-full border bg-muted p-1 text-sm">
          <button
            onClick={() => setBilling("monthly")}
            className={cn(
              "rounded-full px-4 py-1.5 transition-colors",
              billing === "monthly"
                ? "bg-background shadow-sm"
                : "text-muted-foreground",
            )}
          >
            Mensual
          </button>
          <button
            onClick={() => setBilling("annual")}
            className={cn(
              "rounded-full px-4 py-1.5 transition-colors",
              billing === "annual"
                ? "bg-background shadow-sm"
                : "text-muted-foreground",
            )}
          >
            Anual{" "}
            <span className="font-medium text-violet-600">2 meses gratis</span>
          </button>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-5 px-6 md:grid-cols-2 lg:grid-cols-4">
        {plans.map((p, i) => (
          <PricingCard key={p.name} p={p} i={i} annual={billing === "annual"} />
        ))}
      </section>

      <section className="mx-auto mt-24 grid max-w-6xl gap-5 px-6 md:grid-cols-3">
        {pricingEdu.map(([title, description, action]) => (
          <Card key={title} className="flex flex-col p-6">
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="mt-2 flex-1 text-sm text-muted-foreground">
              {description}
            </p>
            <UIButton
              variant="outline"
              className="mt-4 w-full"
              onClick={() => go("/es?auth=login")}
            >
              {action}
            </UIButton>
          </Card>
        ))}
      </section>

      <section className="mx-auto mt-6 max-w-6xl px-6">
        <Card className="flex flex-col items-start justify-between gap-6 p-8 sm:flex-row sm:items-center">
          <div className="max-w-lg">
            <p className="text-sm text-muted-foreground">
              Seguridad y cumplimiento
            </p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight">
              Certificaciones de seguridad y cumplimiento de nivel empresarial
            </h2>
            <UIButton
              variant="outline"
              className="mt-4"
              onClick={() => go("/settings/privacy-security")}
            >
              Más información
            </UIButton>
          </div>
          <div className="flex items-center gap-3">
            {["SOC 2", "GDPR", "ISO 27001"].map((b) => (
              <span
                key={b}
                className="flex size-16 items-center justify-center rounded-full bg-neutral-800 text-center text-[10px] font-semibold text-white"
              >
                {b}
              </span>
            ))}
          </div>
        </Card>
      </section>

      <section className="mx-auto mt-24 max-w-3xl px-6">
        <h2 className="text-3xl font-bold tracking-tight">
          Preguntas frecuentes
        </h2>
        <div className="mt-6">
          {pricingFaqs.map((x) => (
            <details key={x} className="group border-b py-5">
              <summary className="flex cursor-pointer items-center justify-between font-medium">
                {x}
                <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
              </summary>
              <p className="mt-3 text-sm text-muted-foreground">
                Todo está diseñado para que empieces sin fricción y puedas
                ampliar tu plan cuando lo necesites.
              </p>
            </details>
          ))}
        </div>
      </section>

      <section className="mx-auto my-16 max-w-3xl px-6">
        <h3 className="text-sm font-semibold text-muted-foreground">
          Artículos relacionados
        </h3>
        <button
          onClick={() => go("/dashboard/resources")}
          className="mt-3 flex w-full items-center justify-between rounded-xl border p-4 text-left text-sm transition-colors hover:bg-accent"
        >
          Planes y créditos <ExternalLink className="size-4 text-muted-foreground" />
        </button>
      </section>

      <MarketingFooter />
    </main>
  );
}

const navItems = [
  ["/dashboard", LayoutDashboard, "Panel"],
  ["search", Search, "Buscar"],
  ["/dashboard/resources", BookOpen, "Recursos"],
  ["connectors", Plug, "Conectores"],
];
const sideNavClass = (active) =>
  cn(
    "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors [&_svg]:size-4",
    active
      ? "bg-accent font-medium text-accent-foreground"
      : "text-muted-foreground hover:bg-accent hover:text-foreground",
  );
function UserMenu() {
  const { profile, signOut } = useStudio();
  const initial = (profile?.name ?? "?").charAt(0).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex size-8 items-center justify-center rounded-full bg-green-600 text-sm font-semibold text-white outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Cuenta"
        >
          {initial}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-64">
        <div className="flex items-center gap-2.5 p-2">
          <span className="flex size-9 items-center justify-center rounded-full bg-green-600 text-sm font-semibold text-white">
            {initial}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{profile?.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {profile?.email}
            </p>
            <p className="text-xs text-muted-foreground">
              {profile?.credits} créditos · plan {profile?.plan}
            </p>
          </div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem>
          <User /> Perfil
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => go("/settings/account")}>
          <Settings /> Configuración
          <DropdownMenuShortcut>Ctrl .</DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <Palette /> Apariencia
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuItem>Claro</DropdownMenuItem>
            <DropdownMenuItem>Oscuro</DropdownMenuItem>
            <DropdownMenuItem>Sistema</DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <LifeBuoy /> Soporte
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuItem>Centro de ayuda</DropdownMenuItem>
            <DropdownMenuItem>Contactar soporte</DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <BookOpen /> Documentación
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuItem>Guías</DropdownMenuItem>
            <DropdownMenuItem>Referencia de API</DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuItem>
          <Users /> Comunidad
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => go("/es")}>
          <Home /> Inicio
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={async () => {
            await signOut();
            go("/es");
          }}
        >
          <LogOut /> Cerrar sesión
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
function DashboardSide({ width, onResize }) {
  const { projects, profile, workspace } = useStudio();
  const recentProjects = projects.slice(0, 5);
  const openOverlay = (name) => go(`${location.pathname}?${name}=1`);
  const collapsed = width < 160;
  const navCls = (active) =>
    cn(
      "flex items-center rounded-md text-sm transition-colors [&>svg]:size-4 [&>svg]:shrink-0",
      collapsed ? "h-9 w-full justify-center" : "gap-3 px-3 py-2",
      active
        ? "bg-accent font-medium text-accent-foreground"
        : "text-muted-foreground hover:bg-accent hover:text-foreground",
    );
  return (
    <aside
      style={{ width }}
      className={cn(
        "fixed inset-y-0 left-0 flex flex-col gap-1 overflow-hidden border-r bg-muted/30",
        collapsed ? "items-center p-2" : "p-3",
      )}
    >
      <ResizeHandle onResize={onResize} />

      {collapsed ? (
        <button
          onClick={() => go("/es")}
          title="Xframe"
          className="flex size-9 items-center justify-center rounded-md hover:bg-accent"
        >
          <XframeHeart size={22} />
        </button>
      ) : (
        <div className="px-2 py-1">
          <Logo />
        </div>
      )}

      <button
        title={workspace?.name ?? "Espacio de trabajo"}
        className={cn(
          "mt-2 flex items-center rounded-md text-sm transition-colors hover:bg-accent",
          collapsed ? "size-9 justify-center" : "gap-2 p-2",
        )}
      >
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary text-xs font-semibold text-primary-foreground">
          H
        </span>
        {!collapsed && (
          <>
            <span className="flex-1 truncate text-left font-medium">
              {workspace?.name ?? "Espacio de trabajo"}
            </span>
            <ChevronDown className="size-4 text-muted-foreground" />
          </>
        )}
      </button>

      <nav className="mt-2 flex w-full flex-col gap-1">
        {navItems.map(([id, I, l]) => {
          const isOverlay = id === "search" || id === "connectors";
          const active =
            id === "connectors"
              ? location.search.includes("connectors")
              : !isOverlay && location.pathname === id && !location.search;
          return (
            <button
              key={id}
              title={l}
              className={navCls(active)}
              onClick={() =>
                isOverlay ? openOverlay(id) : go(id)
              }
            >
              <I />
              {!collapsed && l}
              {!collapsed && id === "search" && (
                <kbd className="ml-auto rounded border bg-background px-1.5 text-xs text-muted-foreground">
                  Ctrl K
                </kbd>
              )}
            </button>
          );
        })}
      </nav>

      {collapsed ? (
        <Separator className="my-2 w-8" />
      ) : (
        <p className="mt-4 px-3 text-xs font-medium text-muted-foreground">
          PROYECTOS
        </p>
      )}
      <div className="flex w-full flex-col gap-1">
        {[
          [FolderKanban, "Todos los proyectos"],
          [Users, "Creados por mí"],
          [Share2, "Compartido conmigo"],
        ].map(([I, l]) => (
          <button key={l} title={l} className={navCls(false)}>
            <I />
            {!collapsed && l}
          </button>
        ))}
      </div>

      {collapsed ? (
        <Separator className="my-2 w-8" />
      ) : (
        <p className="mt-4 px-3 text-xs font-medium text-muted-foreground">
          RECIENTES
        </p>
      )}
      {recentProjects.map((project) => (
        <button
          key={project.id}
          title={project.title}
          className={navCls(false)}
          onClick={() => go(`/projects/${project.id}`)}
        >
          <span className="size-2 shrink-0 rounded-full bg-green-500" />
          {!collapsed && <span className="truncate">{project.title}</span>}
        </button>
      ))}

      <div
        className={cn(
          "mt-auto flex w-full flex-col gap-2 pt-2",
          collapsed && "items-center",
        )}
      >
        {collapsed ? (
          <>
            <button
              title="Compartir Xframe — 100 créditos por cada referido"
              className="flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <Gift className="size-5" />
            </button>
            <button
              onClick={() => go("/es/pricing")}
              title={profile ? `${profile.credits} créditos · plan ${profile.plan}` : "Plan"}
              className="flex size-9 items-center justify-center rounded-full bg-secondary hover:bg-accent"
            >
              <Zap className="size-4" />
            </button>
          </>
        ) : (
          <>
            <Card className="p-3">
              <div className="flex items-center gap-2.5">
                <Gift className="size-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="text-sm font-medium">Compartir Xframe</p>
                  <p className="truncate text-xs text-muted-foreground">
                    100 créditos por cada referido
                  </p>
                </div>
              </div>
            </Card>
            <button
              onClick={() => go("/es/pricing")}
              className="flex items-center gap-2.5 rounded-xl border bg-card p-3 text-left shadow-sm transition-colors hover:bg-accent"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">
                  {profile?.plan === "free" ? "Cambia a Pro" : "Plan " + profile?.plan}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {profile ? `${profile.credits} créditos disponibles` : "Cargando…"}
                </p>
              </div>
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary">
                <Zap className="size-4" />
              </span>
            </button>
          </>
        )}
        <div
          className={cn(
            "flex items-center gap-2 pt-1",
            collapsed ? "flex-col" : "justify-between px-1",
          )}
        >
          <UserMenu />
          <button
            title="Notificaciones"
            className="relative rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Bell className="size-5" />
            <span className="absolute right-0.5 top-0.5 flex size-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-semibold text-white">
              1
            </span>
          </button>
        </div>
      </div>
    </aside>
  );
}
const projects = [
  "Tráiler — Proyecto Neón",
  "Spot Café Aurora",
  "Videoclip Vórtice",
  "Documental Origen",
];
const cmdItemClass =
  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors [&_svg]:size-4 [&_svg]:text-muted-foreground";
const cmdRecent = [
  "Remix of Prompt Frame Creative Portfolio",
  "Tráiler — Proyecto Neón",
];
const cmdNavigate = [
  [LayoutDashboard, "Dashboard", "/dashboard"],
  [Plus, "Crear un proyecto", "/dashboard"],
  [BookOpen, "Documentation", "/dashboard/resources"],
];
const cmdSettingsItems = [
  [User, "Tu cuenta", "account"],
  [Monitor, "Dispositivos y apps", "apps"],
  [Settings, "Espacio de trabajo", "workspace"],
  [CreditCard, "Planes y uso de créditos", "billing"],
  [Users, "Personas", "people"],
  [BookOpen, "Conocimiento", "knowledge"],
  [Sparkles, "Habilidades", "skills"],
];
function CommandPalette({ close }) {
  const { projects } = useStudio();
  React.useEffect(() => {
    const el = document.documentElement;
    const prevHtml = el.style.overflow;
    const prevBody = document.body.style.overflow;
    el.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    return () => {
      el.style.overflow = prevHtml;
      document.body.style.overflow = prevBody;
    };
  }, []);
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overscroll-contain px-4 pt-[14vh]"
      onClick={close}
    >
      <div
        className="flex max-h-[64vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b px-5">
          <Search className="size-5 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            placeholder="Search..."
            className="h-16 flex-1 bg-transparent text-lg outline-none placeholder:text-muted-foreground"
          />
          <button
            onClick={close}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="overflow-y-auto overscroll-contain p-2">
          <p className="px-3 py-1.5 text-xs font-medium text-muted-foreground">
            Recent projects
          </p>
          {projects.slice(0, 5).map((project) => (
            <button
              key={project.id}
              onClick={() => go(`/projects/${project.id}`)}
              className={cn(cmdItemClass, "hover:bg-accent")}
            >
              <FolderKanban />
              {project.title}
            </button>
          ))}
          <p className="px-3 py-1.5 text-xs font-medium text-muted-foreground">
            Navigate to
          </p>
          {cmdNavigate.map(([I, l, to]) => (
            <button
              key={l}
              onClick={() => go(to)}
              className={cn(cmdItemClass, "hover:bg-accent")}
            >
              <I />
              {l}
            </button>
          ))}
          <button className={cn(cmdItemClass, "hover:bg-accent")}>
            <Clock />
            Changelog
            <ExternalLink className="ml-auto size-3.5 text-muted-foreground" />
          </button>
          <p className="px-3 py-1.5 text-xs font-medium text-muted-foreground">
            Settings
          </p>
          {cmdSettingsItems.map(([I, l, pg]) => (
            <button
              key={l}
              onClick={() => go(`/settings/${pg}`)}
              className={cn(cmdItemClass, "hover:bg-accent")}
            >
              <I />
              {l}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
const projectThumbs = [
  "/assets/prompt-frame.webp",
  "/assets/continuum.jpg",
  "/assets/ecommerce.webp",
  "/assets/vesper.webp",
];
const activityItems = [
  "Regeneraste el plano 3 de Tráiler — Proyecto Neón",
  "Xframe renderizó tu vídeo en 4K",
  "Añadiste voz en off con ElevenLabs",
  "Se guardó una nueva versión del montaje",
];
const projectTabs = [
  ["mine", "Mis proyectos"],
  ["recent", "Vistos recientemente"],
  ["shared", "Compartidos conmigo"],
  ["templates", "Plantillas de Xframe"],
];

const relativeDate = (iso) => {
  const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
  if (days <= 0) return "Editado hoy";
  if (days === 1) return "Editado ayer";
  return `Editado hace ${days} días`;
};

/** Rejilla de proyectos de la cuenta. */
function ProjectGrid({ view }) {
  const { projects, deleteProject } = useStudio();

  if (view === "shared" || view === "templates") {
    return (
      <div className="mt-6 rounded-xl border border-dashed p-10 text-center">
        <FolderKanban className="mx-auto size-7 text-muted-foreground" />
        <p className="mt-3 font-medium">
          {view === "shared"
            ? "Nadie ha compartido proyectos contigo todavía"
            : "Las plantillas de Xframe llegan pronto"}
        </p>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="mt-6 rounded-xl border border-dashed p-10 text-center">
        <Sparkles className="mx-auto size-7 text-muted-foreground" />
        <p className="mt-3 font-medium">Aún no tienes proyectos</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Escribe tu idea arriba y Xframe creará el proyecto por ti.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-6 md:grid-cols-4">
      {projects.map((project) => (
        <div key={project.id} className="group relative cursor-pointer">
          <div
            onClick={() => go(`/projects/${project.id}`)}
            className="aspect-video overflow-hidden rounded-xl border bg-muted bg-cover bg-center transition-shadow group-hover:shadow-md"
            style={{
              backgroundImage: project.cover_url
                ? `url(${project.cover_url})`
                : undefined,
            }}
          />
          <div className="mt-3 flex items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-full bg-green-100 text-xs font-semibold text-green-700">
              H
            </span>
            <div
              className="min-w-0 flex-1"
              onClick={() => go(`/projects/${project.id}`)}
            >
              <p className="truncate text-sm font-medium">{project.title}</p>
              <p className="text-xs text-muted-foreground">
                {relativeDate(project.updated_at)}
              </p>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  aria-label="Acciones del proyecto"
                  className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                >
                  <MoreHorizontal className="size-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => go(`/projects/${project.id}`)}>
                  <ExternalLink className="mr-2 size-3.5" /> Abrir
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => deleteProject(project.id)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="mr-2 size-3.5" /> Eliminar
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      ))}
    </div>
  );
}
function Dashboard({ kind = "home" }) {
  const [projectView, setProjectView] = useState("mine");
  const [sidebarW, resizeSidebar] = useResizableWidth("xf-dash-sidebar", 240, 60, 420);
  return (
    <div className="min-h-screen bg-background">
      <DashboardSide width={sidebarW} onResize={resizeSidebar} />
      <main
        style={{ marginLeft: sidebarW }}
        className="relative isolate min-h-screen"
      >
        {kind === "home" ? (
          <>
            <div
              className="absolute inset-0 -z-10 bg-no-repeat"
              style={{
                backgroundImage: "url(/hero-aura.webp)",
                backgroundSize: "205%",
                backgroundPosition: "center 26%",
              }}
            />
            <section className="relative flex min-h-screen flex-col items-center justify-center gap-6 px-6">
              <button
                className="absolute right-5 top-5 rounded-md p-2 text-foreground/60 transition-colors hover:bg-white/40"
                aria-label="Alternar panel"
              >
                <PanelLeft className="size-5" />
              </button>
              <button className="flex items-center gap-2 rounded-full bg-background/70 py-1.5 pl-1.5 pr-4 text-sm shadow-sm ring-1 ring-black/5 backdrop-blur">
                <Badge className="rounded-full">Nuevo</Badge>
                Xframe ya genera vídeo en 4K con sonido nativo
                <ArrowRight className="size-4" />
              </button>
              <h1 className="text-center text-3xl font-bold tracking-tight sm:text-4xl">
                ¿Cuál es la visión, Héctor?
              </h1>
              <PromptBox />
            </section>
            <section className="relative z-10 -mt-24 px-5 pb-10 sm:px-8">
              <div className="mx-auto max-w-[1500px] rounded-3xl border bg-background p-6 shadow-2xl sm:p-8">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1 rounded-full border bg-background p-1 shadow-sm">
                    <button className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground">
                      <Search className="size-4" />
                      Buscar
                    </button>
                    {projectTabs.map(([v, l]) => (
                      <button
                        key={v}
                        onClick={() => setProjectView(v)}
                        className={cn(
                          "rounded-full px-3 py-1.5 text-sm transition-colors",
                          projectView === v
                            ? "bg-secondary font-medium text-foreground"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {l}
                      </button>
                    ))}
                  </div>
                  <UIButton variant="ghost" className="text-sm text-muted-foreground">
                    Explorar todo <ArrowRight />
                  </UIButton>
                </div>
                <ProjectGrid view={projectView} />
                <div className="mt-16">
                  <div className="mb-4 flex items-end justify-between">
                    <div>
                      <h2 className="text-xl font-semibold">
                        Actividad reciente
                      </h2>
                      <p className="text-sm text-muted-foreground">
                        Últimos cambios en tus proyectos
                      </p>
                    </div>
                    <UIButton variant="outline">Explorar todo</UIButton>
                  </div>
                  <Card className="divide-y overflow-hidden p-0">
                    {activityItems.map((item, i) => (
                      <div key={item} className="flex items-center gap-3 p-4">
                        <span className="flex size-8 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                          {i % 2 ? "L" : "H"}
                        </span>
                        <div className="flex-1">
                          <p className="text-sm font-medium">{item}</p>
                          <p className="text-xs text-muted-foreground">
                            {i + 1} {i ? "días" : "hora"} atrás
                          </p>
                        </div>
                        <span className="hidden text-sm text-muted-foreground sm:block">
                          Tráiler — Proyecto Neón
                        </span>
                      </div>
                    ))}
                  </Card>
                </div>
              </div>
            </section>
          </>
        ) : (
          <Resources />
        )}
      </main>
    </div>
  );
}
function Resources() {
  const items = [...templates, ...templates, ...templates, ...templates];
  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold tracking-tight">Recursos</h1>
      <p className="mt-1 text-muted-foreground">
        Empieza con un estilo para tu próximo vídeo
      </p>
      <div className="mt-6 grid grid-cols-2 gap-6 md:grid-cols-3 lg:grid-cols-4">
        {items.map((x, i) => (
          <div
            key={`${x[0]}-${i}`}
            className="group cursor-pointer"
            onClick={() => go("/dashboard")}
          >
            <div
              className="aspect-[4/3] overflow-hidden rounded-xl border bg-muted bg-cover bg-center transition-shadow group-hover:shadow-md"
              style={{ backgroundImage: `url(${x[2]})` }}
            />
            <h3 className="mt-3 font-medium">{x[0]}</h3>
            <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">
              {x[1]}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

const connectorCategories = [
  ["Ecommerce", 10],
  ["Marketing", 13],
  ["Messaging", 8],
  ["Productivity", 46],
  ["Sales", 12],
  ["Google", 10],
  ["Microsoft", 8],
  ["AWS", 2],
];
// [name, domain, description, category, { enabled, badge, kind, icon }]
const connectors = [
  ["Cloud", null, "Built-in backend, ready to use", "Productivity", { enabled: true, kind: "connections", icon: Cloud }],
  ["AI", null, "Unlock powerful AI features", "Productivity", { enabled: true, icon: Sparkles }],
  ["Stripe", "stripe.com", "Set up payments", "Ecommerce", { enabled: true }],
  ["Paddle", "paddle.com", "Set up payments with tax handled for you", "Ecommerce", {}],
  ["Shopify", "shopify.com", "Build an eCommerce store", "Ecommerce", {}],
  ["Apollo.io", "apollo.io", "Search, enrich, and engage B2B contacts and companies", "Sales", { badge: "New" }],
  ["ClickHouse", "clickhouse.com", "Query ClickHouse databases over the HTTP interface", "Productivity", { badge: "New", kind: "connections" }],
  ["dbt Semantic Layer", "getdbt.com", "Query governed metrics from your dbt Semantic Layer", "Productivity", { badge: "New", kind: "connections" }],
  ["Google Search Console", "search.google.com", "Read Search Console analytics and manage sites", "Google", {}],
  ["Firecrawl", "firecrawl.dev", "AI-powered scraper, search and retrieval tool", "Productivity", {}],
  ["Google Sheets", "sheets.google.com", "Read and update spreadsheet data", "Google", {}],
  ["Google Maps Platform", "mapsplatform.google.com", "Maps, geocoding, directions, and places APIs", "Google", { kind: "connections" }],
  ["Resend", "resend.com", "Email API for developers", "Marketing", {}],
  ["Gmail", "gmail.com", "Read, send, and manage your emails", "Google", {}],
  ["Google Drive", "drive.google.com", "Upload and download files to and from Google Drive", "Google", {}],
  ["Google Calendar", "calendar.google.com", "Create and manage Google Calendar events", "Google", {}],
  ["Telegram", "telegram.org", "Messaging platform with Bot API for automated interactions", "Messaging", {}],
  ["Twilio", "twilio.com", "Cloud communications platform for SMS, voice, and messaging", "Messaging", {}],
  ["ElevenLabs", "elevenlabs.io", "AI voice generation, text-to-speech, and speech-to-text", "Productivity", {}],
  ["Notion", "notion.so", "Add Notion pages and databases to your app", "Productivity", {}],
  ["Google Docs", "docs.google.com", "Create and edit Google Docs documents", "Google", {}],
  ["Brevo", "brevo.com", "Email, SMS, CRM, and marketing automation API", "Marketing", {}],
  ["Airtable", "airtable.com", "Spreadsheet-database hybrid and automation platform", "Productivity", {}],
  ["Slack", "slack.com", "Send messages and interact with Slack workspaces", "Messaging", {}],
  ["Microsoft Outlook", "outlook.com", "Read, send, and manage Outlook email", "Microsoft", {}],
  ["HubSpot", "hubspot.com", "CRM, marketing, and sales platform", "Sales", {}],
  ["GitHub", "github.com", "Sync code and manage repositories", "Productivity", { enabled: true }],
  ["Supabase", "supabase.com", "Postgres database, auth, and storage", "Productivity", { enabled: true, kind: "connections" }],
].map(([name, domain, desc, category, meta]) => ({
  name,
  domain,
  desc,
  category,
  kind: meta.kind || "permissions",
  ...meta,
}));

function ConnectorIcon({ c, className = "size-6" }) {
  if (c.icon) {
    const I = c.icon;
    return <I className={cn("text-foreground", className)} />;
  }
  if (c.domain) {
    return (
      <img
        src={`https://www.google.com/s2/favicons?domain=${c.domain}&sz=64`}
        alt=""
        className={cn("rounded-sm object-contain", className)}
        onError={(e) => {
          e.currentTarget.style.display = "none";
        }}
      />
    );
  }
  return (
    <span
      className={cn(
        "flex items-center justify-center rounded bg-primary text-xs font-bold text-primary-foreground",
        className,
      )}
    >
      {c.name[0]}
    </span>
  );
}

function PermTriToggle() {
  const [v, setV] = useState("ask");
  const opts = [
    ["allow", Check],
    ["ask", null],
    ["deny", Ban],
  ];
  return (
    <div className="flex items-center gap-1.5">
      {opts.map(([k, Icon]) => (
        <button
          key={k}
          onClick={() => setV(k)}
          className={cn(
            "flex size-7 items-center justify-center rounded-md border text-sm transition-colors",
            v === k
              ? "border-transparent bg-blue-600 text-white"
              : "text-muted-foreground hover:bg-accent",
          )}
        >
          {Icon ? <Icon className="size-4" /> : "?"}
        </button>
      ))}
    </div>
  );
}

const permissionRows = [
  ["Recommend payment provider", "Suggest which payment provider to use."],
  ["Create product", "Create a product with a price."],
  ["Batch create products", "Create multiple products with prices."],
  ["Create price", "Create a price for an existing product."],
  ["Check go-live status", "Check whether live payments are ready."],
];

function FauxSelect({ children }) {
  return (
    <button className="flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm">
      {children}
      <ChevronDown className="size-3.5 text-muted-foreground" />
    </button>
  );
}

function ConnectorDetail({ c }) {
  return (
    <div className="mx-auto max-w-3xl pb-4">
      <Card className="flex items-center gap-3 p-4">
        <div className="flex size-11 items-center justify-center rounded-lg border">
          <ConnectorIcon c={c} />
        </div>
        <div className="flex-1">
          <p className="font-semibold">{c.name}</p>
          <p className="text-sm text-muted-foreground">
            {c.enabled ? "Enabled" : "Not connected"}
          </p>
        </div>
        {c.enabled && <UIButton variant="outline">Disable for workspace</UIButton>}
      </Card>

      <h3 className="mt-6 text-lg font-semibold">Overview</h3>
      <p className="mt-1 text-sm text-muted-foreground">{c.desc}.</p>

      {c.kind === "permissions" ? (
        <>
          <h3 className="mt-6 text-lg font-semibold">
            Manage my agent&apos;s permissions
          </h3>
          <Card className="mt-3 divide-y p-0">
            <div className="flex items-center justify-between gap-4 p-4">
              <div>
                <p className="text-sm font-medium">Enable {c.name}</p>
                <p className="text-xs text-muted-foreground">
                  Enable {c.name} for a project.
                </p>
              </div>
              <FauxSelect>Ask each time</FauxSelect>
            </div>
            <div className="flex items-center justify-between gap-4 p-4">
              <div>
                <p className="text-sm font-medium">Manage all permissions</p>
                <p className="text-xs text-muted-foreground">
                  Set the default permission for all tools at once.
                </p>
              </div>
              <FauxSelect>Ask each time</FauxSelect>
            </div>
            {permissionRows.map(([t, d]) => (
              <div key={t} className="flex items-center justify-between gap-4 p-4">
                <div>
                  <p className="text-sm font-medium">{t}</p>
                  <p className="text-xs text-muted-foreground">{d}</p>
                </div>
                <PermTriToggle />
              </div>
            ))}
          </Card>
        </>
      ) : (
        <>
          <div className="mt-6 flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold">Connections</h3>
              <p className="text-sm text-muted-foreground">
                Create and manage connections for {c.name}
              </p>
            </div>
            <UIButton>
              <Plus /> Add connection <ChevronDown />
            </UIButton>
          </div>
          <Card className="mt-3 flex flex-col items-center justify-center gap-2 py-12">
            <span className="flex size-8 items-center justify-center rounded-full border text-sm text-muted-foreground">
              i
            </span>
            <p className="text-sm text-muted-foreground">No connections found</p>
          </Card>
          <h3 className="mt-6 text-lg font-semibold">Features</h3>
          <Card className="mt-3 p-4">
            <div className="flex items-center justify-between">
              <p className="flex items-center gap-2 text-sm font-medium">
                <Plug className="size-4" /> App + chat connector
              </p>
              <UIButton variant="outline" size="sm">
                Disable
              </UIButton>
            </div>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              <li>
                Runs on one shared credential for every request your deployed{" "}
                {c.name} app makes.
              </li>
              <li>Best for data your project should always be able to reach.</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

const sideItemClass =
  "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors";
function ConnectorsDialog({ onClose }) {
  const [selected, setSelected] = useState(null);
  const [category, setCategory] = useState("All");
  React.useEffect(() => {
    const el = document.documentElement;
    const prevHtml = el.style.overflow;
    const prevBody = document.body.style.overflow;
    el.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    return () => {
      el.style.overflow = prevHtml;
      document.body.style.overflow = prevBody;
    };
  }, []);
  const list = connectors.filter((c) =>
    category === "All"
      ? true
      : category === "Enabled"
        ? c.enabled
        : c.category === category,
  );
  return (
    <div
      className="fixed inset-0 z-50 flex items-center overscroll-contain p-4 pl-[248px]"
      onClick={onClose}
    >
      <div
        className="flex h-[85vh] w-full max-w-6xl overflow-hidden rounded-xl border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex w-56 shrink-0 flex-col gap-1 border-r bg-muted/30 p-3">
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <input
              placeholder="Search"
              className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          {["Enabled", "All"].map((c) => (
            <button
              key={c}
              onClick={() => {
                setCategory(c);
                setSelected(null);
              }}
              className={cn(
                sideItemClass,
                category === c ? "bg-accent font-medium" : "hover:bg-accent",
              )}
            >
              {c}
              <span className="ml-auto text-xs text-muted-foreground">
                {c === "Enabled" ? 5 : 97}
              </span>
            </button>
          ))}
          <p className="mt-3 px-2 text-xs font-medium text-muted-foreground">
            Categories
          </p>
          {connectorCategories.map(([c, n]) => (
            <button
              key={c}
              onClick={() => {
                setCategory(c);
                setSelected(null);
              }}
              className={cn(
                sideItemClass,
                category === c ? "bg-accent font-medium" : "hover:bg-accent",
              )}
            >
              {c}
              <span className="ml-auto text-xs text-muted-foreground">{n}</span>
            </button>
          ))}
          <div className="mt-auto flex flex-col gap-2 pt-3">
            <Card className="p-3">
              <Plug className="size-4 text-muted-foreground" />
              <p className="mt-1.5 text-sm font-medium">Missing a connector?</p>
              <UIButton variant="outline" size="sm" className="mt-2 w-full">
                Request
              </UIButton>
            </Card>
            <UIButton variant="outline" size="sm" className="w-full">
              <Settings /> Admin settings
            </UIButton>
          </div>
        </div>

        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex items-center gap-2 border-b px-5 py-3.5 text-sm">
            {selected ? (
              <button
                onClick={() => setSelected(null)}
                className="flex items-center gap-1.5 text-muted-foreground transition-colors hover:text-foreground"
              >
                <Plug className="size-4" />
                Connectors
              </button>
            ) : (
              <span className="flex items-center gap-1.5 font-medium">
                <Plug className="size-4" />
                Connectors
              </span>
            )}
            {selected && (
              <>
                <span className="text-muted-foreground">/</span>
                <span className="font-medium">{selected.name}</span>
              </>
            )}
            <button
              onClick={onClose}
              className="ml-auto text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto overscroll-contain p-5">
            {selected ? (
              <ConnectorDetail c={selected} />
            ) : (
              <>
                <div className="py-4 text-center">
                  <h2 className="text-xl font-bold">
                    Build from what you already use
                  </h2>
                  <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                    Connectors let your Xframe app talk to external tools like
                    Stripe, Slack, and Google. Ask the agent to get started.
                  </p>
                  <div className="mt-4 flex justify-center gap-2">
                    <UIButton variant="outline" size="sm">
                      View the docs <ExternalLink />
                    </UIButton>
                    <UIButton size="sm">Got it</UIButton>
                  </div>
                </div>
                <div className="mb-3 mt-2 flex justify-end">
                  <FauxSelect>Popular</FauxSelect>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {list.map((c) => (
                    <button
                      key={c.name}
                      onClick={() => setSelected(c)}
                      className="flex items-start gap-3 rounded-lg border bg-background p-3 text-left transition-colors hover:bg-accent"
                    >
                      <div className="relative flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background">
                        <ConnectorIcon c={c} className="size-5" />
                        {c.enabled && (
                          <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-background bg-green-500" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{c.name}</span>
                          {c.badge && (
                            <Badge
                              variant="secondary"
                              className="rounded px-1.5 py-0 text-[10px] font-medium"
                            >
                              {c.badge}
                            </Badge>
                          )}
                        </div>
                        <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                          {c.desc}
                        </p>
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const editorTabs = [
  ["preview", Monitor, "Vista previa"],
  ["assets", Layers, "All assets"],
  ["brief", FileText, "Project brief"],
  ["elements", AtSign, "Elements"],
  ["canvas", Frame, "Canvas"],
  ["chat", MessageCircle, "Chat"],
];
const assetFilters = [
  "Todos",
  "Vídeos",
  "Imágenes",
  "Personajes",
  "Fondos",
  "Audio",
];
// [nombre, tipo, meta, thumbnail]
const assetItems = [
  ["Plano 01 — Astronauta", "Vídeos", "00:08 · 4K", "/assets/prompt-frame.webp"],
  ["Plano 02 — Estación", "Vídeos", "00:06 · 4K", "/assets/continuum.jpg"],
  ["Plano 03 — Sala de control", "Vídeos", "00:05 · 1080p", "/assets/inspo.jpg"],
  ["Comandante Vega", "Personajes", "4 referencias", "/assets/vesper.webp"],
  ["Ingeniera Nara", "Personajes", "3 referencias", "/assets/personal-blog.png"],
  ["Estación orbital", "Fondos", "2048 × 858", "/assets/maison.webp"],
  ["Pasillo de emergencia", "Fondos", "2048 × 858", "/assets/ecommerce.webp"],
  ["Nébula ámbar", "Imágenes", "2048 × 858", "/assets/lovable-slides.webp"],
  ["Voz en off — ES", "Audio", "00:24", null],
  ["Score — Noir cálido", "Audio", "01:12", null],
];
const briefSections = [
  ["Logline", "Una frase que resuma la historia.", "Un astronauta descubre que la estación orbital que viene a rescatar lleva años vacía."],
  ["Objetivo", "¿Qué quieres conseguir con este vídeo?", "Tráiler de 24 s para lanzamiento en redes, con corte vertical adicional."],
  ["Audiencia", "¿A quién va dirigido?", "Público de 18-35 aficionado a la ciencia ficción."],
  ["Tono y referencias", "Estilo visual, ritmo y referencias.", "Noir cálido: luz lateral dura, grano fino, paleta ámbar sobre negro. Referencias: Blade Runner 2049, Interstellar."],
  ["Entregables", "Formatos y duración final.", "16:9 4K master · 9:16 para redes · subtítulos ES/EN."],
];
const elementChars = [
  ["Comandante Vega", "Protagonista · traje EVA blanco", "/assets/vesper.webp"],
  ["Ingeniera Nara", "Secundaria · mono técnico", "/assets/personal-blog.png"],
];
const elementLocations = [
  ["Estación orbital", "Interior abandonado, luz de emergencia", "/assets/maison.webp"],
  ["Sala de control", "Holografías, paneles rojos", "/assets/inspo.jpg"],
  ["Exterior órbita", "Tierra al fondo, silencio", "/assets/continuum.jpg"],
];
const canvasShots = [
  ["Plano 01", "Astronauta solitario en traje EVA flotando en gravedad cero, luz cinematográfica desde atrás.", "/assets/prompt-frame.webp"],
  ["Plano 02", "La lanzadera se aproxima a la estación abandonada, dolly lento hacia delante.", "/assets/continuum.jpg"],
  ["Plano 03", "Entra por la esclusa, la linterna del casco corta la oscuridad.", "/assets/inspo.jpg"],
  ["Plano 04", "Descubre la sala de control, holografías y paneles rojos parpadeando.", "/assets/maison.webp"],
  ["Plano 05", "La estación se sacude, luces de alarma y detritos flotando.", "/assets/ecommerce.webp"],
  ["Plano 06", "La cápsula de escape se aleja, la Tierra llena el encuadre.", "/assets/vesper.webp"],
];
const teamMessages = [
  ["H", "Héctor", "Subo el brief actualizado, el plano 4 necesita más contraste.", "10:24", true],
  ["N", "Nara", "De acuerdo. ¿Probamos con la paleta ámbar en lugar del azul?", "10:31", false],
  ["H", "Héctor", "Sí, y alarguemos el plano 2 a 8 s para que respire.", "10:33", true],
  ["M", "Marco", "Hecho. Regenerando planos 2 y 4 con Cinema Studio 3.5.", "10:40", false],
];
function ShareMenu({ projectId }) {
  const { profile } = useStudio();
  const [open, setOpen] = useState(false);
  const [invite, setInvite] = useState("");
  const [copied, setCopied] = useState(false);
  const [invited, setInvited] = useState([]);
  const link = `https://xframe.app/join/${projectId ?? "proyecto"}`;
  const copyLink = () => {
    navigator.clipboard?.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  // Compartir un proyecto crea un colaborador: acceso a ese proyecto y solo a
  // ese, sin ocupar plaza en el espacio de trabajo.
  const sendInvite = async () => {
    const email = invite.trim().toLowerCase();
    if (!email || !projectId) return;
    try {
      await db.addCollaborator(projectId, {
        email,
        role: "editor",
        invitedBy: profile?.id,
      });
      setInvited((list) => [...list, email]);
      setInvite("");
    } catch (error) {
      setInvited((list) => [...list, `${email} — ya tenía acceso`]);
      setInvite("");
    }
  };
  return (
    <div className="relative">
      <UIButton variant="outline" size="sm" onClick={() => setOpen(!open)}>
        <span className="flex size-5 items-center justify-center rounded-full bg-green-600 text-[10px] font-semibold text-white">
          H
        </span>
        Compartir
      </UIButton>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-2 w-[480px] rounded-xl border bg-background p-5 text-left shadow-2xl">
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-semibold">Compartir proyecto</h3>
              <button
                onClick={copyLink}
                className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {copied ? <Check className="size-4" /> : <Link className="size-4" />}
                {copied ? "Enlace copiado" : "Copiar enlace de invitación"}
              </button>
            </div>

            <div className="mt-4 flex gap-2">
              <Input
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendInvite()}
                type="email"
                placeholder="Invitar por correo electrónico"
                className="flex-1"
              />
              <UIButton
                disabled={!invite.trim()}
                onClick={sendInvite}
                className="bg-blue-500 text-white hover:bg-blue-600"
              >
                Invitar
              </UIButton>
            </div>

            <p className="mt-5 text-xs font-medium text-muted-foreground">
              Quién tiene acceso al proyecto
            </p>
            <div className="mt-3 space-y-3">
              <button className="flex items-center gap-2.5 text-sm">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full border text-muted-foreground">
                  <Ban className="size-3.5" />
                </span>
                Enlace de invitación desactivado
                <ChevronDown className="size-3.5 text-muted-foreground" />
              </button>
              <div className="flex items-center gap-2.5">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-green-600 text-xs font-semibold text-white">
                  H
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    Héctor Vidal Sánchez (tú)
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    hectorvidal0411@gmail.com
                  </p>
                </div>
                <span className="shrink-0 text-sm text-muted-foreground">
                  Propietario
                </span>
              </div>
            </div>

            <p className="mt-5 text-xs font-medium text-muted-foreground">
              Acceso general al proyecto
            </p>
            <div className="mt-3 flex items-center gap-2.5">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-pink-600 text-xs font-semibold text-white">
                H
              </span>
              <div className="min-w-0 flex-1">
                <button className="flex items-center gap-1 text-sm font-medium">
                  Espacio de trabajo de Héctor's Xframe
                  <ChevronDown className="size-3.5 text-muted-foreground" />
                </button>
                <p className="truncate text-xs text-muted-foreground">
                  Personas en este espacio de trabajo
                </p>
              </div>
              <button className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground">
                Puede editar
                <ChevronDown className="size-3.5" />
              </button>
            </div>

            {invited.map((email) => (
              <div key={email} className="mt-3 flex items-center gap-2.5">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold uppercase">
                  {email[0]}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{email}</p>
                  <p className="text-xs text-muted-foreground">Invitación enviada</p>
                </div>
              </div>
            ))}

            <UIButton variant="outline" className="mt-5 w-full" onClick={copyLink}>
              {copied ? <Check /> : <Link />}
              {copied ? "Enlace copiado" : "Compartir vista previa"}
            </UIButton>
          </div>
        </>
      )}
    </div>
  );
}
const EditorIconBtn = ({ children, onClick, className = "" }) => (
  <button
    onClick={onClick}
    className={cn(
      "flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground [&_svg]:size-4",
      className,
    )}
  >
    {children}
  </button>
);

// El sidebar es el mismo en todas las pestañas, pero lo que genera depende de
// dónde estés: en All assets crea assets, en Vista previa edita el montaje, en
// Project brief redacta y en Canvas ordena el mapa.
const chatContext = {
  assets: {
    label: "Generación de assets",
    hint: "Lo que pidas aquí se genera como asset del proyecto.",
    placeholder: "Describe el asset: un personaje, un fondo, un plano…",
    chips: [
      "Un astronauta con traje EVA desgastado",
      "Interior de estación orbital abandonada",
      "Nébula ámbar de fondo",
    ],
  },
  preview: {
    label: "Edición del montaje",
    hint: "Aquí solo se editan el corte y el ritmo del vídeo final.",
    placeholder: "Pide un cambio en el montaje: ritmo, orden, duración…",
    chips: ["Déjalo en 30 s", "Ritmo de tráiler", "Alarga el plano 2"],
  },
  brief: {
    label: "Redacción del brief",
    hint: "Te ayudo a afinar el brief del proyecto.",
    placeholder: "Pide ayuda con el brief: logline, tono, entregables…",
    chips: ["Mejora el logline", "Añade referencias visuales", "Resume el brief"],
  },
  canvas: {
    label: "Organización del canvas",
    hint: "Reordeno y agrupo los nodos del mapa mental.",
    placeholder: "Pide reorganizar el canvas: agrupar, ordenar, conectar…",
    chips: ["Ordena los planos", "Agrupa por escena", "Conecta los conceptos"],
  },
  elements: {
    label: "Elements del proyecto",
    hint: "Los elements se crean desde All assets: genera y asígnalos.",
    placeholder: "Pide ajustes sobre personajes y localizaciones…",
    chips: ["Revisa la continuidad", "Describe a Vega", "Falta una localización"],
  },
  chat: {
    label: "Chat de equipo",
    hint: "Esta pestaña es la conversación con tu equipo, no conmigo.",
    placeholder: "Escríbeme para trabajar sobre el proyecto…",
    chips: [],
  },
};

function EditorChat({
  width,
  onResize,
  tab,
  log,
  onSend,
  onStop,
  busy,
  stream = null,
  elements = [],
  onUpload,
}) {
  const [draft, setDraft] = useState("");
  const [mentionAt, setMentionAt] = useState(null);
  const { preferences } = useStudio();
  const ctx = chatContext[tab] ?? chatContext.assets;
  const endRef = useRef(null);
  const areaRef = useRef(null);
  const fileRef = useRef(null);

  // Menciones @: se abren al escribir "@" y filtran por lo que sigue.
  const mentionQuery =
    mentionAt === null ? null : draft.slice(mentionAt + 1).toLowerCase();
  const matches =
    mentionQuery === null
      ? []
      : elements.filter((e) => e.name.toLowerCase().includes(mentionQuery));

  const insertMention = (element) => {
    const before = draft.slice(0, mentionAt);
    setDraft(`${before}@${element.name} `);
    setMentionAt(null);
    areaRef.current?.focus();
  };

  const openMention = () => {
    const next = draft.endsWith(" ") || !draft ? `${draft}@` : `${draft} @`;
    setMentionAt(next.length - 1);
    setDraft(next);
    areaRef.current?.focus();
  };

  const onDraftChange = (value) => {
    setDraft(value);
    const at = value.lastIndexOf("@");
    // Solo es mención si el @ abre palabra y no hay espacio después.
    const open =
      at >= 0 &&
      (at === 0 || /\s/.test(value[at - 1])) &&
      !/\s/.test(value.slice(at + 1));
    setMentionAt(open ? at : null);
  };

  // El autoscroll también depende del texto en curso: el turno del agente llega
  // token a token, así que sin esto el mensaje crece por debajo del recorte.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [log.length, busy, stream?.text, stream?.assets?.length]);

  const send = (text) => {
    const value = (text ?? draft).trim();
    if (!value || busy) return;
    onSend(value);
    setDraft("");
    setMentionAt(null);
  };

  return (
    <aside
      style={{ width }}
      className="relative flex shrink-0 flex-col border-r bg-background"
    >
      <ResizeHandle onResize={onResize} />

      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
        {log.length === 0 && !draft.trim() && (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <Sparkles className="size-5 text-muted-foreground" />
            <p className="mt-2 text-sm font-medium">{ctx.label}</p>
            <p className="mt-1 text-sm text-muted-foreground">{ctx.hint}</p>
          </div>
        )}

        {log.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="ml-8 rounded-2xl bg-muted p-3">
              {m.text}
            </div>
          ) : (
            <div key={m.id} className="space-y-2">
              <p className="leading-relaxed">{m.text}</p>
              {m.actions && (
                <div className="flex items-center gap-1 text-muted-foreground">
                  {[Undo2, ThumbsUp, ThumbsDown, Copy].map((I, i) => (
                    <EditorIconBtn key={i}>
                      <I />
                    </EditorIconBtn>
                  ))}
                </div>
              )}
            </div>
          ),
        )}

        {/* Turno en curso. Va fuera de `log` a propósito: solo se persiste el
            mensaje final, así que mientras dura el stream vive aparte y al
            terminar el Editor lo vuelca a `log` de una pieza. */}
        {stream && (
          <div className="space-y-2">
            {stream.text && <p className="leading-relaxed">{stream.text}</p>}

            {stream.assets?.length > 0 && (
              <div className="grid grid-cols-3 gap-1.5">
                {stream.assets.map((a) => (
                  <div
                    key={a.id}
                    className="aspect-video overflow-hidden rounded-md border bg-muted bg-cover bg-center"
                    style={{ backgroundImage: a.url ? `url(${a.url})` : undefined }}
                    title={a.name}
                  >
                    {!a.url && (
                      <div className="flex h-full items-center justify-center">
                        <RefreshCw className="size-3.5 animate-spin text-muted-foreground" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {stream.tool && (
              <p className="flex items-center gap-2 text-muted-foreground">
                <RefreshCw className="size-3.5 animate-spin" />
                {stream.tool}
              </p>
            )}
          </div>
        )}

        {busy && !stream?.text && !stream?.tool && (
          <p className="flex items-center gap-2 text-muted-foreground">
            <RefreshCw className="size-3.5 animate-spin" />
            Generando…
          </p>
        )}

        <div ref={endRef} />
      </div>

      {preferences.chatSuggestions && !busy && !draft.trim() && ctx.chips.length > 0 && (
        <div className="flex flex-wrap gap-2 px-3 pb-1">
          {ctx.chips.map((c) => (
            <button
              key={c}
              onClick={() => send(c)}
              className="rounded-full border px-3 py-1.5 text-xs transition-colors hover:bg-accent"
            >
              {c}
            </button>
          ))}
        </div>
      )}

      <div className="relative p-3">
        {mentionAt !== null && matches.length > 0 && (
          <div className="absolute bottom-full left-3 right-3 z-30 mb-1 max-h-56 overflow-y-auto rounded-xl border bg-background p-1 shadow-2xl">
            <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Elements del proyecto
            </p>
            {matches.map((element) => (
              <button
                key={element.id}
                onMouseDown={(e) => (e.preventDefault(), insertMention(element))}
                className="flex w-full items-center gap-2 rounded-md p-1 text-left transition-colors hover:bg-accent"
              >
                <div
                  className="size-7 shrink-0 rounded bg-muted bg-cover bg-center"
                  style={{
                    backgroundImage: element.url ? `url(${element.url})` : undefined,
                  }}
                />
                <div className="min-w-0">
                  <p className="truncate text-sm">{element.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {element.role}
                  </p>
                </div>
              </button>
            ))}
          </div>
        )}
        {mentionAt !== null && matches.length === 0 && elements.length === 0 && (
          <div className="absolute bottom-full left-3 right-3 z-30 mb-1 rounded-xl border bg-background p-3 text-xs text-muted-foreground shadow-2xl">
            Aún no hay elements. Genera assets y asígnalos desde All assets.
          </div>
        )}

        <Card className="p-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*,video/*,audio/*"
            multiple
            className="hidden"
            onChange={(e) => {
              onUpload?.(e.target.files);
              e.target.value = "";
            }}
          />
          <Textarea
            ref={areaRef}
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={(e) => {
              if (mentionAt !== null && matches.length && e.key === "Enter") {
                e.preventDefault();
                return insertMention(matches[0]);
              }
              if (e.key === "Escape") return setMentionAt(null);
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={ctx.placeholder}
            className="min-h-[52px] resize-none border-0 text-sm shadow-none focus-visible:ring-0"
          />
          <GenSettingsBar
            onMention={openMention}
            onAttach={() => fileRef.current?.click()}
            trailing={
              <>
                <EditorIconBtn>
                  <Mic />
                </EditorIconBtn>
                {/* Mientras el agente responde, el mismo botón corta el turno.
                    Un stream que solo se puede esperar es una trampa: los
                    turnos duran minutos porque hay renders de por medio. */}
                {busy && onStop ? (
                  <UIButton size="icon" className="size-8" onClick={onStop}>
                    <X />
                  </UIButton>
                ) : (
                  <UIButton
                    size="icon"
                    className="size-8"
                    disabled={!draft.trim() || busy}
                    onClick={() => send()}
                  >
                    <ArrowUp />
                  </UIButton>
                )}
              </>
            }
          />
        </Card>
      </div>
    </aside>
  );
}



/** Exportación del montaje: formato, resolución y progreso. */
function ExportDialog({ onClose }) {
  const [format, setFormat] = useState("MP4");
  const [quality, setQuality] = useState("1080p");
  const [progress, setProgress] = useState(null);

  const start = () => {
    setProgress(0);
    const id = setInterval(
      () =>
        setProgress((p) => {
          if (p === null) return p;
          if (p >= 100) {
            clearInterval(id);
            return 100;
          }
          return p + 10;
        }),
      220,
    );
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Exportar vídeo</DialogTitle>
          <DialogDescription>
            Se renderiza el montaje completo con el audio del proyecto.
          </DialogDescription>
        </DialogHeader>

        {progress === null ? (
          <>
            <SettingsSlider
              label="Formato"
              value={format}
              options={["MP4", "MOV", "WebM", "GIF"]}
              onChange={setFormat}
            />
            <SettingsSlider
              label="Resolución"
              value={quality}
              options={resolutionList}
              onChange={setQuality}
            />
            <div className="flex justify-end gap-2">
              <UIButton variant="outline" onClick={onClose}>
                Cancelar
              </UIButton>
              <UIButton onClick={start}>
                <Download /> Exportar
              </UIButton>
            </div>
          </>
        ) : (
          <div className="space-y-3 py-2">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-sm text-muted-foreground">
              {progress >= 100
                ? `Listo · ${format} ${quality}`
                : `Renderizando… ${progress}%`}
            </p>
            {progress >= 100 && (
              <div className="flex justify-end">
                <UIButton onClick={onClose}>
                  <Check /> Hecho
                </UIButton>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const previewAspects = [
  ["16:9", "aspect-video"],
  ["9:16", "aspect-[9/16]"],
  ["1:1", "aspect-square"],
];
const fmt = (s) =>
  Number.isFinite(s)
    ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`
    : "0:00";

function EditorPreview({ assets = [] }) {
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);
  // Los planos del montaje salen de los assets del proyecto; si aún no hay,
  // se usa el guion de ejemplo para que la vista previa nunca quede vacía.
  const shots = assets.filter((a) => a.url && a.status === "ready").length
    ? assets
        .filter((a) => a.url && a.status === "ready")
        .slice(0, 8)
        .map((a) => [a.name, a.meta, a.url])
    : canvasShots;
  const videoRef = useRef(null);
  const barRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [loop, setLoop] = useState(true);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const [aspect, setAspect] = useState("16:9");

  const shotLen = dur ? dur / shots.length : 0;
  const active = shotLen ? Math.min(shots.length - 1, Math.floor(time / shotLen)) : 0;

  const seek = (t) => {
    const v = videoRef.current;
    if (!v || !Number.isFinite(dur)) return;
    v.currentTime = Math.min(dur, Math.max(0, t));
    setTime(v.currentTime);
  };
  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    v.paused ? v.play() : v.pause();
  };
  const scrub = (e) => {
    const r = barRef.current.getBoundingClientRect();
    const at = (clientX) => seek(((clientX - r.left) / r.width) * dur);
    at(e.clientX);
    const move = (ev) => at(ev.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  useEffect(() => {
    const onKey = (e) => {
      if (/INPUT|TEXTAREA/.test(document.activeElement?.tagName)) return;
      if (e.code === "Space") (e.preventDefault(), toggle());
      if (e.key === "ArrowLeft") seek(time - 5);
      if (e.key === "ArrowRight") seek(time + 5);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [time, dur]);

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center gap-2 rounded-xl border bg-background px-3 py-2">
        <div className="flex items-center rounded-md border p-0.5">
          {previewAspects.map(([id]) => (
            <button
              key={id}
              onClick={() => setAspect(id)}
              className={cn(
                "rounded px-2 py-0.5 text-xs transition-colors",
                aspect === id
                  ? "bg-accent font-medium text-foreground"
                  : "text-muted-foreground hover:bg-accent",
              )}
            >
              {id}
            </button>
          ))}
        </div>
        <Badge variant="secondary" className="font-normal">
          1080p · {shots.length} planos
        </Badge>
        <div className="flex-1" />
        <UIButton
          variant="ghost"
          size="sm"
          onClick={() => {
            navigator.clipboard?.writeText(location.href);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
        >
          {copied ? <Check /> : <Share2 />} {copied ? "Copiado" : "Compartir"}
        </UIButton>
        <UIButton variant="outline" size="sm" onClick={() => setExporting(true)}>
          <Download /> Exportar
        </UIButton>
      </div>

      <div className="flex min-h-0 flex-1 flex-col rounded-xl border bg-background">
        <div className="flex min-h-0 flex-1 items-center justify-center bg-neutral-950 p-4">
          <video
            ref={videoRef}
            src="/assets/scene-1.webm"
            poster="/assets/prompt-frame.webp"
            playsInline
            loop={loop}
            muted={muted}
            onClick={toggle}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
            onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
            className={cn(
              "max-h-full cursor-pointer rounded-lg bg-black object-contain",
              previewAspects.find(([id]) => id === aspect)[1],
            )}
          />
        </div>

        <div className="border-t px-3 py-2">
          <div
            ref={barRef}
            onPointerDown={scrub}
            className="group relative h-4 cursor-pointer touch-none"
          >
            <div className="absolute top-1.5 h-1 w-full rounded-full bg-muted" />
            <div
              className="absolute top-1.5 h-1 rounded-full bg-primary"
              style={{ width: `${dur ? (time / dur) * 100 : 0}%` }}
            />
            {shots.map((_, i) =>
              i ? (
                <span
                  key={i}
                  className="absolute top-1.5 h-1 w-px bg-background"
                  style={{ left: `${(i / shots.length) * 100}%` }}
                />
              ) : null,
            )}
            <div
              className="absolute top-0.5 size-3 -translate-x-1/2 rounded-full bg-primary opacity-0 shadow transition-opacity group-hover:opacity-100"
              style={{ left: `${dur ? (time / dur) * 100 : 0}%` }}
            />
          </div>

          <div className="mt-1 flex items-center gap-1">
            <button
              onClick={() => seek(active * shotLen - 0.01)}
              title="Plano anterior"
              className="flex size-8 items-center justify-center rounded-md hover:bg-accent"
            >
              <SkipBack className="size-4" />
            </button>
            <button
              onClick={toggle}
              title="Reproducir / pausar (Espacio)"
              className="flex size-8 items-center justify-center rounded-md hover:bg-accent"
            >
              {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
            </button>
            <button
              onClick={() => seek((active + 1) * shotLen)}
              title="Plano siguiente"
              className="flex size-8 items-center justify-center rounded-md hover:bg-accent"
            >
              <SkipForward className="size-4" />
            </button>
            <span className="ml-1 text-xs tabular-nums text-muted-foreground">
              {fmt(time)} / {fmt(dur)}
            </span>
            <div className="flex-1" />
            <button
              onClick={() => setLoop(!loop)}
              title="Bucle"
              className={cn(
                "flex size-8 items-center justify-center rounded-md hover:bg-accent",
                loop ? "text-foreground" : "text-muted-foreground",
              )}
            >
              <Repeat className="size-4" />
            </button>
            <button
              onClick={() => setMuted(!muted)}
              title={muted ? "Activar sonido" : "Silenciar"}
              className="flex size-8 items-center justify-center rounded-md hover:bg-accent"
            >
              {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
            </button>
            <button
              onClick={() => videoRef.current?.requestFullscreen?.()}
              title="Pantalla completa"
              className="flex size-8 items-center justify-center rounded-md hover:bg-accent"
            >
              <Maximize2 className="size-4" />
            </button>
          </div>
        </div>
      </div>

      {exporting && <ExportDialog onClose={() => setExporting(false)} />}

      <div className="shrink-0 rounded-xl border bg-background p-2">
        <div className="flex gap-2 overflow-x-auto">
          {shots.map(([title, text, thumb], i) => (
            <button
              key={title}
              onClick={() => seek(i * shotLen)}
              title={text}
              className={cn(
                "w-32 shrink-0 overflow-hidden rounded-lg border text-left transition-shadow hover:shadow-md",
                active === i && "ring-2 ring-primary",
              )}
            >
              <div
                className="aspect-video bg-muted bg-cover bg-center"
                style={{ backgroundImage: `url(${thumb})` }}
              />
              <div className="px-2 py-1.5">
                <p className="truncate text-xs font-medium">{title}</p>
                <p className="text-[10px] tabular-nums text-muted-foreground">
                  {fmt(i * shotLen)}
                </p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

const elementRoles = ["Personaje", "Localización", "Objeto"];

// Vista ampliada del asset.
function AssetLightbox({ asset, onClose, onAssign, onRegenerate, onDuplicate }) {
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="truncate pr-6">{asset.name}</DialogTitle>
          <DialogDescription className="flex items-center gap-2">
            <Badge variant="secondary" className="rounded px-1.5 py-0 text-[10px]">
              {asset.type}
            </Badge>
            {asset.meta}
            {asset.role && (
              <span className="flex items-center gap-1 text-foreground">
                <AtSign className="size-3" />
                {asset.role}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {asset.url ? (
          <img
            src={asset.url}
            alt={asset.name}
            className="max-h-[65vh] w-full rounded-lg bg-muted object-contain"
          />
        ) : (
          <div className="flex h-64 items-center justify-center rounded-lg bg-muted">
            <Volume2 className="size-10 text-muted-foreground" />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <UIButton variant="outline" size="sm" onClick={() => onRegenerate(asset.id)}>
            <RefreshCw /> Regenerar
          </UIButton>
          <UIButton variant="outline" size="sm" onClick={() => onDuplicate(asset.id)}>
            <Copy /> Duplicar
          </UIButton>
          <UIButton variant="outline" size="sm" asChild>
            <a href={asset.url ?? "#"} download>
              <Download /> Descargar
            </a>
          </UIButton>
          <div className="flex-1" />
          {elementRoles.map((role) => (
            <UIButton
              key={role}
              size="sm"
              variant={asset.role === role ? "default" : "outline"}
              onClick={() => onAssign(asset.id, asset.role === role ? null : role)}
            >
              <AtSign /> {role}
            </UIButton>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Diálogo para asignar un rol de elemento escrito por el usuario.
function CustomRoleDialog({ asset, onClose, onAssign }) {
  const [value, setValue] = useState(asset.role ?? "");
  const confirm = () => {
    const role = value.trim();
    if (!role) return;
    onAssign(asset.id, role);
    onClose();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>Nuevo tipo de elemento</DialogTitle>
          <DialogDescription>
            Escribe el tipo que quieras — vehículo, criatura, prop, lo que necesite
            tu proyecto.
          </DialogDescription>
        </DialogHeader>
        <Input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && confirm()}
          placeholder="Vehículo, criatura, prop…"
        />
        <div className="flex justify-end gap-2">
          <UIButton variant="outline" onClick={onClose}>
            Cancelar
          </UIButton>
          <UIButton disabled={!value.trim()} onClick={confirm}>
            Asignar
          </UIButton>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Acciones del asset: aparecen al pasar el ratón sobre la tarjeta.
function AssetMenu({
  asset,
  onAssign,
  onDuplicate,
  onRemove,
  onRegenerate,
  onOpen,
  onCustomRole,
}) {
  return (
    <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 transition-opacity group-hover/card:opacity-100 focus-within:opacity-100">
      <button
        onClick={() => onRegenerate(asset.id)}
        title="Regenerar"
        className="flex size-7 items-center justify-center rounded-md bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/75"
      >
        <RefreshCw className="size-3.5" />
      </button>
      <button
        onClick={() => onDuplicate(asset.id)}
        title="Duplicar"
        className="flex size-7 items-center justify-center rounded-md bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/75"
      >
        <Copy className="size-3.5" />
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            title="Más acciones"
            className="flex size-7 items-center justify-center rounded-md bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/75"
          >
            <MoreHorizontal className="size-3.5" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <AtSign className="mr-2 size-3.5" />
              Asignar a Elements
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {(asset.role && !elementRoles.includes(asset.role)
                ? [...elementRoles, asset.role]
                : elementRoles
              ).map((role) => (
                <DropdownMenuItem
                  key={role}
                  onClick={() => onAssign(asset.id, asset.role === role ? null : role)}
                >
                  {role}
                  {asset.role === role && <Check className="ml-auto size-3.5" />}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => onCustomRole(asset.id)}>
                <Plus className="mr-2 size-3.5" />
                Otro tipo…
              </DropdownMenuItem>
              {asset.role && (
                <DropdownMenuItem onClick={() => onAssign(asset.id, null)}>
                  <X className="mr-2 size-3.5" />
                  Quitar de Elements
                </DropdownMenuItem>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => onOpen(asset.id)}>
            <Maximize2 className="mr-2 size-3.5" />
            Abrir en grande
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onRegenerate(asset.id)}>
            <RefreshCw className="mr-2 size-3.5" />
            Regenerar
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onDuplicate(asset.id)}>
            <Copy className="mr-2 size-3.5" />
            Duplicar
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <a href={asset.url ?? "#"} download>
              <Download className="mr-2 size-3.5" />
              Descargar
            </a>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => onRemove(asset.id)}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="mr-2 size-3.5" />
            Eliminar
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function EditorAssets({
  assets,
  onAssign,
  onDuplicate,
  onRemove,
  onRegenerate,
  onUpload,
}) {
  const fileRef = useRef(null);
  const [filter, setFilter] = useState("Todos");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState(null);
  const [customId, setCustomId] = useState(null);
  const openAsset = assets.find((a) => a.id === openId);
  const customAsset = assets.find((a) => a.id === customId);
  const list = assets.filter(
    (a) =>
      (filter === "Todos" || a.type === filter) &&
      a.name.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border bg-background">
      <div className="flex flex-wrap items-center gap-2 border-b p-4">
        <div className="relative w-56">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar en assets…"
            className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {assetFilters.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "rounded-full px-3 py-1.5 text-xs transition-colors",
                filter === f
                  ? "bg-secondary font-medium text-foreground"
                  : "text-muted-foreground hover:bg-accent",
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {list.length} elementos
          </span>
          <input
            ref={fileRef}
            type="file"
            accept="image/*,video/*,audio/*"
            multiple
            className="hidden"
            onChange={(e) => {
              onUpload?.(e.target.files);
              e.target.value = "";
            }}
          />
          <UIButton size="sm" onClick={() => fileRef.current?.click()}>
            <Plus /> Subir
          </UIButton>
        </div>
      </div>
      <div className="grid flex-1 auto-rows-min grid-cols-2 gap-4 overflow-y-auto p-4 md:grid-cols-3 xl:grid-cols-4">
        {list.map((a) => (
          <div key={a.id} className="group/card relative">
            <button
              title={a.name}
              onClick={() => a.status === "ready" && setOpenId(a.id)}
              className={cn(
                "relative block w-full overflow-hidden rounded-xl transition-shadow hover:shadow-md",
                a.role && "ring-2 ring-primary ring-offset-2 ring-offset-background",
                a.status === "generating" && "cursor-default",
              )}
            >
              {a.status === "generating" ? (
                <div className="flex aspect-video animate-pulse items-center justify-center bg-muted">
                  <RefreshCw className="size-6 animate-spin text-muted-foreground" />
                </div>
              ) : a.url ? (
                <div
                  className="aspect-video bg-muted bg-cover bg-center"
                  style={{ backgroundImage: `url(${a.url})` }}
                />
              ) : (
                <div className="flex aspect-video items-center justify-center bg-muted">
                  <Volume2 className="size-7 text-muted-foreground" />
                </div>
              )}

              <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-black/55 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                {a.status === "generating" ? "Generando…" : a.type}
              </span>

              {a.status === "ready" && (
                <span className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/70 to-transparent px-2 pb-1.5 pt-6 text-left text-[11px] text-white opacity-0 transition-opacity group-hover/card:opacity-100">
                  {a.name}
                </span>
              )}
            </button>

            {a.role && (
              <span className="pointer-events-none absolute right-2 top-2 flex items-center gap-1 rounded-full bg-primary px-2 py-0.5 text-[10px] font-medium text-primary-foreground group-hover/card:opacity-0">
                <AtSign className="size-2.5" />
                {a.role}
              </span>
            )}

            {a.status === "ready" && (
              <AssetMenu
                asset={a}
                onAssign={onAssign}
                onDuplicate={onDuplicate}
                onRemove={onRemove}
                onRegenerate={onRegenerate}
                onOpen={setOpenId}
                onCustomRole={setCustomId}
              />
            )}
          </div>
        ))}
      </div>

      {openAsset && (
        <AssetLightbox
          asset={openAsset}
          onClose={() => setOpenId(null)}
          onAssign={onAssign}
          onRegenerate={onRegenerate}
          onDuplicate={onDuplicate}
        />
      )}
      {customAsset && (
        <CustomRoleDialog
          asset={customAsset}
          onClose={() => setCustomId(null)}
          onAssign={onAssign}
        />
      )}
    </div>
  );
}

const blockTypes = [
  ["text", "Texto", Type, "Escribe algo, o pulsa / para comandos"],
  ["h1", "Título 1", Heading1, "Título"],
  ["h2", "Título 2", Heading2, "Subtítulo"],
  ["bullet", "Lista", List, "Elemento de lista"],
  ["todo", "Tareas", ListTodo, "Por hacer"],
  ["quote", "Cita", Quote, "Cita"],
  ["callout", "Destacado", Lightbulb, "Idea clave"],
  ["image", "Imagen", ImageIcon, ""],
  ["divider", "Separador", Minus, ""],
];
const blockMeta = Object.fromEntries(
  blockTypes.map(([id, label, icon, ph]) => [id, { label, icon, ph }]),
);
let briefUid = 0;
const newBlock = (type = "text", extra) => ({
  id: `b${++briefUid}`,
  type,
  text: "",
  checked: false,
  src: null,
  ...extra,
});
const initialBrief = () =>
  briefSections.flatMap(([title, hint, value]) => [
    newBlock("h2", { text: title }),
    newBlock("text", { text: value }),
  ]);

function AutoTextarea({ value, className, autoFocus, ...props }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  useEffect(() => {
    if (!autoFocus) return;
    const el = ref.current;
    el?.focus();
    el?.setSelectionRange(el.value.length, el.value.length);
  }, [autoFocus]);
  return (
    <textarea
      ref={ref}
      rows={1}
      value={value}
      className={cn(
        "w-full resize-none overflow-hidden bg-transparent outline-none placeholder:text-muted-foreground/60",
        className,
      )}
      {...props}
    />
  );
}

function BriefBlock({ block, focus, update, onEnter, onBackspace, onRemove, dragProps }) {
  const [menu, setMenu] = useState(false);
  const q = block.text.startsWith("/") ? block.text.slice(1).toLowerCase() : "";
  const matches = blockTypes.filter(([, label]) => label.toLowerCase().includes(q));

  const setType = (type) => {
    update({ type, text: "" });
    setMenu(false);
  };
  const onKeyDown = (e) => {
    if (menu && matches.length) {
      if (e.key === "Enter") return e.preventDefault(), setType(matches[0][0]);
      if (e.key === "Escape") return setMenu(false);
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onEnter();
    }
    if (e.key === "Backspace" && !block.text) {
      e.preventDefault();
      onBackspace();
    }
  };
  const onChange = (e) => {
    const text = e.target.value;
    update({ text });
    setMenu(text.startsWith("/"));
  };
  const shared = {
    value: block.text,
    onChange,
    onKeyDown,
    autoFocus: focus,
    placeholder: blockMeta[block.type].ph,
  };

  return (
    <div className="group relative -ml-14 flex items-start gap-1 pl-14">
      <div className="absolute left-0 top-0.5 flex opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <button
          onClick={onRemove}
          title="Eliminar bloque"
          className="flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-accent"
        >
          <Trash2 className="size-3.5" />
        </button>
        <button
          {...dragProps}
          title="Arrastra para reordenar"
          className="flex size-6 cursor-grab items-center justify-center rounded text-muted-foreground hover:bg-accent active:cursor-grabbing"
        >
          <GripVertical className="size-3.5" />
        </button>
      </div>

      <div className="min-w-0 flex-1 py-0.5">
        {block.type === "divider" && <Separator className="my-3" />}
        {block.type === "h1" && (
          <AutoTextarea {...shared} className="text-2xl font-bold tracking-tight" />
        )}
        {block.type === "h2" && (
          <AutoTextarea {...shared} className="text-lg font-semibold tracking-tight" />
        )}
        {block.type === "text" && <AutoTextarea {...shared} className="leading-relaxed" />}
        {block.type === "bullet" && (
          <div className="flex gap-2">
            <span className="mt-2 size-1.5 shrink-0 rounded-full bg-foreground" />
            <AutoTextarea {...shared} className="leading-relaxed" />
          </div>
        )}
        {block.type === "todo" && (
          <div className="flex gap-2">
            <input
              type="checkbox"
              checked={block.checked}
              onChange={(e) => update({ checked: e.target.checked })}
              className="mt-1.5 size-3.5 shrink-0 accent-primary"
            />
            <AutoTextarea
              {...shared}
              className={cn(
                "leading-relaxed",
                block.checked && "text-muted-foreground line-through",
              )}
            />
          </div>
        )}
        {block.type === "quote" && (
          <div className="border-l-2 pl-3">
            <AutoTextarea {...shared} className="italic leading-relaxed text-muted-foreground" />
          </div>
        )}
        {block.type === "callout" && (
          <div className="flex gap-2 rounded-lg bg-muted p-3">
            <Lightbulb className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <AutoTextarea {...shared} className="text-sm leading-relaxed" />
          </div>
        )}
        {block.type === "image" &&
          (block.src ? (
            <figure className="my-1">
              <img src={block.src} alt="" className="max-h-[420px] w-full rounded-lg object-cover" />
              <input
                value={block.text}
                onChange={onChange}
                placeholder="Añade un pie de foto…"
                className="mt-1.5 w-full bg-transparent text-xs text-muted-foreground outline-none"
              />
            </figure>
          ) : (
            <label className="my-1 flex cursor-pointer items-center gap-2 rounded-lg border border-dashed p-4 text-sm text-muted-foreground transition-colors hover:bg-accent">
              <Upload className="size-4" />
              Sube una imagen o arrastra un archivo aquí
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) update({ src: URL.createObjectURL(f) });
                }}
              />
            </label>
          ))}

        {menu && matches.length > 0 && (
          <div className="absolute z-30 mt-1 w-56 rounded-xl border bg-background p-1 shadow-2xl">
            {matches.map(([id, label, I]) => (
              <button
                key={id}
                onMouseDown={(e) => (e.preventDefault(), setType(id))}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
              >
                <I className="size-3.5 text-muted-foreground" />
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EditorBrief({ data, title = "", onRename }) {
  const [blocks, setBlocksLocal] = useState(() => data.brief ?? initialBrief());
  const setBlocks = (next) =>
    setBlocksLocal((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      data.saveBrief(value);
      return value;
    });
  const [focusId, setFocusId] = useState(null);
  const [dragIdx, setDragIdx] = useState(null);

  const update = (id, patch) =>
    setBlocks((bs) => bs.map((b) => (b.id === id ? { ...b, ...patch } : b)));
  const insertAfter = (i, type = "text") => {
    const b = newBlock(type);
    setBlocks((bs) => [...bs.slice(0, i + 1), b, ...bs.slice(i + 1)]);
    setFocusId(b.id);
  };
  const remove = (i) => {
    if (blocks.length === 1) return;
    setFocusId(blocks[Math.max(0, i - 1)].id);
    setBlocks((bs) => bs.filter((_, n) => n !== i));
  };
  const move = (from, to) =>
    setBlocks((bs) => {
      const next = [...bs];
      next.splice(to, 0, next.splice(from, 1)[0]);
      return next;
    });

  const onDrop = (e) => {
    e.preventDefault();
    const files = [...(e.dataTransfer?.files || [])].filter((f) =>
      f.type.startsWith("image/"),
    );
    if (!files.length) return;
    setBlocks((bs) => [
      ...bs,
      ...files.map((f) => newBlock("image", { src: URL.createObjectURL(f) })),
    ]);
  };

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      className="h-full overflow-y-auto rounded-xl border bg-background"
    >
      <div className="mx-auto max-w-3xl px-8 py-10 pl-20">
        <input
          value={title}
          onChange={(e) => onRename?.(e.target.value)}
          placeholder="Título del proyecto"
          className="w-full bg-transparent text-4xl font-bold tracking-tight outline-none placeholder:text-muted-foreground/40"
        />
        <p className="mt-1 text-sm text-muted-foreground">
          Escribe <span className="font-medium text-foreground">/</span> para
          insertar títulos, listas, imágenes y más. Arrastra archivos aquí para
          añadirlos.
        </p>

        <div className="mt-8">
          {blocks.map((b, i) => (
            <div
              key={b.id}
              onDragOver={(e) => {
                e.preventDefault();
                if (dragIdx !== null && dragIdx !== i) {
                  move(dragIdx, i);
                  setDragIdx(i);
                }
              }}
              className={cn(dragIdx === i && "opacity-40")}
            >
              <BriefBlock
                block={b}
                focus={focusId === b.id}
                update={(patch) => update(b.id, patch)}
                onEnter={() => insertAfter(i)}
                onBackspace={() => remove(i)}
                onRemove={() => remove(i)}
                dragProps={{
                  draggable: true,
                  onDragStart: () => setDragIdx(i),
                  onDragEnd: () => setDragIdx(null),
                }}
              />
            </div>
          ))}
        </div>

        <button
          onClick={() => insertAfter(blocks.length - 1)}
          className="mt-2 flex w-full items-center gap-2 rounded-md py-1.5 text-sm text-muted-foreground opacity-60 transition-opacity hover:opacity-100"
        >
          <Plus className="size-4" /> Añadir un bloque
        </button>
      </div>
    </div>
  );
}

function ElementGrid({ title, desc, items, action, onAction }) {
  return (
    <section className="mt-8 first:mt-0">
      <div className="flex items-end justify-between">
        <div>
          <h3 className="font-semibold">{title}</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>
        </div>
        <UIButton variant="outline" size="sm" onClick={onAction}>
          <Plus /> {action}
        </UIButton>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-3">
        {items.map(([name, meta, thumb]) => (
          <button
            key={name}
            className="overflow-hidden rounded-xl border text-left transition-shadow hover:shadow-md"
          >
            <div
              className="aspect-[4/3] bg-muted bg-cover bg-center"
              style={{ backgroundImage: `url(${thumb})` }}
            />
            <div className="p-3">
              <p className="flex items-center gap-1 truncate text-sm font-medium">
                <AtSign className="size-3.5 text-muted-foreground" />
                {name}
              </p>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {meta}
              </p>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
function EditorElements({ assets, onGoToAssets }) {
  const elements = assets.filter((a) => a.role);
  const byRole = (role) =>
    elements
      .filter((a) => a.role === role)
      .map((a) => [a.name, a.meta, a.url]);

  return (
    <div className="h-full overflow-y-auto rounded-xl border bg-background">
      <div className="mx-auto max-w-4xl px-8 py-10">
        <h2 className="text-2xl font-bold tracking-tight">Elements</h2>
        <p className="mt-1 text-muted-foreground">
          Los assets que has asignado como elemento. El agente los tiene en
          cuenta al montar el vídeo, y puedes referenciarlos con{" "}
          <span className="font-medium text-foreground">@</span> en cualquier
          prompt para mantener la continuidad entre planos.
        </p>

        {elements.length === 0 ? (
          <div className="mt-10 rounded-xl border border-dashed p-10 text-center">
            <AtSign className="mx-auto size-7 text-muted-foreground" />
            <h3 className="mt-3 font-semibold">Aún no hay elements</h3>
            <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
              Genera assets desde el chat en All assets y pulsa sobre el que te
              guste para asignarlo como personaje, localización u objeto.
            </p>
            <UIButton className="mt-4" onClick={onGoToAssets}>
              <Layers /> Ir a All assets
            </UIButton>
          </div>
        ) : (
          [...new Set([...elementRoles, ...elements.map((a) => a.role)])].map((role) => {
            const items = byRole(role);
            if (items.length === 0) return null;
            return (
              <ElementGrid
                key={role}
                title={`${role}s`}
                desc={
                  role === "Personaje"
                    ? "Se mantienen consistentes en todos los planos."
                    : role === "Localización"
                      ? "Escenarios reutilizables del proyecto."
                      : "Atrezo y objetos recurrentes."
                }
                items={items}
                action={`Nuevo ${role.toLowerCase()}`}
                onAction={onGoToAssets}
              />
            );
          })
        )}
      </div>
    </div>
  );
}

const NODE_W = { concept: 250, shot: 190 };
const NODE_H = { concept: 118, shot: 178 };
const buildCanvasNodes = () => [
  {
    id: "c1",
    type: "concept",
    x: 40,
    y: 110,
    title: "Concepto",
    text: "Astronauta solitario en traje EVA blanco, gravedad cero, luz cinematográfica desde atrás, sci-fi fotorrealista.",
  },
  {
    id: "c2",
    type: "concept",
    x: 40,
    y: 330,
    title: "Localización",
    text: "Interior de estación orbital abandonada, luz de emergencia, detritos flotando, Tierra visible.",
  },
  ...canvasShots.map(([title, text, thumb], i) => ({
    id: `s${i + 1}`,
    type: "shot",
    x: 380 + i * 220,
    y: 480,
    title,
    text,
    thumb,
  })),
];
const buildCanvasEdges = () =>
  canvasShots.map((_, i) => ({ from: i < 3 ? "c1" : "c2", to: `s${i + 1}` }));

const PICKER_W = 288;
const PICKER_H = 380;
/**
 * Fuentes del selector, derivadas de los assets vivos del proyecto: lo que
 * generes o subas en All assets aparece aquí al momento.
 */
const mediaSourcesFor = (assets) => [
  [
    "elements",
    "Elements",
    assets.filter((a) => a.role && a.url).map((a) => [a.name, a.role, a.url]),
  ],
  [
    "assets",
    "Assets",
    assets.filter((a) => !a.role && a.url).map((a) => [a.name, a.type, a.url]),
  ],
  ["shots", "Planos", canvasShots.map(([n, d, t]) => [n, d, t])],
];

function CanvasMediaPicker({ onPick, onClose, at, assets = [] }) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const sources = mediaSourcesFor(assets);
  const groups = sources
    .filter(([id]) => cat === "all" || cat === id)
    .map(([, title, items]) => [
      title,
      items.filter(([n]) => n.toLowerCase().includes(q.toLowerCase())),
    ])
    .filter(([, items]) => items.length);

  return (
    <div
      data-canvas-overlay
      onPointerDown={(e) => e.stopPropagation()}
      style={{ left: at.left, top: at.top, width: PICKER_W, maxHeight: PICKER_H }}
      className="absolute z-30 flex flex-col overflow-hidden rounded-xl border bg-background shadow-2xl"
    >
      <div className="flex items-center gap-2 border-b p-2">
        <Search className="size-3.5 shrink-0 text-muted-foreground" />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Buscar assets y elementos…"
          className="min-w-0 flex-1 bg-transparent text-sm outline-none"
        />
        <button
          onClick={onClose}
          className="flex size-6 shrink-0 items-center justify-center rounded hover:bg-accent"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <div className="flex flex-wrap gap-1 border-b px-2 py-1.5">
        {[["all", "Todo"], ...sources.map(([id, l]) => [id, l])].map(
          ([id, label]) => (
            <button
              key={id}
              onClick={() => setCat(id)}
              className={cn(
                "rounded-full px-2 py-0.5 text-xs transition-colors",
                cat === id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent",
              )}
            >
              {label}
            </button>
          ),
        )}
      </div>

      <label className="flex cursor-pointer items-center gap-2 border-b p-2 text-sm transition-colors hover:bg-accent">
        <Upload className="size-3.5 text-muted-foreground" />
        Subir una imagen…
        <input
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onPick(URL.createObjectURL(f), f.name);
          }}
        />
      </label>

      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {groups.map(([title, items]) => (
          <div key={title} className="mb-1">
            <p className="sticky top-0 z-10 bg-background px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {title}
            </p>
            {items.map(([name, meta, thumb]) => (
              <button
                key={title + name}
                onClick={() => onPick(thumb, name)}
                className="flex w-full items-center gap-2 rounded-md p-1 text-left transition-colors hover:bg-accent"
              >
                <div
                  className="size-9 shrink-0 rounded bg-muted bg-cover bg-center"
                  style={{ backgroundImage: `url(${thumb})` }}
                />
                <div className="min-w-0">
                  <p className="truncate text-sm">{name}</p>
                  <p className="truncate text-xs text-muted-foreground">{meta}</p>
                </div>
              </button>
            ))}
          </div>
        ))}
        {!groups.length && (
          <p className="p-3 text-center text-sm text-muted-foreground">
            Sin resultados
          </p>
        )}
      </div>
    </div>
  );
}

function EditorCanvas({ data, assets = [] }) {
  const [nodes, setNodesLocal] = useState(
    () => data?.canvas?.nodes ?? buildCanvasNodes(),
  );
  const [edges, setEdgesLocal] = useState(
    () => data?.canvas?.edges ?? buildCanvasEdges(),
  );
  // Cada cambio se guarda en el proyecto: el layout sobrevive al cambio de pestaña.
  const persist = (nextNodes, nextEdges) =>
    data?.saveCanvas({ nodes: nextNodes, edges: nextEdges });
  const setNodes = (next) =>
    setNodesLocal((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      persist(value, edges);
      return value;
    });
  const setEdges = (next) =>
    setEdgesLocal((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      persist(nodes, value);
      return value;
    });
  const [zoom, setZoom] = useState(0.7);
  const [pan, setPan] = useState({ x: 20, y: 0 });
  const [selected, setSelected] = useState(null);
  const [linking, setLinking] = useState(null);
  const [picking, setPicking] = useState(null);
  const [heights, setHeights] = useState({});
  const wrapRef = useRef(null);
  const elsRef = useRef({});
  const measure = (id) => (el) => {
    if (el) elsRef.current[id] = el;
    else delete elsRef.current[id];
  };
  // Ports sit at 50% of each node's *rendered* height, so edges must anchor to
  // the measured height — nodes grow when media or text is added.
  useEffect(() => {
    setHeights((h) => {
      let next = h;
      for (const [id, el] of Object.entries(elsRef.current)) {
        const v = el.offsetHeight;
        if (h[id] !== v) next = next === h ? { ...h, [id]: v } : ((next[id] = v), next);
      }
      return next;
    });
  });

  const toCanvas = (clientX, clientY) => {
    const r = wrapRef.current.getBoundingClientRect();
    return {
      x: (clientX - r.left - pan.x) / zoom,
      y: (clientY - r.top - pan.y) / zoom,
    };
  };
  const drag = (onMove) => {
    const move = (ev) => onMove(ev);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.removeProperty("user-select");
    };
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const startNodeDrag = (e, id) => {
    e.stopPropagation();
    setSelected(id);
    const n = nodes.find((x) => x.id === id);
    const sx = e.clientX;
    const sy = e.clientY;
    const ox = n.x;
    const oy = n.y;
    drag((ev) =>
      setNodes((ns) =>
        ns.map((x) =>
          x.id === id
            ? { ...x, x: ox + (ev.clientX - sx) / zoom, y: oy + (ev.clientY - sy) / zoom }
            : x,
        ),
      ),
    );
  };
  const startPan = (e) => {
    setSelected(null);
    setPicking(null);
    const sx = e.clientX;
    const sy = e.clientY;
    const o = { ...pan };
    drag((ev) =>
      setPan({ x: o.x + (ev.clientX - sx), y: o.y + (ev.clientY - sy) }),
    );
  };
  const startLink = (e, id) => {
    e.stopPropagation();
    const p = toCanvas(e.clientX, e.clientY);
    setLinking({ from: id, x: p.x, y: p.y });
    const move = (ev) => {
      const q = toCanvas(ev.clientX, ev.clientY);
      setLinking((l) => l && { ...l, x: q.x, y: q.y });
    };
    const up = (ev) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const el = document.elementFromPoint(ev.clientX, ev.clientY);
      const target = el?.closest("[data-node-id]")?.dataset.nodeId;
      if (target && target !== id) {
        setEdges((es) =>
          es.some((x) => x.from === id && x.to === target)
            ? es
            : [...es, { from: id, to: target }],
        );
      }
      setLinking(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e) => {
      // Overlays (media picker, toolbars) scroll on their own — never zoom there.
      if (e.target.closest?.("[data-canvas-overlay]")) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      setZoom((z) => {
        const next = Math.min(2, Math.max(0.2, z * (e.deltaY > 0 ? 0.9 : 1.1)));
        setPan((p) => ({
          x: mx - ((mx - p.x) / z) * next,
          y: my - ((my - p.y) / z) * next,
        }));
        return next;
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") setPicking(null);
      if ((e.key === "Delete" || e.key === "Backspace") && selected) {
        if (/INPUT|TEXTAREA/.test(document.activeElement?.tagName)) return;
        setNodes((ns) => ns.filter((n) => n.id !== selected));
        setEdges((es) => es.filter((x) => x.from !== selected && x.to !== selected));
        setSelected(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  const anchor = (n, side) => ({
    x: n.x + (side === "out" ? NODE_W[n.type] : 0),
    y: n.y + (heights[n.id] ?? NODE_H[n.type]) / 2,
  });
  const curve = (a, b) =>
    `M ${a.x} ${a.y} C ${a.x + 70} ${a.y}, ${b.x - 70} ${b.y}, ${b.x} ${b.y}`;

  const fit = () => {
    if (!nodes.length) return;
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const maxX = Math.max(...nodes.map((n) => n.x + NODE_W[n.type]));
    const maxY = Math.max(...nodes.map((n) => n.y + NODE_H[n.type]));
    const r = wrapRef.current.getBoundingClientRect();
    const z = Math.min(
      1.2,
      Math.max(0.2, Math.min((r.width - 80) / (maxX - Math.min(...xs)), (r.height - 80) / (maxY - Math.min(...ys)))),
    );
    setZoom(z);
    setPan({ x: 40 - Math.min(...xs) * z, y: 40 - Math.min(...ys) * z });
  };
  // Screen-space position for the media picker: pinned beside the node, flipped
  // to its left when it would overflow, and clamped inside the canvas.
  const pickerPos = (id) => {
    const n = nodes.find((x) => x.id === id);
    const r = wrapRef.current?.getBoundingClientRect();
    if (!n || !r) return { left: 16, top: 16 };
    const nodeLeft = pan.x + n.x * zoom;
    const nodeRight = nodeLeft + NODE_W[n.type] * zoom;
    const left =
      nodeRight + 8 + PICKER_W <= r.width ? nodeRight + 8 : nodeLeft - 8 - PICKER_W;
    const top = pan.y + n.y * zoom;
    return {
      left: Math.min(r.width - PICKER_W - 8, Math.max(8, left)),
      top: Math.min(r.height - PICKER_H - 8, Math.max(8, top)),
    };
  };
  const attach = (id, patch) => {
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, ...patch } : n)));
    setPicking(null);
  };
  const dropFiles = (e) => {
    e.preventDefault();
    const files = [...(e.dataTransfer?.files || [])].filter((f) =>
      f.type.startsWith("image/"),
    );
    if (!files.length) return;
    const p = toCanvas(e.clientX, e.clientY);
    setNodes((ns) => [
      ...ns,
      ...files.map((f, i) => ({
        id: `n${Date.now()}${i}`,
        type: "concept",
        x: p.x + i * 30,
        y: p.y + i * 30,
        title: "Referencia",
        text: f.name,
        thumb: URL.createObjectURL(f),
        media: f.name,
      })),
    ]);
  };
  const addNode = () => {
    const r = wrapRef.current.getBoundingClientRect();
    const p = toCanvas(r.left + r.width / 2, r.top + r.height / 2);
    const id = `n${Date.now()}`;
    setNodes((ns) => [
      ...ns,
      { id, type: "concept", x: p.x - 125, y: p.y - 60, title: "Nuevo nodo", text: "Describe esta idea…" },
    ]);
    setSelected(id);
  };

  return (
    <div
      ref={wrapRef}
      onPointerDown={startPan}
      onDragOver={(e) => e.preventDefault()}
      onDrop={dropFiles}
      className="relative h-full cursor-grab overflow-hidden rounded-xl border bg-muted/20 active:cursor-grabbing"
      style={{
        backgroundImage:
          "radial-gradient(circle, hsl(var(--border)) 1px, transparent 1px)",
        backgroundSize: `${22 * zoom}px ${22 * zoom}px`,
        backgroundPosition: `${pan.x}px ${pan.y}px`,
      }}
    >
      <div
        className="absolute left-0 top-0 origin-top-left"
        style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
      >
        <svg className="pointer-events-none absolute overflow-visible text-muted-foreground/50">
          {edges.map(({ from, to }, i) => {
            const a = nodes.find((n) => n.id === from);
            const b = nodes.find((n) => n.id === to);
            if (!a || !b) return null;
            return (
              <path
                key={i}
                d={curve(anchor(a, "out"), anchor(b, "in"))}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
            );
          })}
          {linking &&
            (() => {
              const a = nodes.find((n) => n.id === linking.from);
              return (
                <path
                  d={curve(anchor(a, "out"), { x: linking.x, y: linking.y })}
                  fill="none"
                  stroke="currentColor"
                  strokeDasharray="4 4"
                  strokeWidth="1.5"
                />
              );
            })()}
        </svg>

        {nodes.map((n) => (
          <div
            key={n.id}
            ref={measure(n.id)}
            data-node-id={n.id}
            onPointerDown={(e) => startNodeDrag(e, n.id)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const f = [...(e.dataTransfer?.files || [])].find((x) =>
                x.type.startsWith("image/"),
              );
              if (f) attach(n.id, { thumb: URL.createObjectURL(f), media: f.name });
            }}
            style={{ left: n.x, top: n.y, width: NODE_W[n.type] }}
            className={cn(
              "group absolute cursor-grab rounded-xl border bg-background shadow-sm active:cursor-grabbing",
              selected === n.id && "ring-2 ring-primary",
            )}
          >
            {n.thumb && (
              <div className="relative">
                <div
                  className="aspect-video rounded-t-xl bg-muted bg-cover bg-center"
                  style={{ backgroundImage: `url(${n.thumb})` }}
                />
                <button
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => attach(n.id, { thumb: null, media: null })}
                  title="Quitar media"
                  className="absolute right-1 top-1 flex size-5 items-center justify-center rounded-md bg-black/55 text-white opacity-0 transition-opacity group-hover:opacity-100"
                >
                  <X className="size-3" />
                </button>
                {n.media && (
                  <span className="absolute bottom-1 left-1 max-w-[85%] truncate rounded bg-black/55 px-1.5 py-0.5 text-[9px] text-white">
                    {n.media}
                  </span>
                )}
              </div>
            )}
            <div className="p-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {n.title}
              </p>
              <textarea
                value={n.text}
                onPointerDown={(e) => e.stopPropagation()}
                onChange={(e) =>
                  setNodes((ns) =>
                    ns.map((x) =>
                      x.id === n.id ? { ...x, text: e.target.value } : x,
                    ),
                  )
                }
                className="mt-1 h-14 w-full resize-none bg-transparent text-[10px] leading-relaxed outline-none"
              />
              <button
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => setPicking(n.id)}
                className="flex w-full items-center gap-1 rounded px-1 py-0.5 text-[10px] text-muted-foreground opacity-0 transition-opacity hover:bg-accent group-hover:opacity-100"
              >
                <Paperclip className="size-3" />
                {n.thumb ? "Cambiar media" : "Añadir asset, elemento o foto"}
              </button>
            </div>
            <span
              onPointerDown={(e) => startLink(e, n.id)}
              title="Arrastra para conectar"
              className="absolute -right-1.5 top-1/2 size-3 -translate-y-1/2 cursor-crosshair rounded-full border-2 border-background bg-primary"
            />
            <span className="absolute -left-1.5 top-1/2 size-3 -translate-y-1/2 rounded-full border-2 border-background bg-muted-foreground/40" />
          </div>
        ))}
      </div>

      <div
        data-canvas-overlay onPointerDown={(e) => e.stopPropagation()}
        className="absolute bottom-4 left-4 flex items-center gap-1 rounded-lg border bg-background p-1 shadow-sm"
      >
        <button
          onClick={() => setZoom((z) => Math.max(0.2, +(z - 0.1).toFixed(2)))}
          className="flex size-7 items-center justify-center rounded hover:bg-accent"
        >
          <Minus className="size-3.5" />
        </button>
        <span className="w-12 text-center text-xs tabular-nums">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom((z) => Math.min(2, +(z + 0.1).toFixed(2)))}
          className="flex size-7 items-center justify-center rounded hover:bg-accent"
        >
          <Plus className="size-3.5" />
        </button>
        <Separator orientation="vertical" className="mx-1 h-5" />
        <button
          onClick={fit}
          title="Ajustar a la vista"
          className="flex size-7 items-center justify-center rounded hover:bg-accent"
        >
          <Maximize2 className="size-3.5" />
        </button>
        <button
          onClick={() => {
            setNodes(buildCanvasNodes());
            setEdges(buildCanvasEdges());
            setSelected(null);
          }}
          title="Restablecer"
          className="flex size-7 items-center justify-center rounded hover:bg-accent"
        >
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      <div
        data-canvas-overlay onPointerDown={(e) => e.stopPropagation()}
        className="absolute right-4 top-4 flex items-center gap-2"
      >
        {selected && (
          <UIButton
            variant="outline"
            size="sm"
            onClick={() => {
              setNodes((ns) => ns.filter((n) => n.id !== selected));
              setEdges((es) =>
                es.filter((x) => x.from !== selected && x.to !== selected),
              );
              setSelected(null);
            }}
          >
            <X /> Eliminar
          </UIButton>
        )}
        <UIButton size="sm" onClick={addNode}>
          <Plus /> Añadir nodo
        </UIButton>
      </div>

      {picking && nodes.some((n) => n.id === picking) && (
        <CanvasMediaPicker
          key={picking}
          assets={assets}
          at={pickerPos(picking)}
          onClose={() => setPicking(null)}
          onPick={(thumb, media) => attach(picking, { thumb, media })}
        />
      )}

      <p className="pointer-events-none absolute bottom-5 right-4 text-xs text-muted-foreground">
        Arrastra para mover · rueda para zoom · tira del punto azul para conectar
      </p>
    </div>
  );
}

function EditorTeamChat() {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border bg-background">
      <div className="flex items-center gap-3 border-b px-5 py-3">
        <MessageCircle className="size-4 text-muted-foreground" />
        <div className="flex-1">
          <p className="text-sm font-medium">Chat del equipo</p>
          <p className="text-xs text-muted-foreground">
            3 miembros · Tráiler — Proyecto Neón
          </p>
        </div>
        <div className="flex -space-x-2">
          {["H", "N", "M"].map((a) => (
            <span
              key={a}
              className="flex size-7 items-center justify-center rounded-full border-2 border-background bg-muted text-xs font-semibold"
            >
              {a}
            </span>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-5">
        <div className="mx-auto w-full max-w-3xl space-y-5">
        {teamMessages.map(([initial, name, text, time, me], i) => (
          <div key={i} className={cn("flex gap-3", me && "flex-row-reverse")}>
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
              {initial}
            </span>
            <div className={cn("max-w-[70%]", me && "text-right")}>
              <p className="text-xs text-muted-foreground">
                {name} · {time}
              </p>
              <div
                className={cn(
                  "mt-1 rounded-2xl px-3 py-2 text-sm",
                  me ? "bg-primary text-primary-foreground" : "bg-muted",
                )}
              >
                {text}
              </div>
            </div>
          </div>
        ))}
        </div>
      </div>
      <div className="border-t p-3">
        <Card className="mx-auto flex w-full max-w-3xl items-center gap-2 p-2">
          <EditorIconBtn>
            <Plus />
          </EditorIconBtn>
          <input
            placeholder="Escribe un mensaje al equipo…"
            className="h-8 flex-1 bg-transparent text-sm outline-none"
          />
          <UIButton size="icon" className="size-8">
            <ArrowUp />
          </UIButton>
        </Card>
      </div>
    </div>
  );
}

/** Saldo de créditos en la cabecera del editor. */
function CreditsBadge() {
  const { profile } = useStudio();
  if (!profile) return null;
  const low = profile.credits < 30;
  return (
    <button
      onClick={() => go("/es/pricing")}
      title={`${profile.credits} créditos · plan ${profile.plan}`}
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors hover:bg-accent",
        low && "border-destructive/40 text-destructive",
      )}
    >
      <Zap className="size-3.5" />
      <span className="tabular-nums">{profile.credits}</span>
    </button>
  );
}

function CreditsDialog({ credits, onClose }) {
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Te has quedado sin créditos</DialogTitle>
          <DialogDescription>
            Te quedan {credits} créditos. Mejora el plan para seguir generando
            sin límites.
          </DialogDescription>
        </DialogHeader>
        <div className="flex justify-end gap-2">
          <UIButton variant="outline" onClick={onClose}>
            Ahora no
          </UIButton>
          <UIButton onClick={() => go("/es/pricing")}>
            <Zap /> Ver planes
          </UIButton>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PublishDialog({ project, onClose }) {
  const url = `https://xframe.app/v/${project.id}`;
  const [copied, setCopied] = useState(false);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle>Publicar «{project.title}»</DialogTitle>
          <DialogDescription>
            Se creará una página pública con el vídeo final. Cualquiera con el
            enlace podrá verlo.
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2 rounded-lg border bg-muted/40 p-2">
          <Globe className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-sm">{url}</span>
          <UIButton
            variant="ghost"
            size="sm"
            onClick={() => {
              navigator.clipboard?.writeText(url);
              setCopied(true);
            }}
          >
            {copied ? <Check /> : <Copy />}
            {copied ? "Copiado" : "Copiar"}
          </UIButton>
        </div>
        <div className="flex justify-end gap-2">
          <UIButton variant="outline" onClick={onClose}>
            Cancelar
          </UIButton>
          <UIButton onClick={onClose}>Publicar</UIButton>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Editor({ projectId }) {
  const { projects, profile, genSettings, refreshCredits, updateProject, ready } =
    useStudio();
  const project = projects.find((p) => p.id === projectId);
  const data = useProjectData(projectId);
  const {
    assets,
    addAssets,
    patchAsset,
    removeAsset,
    messages,
    addMessage,
    loaded,
  } = data;

  const [tab, setTab] = useState("preview");
  const [chatW, resizeChat] = useResizableWidth("xf-editor-chat", 380, 300, 720);
  const [busy, setBusy] = useState(false);
  const [noCredits, setNoCredits] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const ranInitial = useRef(false);
  // Turno del agente en curso: el texto que va llegando y los assets que aún no
  // tienen render. Vive fuera de `messages` porque solo se persiste el final.
  const [stream, setStream] = useState(null);
  const turn = useRef(null);

  // Cambiar de proyecto o salir del editor corta el stream, no el trabajo: los
  // jobs encolados son del worker y deben terminar aunque nadie mire.
  useEffect(() => () => turn.current?.cancel(), [projectId]);

  const elements = assets.filter((a) => a.role);

  /**
   * Sube archivos del usuario al bucket `assets` de Supabase y los registra
   * como assets del proyecto. Sin backend cae a una URL local temporal.
   */
  const uploadFiles = async (files) => {
    const accepted = [...files].filter((f) => /^(image|video|audio)\//.test(f.type));
    if (!accepted.length) return 0;

    const rows = await Promise.all(
      accepted.map(async (file) => ({
        name: file.name.replace(/\.[^.]+$/, ""),
        type: file.type.startsWith("video")
          ? "Vídeos"
          : file.type.startsWith("audio")
            ? "Audio"
            : "Imágenes",
        meta: `${Math.round(file.size / 1024)} KB`,
        url: await uploadAsset({ userId: profile.id, projectId, file }),
        status: "ready",
      })),
    );
    await addAssets(rows);
    return rows.length;
  };

  /**
   * Un turno del agente.
   *
   * Todo lo que el usuario escribe pasa por aquí, sea la pestaña que sea: quien
   * decide si esto es una generación, una edición del brief o una respuesta es
   * el agente, no el frontend. Antes había un `if (tab === "assets")` que
   * bifurcaba entre generar y contestar con texto fijo; esa decisión ahora vive
   * en el grafo, y el tab solo viaja como contexto (`open_tab`).
   *
   * El texto llega token a token en `message_delta` y se acumula en `stream`.
   * Solo al terminar se vuelca a `messages` con `addMessage`, porque lo que se
   * persiste es el mensaje final, no cada fragmento.
   */
  const runTurn = async (text) => {
    if (!profile) return;

    turn.current?.cancel();
    setBusy(true);
    setStream({ text: "", tool: null, assets: [] });

    let full = "";

    // Ids que ya existen como fila. Se lleva aparte y no se consulta `assets`
    // porque dentro del turno ese array es la foto de cuando arrancó: un asset
    // insertado hace dos eventos todavía no está ahí, y buscarlo allí acabaría
    // insertándolo por segunda vez al llegar su `asset_ready`.
    const known = new Set(assets.map((a) => String(a.id)));

    const uiContext = buildUIContext({
      project,
      tab,
      brief: data.brief,
      canvas: data.canvas,
      assets,
      // La selección de assets todavía vive dentro de EditorAssets; hasta que
      // se levante aquí, el agente recibe la lista vacía.
      selectedIds: [],
      genSettings,
      credits: profile.credits,
    });

    turn.current = sendMessage({
      conversationId: conversationIdFor(projectId),
      projectId,
      userId: profile.id,
      message: text,
      uiContext,

      onMessageDelta: (e) => {
        full += e.content ?? "";
        setStream((s) => (s ? { ...s, text: full } : s));
      },

      onToolStart: (e) => {
        const [first] = e.tools ?? [];
        setStream((s) => (s ? { ...s, tool: first ? labelForTool(first) : null } : s));
      },

      onToolResult: () => {
        setStream((s) => (s ? { ...s, tool: null } : s));
      },

      // Una generación encolada devuelve una referencia en `generating`, no un
      // render. Se inserta ya como asset para que aparezca en All assets con su
      // placeholder; el worker es quien lo completará.
      onJobStatus: async (e) => {
        if (e.status !== "queued" || !e.asset) return;
        const [row] = await addAssets([
          {
            ...e.asset,
            status: "generating",
            meta: e.asset.meta ?? "Generando",
          },
        ]);
        if (!row) return;
        known.add(String(row.id));
        setStream((s) => (s ? { ...s, assets: [...s.assets, row] } : s));
      },

      // El render ha aterrizado. Si el asset ya existía como placeholder se
      // parchea; si no (el worker lo creó entero), se añade.
      onAssetReady: async (e) => {
        const incoming = e.asset ?? e;
        if (known.has(String(incoming.id))) {
          patchAsset(incoming.id, { ...incoming, status: "ready" });
        } else {
          known.add(String(incoming.id));
          await addAssets([{ ...incoming, status: "ready" }]);
        }

        setStream((s) =>
          s
            ? {
                ...s,
                assets: s.assets.map((a) =>
                  a.id === incoming.id ? { ...a, ...incoming } : a,
                ),
              }
            : s,
        );

        // La primera imagen del proyecto también le pone portada.
        if (project && !project.cover_url && incoming.url) {
          updateProject(projectId, { cover_url: incoming.url });
        }
      },

      // Un interrupt del grafo es una pregunta al usuario. Se muestra como un
      // mensaje más: responder es simplemente escribir el siguiente turno.
      onInterruptRequest: (e) => {
        full += (full ? "\n\n" : "") + (e.question ?? e.message ?? "");
        setStream((s) => (s ? { ...s, text: full, tool: null } : s));
      },

      onError: (e) => {
        full += (full ? "\n\n" : "") + (e.message ?? AGENT_DOWN_MESSAGE);
        setStream((s) => (s ? { ...s, text: full, tool: null } : s));
      },

      onDone: () => {
        setBusy(false);
        setStream(null);
        turn.current = null;
        if (full.trim()) addMessage("agent", full.trim());
        // Quien cobra es el backend contra el libro mayor, así que el saldo
        // nuevo no se deduce: se vuelve a preguntar.
        refreshCredits();
      },
    });

    await turn.current.promise;
  };

  /** Corta el turno en curso. Los jobs ya encolados siguen: son del worker. */
  const stopTurn = () => {
    turn.current?.cancel();
    turn.current = null;
    setBusy(false);
    setStream(null);
  };

  /**
   * Regenerar es otro turno del agente, no una operación aparte: así respeta
   * los mismos ajustes, el mismo contexto y el mismo libro de créditos.
   */
  const regenerateAsset = (id) => {
    const asset = assets.find((a) => a.id === id);
    if (!asset || busy) return;
    patchAsset(id, { status: "generating", url: null });
    runTurn(`Regenera el asset "${asset.name}" manteniendo su intención original.`);
  };

  const duplicateAsset = (id) => {
    const source = assets.find((a) => a.id === id);
    if (!source) return;
    const { id: _id, project_id, created_at, ...rest } = source;
    addAssets([{ ...rest, name: `${source.name} (copia)`, role: null }]);
  };

  const handleSend = (text) => {
    addMessage("user", text);
    runTurn(text);
  };

  // ?run=1 → el prompt con el que se creó el proyecto se ejecuta al entrar.
  useEffect(() => {
    if (!loaded || !project || ranInitial.current) return;
    if (!new URLSearchParams(location.search).has("run")) return;
    ranInitial.current = true;
    history.replaceState({}, "", `/projects/${projectId}`);
    setTab("assets");
    if (project.prompt) {
      addMessage("user", project.prompt);
      runTurn(project.prompt);
    }
  }, [loaded, project]);

  if (!ready || !loaded) {
    return (
      <div className="flex h-screen items-center justify-center bg-muted/30 text-sm text-muted-foreground">
        Cargando proyecto…
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 bg-muted/30">
        <FolderKanban className="size-8 text-muted-foreground" />
        <p className="font-medium">Este proyecto ya no existe</p>
        <UIButton onClick={() => go("/dashboard")}>
          <Home /> Volver al panel
        </UIButton>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-muted/30">
      {noCredits && (
        <CreditsDialog
          credits={profile.credits}
          onClose={() => setNoCredits(false)}
        />
      )}
      {publishing && (
        <PublishDialog project={project} onClose={() => setPublishing(false)} />
      )}
      <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3">
        <button
          className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm font-medium transition-colors hover:bg-accent"
          onClick={() => go("/dashboard")}
        >
          <img src="/lovable-logo.svg" alt="" className="size-6" />
          <span className="max-w-[240px] truncate">{project.title}</span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </button>
        <div className="flex items-center">
          <EditorIconBtn>
            <History />
          </EditorIconBtn>
          <EditorIconBtn>
            <PanelLeft />
          </EditorIconBtn>
        </div>
        <div className="ml-1 flex items-center gap-0.5 rounded-lg border p-0.5">
          {editorTabs.map(([id, I, l]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm transition-colors [&_svg]:size-4",
                tab === id
                  ? "bg-blue-50 font-medium text-blue-600"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <I />
              {l}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <CreditsBadge />
          <ShareMenu projectId={projectId} />
          <UIButton
            size="sm"
            className="bg-violet-600 text-white hover:bg-violet-700"
            onClick={() => go("/es/pricing")}
          >
            <Zap /> Mejorar plan
          </UIButton>
          <UIButton
            size="sm"
            className="bg-blue-600 text-white hover:bg-blue-700"
            onClick={() => setPublishing(true)}
          >
            Publicar
          </UIButton>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {tab !== "chat" && (
          <EditorChat
            width={chatW}
            onResize={resizeChat}
            tab={tab}
            log={messages}
            busy={busy}
            stream={stream}
            onSend={handleSend}
            onStop={stopTurn}
            elements={elements}
            onUpload={(files) => uploadFiles(files)}
          />
        )}
        <main className="flex-1 overflow-hidden p-2">
          {tab === "preview" && <EditorPreview assets={assets} />}
          {tab === "assets" && (
            <EditorAssets
              assets={assets}
              onAssign={(id, role) => patchAsset(id, { role })}
              onDuplicate={duplicateAsset}
              onRemove={removeAsset}
              onRegenerate={regenerateAsset}
              onUpload={uploadFiles}
            />
          )}
          {tab === "brief" && (
            <EditorBrief
              data={data}
              title={project.title}
              onRename={(t) => updateProject(projectId, { title: t })}
            />
          )}
          {tab === "elements" && (
            <EditorElements assets={assets} onGoToAssets={() => setTab("assets")} />
          )}
          {tab === "canvas" && <EditorCanvas data={data} assets={assets} />}
          {tab === "chat" && <EditorTeamChat />}
        </main>
      </div>
    </div>
  );
}

const settingsGroups = [
  {
    title: "CUENTA",
    items: [
      ["account", "__PROFILE_NAME__", User],
      ["apps", "Dispositivos y apps", Monitor],
    ],
  },
  {
    title: "ESPACIO DE TRABAJO",
    items: [
      ["workspace", "__WORKSPACE_NAME__", "H"],
      ["billing", "Planes y uso de créditos", CreditCard],
    ],
  },
  {
    title: "ACCESO",
    items: [
      ["people", "Personas", Users],
      ["groups", "Grupos", Users, "Business"],
      ["identity", "Identidad", Shield, "Business"],
    ],
  },
  {
    title: "PERSONALIZACIÓN",
    items: [
      ["knowledge", "Conocimiento", BookOpen],
      ["skills", "Habilidades", Sparkles],
      ["templates", "Plantillas", Grid2X2, "Business"],
      ["design-systems", "Sistemas de diseño", PanelLeft, "Enterprise"],
      ["connectors", "Conectores", Plug, null, true],
    ],
  },
  {
    title: "CONSTRUCCIÓN Y DESPLIEGUE",
    items: [
      ["git", "Git", Code2],
      ["mcp-server", "Servidor MCP", Plug],
      ["domains", "Dominios del espacio de trabajo", Globe],
    ],
  },
  {
    title: "SEGURIDAD",
    items: [
      ["privacy-security", "Privacidad y seguridad", Shield],
      ["security-center", "Centro de seguridad", Shield, "Business"],
      ["audit-logs", "Registros de auditoría", Grid2X2, "Enterprise"],
    ],
  },
];
function SettingsSide({ page, width, onResize }) {
  const { profile, workspace } = useStudio();
  // Los dos primeros apartados llevan el nombre real de la persona y su espacio.
  const resolveLabel = (label) =>
    label === "__PROFILE_NAME__"
      ? (profile?.name ?? "Tu cuenta")
      : label === "__WORKSPACE_NAME__"
        ? (workspace?.name ?? "Espacio de trabajo")
        : label;
  return (
    <aside
      style={{ width }}
      className="fixed inset-y-0 left-0 flex flex-col overflow-y-auto overflow-x-hidden border-r bg-muted/30 p-3"
    >
      <ResizeHandle onResize={onResize} />
      <button
        onClick={() => go("/dashboard")}
        className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Volver
      </button>
      <div className="relative my-2">
        <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
        <input
          placeholder="Buscar ajustes"
          className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      {settingsGroups.map((group) => (
        <div key={group.title} className="mt-3">
          <p className="px-2 pb-1 text-xs font-medium text-muted-foreground">
            {group.title}
          </p>
          {group.items.map(([id, rawLabel, Icon, badge, external]) => {
            const label = resolveLabel(rawLabel);
            return (
            <button
              key={id}
              onClick={() => go(`/settings/${id}`)}
              className={cn(
                "flex w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors [&>svg]:size-4 [&>svg]:shrink-0 [&>svg]:text-muted-foreground",
                page === id
                  ? "bg-accent font-medium text-accent-foreground"
                  : "text-foreground/80 hover:bg-accent",
              )}
            >
              {Icon === "H" ? (
                <span className="flex size-5 items-center justify-center rounded bg-pink-600 text-[10px] font-semibold text-white">
                  H
                </span>
              ) : (
                <Icon />
              )}
              <span className="flex-1 truncate text-left">{label}</span>
              {badge && (
                <Badge
                  variant="secondary"
                  className={cn(
                    "shrink-0 rounded px-1.5 py-0 text-[10px] font-normal",
                    badge === "Enterprise" &&
                      "bg-purple-100 text-purple-700 hover:bg-purple-100",
                  )}
                >
                  {badge}
                </Badge>
              )}
              {external && (
                <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />
              )}
            </button>
            );
          })}
        </div>
      ))}
    </aside>
  );
}
const settingContent = {
  account: [
    "Cuenta",
    "Gestiona tu información personal y preferencias",
    [
      ["Perfil", "Actualiza tu nombre y foto de perfil."],
      ["Correo electrónico", "hector@example.com"],
      ["Tema", "Usar la configuración del sistema"],
      [
        "Eliminar cuenta",
        "Elimina permanentemente tu cuenta y todos tus datos.",
      ],
    ],
  ],
  apps: [
    "Dispositivos y apps",
    "Gestiona tus sesiones y aplicaciones conectadas",
    [
      ["Sesiones activas", "Windows · Cartagena, España · Ahora"],
      [
        "Xframe Desktop",
        "Conecta el escritorio para trabajar con proyectos locales.",
      ],
      [
        "Aplicaciones autorizadas",
        "No hay aplicaciones de terceros conectadas.",
      ],
    ],
  ],
  project: [
    "Ajustes del proyecto",
    "Configura Tráiler — Proyecto Neón",
    [
      ["Nombre del proyecto", "Tráiler — Proyecto Neón"],
      ["Visibilidad", "Privado"],
      ["Dominio de Xframe", "telemetry-landing-pages.xframe.app"],
      ["Eliminar proyecto", "Esta acción no se puede deshacer."],
    ],
  ],
  workspace: [
    "Espacio de trabajo",
    "Gestiona Héctor's Xframe",
    [
      ["Nombre del espacio de trabajo", "Héctor's Xframe"],
      ["Icono", "H"],
      [
        "Preferencias",
        "Configura los valores predeterminados de tus proyectos.",
      ],
    ],
  ],
  billing: [
    "Planes y uso de créditos",
    "Consulta tu plan, créditos y facturación",
    [
      ["Plan actual", "Free"],
      ["Créditos mensuales", "5 créditos diarios"],
      ["Uso de créditos", "2 de 5 créditos usados hoy"],
      ["Historial de facturación", "No hay facturas disponibles."],
    ],
  ],
  people: [
    "Personas",
    "Gestiona quién tiene acceso al espacio de trabajo",
    [
      ["Héctor", "Propietario · hector@example.com"],
      ["Invitar personas", "Añade colaboradores por correo electrónico."],
    ],
  ],
  knowledge: [
    "Conocimiento",
    "Añade contexto reutilizable a todos tus proyectos",
    [
      [
        "Conocimiento del espacio de trabajo",
        "Xframe usará estas instrucciones en nuevas conversaciones.",
      ],
      ["Archivos", "Añade documentación, guías y referencias."],
    ],
  ],
  skills: [
    "Habilidades",
    "Crea instrucciones especializadas para tus proyectos",
    [
      ["Habilidades personalizadas", "No hay habilidades instaladas todavía."],
      [
        "Crear una habilidad",
        "Enseña a Xframe un flujo de trabajo repetible.",
      ],
    ],
  ],
  "mcp-server": [
    "Conectores MCP",
    "Controla los servidores MCP que Xframe puede usar desde el chat.",
    [
      [
        "Conectores MCP remotos",
        "Permite que los miembros del espacio de trabajo conecten servidores MCP que Xframe puede invocar desde el chat. Al desactivarlo se eliminan las conexiones MCP existentes.",
      ],
      [
        "Servidores MCP locales de escritorio",
        "Permite que los miembros usen servidores MCP de sesiones conectadas de Xframe Desktop. Requiere que los conectores MCP remotos permanezcan habilitados.",
      ],
      [
        "Añadir servidor MCP",
        "Configura un servidor remoto mediante su URL y credenciales de conexión.",
      ],
    ],
  ],
  "privacy-security": [
    "Privacidad y seguridad",
    "Controla el acceso, la recopilación y protección de datos",
    [
      [
        "Descarga del código fuente",
        "Cuando está deshabilitado, solo los administradores y propietarios del espacio de trabajo pueden descargar el código fuente del proyecto.",
      ],
      [
        "Uso compartido entre proyectos",
        "Permite que los proyectos de este espacio de trabajo lean archivos de otros proyectos.",
      ],
      [
        "Exclusión de recopilación de datos",
        "Excluye este espacio de trabajo de la recopilación de datos.",
      ],
      [
        "Análisis de datos confidenciales",
        "Activa la detección de información personal en el historial de chat, la base de datos y el almacenamiento de Xframe Cloud.",
      ],
      [
        "Bloquear buckets de almacenamiento públicos",
        "Impide que los usuarios creen buckets de almacenamiento de acceso público en Xframe Cloud.",
      ],
      [
        "Región de alojamiento predeterminada",
        "Elige dónde se alojan los nuevos proyectos de este espacio de trabajo.",
      ],
    ],
  ],
};
function SettingsSection({ title, desc, children }) {
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold">{title}</h2>
      {desc && <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>}
      <Card className="mt-3 divide-y p-0">{children}</Card>
    </section>
  );
}
function SettingsRow({ title, desc, children }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4">
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
/** Select real con la estética de los ajustes. */
function SettingSelect({ value, options, onChange, className }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={cn("h-9 w-[200px]", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map(([id, label]) => (
          <SelectItem key={id} value={id}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Campo editable en línea: se guarda al confirmar y avisa del resultado. */
function InlineEdit({ value, onSave, placeholder, validate }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => setDraft(value ?? ""), [value]);

  const commit = async () => {
    const next = draft.trim();
    if (next === (value ?? "")) return setEditing(false);
    const problem = validate?.(next);
    if (problem) return setError(problem);
    setSaving(true);
    try {
      await onSave(next);
      setEditing(false);
      setError(null);
    } catch (e) {
      setError(String(e?.message ?? e));
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        {value || <span className="italic">{placeholder}</span>}
        <Pencil className="size-3.5" />
      </button>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-1.5">
        <Input
          autoFocus
          value={draft}
          disabled={saving}
          onChange={(e) => {
            setDraft(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setDraft(value ?? "");
              setEditing(false);
              setError(null);
            }
          }}
          placeholder={placeholder}
          className="h-9 w-56"
        />
        <UIButton size="icon" className="size-9" disabled={saving} onClick={commit}>
          {saving ? <RefreshCw className="animate-spin" /> : <Check />}
        </UIButton>
        <UIButton
          size="icon"
          variant="ghost"
          className="size-9"
          onClick={() => {
            setDraft(value ?? "");
            setEditing(false);
            setError(null);
          }}
        >
          <X />
        </UIButton>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

/**
 * Marca de cada proveedor de acceso. El favicon del dominio real da el logo
 * a todo color; `email` y `phone` no son marcas, así que llevan icono propio.
 */
const authBrands = {
  email: { label: "Correo electrónico", icon: Mail },
  phone: { label: "Teléfono", icon: Smartphone },
  google: { label: "Google", domain: "google.com" },
  github: { label: "GitHub", domain: "github.com" },
  apple: { label: "Apple", domain: "apple.com" },
  azure: { label: "Microsoft", domain: "microsoft.com" },
  gitlab: { label: "GitLab", domain: "gitlab.com" },
  bitbucket: { label: "Bitbucket", domain: "bitbucket.org" },
  discord: { label: "Discord", domain: "discord.com" },
  facebook: { label: "Facebook", domain: "facebook.com" },
  figma: { label: "Figma", domain: "figma.com" },
  linkedin: { label: "LinkedIn", domain: "linkedin.com" },
  linkedin_oidc: { label: "LinkedIn", domain: "linkedin.com" },
  notion: { label: "Notion", domain: "notion.so" },
  slack: { label: "Slack", domain: "slack.com" },
  slack_oidc: { label: "Slack", domain: "slack.com" },
  spotify: { label: "Spotify", domain: "spotify.com" },
  twitch: { label: "Twitch", domain: "twitch.tv" },
  twitter: { label: "X", domain: "x.com" },
  zoom: { label: "Zoom", domain: "zoom.us" },
  workos: { label: "WorkOS", domain: "workos.com" },
  kakao: { label: "Kakao", domain: "kakao.com" },
  keycloak: { label: "Keycloak", domain: "keycloak.org" },
};

const brandFavicon = (domain) =>
  `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;

/** Logo del proveedor, a todo color, con icono de respaldo. */
function AuthBrandIcon({ provider, className = "size-6" }) {
  const brand = authBrands[provider];
  if (!brand?.domain) {
    const Icon = brand?.icon ?? Globe;
    return <Icon className={cn(className, "text-muted-foreground")} />;
  }
  return (
    <img src={brandFavicon(brand.domain)} alt="" className={className} />
  );
}

const brandLabel = (provider) =>
  authBrands[provider]?.label ??
  provider.charAt(0).toUpperCase() + provider.slice(1);

const languageOptions = [
  ["es", "Español"],
  ["en", "English"],
  ["fr", "Français"],
  ["pt", "Português"],
];
const themeOptions = [
  ["light", "Claro"],
  ["dark", "Oscuro"],
  ["system", "Sistema"],
];
const visibilityOptions = [
  ["public", "Público"],
  ["workspace", "Solo mi espacio"],
  ["private", "Privado"],
];
const soundOptions = [
  ["off", "Desactivado"],
  ["first", "Primera generación"],
  ["always", "Todas"],
];

function AccountSettings() {
  const { profile, preferences, setPreferences, updateProfile, isRemote } =
    useStudio();
  const [identities, setIdentities] = useState([]);
  const [dialog, setDialog] = useState(null);
  const [toast, setToast] = useState(null);
  const avatarRef = useRef(null);

  useEffect(() => {
    db.listIdentities().then(setIdentities).catch(() => setIdentities([]));
  }, [profile?.id]);

  const notify = (text, kind = "ok") => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 4000);
  };

  const uploadAvatar = async (file) => {
    if (!file) return;
    try {
      const url = await uploadAsset({
        userId: profile.id,
        projectId: "avatar",
        file,
      });
      await updateProfile({ avatar_url: url });
      notify("Foto de perfil actualizada");
    } catch (error) {
      notify(String(error?.message ?? error), "error");
    }
  };

  if (!profile) return null;
  const initial = (profile.name ?? "?").charAt(0).toUpperCase();

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Cuenta</h1>
      <p className="mt-1 text-muted-foreground">
        Tus datos, tus preferencias y la seguridad de tu cuenta.
      </p>

      {toast && (
        <div
          className={cn(
            "mt-4 flex items-center gap-2 rounded-lg border p-3 text-sm",
            toast.kind === "error"
              ? "border-destructive/40 text-destructive"
              : "text-muted-foreground",
          )}
        >
          {toast.kind === "error" ? (
            <Info className="size-4 shrink-0" />
          ) : (
            <Check className="size-4 shrink-0" />
          )}
          {toast.text}
        </div>
      )}

      {/* Resumen de la cuenta */}
      <Card className="mt-6 flex flex-wrap items-center gap-4 p-5">
        <button
          onClick={() => avatarRef.current?.click()}
          title="Cambiar foto"
          className="group relative size-16 shrink-0 overflow-hidden rounded-full bg-green-600"
        >
          {profile.avatar_url ? (
            <img
              src={profile.avatar_url}
              alt=""
              className="size-full object-cover"
            />
          ) : (
            <span className="flex size-full items-center justify-center text-xl font-semibold text-white">
              {initial}
            </span>
          )}
          <span className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition-opacity group-hover:opacity-100">
            <Pencil className="size-4 text-white" />
          </span>
        </button>
        <input
          ref={avatarRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            uploadAvatar(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{profile.name}</p>
          <p className="truncate text-sm text-muted-foreground">
            {profile.email}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="rounded capitalize">
            Plan {profile.plan}
          </Badge>
          <Badge variant="secondary" className="gap-1 rounded">
            <Zap className="size-3" />
            {profile.credits} créditos
          </Badge>
          <UIButton size="sm" onClick={() => go("/es/pricing")}>
            Mejorar plan
          </UIButton>
        </div>
      </Card>

      <SettingsSection title="Perfil" desc="Controla cómo apareces en Xframe.">
        <SettingsRow title="Nombre" desc="El nombre que ven tus colaboradores.">
          <InlineEdit
            value={profile.name}
            placeholder="Tu nombre"
            validate={(v) => (v.length < 2 ? "Mínimo 2 caracteres" : null)}
            onSave={(name) => updateProfile({ name }).then(() => notify("Nombre actualizado"))}
          />
        </SettingsRow>
        <SettingsRow
          title="Nombre de usuario"
          desc="Tu identificador público y la URL de tu perfil."
        >
          <InlineEdit
            value={profile.username}
            placeholder="sin definir"
            validate={(v) =>
              !/^[a-zA-Z0-9_]{3,24}$/.test(v)
                ? "Entre 3 y 24 caracteres: letras, números y guion bajo"
                : null
            }
            onSave={async (username) => {
              const free = await db.isUsernameAvailable(username, profile.id);
              if (!free) throw new Error("Ese nombre ya está en uso");
              await updateProfile({ username });
              notify("Nombre de usuario actualizado");
            }}
          />
        </SettingsRow>
        <SettingsRow
          title="Correo electrónico"
          desc="Se usa para iniciar sesión y recibir avisos."
        >
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">{profile.email}</span>
            {isRemote && (
              <UIButton
                variant="outline"
                size="sm"
                onClick={() => setDialog("email")}
              >
                Cambiar
              </UIButton>
            )}
          </div>
        </SettingsRow>
        <SettingsRow
          title="Visibilidad del perfil"
          desc="Controla quién puede ver tu perfil público."
        >
          <SettingSelect
            value={preferences.profileVisibility}
            options={visibilityOptions}
            onChange={(profileVisibility) => setPreferences({ profileVisibility })}
          />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Preferencias"
        desc="Personaliza cómo funciona Xframe para ti."
      >
        <SettingsRow
          title="Idioma"
          desc="El idioma de la interfaz de Xframe."
        >
          <SettingSelect
            value={preferences.language}
            options={languageOptions}
            onChange={(language) => setPreferences({ language })}
          />
        </SettingsRow>
        <SettingsRow title="Tema" desc="Claro, oscuro o el del sistema.">
          <SettingSelect
            value={preferences.theme}
            options={themeOptions}
            onChange={(theme) => setPreferences({ theme })}
          />
        </SettingsRow>
        <SettingsRow
          title="Sonido al terminar una generación"
          desc="Avisa cuando el material esté listo."
        >
          <SettingSelect
            value={preferences.generationSound}
            options={soundOptions}
            onChange={(generationSound) => setPreferences({ generationSound })}
          />
        </SettingsRow>
        <SettingsRow
          title="Sugerencias en el chat"
          desc="Muestra atajos bajo el cuadro de texto del agente."
        >
          <Switch
            checked={preferences.chatSuggestions}
            onCheckedChange={(chatSuggestions) => setPreferences({ chatSuggestions })}
          />
        </SettingsRow>
        <SettingsRow
          title="Reducir animaciones"
          desc="Minimiza los movimientos de la interfaz."
        >
          <Switch
            checked={preferences.reducedMotion}
            onCheckedChange={(reducedMotion) => setPreferences({ reducedMotion })}
          />
        </SettingsRow>
        <SettingsRow
          title="Aceptar invitaciones automáticamente"
          desc="Únete a proyectos y espacios sin confirmar cada invitación."
        >
          <Switch
            checked={preferences.autoAcceptInvites}
            onCheckedChange={(autoAcceptInvites) => setPreferences({ autoAcceptInvites })}
          />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Notificaciones por correo"
        desc="Decide qué te enviamos."
      >
        <SettingsRow
          title="Novedades del producto"
          desc="Funciones nuevas y cambios importantes."
        >
          <Switch
            checked={preferences.emailProduct}
            onCheckedChange={(emailProduct) => setPreferences({ emailProduct })}
          />
        </SettingsRow>
        <SettingsRow
          title="Consejos y tutoriales"
          desc="Ideas para sacarle más partido a Xframe."
        >
          <Switch
            checked={preferences.emailTips}
            onCheckedChange={(emailTips) => setPreferences({ emailTips })}
          />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Cuentas vinculadas"
        desc="Proveedores con los que puedes iniciar sesión."
      >
        {identities.length === 0 && (
          <div className="px-5 py-4 text-sm text-muted-foreground">
            Solo inicias sesión con correo y contraseña.
          </div>
        )}
        {identities.map((identity) => (
          <div key={identity.identity_id} className="flex items-center gap-3 px-5 py-4">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border">
              <AuthBrandIcon provider={identity.provider} className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {brandLabel(identity.provider)}
              </p>
              <p className="truncate text-sm text-muted-foreground">
                {identity.identity_data?.email ?? profile.email}
              </p>
            </div>
            {identities.length > 1 && (
              <UIButton
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={async () => {
                  try {
                    await db.unlinkIdentity(identity);
                    setIdentities(await db.listIdentities());
                    notify("Cuenta desvinculada");
                  } catch (error) {
                    notify(String(error?.message ?? error), "error");
                  }
                }}
              >
                Desvincular
              </UIButton>
            )}
          </div>
        ))}

        {isRemote &&
          ["google", "github", "apple"]
            .filter((p) => !identities.some((i) => i.provider === p))
            .map((provider) => (
              <div key={provider} className="flex items-center gap-3 px-5 py-4">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border">
                  <AuthBrandIcon provider={provider} className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{brandLabel(provider)}</p>
                  <p className="text-sm text-muted-foreground">Sin vincular</p>
                </div>
                <UIButton
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    try {
                      await db.linkIdentity(provider);
                    } catch (error) {
                      notify(String(error?.message ?? error), "error");
                    }
                  }}
                >
                  Vincular
                </UIButton>
              </div>
            ))}
      </SettingsSection>

      <SettingsSection title="Seguridad" desc="Protege el acceso a tu cuenta.">
        <SettingsRow
          title="Contraseña"
          desc="Cámbiala periódicamente y no la reutilices."
        >
          <UIButton variant="outline" onClick={() => setDialog("password")}>
            Cambiar contraseña
          </UIButton>
        </SettingsRow>
        <SettingsRow
          title="Sesiones abiertas"
          desc="Cierra la sesión en todos los dispositivos donde hayas entrado."
        >
          <UIButton
            variant="outline"
            onClick={async () => {
              await db.signOutEverywhere();
              go("/es");
            }}
          >
            Cerrar en todas partes
          </UIButton>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Zona de peligro">
        <SettingsRow
          title="Eliminar cuenta"
          desc="Borra tu cuenta, tus proyectos y todo tu material. No se puede deshacer."
        >
          <UIButton
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => setDialog("delete")}
          >
            Eliminar cuenta
          </UIButton>
        </SettingsRow>
      </SettingsSection>

      {dialog === "password" && (
        <PasswordDialog
          email={profile.email}
          onClose={() => setDialog(null)}
          onDone={(msg) => notify(msg)}
        />
      )}
      {dialog === "email" && (
        <EmailDialog
          current={profile.email}
          onClose={() => setDialog(null)}
          onDone={(msg) => notify(msg)}
        />
      )}
      {dialog === "delete" && (
        <DeleteAccountDialog onClose={() => setDialog(null)} />
      )}
    </div>
  );
}

function PasswordDialog({ email, onClose, onDone }) {
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (password.length < 8) return setError("Mínimo 8 caracteres");
    if (password !== repeat) return setError("Las contraseñas no coinciden");
    setBusy(true);
    try {
      await db.updatePassword(password);
      onDone("Contraseña actualizada");
      onClose();
    } catch (err) {
      setError(String(err?.message ?? err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Cambiar contraseña</DialogTitle>
          <DialogDescription>
            Se aplicará de inmediato a esta sesión.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Input
            autoFocus
            type="password"
            value={password}
            onChange={(e) => (setPassword(e.target.value), setError(null))}
            placeholder="Contraseña nueva"
            autoComplete="new-password"
          />
          <Input
            type="password"
            value={repeat}
            onChange={(e) => (setRepeat(e.target.value), setError(null))}
            placeholder="Repite la contraseña"
            autoComplete="new-password"
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={async () => {
                await db.sendPasswordReset(email);
                onDone("Te hemos enviado un correo para restablecerla");
                onClose();
              }}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              No la recuerdo
            </button>
            <div className="flex gap-2">
              <UIButton type="button" variant="outline" onClick={onClose}>
                Cancelar
              </UIButton>
              <UIButton type="submit" disabled={busy}>
                {busy && <RefreshCw className="animate-spin" />} Guardar
              </UIButton>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EmailDialog({ current, onClose, onDone }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (email === current) return setError("Es el correo que ya tienes");
    setBusy(true);
    try {
      await db.updateEmail(email);
      onDone("Confirma el cambio desde el correo que te hemos enviado");
      onClose();
    } catch (err) {
      setError(String(err?.message ?? err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Cambiar correo</DialogTitle>
          <DialogDescription>
            Enviaremos un enlace de confirmación a la dirección nueva. El cambio
            no se aplica hasta que lo confirmes.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Input
            autoFocus
            type="email"
            required
            value={email}
            onChange={(e) => (setEmail(e.target.value), setError(null))}
            placeholder="nuevo@correo.com"
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <UIButton type="button" variant="outline" onClick={onClose}>
              Cancelar
            </UIButton>
            <UIButton type="submit" disabled={busy}>
              {busy && <RefreshCw className="animate-spin" />} Enviar
            </UIButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Borrado de cuenta: exige escribir ELIMINAR para evitar accidentes. */
function DeleteAccountDialog({ onClose }) {
  const { projects } = useStudio();
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await db.deleteAccount();
      go("/es");
    } catch (err) {
      setError(String(err?.message ?? err));
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="text-destructive">Eliminar cuenta</DialogTitle>
          <DialogDescription>
            Se borrarán tu perfil, tus {projects.length} proyectos y todo su
            material. Esta acción no se puede deshacer.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            Escribe <span className="font-medium text-foreground">ELIMINAR</span>{" "}
            para confirmar.
          </p>
          <Input
            autoFocus
            value={confirm}
            onChange={(e) => (setConfirm(e.target.value), setError(null))}
            placeholder="ELIMINAR"
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <UIButton variant="outline" onClick={onClose}>
              Cancelar
            </UIButton>
            <UIButton
              variant="destructive"
              disabled={confirm !== "ELIMINAR" || busy}
              onClick={submit}
            >
              {busy && <RefreshCw className="animate-spin" />} Eliminar para siempre
            </UIButton>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Lee navegador, sistema y tipo de aparato del user-agent. */
function describeDevice(userAgent = "") {
  const ua = userAgent;
  const browser =
    /Edg\//.test(ua) ? "Edge"
    : /OPR\/|Opera/.test(ua) ? "Opera"
    : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari"
    : /Firefox\//.test(ua) ? "Firefox"
    : "Navegador desconocido";

  const os =
    /Windows NT 10/.test(ua) ? "Windows"
    : /Windows/.test(ua) ? "Windows"
    : /iPhone|iPad/.test(ua) ? "iOS"
    : /Android/.test(ua) ? "Android"
    : /Mac OS X/.test(ua) ? "macOS"
    : /Linux/.test(ua) ? "Linux"
    : "Sistema desconocido";

  const mobile = /iPhone|Android|Mobile/.test(ua);
  return { browser, os, icon: mobile ? Smartphone : Monitor };
}

/** "hace 5 minutos", "ayer", "12 mar 2026". */
function timeAgo(value) {
  if (!value) return "—";
  // Postgres devuelve unas columnas con zona («…+00:00») y otras sin ella
  // (timestamp without time zone). A las segundas hay que marcarlas como UTC.
  const hasZone = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(value);
  const then = new Date(hasZone ? value : `${value.replace(" ", "T")}Z`);
  const minutes = Math.round((Date.now() - then) / 60000);
  if (Number.isNaN(minutes)) return "—";
  if (minutes < 2) return "ahora mismo";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "ayer";
  if (days < 30) return `hace ${days} días`;
  return then.toLocaleDateString("es-ES", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function AppsSettings() {
  const { profile, isRemote } = useStudio();
  const [sessions, setSessions] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [keys, setKeys] = useState([]);
  const [newKey, setNewKey] = useState(null);
  const [creating, setCreating] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [toast, setToast] = useState(null);

  const notify = (text, kind = "ok") => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 4000);
  };

  const reload = async () => {
    if (!profile) return;
    const [s, id, k] = await Promise.all([
      db.listSessions().catch(() => []),
      db.currentSessionId().catch(() => null),
      db.listApiKeys(profile.id).catch(() => []),
    ]);
    setSessions(s);
    setCurrentId(id);
    setKeys(k);
  };

  useEffect(() => {
    reload();
  }, [profile?.id]);

  if (!profile) return null;

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Dispositivos y apps</h1>
      <p className="mt-1 text-muted-foreground">
        Dónde tienes la sesión abierta y qué aplicaciones acceden a tu cuenta.
      </p>

      {toast && (
        <div
          className={cn(
            "mt-4 flex items-center gap-2 rounded-lg border p-3 text-sm",
            toast.kind === "error"
              ? "border-destructive/40 text-destructive"
              : "text-muted-foreground",
          )}
        >
          <Check className="size-4 shrink-0" />
          {toast.text}
        </div>
      )}

      <SettingsSection
        title="Sesiones activas"
        desc="Dispositivos con la sesión iniciada en tu cuenta."
      >
        {sessions.length === 0 && (
          <div className="px-5 py-4 text-sm text-muted-foreground">
            {isRemote
              ? "No hay más sesiones abiertas."
              : "Las sesiones se muestran al conectar Supabase."}
          </div>
        )}
        {sessions.map((session) => {
          const device = describeDevice(session.user_agent);
          const isCurrent = session.id === currentId;
          return (
            <div key={session.id} className="flex items-center gap-3 px-5 py-4">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border">
                <device.icon className="size-4 text-muted-foreground" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {device.browser} · {device.os}
                  {isCurrent && (
                    <Badge variant="secondary" className="rounded">
                      Este dispositivo
                    </Badge>
                  )}
                </p>
                <p className="truncate text-sm text-muted-foreground">
                  {session.ip ?? "IP desconocida"} · Actividad{" "}
                  {timeAgo(session.refreshed_at ?? session.created_at)}
                </p>
              </div>
              {!isCurrent && (
                <UIButton
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={async () => {
                    await db.revokeSession(session.id);
                    await reload();
                    notify("Sesión cerrada en ese dispositivo");
                  }}
                >
                  Cerrar sesión
                </UIButton>
              )}
            </div>
          );
        })}
        <SettingsRow
          title="Cerrar todas las sesiones"
          desc="Se cerrará también la de este dispositivo y tendrás que volver a entrar."
        >
          <UIButton
            variant="outline"
            onClick={async () => {
              await db.signOutEverywhere();
              go("/es");
            }}
          >
            Cerrar todas
          </UIButton>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Claves de API"
        desc="Para usar Xframe desde tus propias herramientas o scripts."
      >
        {keys.length === 0 && (
          <div className="px-5 py-4 text-sm text-muted-foreground">
            Todavía no has creado ninguna clave.
          </div>
        )}
        {keys.map((key) => (
          <div key={key.id} className="flex items-center gap-3 px-5 py-4">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border">
              <Code2 className="size-4 text-muted-foreground" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{key.name}</p>
              <p className="truncate font-mono text-xs text-muted-foreground">
                {key.prefix}··········· · Creada {timeAgo(key.created_at)} ·{" "}
                {key.last_used_at ? `Usada ${timeAgo(key.last_used_at)}` : "Sin usar"}
              </p>
            </div>
            <UIButton
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={async () => {
                await db.revokeApiKey(key.id);
                await reload();
                notify("Clave revocada");
              }}
            >
              Revocar
            </UIButton>
          </div>
        ))}
        <div className="flex items-center gap-2 px-5 py-4">
          <Input
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            placeholder="Nombre de la clave — por ejemplo, «Mi script»"
            className="h-9 flex-1"
          />
          <UIButton
            disabled={creating || !isRemote}
            onClick={async () => {
              setCreating(true);
              try {
                const { token } = await db.createApiKey(profile.id, keyName.trim());
                setNewKey(token);
                setKeyName("");
                await reload();
              } catch (error) {
                notify(String(error?.message ?? error), "error");
              } finally {
                setCreating(false);
              }
            }}
          >
            {creating ? <RefreshCw className="animate-spin" /> : <Plus />}
            Crear clave
          </UIButton>
        </div>
      </SettingsSection>

      <SettingsSection
        title="Aplicaciones conectadas"
        desc="Servicios de terceros con acceso a tus proyectos."
      >
        <SettingsRow
          title="Conectores"
          desc="Gestiona las integraciones activas de tu espacio de trabajo."
        >
          <UIButton variant="outline" onClick={() => go("/dashboard?connectors=1")}>
            Ver conectores <ArrowRight />
          </UIButton>
        </SettingsRow>
      </SettingsSection>

      {newKey && (
        <Dialog open onOpenChange={(o) => !o && setNewKey(null)}>
          <DialogContent className="sm:max-w-[460px]">
            <DialogHeader>
              <DialogTitle>Guarda tu clave ahora</DialogTitle>
              <DialogDescription>
                Es la única vez que se muestra completa. Después solo verás sus
                primeros caracteres.
              </DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-2 rounded-lg border bg-muted/40 p-2">
              <code className="min-w-0 flex-1 truncate font-mono text-xs">
                {newKey}
              </code>
              <UIButton
                variant="ghost"
                size="sm"
                onClick={() => {
                  navigator.clipboard?.writeText(newKey);
                  notify("Clave copiada");
                }}
              >
                <Copy /> Copiar
              </UIButton>
            </div>
            <div className="flex justify-end">
              <UIButton onClick={() => setNewKey(null)}>Hecho</UIButton>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

function GenericSettings({ page }) {
  const navItem = settingsGroups
    .flatMap((group) => group.items)
    .find(([id]) => id === page);
  const label = navItem?.[1] || "Ajustes";
  const c = settingContent[page] || [
    label,
    `Configura ${label.toLowerCase()} para este proyecto.`,
    [
      [label, "Esta sección está disponible en el prototipo de navegación."],
      ["Configuración", "Administra las opciones y permisos relacionados."],
    ],
  ];
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h1 className="text-2xl font-bold tracking-tight">{c[0]}</h1>
      <p className="mt-1 text-muted-foreground">{c[1]}</p>
      <Card className="mt-6 divide-y p-0">
        {c[2].map(([title, desc], i) => (
          <div
            key={title}
            className="flex items-center justify-between gap-4 px-5 py-4"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium">{title}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>
            </div>
            {/Eliminar/.test(title) ? (
              <UIButton
                variant="ghost"
                className="text-destructive hover:text-destructive"
              >
                Eliminar
              </UIButton>
            ) : /Nombre|Correo|Dominio|Icono|Región|Añadir/.test(title) ? (
              <UIButton variant="outline">Editar</UIButton>
            ) : (
              <Switch defaultChecked={i % 2 === 0} />
            )}
          </div>
        ))}
      </Card>
    </div>
  );
}

const workspaceColors = [
  ["pink", "bg-pink-600", "Rosa"],
  ["violet", "bg-violet-600", "Violeta"],
  ["blue", "bg-blue-600", "Azul"],
  ["green", "bg-green-600", "Verde"],
  ["amber", "bg-amber-500", "Ámbar"],
  ["neutral", "bg-neutral-800", "Negro"],
];

function WorkspaceSettings() {
  const { profile, projects, isRemote } = useStudio();
  const [workspace, setWorkspace] = useState(null);
  const [name, setName] = useState("");
  const [limit, setLimit] = useState("");
  const [copied, setCopied] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [slugOpen, setSlugOpen] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = (text) => {
    setToast(text);
    setTimeout(() => setToast(null), 3500);
  };

  useEffect(() => {
    if (!profile) return;
    db.getWorkspace(profile.id).then((w) => {
      setWorkspace(w);
      setName(w?.name ?? "");
      setLimit(w?.member_credit_limit == null ? "" : String(w.member_credit_limit));
    });
  }, [profile?.id]);

  const validateSlug = (v) =>
    !/^[a-z0-9-]{3,32}$/.test(v)
      ? "Entre 3 y 32 caracteres: minúsculas, números y guiones"
      : null;

  const saveSlug = async (slug) => {
    const free = await db.isWorkspaceSlugAvailable(slug, workspace.id);
    if (!free) throw new Error("Ese identificador ya está en uso");
    await save({ slug }, "Identificador actualizado");
  };

  const save = async (patch, message) => {
    const next = await db.updateWorkspace(workspace.id, patch);
    setWorkspace(next);
    if (message) notify(message);
    return next;
  };

  if (!profile || !workspace) return null;
  const initial = (workspace.name || "?").charAt(0).toUpperCase();
  const colorClass =
    workspaceColors.find(([id]) => id === workspace.avatar_color)?.[1] ??
    "bg-pink-600";

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Configuración del espacio de trabajo
          </h1>
          <p className="mt-1 text-muted-foreground">
            Los espacios de trabajo te permiten colaborar en proyectos en tiempo
            real.
          </p>
        </div>
      </div>

      {toast && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border p-3 text-sm text-muted-foreground">
          <Check className="size-4 shrink-0" />
          {toast}
        </div>
      )}

      <SettingsSection
        title="Perfil del espacio de trabajo"
        desc="Controla cómo aparece este espacio de trabajo en Xframe."
      >
        <SettingsRow
          title="Avatar"
          desc="Configura un avatar para tu espacio de trabajo."
        >
          {/* El selector de color vive en un menú para no recargar la fila. */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                aria-label="Cambiar color del avatar"
                className={cn(
                  "flex size-9 items-center justify-center rounded-lg text-sm font-semibold text-white transition-transform hover:scale-105",
                  colorClass,
                )}
              >
                {initial}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              {workspaceColors.map(([id, cls, label]) => (
                <DropdownMenuItem
                  key={id}
                  onClick={() => save({ avatar_color: id }, "Color actualizado")}
                >
                  <span className={cn("mr-2 size-3.5 rounded-full", cls)} />
                  {label}
                  {workspace.avatar_color === id && (
                    <Check className="ml-auto size-3.5" />
                  )}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </SettingsRow>

        <div className="flex items-start justify-between gap-4 px-5 py-4">
          <div className="min-w-0">
            <p className="text-sm font-medium">Nombre</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              El nombre completo de tu espacio de trabajo, tal como lo ven los
              demás.
            </p>
          </div>
          <div className="w-64 shrink-0">
            <Input
              value={name}
              maxLength={50}
              onChange={(e) => setName(e.target.value)}
              onBlur={() =>
                name.trim() &&
                name !== workspace.name &&
                save({ name: name.trim() }, "Nombre actualizado")
              }
              onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
            />
            <p className="mt-1 text-right text-xs text-muted-foreground">
              {name.length} / 50 caracteres
            </p>
          </div>
        </div>

        <SettingsRow
          title="ID del espacio de trabajo"
          desc="Identificador único del espacio de trabajo"
        >
          <button
            onClick={() => {
              navigator.clipboard?.writeText(workspace.id);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
            className="flex items-center gap-2 font-mono text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            {workspace.id}
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          </button>
        </SettingsRow>

        <SettingsRow
          title="Identificador del espacio de trabajo"
          desc="Configura un identificador para la página de perfil del espacio de trabajo."
        >
          {workspace.slug ? (
            <InlineEdit
              value={workspace.slug}
              placeholder="sin definir"
              validate={validateSlug}
              onSave={saveSlug}
            />
          ) : (
            <UIButton variant="outline" onClick={() => setSlugOpen(true)}>
              Establecer identificador
            </UIButton>
          )}
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Valores predeterminados de los miembros"
        desc="Límites que se aplican a quien se une a este espacio."
      >
        <div className="flex items-start justify-between gap-4 px-5 py-4">
          <div className="min-w-0">
            <p className="text-sm font-medium">
              Límite de créditos mensual por miembro
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Déjalo vacío para no aplicar ningún límite.
            </p>
          </div>
          <Input
            type="number"
            min={0}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            onBlur={() => {
              const value = limit.trim() === "" ? null : Number(limit);
              if (value === workspace.member_credit_limit) return;
              save({ member_credit_limit: value }, "Límite actualizado");
            }}
            placeholder="Sin límite"
            className="w-64 shrink-0"
          />
        </div>
      </SettingsSection>

      <SettingsSection
        title="Contenido"
        desc="Lo que hay dentro de este espacio de trabajo."
      >
        <SettingsRow title="Proyectos" desc="Proyectos creados en este espacio.">
          <span className="text-sm text-muted-foreground">
            {projects.length}
          </span>
        </SettingsRow>
        <SettingsRow title="Miembros" desc="Personas con acceso al espacio.">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">1</span>
            <UIButton
              variant="outline"
              size="sm"
              onClick={() => go("/settings/people")}
            >
              Gestionar
            </UIButton>
          </div>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Acceso al espacio de trabajo">
        <SettingsRow
          title="Salir del espacio de trabajo"
          desc="No puedes salir porque eres el único propietario. Primero transfiere la propiedad."
        >
          <UIButton variant="ghost" disabled className="text-destructive/60">
            Salir del espacio de trabajo
          </UIButton>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Zona de peligro">
        <SettingsRow
          title="Eliminar espacio de trabajo"
          desc="Elimina este espacio y todos los proyectos que contiene. Los miembros pierden el acceso de inmediato."
        >
          <UIButton
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => setDeleting(true)}
          >
            Eliminar espacio de trabajo
          </UIButton>
        </SettingsRow>
      </SettingsSection>

      {slugOpen && (
        <SetSlugDialog
          validate={validateSlug}
          onSave={saveSlug}
          onClose={() => setSlugOpen(false)}
        />
      )}

      {deleting && (
        <ConfirmDangerDialog
          title="Eliminar espacio de trabajo"
          description={`Se eliminará «${workspace.name}» y sus ${projects.length} proyectos. Esta acción no se puede deshacer.`}
          word="ELIMINAR"
          onClose={() => setDeleting(false)}
          onConfirm={async () => {
            await db.deleteWorkspace(workspace.id);
            go("/dashboard");
          }}
        />
      )}
    </div>
  );
}

/** Primera vez que se define el identificador del espacio de trabajo. */
function SetSlugDialog({ validate, onSave, onClose }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const slug = value.trim().toLowerCase();
    const problem = validate(slug);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      await onSave(slug);
      onClose();
    } catch (err) {
      setError(String(err?.message ?? err));
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Establecer identificador</DialogTitle>
          <DialogDescription>
            Será la dirección pública del espacio de trabajo.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex items-center gap-1 rounded-md border px-3 py-2 text-sm">
            <span className="shrink-0 text-muted-foreground">xframe.app/</span>
            <input
              autoFocus
              value={value}
              onChange={(e) => (setValue(e.target.value), setError(null))}
              placeholder="mi-estudio"
              className="min-w-0 flex-1 bg-transparent outline-none"
            />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <UIButton type="button" variant="outline" onClick={onClose}>
              Cancelar
            </UIButton>
            <UIButton type="submit" disabled={!value.trim() || busy}>
              {busy && <RefreshCw className="animate-spin" />} Guardar
            </UIButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Confirmación escrita para acciones destructivas. */
function ConfirmDangerDialog({ title, description, word, onClose, onConfirm }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="text-destructive">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            Escribe <span className="font-medium text-foreground">{word}</span>{" "}
            para confirmar.
          </p>
          <Input
            autoFocus
            value={text}
            onChange={(e) => (setText(e.target.value), setError(null))}
            placeholder={word}
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <UIButton variant="outline" onClick={onClose}>
              Cancelar
            </UIButton>
            <UIButton
              variant="destructive"
              disabled={text !== word || busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onConfirm();
                } catch (e) {
                  setError(String(e?.message ?? e));
                  setBusy(false);
                }
              }}
            >
              {busy && <RefreshCw className="animate-spin" />} Eliminar
            </UIButton>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Escalones de créditos de cada plan. El precio base es el del escalón de 100;
 * a partir de 1.200 se aplica un descuento por volumen creciente.
 */
const creditTiers = [100, 200, 400, 800, 1200, 2000, 3000, 4000, 5000, 10000];
const volumeDiscount = (credits) => {
  if (credits < 1200) return 0;
  if (credits < 2000) return 0.02;
  if (credits < 3000) return 0.04;
  if (credits < 4000) return 0.06;
  if (credits < 5000) return 0.08;
  return 0.1;
};

const tierPrice = (basePrice, credits, annual) => {
  const units = credits / 100;
  const gross = basePrice * units;
  const price = Math.round(gross * (1 - volumeDiscount(credits)));
  // El plan anual regala dos meses: se cobran 10 de 12.
  return annual ? Math.round((price * 10) / 12) : price;
};

/** Desplegable de créditos con su precio y el ahorro por volumen. */
function CreditTierSelect({ basePrice, annual, value, onChange }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative mt-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex h-9 w-full items-center justify-between rounded-md border bg-background px-3 text-sm"
      >
        {value.toLocaleString("es-ES")} créditos mensuales
        <ChevronsUpDown className="size-3.5 text-muted-foreground" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="scrollbar-hidden absolute left-0 top-full z-50 mt-1 max-h-[420px] w-[300px] overflow-y-auto rounded-lg border bg-background p-1 shadow-2xl">
            {creditTiers.map((credits) => {
              const discount = volumeDiscount(credits);
              return (
                <button
                  key={credits}
                  onClick={() => {
                    onChange(credits);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent",
                    credits === value && "bg-violet-50 text-violet-700",
                  )}
                >
                  <span className="flex-1 whitespace-nowrap text-left font-medium">
                    {credits.toLocaleString("es-ES")} créditos
                  </span>
                  {discount > 0 && (
                    <span className="rounded bg-green-100 px-1.5 py-0.5 text-[11px] font-medium text-green-700">
                      Ahorra {Math.round(discount * 100)}%
                    </span>
                  )}
                  <span className="shrink-0 tabular-nums">
                    €{tierPrice(basePrice, credits, annual).toLocaleString("es-ES")}
                    <span className="text-muted-foreground">/mes</span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function BillingPlanCard({ p, annual = false }) {
  const isPro = p.name === "Pro";
  const isEnterprise = p.name === "Enterprise";
  const basePrice = isPro ? 25 : 50;
  const [credits, setCredits] = useState(100);
  const price = tierPrice(basePrice, credits, annual);

  return (
    <Card className="flex flex-col p-6">
      <h3 className="text-xl font-semibold">{p.name}</h3>
      <p className="mt-2 min-h-[40px] text-sm text-muted-foreground">{p.desc}</p>
      <div className="mt-4 flex min-h-[44px] items-end">
        <span
          className={cn(
            "font-bold tracking-tight",
            isEnterprise ? "text-xl text-muted-foreground" : "text-4xl",
          )}
        >
          {isEnterprise ? p.price : `€${price.toLocaleString("es-ES")}`}
        </span>
      </div>
      <p className="mt-1 min-h-[20px] text-sm text-muted-foreground">
        {isEnterprise ? "" : `al mes IVA incl.${annual ? " · facturado anual" : ""}`}
      </p>
      {!isEnterprise && (
        <CreditTierSelect
          basePrice={basePrice}
          annual={annual}
          value={credits}
          onChange={setCredits}
        />
      )}
      <UIButton
        variant={isPro ? "default" : "outline"}
        onClick={() => go("/es/pricing")}
        className={cn(
          "mt-4 w-full",
          isPro && "bg-violet-600 text-white hover:bg-violet-700",
          isEnterprise && "mt-[76px]",
        )}
      >
        {isEnterprise ? "Reservar una demo" : "Mejorar plan"}
      </UIButton>
      <div className="mt-6 space-y-3 border-t pt-5">
        {p.leads.map(([label, Icon, expandable]) => (
          <div key={label} className="flex items-center gap-2 text-sm">
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <span className="flex-1">{label}</span>
            {expandable && (
              <ChevronDown className="size-3.5 text-muted-foreground" />
            )}
          </div>
        ))}
      </div>
      <ul className="mt-5 space-y-2.5">
        {p.features.map((f) => (
          <li key={f} className="flex gap-2 text-sm text-muted-foreground">
            <Check className="size-4 shrink-0 text-foreground" />
            {f}
          </li>
        ))}
      </ul>
      {p.note && (
        <p className="mt-3 flex gap-2 text-sm text-muted-foreground">
          <Check className="size-4 shrink-0 text-foreground" />
          {p.note}
        </p>
      )}
    </Card>
  );
}

const eduCards = [
  [
    "Xframe para estudiantes",
    "Verifica tu condición de estudiante y obtén hasta un 50 % de descuento en Xframe Pro.",
    "Empezar",
  ],
  [
    "Xframe para campus",
    "Controles de facturación y administración para universidades y centros de educación superior.",
    "Contactar con ventas",
  ],
  [
    "Xframe para niños",
    "Acceso conforme a la normativa y plan de estudios para colegios, en colaboración con imagi.",
    "Más información",
  ],
];
const usageRanges = [
  [7, "Últimos 7 días"],
  [30, "Últimos 30 días"],
  [90, "Últimos 90 días"],
];
const usageKinds = [
  ["all", "Todos los créditos"],
  ["build", "Generación"],
  ["run", "Reproceso"],
];

/** Serie diaria de consumo, con los días vacíos rellenos a cero. */
function buildUsageSeries(usage, days) {
  const buckets = new Map();
  for (let i = days - 1; i >= 0; i--) {
    const day = new Date(Date.now() - i * 86400000);
    const key = day.toISOString().slice(0, 10);
    buckets.set(key, {
      day: key,
      label: day.toLocaleDateString("es-ES", { day: "numeric", month: "short" }),
      build: 0,
      run: 0,
    });
  }
  for (const row of usage) {
    const key = row.created_at.slice(0, 10);
    const bucket = buckets.get(key);
    if (bucket) bucket[row.kind] = (bucket[row.kind] ?? 0) + row.amount;
  }
  return [...buckets.values()];
}

const usageChartConfig = {
  build: { label: "Generación", color: "hsl(258 90% 60%)" },
  run: { label: "Reproceso", color: "hsl(217 91% 60%)" },
};

/** Detalle de consumo de créditos: serie diaria y desglose por proyecto. */
function UsageDetails({ onBack }) {
  const { profile, projects } = useStudio();
  const [usage, setUsage] = useState([]);
  const [days, setDays] = useState(30);
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!profile) return;
    db.listCreditUsage(profile.id, days).then(setUsage).catch(() => setUsage([]));
  }, [profile?.id, days]);

  const filtered = usage.filter((row) => kind === "all" || row.kind === kind);
  const series = buildUsageSeries(filtered, days);
  const total = filtered.reduce((sum, row) => sum + row.amount, 0);

  const byProject = projects
    .map((project) => ({
      project,
      total: filtered
        .filter((row) => row.project_id === project.id)
        .reduce((sum, row) => sum + row.amount, 0),
    }))
    .filter(({ total, project }) =>
      total > 0 && project.title.toLowerCase().includes(query.toLowerCase()),
    )
    .sort((a, b) => b.total - a.total);

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <UIButton variant="outline" size="icon" onClick={onBack}>
            <ArrowLeft />
          </UIButton>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Detalle de uso
            </h1>
            <p className="mt-1 text-muted-foreground">
              Desglose del consumo de créditos por día y por proyecto.
            </p>
          </div>
        </div>
      </div>

      <Card className="mt-6 p-6">
        <p className="text-2xl font-bold tracking-tight">
          {total.toLocaleString("es-ES")} créditos
        </p>
        <p className="text-sm text-muted-foreground">
          en los {days} últimos días
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <SettingSelect
            value={kind}
            options={usageKinds}
            onChange={setKind}
            className="w-[190px]"
          />
          <div className="flex-1" />
          <SettingSelect
            value={String(days)}
            options={usageRanges.map(([d, l]) => [String(d), l])}
            onChange={(value) => setDays(Number(value))}
            className="w-[180px]"
          />
        </div>

        {total === 0 ? (
          <div className="mt-6 rounded-lg border border-dashed p-10 text-center">
            <BarChart3 className="mx-auto size-7 text-muted-foreground" />
            <p className="mt-3 font-medium">Todavía no has gastado créditos</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Genera material y aquí verás el consumo día a día.
            </p>
          </div>
        ) : (
          <ChartContainer config={usageChartConfig} className="mt-6 h-[260px] w-full">
            <BarChart data={series} barCategoryGap={2}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={24}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={28}
                allowDecimals={false}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar dataKey="build" stackId="c" fill="var(--color-build)" radius={[0, 0, 0, 0]} />
              <Bar dataKey="run" stackId="c" fill="var(--color-run)" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ChartContainer>
        )}
      </Card>

      <Card className="mt-5 p-0">
        <div className="border-b p-4">
          <div className="relative w-72">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar proyectos…"
              className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        </div>
        <div className="flex items-center justify-between px-5 py-2.5 text-xs font-medium text-muted-foreground">
          <span>Proyecto</span>
          <span>Consumo</span>
        </div>
        {byProject.length === 0 ? (
          <p className="px-5 pb-5 text-sm text-muted-foreground">
            Ningún proyecto ha consumido créditos en este periodo.
          </p>
        ) : (
          <div className="divide-y border-t">
            {byProject.map(({ project, total: amount }) => (
              <button
                key={project.id}
                onClick={() => go(`/projects/${project.id}`)}
                className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-accent"
              >
                <div
                  className="size-10 shrink-0 rounded bg-muted bg-cover bg-center"
                  style={{
                    backgroundImage: project.cover_url
                      ? `url(${project.cover_url})`
                      : undefined,
                  }}
                />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {project.title}
                </span>
                <span className="shrink-0 text-sm text-muted-foreground tabular-nums">
                  {amount.toLocaleString("es-ES")} créditos
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function BillingSettings() {
  const [billing, setBilling] = useState("monthly");
  const [showUsage, setShowUsage] = useState(false);
  const { profile, projects } = useStudio();
  const [usage, setUsage] = useState([]);

  useEffect(() => {
    if (!profile) return;
    db.listCreditUsage(profile.id, 30).then(setUsage).catch(() => setUsage([]));
  }, [profile?.id]);

  if (showUsage) return <UsageDetails onBack={() => setShowUsage(false)} />;

  const spent = usage.reduce((sum, row) => sum + row.amount, 0);
  const series = buildUsageSeries(usage, 30);
  const topProjects = projects
    .map((project) => ({
      project,
      total: usage
        .filter((row) => row.project_id === project.id)
        .reduce((sum, row) => sum + row.amount, 0),
    }))
    .filter(({ total }) => total > 0)
    .sort((a, b) => b.total - a.total)
    .slice(0, 3);

  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Planes y uso de créditos
          </h1>
          <p className="mt-1 text-muted-foreground">
            Gestiona tu plan y el saldo de créditos.
          </p>
        </div>
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Abrir docs <ExternalLink />
        </UIButton>
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <img src="/lovable-logo.svg" alt="" className="size-7" />
            <div className="flex flex-1 items-center gap-2">
              <span className="font-semibold">Xframe Free</span>
              <UIButton variant="outline" size="sm">
                Manage
              </UIButton>
            </div>
          </div>
          <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
            Free usage included <Info className="size-3" />
          </p>
          <div className="mt-4 rounded-lg border bg-muted/30 p-4">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-1 font-medium">
                Daily build credits <Info className="size-3" />
              </span>
              <span className="text-muted-foreground">
                <b className="text-foreground">5</b> left
              </span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-secondary">
              <div className="h-full w-full rounded-full bg-blue-600" />
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Resets at midnight UTC
            </p>
          </div>
          <div className="mt-4 flex items-center justify-between gap-4 rounded-lg border p-4">
            <div>
              <p className="text-sm font-medium">Need more credits?</p>
              <p className="text-xs text-muted-foreground">
                Upgrade your plan for more credits.
              </p>
            </div>
            <UIButton>Upgrade plan</UIButton>
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center justify-between">
            <span className="font-semibold">Usage</span>
            <ChevronRight className="size-4 text-muted-foreground" />
          </div>
          <ChartContainer config={usageChartConfig} className="mt-4 h-24 w-full">
            <AreaChart data={series} margin={{ left: 0, right: 0, top: 4, bottom: 0 }}>
              <defs>
                <linearGradient id="usageFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-build)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--color-build)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <ChartTooltip content={<ChartTooltipContent />} />
              <Area
                type="monotone"
                dataKey="build"
                stroke="var(--color-build)"
                strokeWidth={1.5}
                fill="url(#usageFill)"
              />
            </AreaChart>
          </ChartContainer>
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{series[0]?.label}</span>
            <span>{series[series.length - 1]?.label}</span>
          </div>
          <div className="mt-4 flex items-center justify-between border-t pt-4 text-sm">
            <span className="text-muted-foreground">Últimos 30 días</span>
            <span className="font-medium">
              {spent.toLocaleString("es-ES")} créditos
            </span>
          </div>
          {topProjects.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">
              Aún no hay consumo en este periodo.
            </p>
          ) : (
            topProjects.map(({ project, total }) => (
              <div
                key={project.id}
                className="mt-2 flex items-center justify-between gap-3 text-sm"
              >
                <span className="min-w-0 truncate">{project.title}</span>
                <span className="shrink-0 text-muted-foreground tabular-nums">
                  {total.toLocaleString("es-ES")} créditos
                </span>
              </div>
            ))
          )}
          <UIButton
            variant="outline"
            className="mt-4"
            onClick={() => setShowUsage(true)}
          >
            Más detalles de uso
          </UIButton>
        </Card>
      </div>

      <h2 className="mt-12 text-xl font-semibold">Cambia tu plan</h2>
      <div className="mt-4 inline-flex rounded-full border bg-muted p-1 text-sm">
        <button
          onClick={() => setBilling("monthly")}
          className={cn(
            "rounded-full px-4 py-1.5 transition-colors",
            billing === "monthly"
              ? "bg-background shadow-sm"
              : "text-muted-foreground",
          )}
        >
          Mensual
        </button>
        <button
          onClick={() => setBilling("annual")}
          className={cn(
            "rounded-full px-4 py-1.5 transition-colors",
            billing === "annual"
              ? "bg-background shadow-sm"
              : "text-muted-foreground",
          )}
        >
          Anual <span className="font-medium text-violet-600">2 meses gratis</span>
        </button>
      </div>
      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        {plans.slice(1).map((p) => (
          <BillingPlanCard key={p.name} p={p} annual={billing === "annual"} />
        ))}
      </div>

      <div className="mt-6 grid gap-5 md:grid-cols-3">
        {eduCards.map(([title, desc, action]) => (
          <Card key={title} className="flex flex-col p-6">
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="mt-2 flex-1 text-sm text-muted-foreground">{desc}</p>
            <UIButton variant="outline" className="mt-4 w-full">
              {action}
            </UIButton>
          </Card>
        ))}
      </div>

      <Card className="mt-6 flex flex-col items-start justify-between gap-6 p-8 sm:flex-row sm:items-center">
        <div>
          <h3 className="font-semibold">Seguridad y cumplimiento</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Certificaciones de seguridad y cumplimiento de nivel empresarial
          </p>
        </div>
        <div className="flex items-center gap-3">
          {["SOC 2", "GDPR", "ISO 27001"].map((b) => (
            <span
              key={b}
              className="flex size-16 items-center justify-center rounded-full bg-neutral-800 text-center text-[10px] font-semibold text-white"
            >
              {b}
            </span>
          ))}
          <UIButton variant="outline">Más información</UIButton>
        </div>
      </Card>
    </div>
  );
}


const peopleTabs = [
  ["all", "Todos"],
  ["invites", "Invitaciones"],
  ["collaborators", "Colaboradores"],
  ["requests", "Solicitudes"],
];
// Los colaboradores entran a un proyecto suelto, no al espacio de trabajo.
const collaboratorRoles = [
  ["editor", "Puede editar"],
  ["commenter", "Puede comentar"],
  ["viewer", "Puede ver"],
];
const memberRoles = [
  ["admin", "Administrador"],
  ["member", "Miembro"],
  ["viewer", "Solo lectura"],
];
const roleLabel = (role) =>
  role === "owner"
    ? "Propietario"
    : (memberRoles.find(([id]) => id === role)?.[1] ?? role);

/** El trabajo en equipo es de plan Business en adelante. */
const canInvite = (plan) => plan === "business" || plan === "enterprise";

function PeopleSettings() {
  const { profile, workspace, projects } = useStudio();
  const [tab, setTab] = useState("all");
  const [members, setMembers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [requests, setRequests] = useState([]);
  const [collaborators, setCollaborators] = useState([]);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [inviting, setInviting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = (text) => {
    setToast(text);
    setTimeout(() => setToast(null), 3500);
  };

  const reload = async () => {
    if (!workspace) return;
    const [m, i, r, c] = await Promise.all([
      db.listMembers(workspace.id).catch(() => []),
      db.listInvites(workspace.id).catch(() => []),
      db.listJoinRequests(workspace.id).catch(() => []),
      db.listCollaborators(projects.map((p) => p.id)).catch(() => []),
    ]);
    setMembers(m);
    setInvites(i);
    setRequests(r);
    setCollaborators(c);
  };

  useEffect(() => {
    reload();
  }, [workspace?.id, projects.length]);

  if (!profile || !workspace) return null;

  const teamEnabled = canInvite(profile.plan);
  const pendingInvites = invites.filter((i) => i.status === "pending");
  const pendingRequests = requests.filter((r) => r.status === "pending");

  const matches = (text) => text.toLowerCase().includes(query.toLowerCase());
  const visibleMembers = members.filter(
    (m) =>
      (roleFilter === "all" || m.role === roleFilter) &&
      (matches(m.profile?.name ?? "") || matches(m.profile?.email ?? "")),
  );

  /** Exporta la lista tal y como se ve, en CSV. */
  const exportCsv = () => {
    const rows = [
      ["Nombre", "Correo", "Rol", "Alta", "Límite de créditos"],
      ...visibleMembers.map((m) => [
        m.profile?.name ?? "",
        m.profile?.email ?? "",
        roleLabel(m.role),
        new Date(m.joined_at).toLocaleDateString("es-ES"),
        m.credit_limit ?? "Sin límite",
      ]),
    ];
    const csv = rows
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `miembros-${workspace.slug ?? workspace.id}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const inviteLink = `${location.origin}/join/${workspace.slug ?? workspace.id}`;

  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Personas</h1>
          <p className="mt-1 max-w-2xl text-muted-foreground">
            Invitar a alguien a <b className="text-foreground">{workspace.name}</b>{" "}
            le da acceso a los proyectos y créditos compartidos. Ahora mismo hay{" "}
            {members.length} {members.length === 1 ? "persona" : "personas"} en
            este espacio.
          </p>
        </div>
      </div>

      {!teamEnabled && (
        <Card className="mt-6 flex flex-wrap items-center gap-4 border-violet-200 bg-violet-50/50 p-4">
          <Users className="size-5 shrink-0 text-violet-600" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              El trabajo en equipo es del plan Business
            </p>
            <p className="text-sm text-muted-foreground">
              Mejora el plan para invitar a tu equipo, asignar roles y repartir
              créditos entre sus miembros.
            </p>
          </div>
          <UIButton
            className="bg-violet-600 text-white hover:bg-violet-700"
            onClick={() => go("/settings/billing")}
          >
            <Zap /> Mejorar plan
          </UIButton>
        </Card>
      )}

      {toast && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border p-3 text-sm text-muted-foreground">
          <Check className="size-4 shrink-0" />
          {toast}
        </div>
      )}

      <div className="mt-6 inline-flex rounded-full border bg-muted p-1 text-sm">
        {peopleTabs.map(([id, label]) => {
          const count =
            id === "invites"
              ? pendingInvites.length
              : id === "requests"
                ? pendingRequests.length
                : id === "collaborators"
                  ? collaborators.length
                  : 0;
          return (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                "flex items-center gap-1.5 rounded-full px-4 py-1.5 transition-colors",
                tab === id
                  ? "bg-background shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
              {count > 0 && (
                <span className="rounded-full bg-primary px-1.5 text-[10px] font-medium text-primary-foreground">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 md:max-w-xs">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por nombre o correo…"
            className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <SettingSelect
          value={roleFilter}
          options={[["all", "Todos los roles"], ["owner", "Propietario"], ...memberRoles]}
          onChange={setRoleFilter}
          className="w-[180px]"
        />
        <div className="ml-auto flex items-center gap-2">
          <UIButton variant="outline" onClick={exportCsv}>
            <Download /> Exportar
          </UIButton>
          <UIButton
            variant="outline"
            disabled={!teamEnabled}
            onClick={() => {
              navigator.clipboard?.writeText(inviteLink);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
          >
            {copied ? <Check /> : <Link />} {copied ? "Copiado" : "Enlace de invitación"}
          </UIButton>
          <UIButton disabled={!teamEnabled} onClick={() => setInviting(true)}>
            <UserPlus /> Invitar
          </UIButton>
        </div>
      </div>

      {tab === "all" && (
        <Card className="mt-4 overflow-hidden p-0">
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr_auto] items-center gap-4 border-b px-5 py-3 text-xs font-medium text-muted-foreground">
            <span>Nombre</span>
            <span>Rol</span>
            <span>Alta</span>
            <span>Límite de créditos</span>
            <span />
          </div>
          {visibleMembers.length === 0 ? (
            <p className="px-5 py-6 text-sm text-muted-foreground">
              Nadie coincide con la búsqueda.
            </p>
          ) : (
            <div className="divide-y">
              {visibleMembers.map((member) => {
                const isMe = member.user_id === profile.id;
                const isOwner = member.role === "owner";
                return (
                  <div
                    key={member.id}
                    className="grid grid-cols-[2fr_1fr_1fr_1fr_auto] items-center gap-4 px-5 py-4 text-sm"
                  >
                    <div className="flex items-center gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-green-600 text-xs font-semibold text-white">
                        {member.profile?.avatar_url ? (
                          <img
                            src={member.profile.avatar_url}
                            alt=""
                            className="size-full object-cover"
                          />
                        ) : (
                          (member.profile?.name ?? "?").charAt(0).toUpperCase()
                        )}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate font-medium">
                          {member.profile?.name}
                          {isMe && (
                            <span className="text-muted-foreground"> (tú)</span>
                          )}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {member.profile?.email}
                        </p>
                      </div>
                    </div>

                    {isOwner ? (
                      <span className="text-muted-foreground">Propietario</span>
                    ) : (
                      <SettingSelect
                        value={member.role}
                        options={memberRoles}
                        onChange={async (role) => {
                          await db.updateMember(member.id, { role });
                          await reload();
                          notify("Rol actualizado");
                        }}
                        className="h-8 w-[150px]"
                      />
                    )}

                    <span className="text-muted-foreground">
                      {new Date(member.joined_at).toLocaleDateString("es-ES", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </span>

                    <span className="text-muted-foreground">
                      {isOwner ? (
                        "Sin límite"
                      ) : (
                        <InlineEdit
                          value={
                            member.credit_limit == null
                              ? ""
                              : String(member.credit_limit)
                          }
                          placeholder="Sin límite"
                          validate={(v) =>
                            v && !/^\d+$/.test(v) ? "Solo números" : null
                          }
                          onSave={async (value) => {
                            await db.updateMember(member.id, {
                              credit_limit: value === "" ? null : Number(value),
                            });
                            await reload();
                            notify("Límite actualizado");
                          }}
                        />
                      )}
                    </span>

                    {isOwner ? (
                      <span />
                    ) : (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            aria-label="Acciones"
                            className="text-muted-foreground"
                          >
                            <MoreHorizontal className="size-4" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={async () => {
                              await db.removeMember(member.id);
                              await reload();
                              notify("Persona eliminada del espacio");
                            }}
                            className="text-destructive focus:text-destructive"
                          >
                            <X className="mr-2 size-3.5" /> Quitar del espacio
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      )}

      {tab === "invites" && (
        <Card className="mt-4 overflow-hidden p-0">
          {pendingInvites.length === 0 ? (
            <div className="p-10 text-center">
              <Mail className="mx-auto size-7 text-muted-foreground" />
              <p className="mt-3 font-medium">No hay invitaciones pendientes</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Las invitaciones que envíes aparecerán aquí hasta que se acepten.
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {pendingInvites.map((invite) => (
                <div key={invite.id} className="flex items-center gap-3 px-5 py-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted">
                    <Mail className="size-4 text-muted-foreground" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{invite.email}</p>
                    <p className="text-xs text-muted-foreground">
                      {roleLabel(invite.role)} · Enviada {timeAgo(invite.created_at)}{" "}
                      · Caduca{" "}
                      {new Date(invite.expires_at).toLocaleDateString("es-ES")}
                    </p>
                  </div>
                  <UIButton
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      navigator.clipboard?.writeText(
                        `${location.origin}/join/${invite.token}`,
                      );
                      notify("Enlace de la invitación copiado");
                    }}
                  >
                    <Copy /> Copiar enlace
                  </UIButton>
                  <UIButton
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={async () => {
                      await db.updateInvite(invite.id, { status: "revoked" });
                      await reload();
                      notify("Invitación revocada");
                    }}
                  >
                    Revocar
                  </UIButton>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {tab === "collaborators" && (
        <Card className="mt-4 overflow-hidden p-0">
          {(() => {
            const visible = collaborators.filter(
              (c) => matches(c.email) || matches(c.profile?.name ?? ""),
            );
            if (visible.length === 0)
              return (
                <div className="p-10 text-center">
                  <Share2 className="mx-auto size-7 text-muted-foreground" />
                  <p className="mt-3 font-medium">Todavía no hay colaboradores</p>
                  <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                    Los colaboradores acceden a un proyecto concreto sin ocupar
                    plaza en el espacio. Se añaden desde el botón Compartir de
                    cada proyecto.
                  </p>
                </div>
              );

            // Agrupados por proyecto: es su unidad de acceso.
            const byProject = projects
              .map((project) => ({
                project,
                people: visible.filter((c) => c.project_id === project.id),
              }))
              .filter(({ people }) => people.length);

            return byProject.map(({ project, people }) => (
              <div key={project.id} className="border-b last:border-b-0">
                <button
                  onClick={() => go(`/projects/${project.id}`)}
                  className="flex w-full items-center gap-2 bg-muted/30 px-5 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  <FolderKanban className="size-3.5" />
                  {project.title}
                  <span className="ml-auto">
                    {people.length}{" "}
                    {people.length === 1 ? "colaborador" : "colaboradores"}
                  </span>
                </button>
                <div className="divide-y">
                  {people.map((person) => (
                    <div
                      key={person.id}
                      className="flex items-center gap-3 px-5 py-4"
                    >
                      <span className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xs font-semibold">
                        {person.profile?.avatar_url ? (
                          <img
                            src={person.profile.avatar_url}
                            alt=""
                            className="size-full object-cover"
                          />
                        ) : (
                          person.email.charAt(0).toUpperCase()
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {person.profile?.name ?? person.email}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {person.email}
                          {person.status === "pending" && " · Invitación pendiente"}
                        </p>
                      </div>
                      <SettingSelect
                        value={person.role}
                        options={collaboratorRoles}
                        onChange={async (role) => {
                          await db.updateCollaborator(person.id, { role });
                          await reload();
                          notify("Permiso actualizado");
                        }}
                        className="h-8 w-[160px]"
                      />
                      <UIButton
                        variant="ghost"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={async () => {
                          await db.removeCollaborator(person.id);
                          await reload();
                          notify("Colaborador retirado del proyecto");
                        }}
                      >
                        Quitar
                      </UIButton>
                    </div>
                  ))}
                </div>
              </div>
            ));
          })()}
        </Card>
      )}

      {tab === "requests" && (
        <Card className="mt-4 overflow-hidden p-0">
          {pendingRequests.length === 0 ? (
            <div className="p-10 text-center">
              <UserPlus className="mx-auto size-7 text-muted-foreground" />
              <p className="mt-3 font-medium">No hay solicitudes pendientes</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Cuando alguien pida entrar en el espacio, lo verás aquí.
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {pendingRequests.map((request) => (
                <div key={request.id} className="flex items-center gap-3 px-5 py-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-green-600 text-xs font-semibold text-white">
                    {(request.profile?.name ?? "?").charAt(0).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {request.profile?.name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {request.profile?.email} · {timeAgo(request.created_at)}
                    </p>
                    {request.message && (
                      <p className="mt-1 text-sm text-muted-foreground">
                        «{request.message}»
                      </p>
                    )}
                  </div>
                  <UIButton
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      await db.resolveJoinRequest(request, false);
                      await reload();
                      notify("Solicitud rechazada");
                    }}
                  >
                    Rechazar
                  </UIButton>
                  <UIButton
                    size="sm"
                    disabled={!teamEnabled}
                    onClick={async () => {
                      await db.resolveJoinRequest(request, true);
                      await reload();
                      notify("Persona añadida al espacio");
                    }}
                  >
                    <Check /> Aceptar
                  </UIButton>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {inviting && (
        <InviteDialog
          workspace={workspace}
          profile={profile}
          onClose={() => setInviting(false)}
          onDone={async (message) => {
            await reload();
            notify(message);
          }}
        />
      )}
    </div>
  );
}

function InviteDialog({ workspace, profile, onClose, onDone }) {
  const [emails, setEmails] = useState("");
  const [role, setRole] = useState("member");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const list = emails
      .split(/[\s,;]+/)
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean);
    const invalid = list.find((value) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value));
    if (!list.length) return setError("Escribe al menos un correo");
    if (invalid) return setError(`«${invalid}» no es un correo válido`);

    setBusy(true);
    try {
      for (const email of list) {
        await db.createInvite(workspace.id, {
          email,
          role,
          invitedBy: profile.id,
        });
      }
      await onDone(
        list.length === 1
          ? "Invitación enviada"
          : `${list.length} invitaciones enviadas`,
      );
      onClose();
    } catch (err) {
      setError(
        /duplicate|unique/i.test(String(err?.message))
          ? "Ya hay una invitación pendiente para ese correo"
          : String(err?.message ?? err),
      );
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle>Invitar a {workspace.name}</DialogTitle>
          <DialogDescription>
            Separa varios correos con comas. Recibirán un enlace para unirse.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Textarea
            autoFocus
            value={emails}
            onChange={(e) => (setEmails(e.target.value), setError(null))}
            placeholder="ana@estudio.com, luis@estudio.com"
            className="min-h-[80px] resize-none"
          />
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">Rol</span>
            <SettingSelect value={role} options={memberRoles} onChange={setRole} />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <UIButton type="button" variant="outline" onClick={onClose}>
              Cancelar
            </UIButton>
            <UIButton type="submit" disabled={busy}>
              {busy && <RefreshCw className="animate-spin" />} Enviar invitaciones
            </UIButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function KnowledgeSettings() {
  const [banner, setBanner] = useState(true);
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Knowledge</h1>
          <p className="mt-1 text-muted-foreground">
            Manage knowledge for your project and workspace.
          </p>
        </div>
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Abrir docs <ExternalLink />
        </UIButton>
      </div>

      {banner && (
        <div className="mt-6 flex items-start gap-3 rounded-lg border bg-muted/40 p-4">
          <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="flex-1">
            <p className="text-sm font-medium">Workspace knowledge</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              You can now add custom instructions that apply across all projects
              in your workspace.
            </p>
          </div>
          <button
            onClick={() => setBanner(false)}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      <div className="mt-8 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Workspace knowledge</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Set shared rules and preferences that apply to every project in this
            workspace.
          </p>
        </div>
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Get inspiration <ExternalLink />
        </UIButton>
      </div>
      <Card className="mt-3 p-4">
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Define coding style and naming conventions.</li>
          <li>Set preferred libraries, frameworks, or patterns.</li>
          <li>Add behavioral rules like tone, language, or formatting.</li>
        </ul>
        <Textarea
          className="mt-4 min-h-[220px] resize-none"
          placeholder="Set coding style, conventions, and preferences for all your projects…"
        />
      </Card>
    </div>
  );
}

const skillFeatures = [
  [
    Pencil,
    "Easy to create",
    "Describe a skill in chat or import skills from GitHub or a URL.",
  ],
  [
    null,
    "Runs when it matters",
    'Trigger a skill with "/" or let Xframe activate it automatically when it matches your task.',
  ],
  [
    Users,
    "Shared with your team",
    "Codify your workflows once. Your whole team uses them on every project.",
  ],
];
const lovableSkills = [
  [
    "accessibility",
    "Audit a project for accessibility issues and fix them. Triggers on check accessibility, a11y review, accessibility audit, make it accessible, screen reader, WCAG, aria labels, keyboard navigation.",
  ],
  [
    "redesign",
    "Use when the user wants to visually redesign an existing UI. Triggers on redesign this, give this a real visual identity, make it look beautiful, rethink the look, or any design-open ask on a project that already has working UI.",
  ],
  [
    "seo-review",
    "Run an SEO review on the current project and direct the user to the results panel. Triggers on /seo-review, check my SEO, SEO audit, review SEO, how is my SEO, SEO issues on my site, improve SEO.",
  ],
  [
    "skill-creator",
    "Use this skill when the user wants to create, update, or prepare a skill candidate. Skills are reusable prompt instructions that teach the agent how to perform specific tasks.",
  ],
  [
    "video-creator",
    "Create animated videos programmatically. Triggers on create a video, make an animation, motion graphics, explainer video, promo video, animated intro, render a video.",
  ],
];
function SkillsSettings() {
  const [intro, setIntro] = useState(true);
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Skills</h1>
          <p className="mt-1 flex items-center gap-1 text-muted-foreground">
            Reusable instructions your agents can apply whenever they're at work.
            <Info className="size-3.5" />
          </p>
        </div>
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Abrir docs <ExternalLink />
        </UIButton>
      </div>

      {intro && (
        <Card className="relative mt-6 overflow-hidden p-6">
          <div
            className="pointer-events-none absolute inset-y-0 right-0 -z-0 w-1/2 bg-no-repeat opacity-70"
            style={{
              backgroundImage: "url(/hero-aura.webp)",
              backgroundSize: "cover",
              backgroundPosition: "left center",
            }}
          />
          <button
            onClick={() => setIntro(false)}
            className="absolute right-4 top-4 text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
          <div className="relative max-w-lg">
            <h2 className="text-lg font-semibold">Teach Xframe how you work</h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Skills let you save how things should be done, so the agent gets it
              right without being told twice.
            </p>
            <div className="mt-5 space-y-4">
              {skillFeatures.map(([Icon, title, desc]) => (
                <div key={title} className="flex gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background text-sm text-muted-foreground">
                    {Icon ? <Icon className="size-4" /> : "/"}
                  </span>
                  <div>
                    <p className="text-sm font-medium">{title}</p>
                    <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      <div className="mt-8 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Workspace skills</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Shared with every project in this workspace, so the agent can use them
            anywhere.
          </p>
        </div>
        <UIButton className="shrink-0">
          Add <ChevronDown />
        </UIButton>
      </div>
      <Card className="mt-3 border-dashed p-6">
        <p className="text-sm text-muted-foreground">No skills found.</p>
      </Card>

      <div className="mt-8">
        <h2 className="text-lg font-semibold">Skills built by Xframe</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Maintained by Xframe and ready to use when your team needs proven
          instructions without creating a custom skill.
        </p>
        <div className="mt-3 space-y-3">
          {lovableSkills.map(([name, desc]) => (
            <Card
              key={name}
              className="cursor-pointer p-4 transition-colors hover:bg-accent/40"
            >
              <p className="font-medium">{name}</p>
              <p className="mt-1 text-sm text-muted-foreground">{desc}</p>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

function TierBadge({ tier }) {
  return (
    <Badge
      variant="secondary"
      className={cn(
        "rounded px-1.5 py-0 text-[10px] font-normal",
        tier === "Enterprise" &&
          "bg-purple-100 text-purple-700 hover:bg-purple-100",
      )}
    >
      {tier}
    </Badge>
  );
}
function SelectPill({ children, className }) {
  return (
    <button
      className={cn(
        "flex h-9 items-center justify-between gap-2 rounded-md border bg-background px-3 text-sm",
        className,
      )}
    >
      {children}
      <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
    </button>
  );
}
function CodeBlock({ title, children }) {
  return (
    <div className="mt-3 overflow-hidden rounded-lg border">
      <div className="flex items-center justify-between border-b bg-muted/50 px-3 py-2 font-mono text-xs text-muted-foreground">
        <span>{title}</span>
        <Copy className="size-3.5 cursor-pointer hover:text-foreground" />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-foreground">
        {children}
      </pre>
    </div>
  );
}

function GitSettings() {
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Git</h1>
          <p className="mt-1 text-muted-foreground">
            Connect the GitHub or GitLab accounts your team uses to sync project
            code.
          </p>
        </div>
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Abrir docs <ExternalLink />
        </UIButton>
      </div>
      <p className="mt-4 max-w-2xl text-sm text-muted-foreground">
        Connections added here are available to every project in this workspace.
        Once a project is linked to a repository, it syncs both ways: edits in
        Xframe are committed to the repo, and pushed commits flow back into the
        project.
      </p>
      <Card className="mt-6 divide-y p-0">
        {[
          [
            "github",
            "GitHub",
            "Two-way sync with your GitHub account or organization",
          ],
          [
            "gitlab",
            "GitLab",
            "Two-way sync with GitLab.com or self-managed GitLab",
          ],
        ].map(([slug, name, desc]) => (
          <button
            key={name}
            className="flex w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-accent"
          >
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border">
              <AuthBrandIcon provider={slug} className="size-5" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">{name}</p>
              <p className="text-sm text-muted-foreground">{desc}</p>
            </div>
            <ChevronRight className="size-4 text-muted-foreground" />
          </button>
        ))}
      </Card>
    </div>
  );
}

const mcpClients = ["Claude", "Claude Code", "Cursor", "VS Code"];
function McpServerSettings() {
  const [client, setClient] = useState("Claude");
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Xframe MCP server</h1>
      <p className="mt-1 text-muted-foreground">
        Connect supported AI clients and developer tools to Xframe.
      </p>

      <div className="mt-6 flex items-start gap-3 rounded-lg border bg-muted/40 p-4">
        <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="flex-1">
          <p className="text-sm font-medium">
            What is Model Context Protocol (MCP)?
          </p>
          <p className="mt-0.5 text-sm text-muted-foreground">
            The Xframe MCP server allows AI agents, such as Claude, Codex, and
            Cursor, to connect to Xframe and build, manage and deploy apps.
          </p>
        </div>
        <UIButton variant="outline" size="sm" className="shrink-0">
          Read docs <ExternalLink />
        </UIButton>
      </div>

      <h2 className="mt-8 text-lg font-semibold">Server</h2>
      <Card className="mt-3 p-5">
        <p className="text-sm font-medium">Server URL</p>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Use this URL when adding Xframe as an MCP server in a supported
          client.
        </p>
        <div className="mt-3 flex items-center justify-between gap-2 rounded-md border px-3 py-2 font-mono text-sm">
          <span>https://mcp.xframe.ai/?src=settings</span>
          <Copy className="size-4 shrink-0 cursor-pointer text-muted-foreground hover:text-foreground" />
        </div>
        <Separator className="my-5" />
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Workspace access</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Connected clients use the signed-in user's Xframe access. Tool
              calls can edit projects, deploy apps, query databases, and consume
              credits.
            </p>
          </div>
          <UIButton variant="outline" className="shrink-0">
            Manage access
          </UIButton>
        </div>
      </Card>

      <h2 className="mt-8 text-lg font-semibold">Connect your client</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">
        Pick your client and follow the steps. Authentication uses OAuth, so
        there are no API keys to manage.
      </p>
      <Card className="mt-3 p-5">
        <div className="inline-flex rounded-full border bg-muted p-1 text-sm">
          {mcpClients.map((c) => (
            <button
              key={c}
              onClick={() => setClient(c)}
              className={cn(
                "rounded-full px-3 py-1 transition-colors",
                client === c
                  ? "bg-background shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {c}
            </button>
          ))}
        </div>

        <div className="mt-5 text-sm">
          {client === "Claude" && (
            <>
              <p>
                Add Xframe through Claude's connector settings. Works in Claude
                Desktop and on claude.ai.
              </p>
              <ol className="mt-4 space-y-3">
                {[
                  "In Claude, click the plus sign in the composer.",
                  "Open Connectors, browse connectors, then search for Xframe.",
                  "Click Connect, then sign in to Xframe when Claude prompts you.",
                ].map((s, i) => (
                  <li key={i} className="flex items-center gap-3">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full border text-xs text-muted-foreground">
                      {i + 1}
                    </span>
                    {s}
                  </li>
                ))}
              </ol>
              <p className="mt-4 text-muted-foreground">
                The Xframe tools appear in the composer's tool menu once
                authentication is complete.
              </p>
              <details className="mt-4">
                <summary className="cursor-pointer font-medium">
                  Prefer editing Claude Desktop config directly?
                </summary>
                <p className="mt-3 text-muted-foreground">
                  Add this to{" "}
                  <code className="rounded bg-muted px-1 font-mono text-xs">
                    claude_desktop_config.json
                  </code>
                  , then restart Claude Desktop:
                </p>
                <CodeBlock title="claude_desktop_config.json">{`{
  "mcpServers": {
    "lovable": {
      "type": "http",
      "url": "https://mcp.xframe.ai/?src=settings"
    }
  }
}`}</CodeBlock>
              </details>
            </>
          )}
          {client === "Claude Code" && (
            <>
              <p>Run this command in your terminal:</p>
              <CodeBlock title="terminal">
                {`claude mcp add --transport http lovable "https://mcp.xframe.ai/?src=settings"`}
              </CodeBlock>
              <p className="mt-3 text-muted-foreground">
                Claude Code opens a browser window for OAuth. Sign in to Xframe
                to complete the connection.
              </p>
            </>
          )}
          {client === "Cursor" && (
            <>
              <p>
                Add this to Cursor's MCP config at{" "}
                <code className="rounded bg-muted px-1 font-mono text-xs">
                  ~/.cursor/mcp.json
                </code>
                :
              </p>
              <CodeBlock title="~/.cursor/mcp.json">{`{
  "mcpServers": {
    "lovable": {
      "url": "https://mcp.xframe.ai/?src=settings"
    }
  }
}`}</CodeBlock>
            </>
          )}
          {client === "VS Code" && (
            <>
              <p>
                Run{" "}
                <code className="rounded bg-muted px-1 font-mono text-xs">
                  MCP: Add Server
                </code>{" "}
                or add this to{" "}
                <code className="rounded bg-muted px-1 font-mono text-xs">
                  .vscode/mcp.json
                </code>
                :
              </p>
              <CodeBlock title=".vscode/mcp.json">{`{
  "servers": {
    "lovable": {
      "type": "http",
      "url": "https://mcp.xframe.ai/?src=settings"
    }
  }
}`}</CodeBlock>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

const privacySections = [
  {
    title: "Acceso y membresía",
    desc: "Quién puede unirse al espacio de trabajo y mover proyectos.",
    rows: [
      { t: "Acceso predeterminado a los proyectos", d: "Elige si los nuevos proyectos son accesibles para todos los miembros del espacio de trabajo o si se restringen únicamente a los usuarios invitados.", control: "select", value: "Workspace" },
      { t: "Restringir invitaciones al espacio de trabajo", tier: "Enterprise", d: "Cuando está activado, solo los administradores y propietarios pueden invitar miembros a este espacio de trabajo.", on: false },
      { t: "Enlaces de invitación", d: "Permite que los miembros del espacio de trabajo creen y compartan enlaces de invitación.", on: true },
      { t: "Detección del espacio de trabajo", tier: "Business", d: "Permite que los miembros del mismo dominio de correo electrónico descubran este espacio de trabajo y soliciten acceso a él.", on: false },
      { t: "Perfiles públicos de miembros", tier: "Enterprise", d: "Los espacios de trabajo empresariales ocultan los perfiles de los miembros de forma predeterminada. Activa esta opción para que los perfiles públicos de Xframe de los miembros (xframe.ai/@username) sean visibles fuera del espacio de trabajo.", on: false },
      { t: "Transferencias de proyectos por editores", tier: "Enterprise", d: "Cuando está habilitado, los editores propietarios de un proyecto pueden transferirlo, o hacer un remix de una copia, a otro espacio de trabajo.", on: false },
      { t: "Exigir rol de editor del espacio de trabajo", tier: "Enterprise", d: "Cuando está activado, los espectadores del espacio de trabajo y los colaboradores externos pueden ver los proyectos, pero no editarlos, ni siquiera mediante la propiedad del proyecto o el acceso como colaborador.", on: false },
      { t: "Colaboradores externos del proyecto", tier: "Business", d: "Elige el rol de proyecto más alto que pueden tener las personas ajenas a este espacio de trabajo.", control: "select", value: "Permitir todos" },
    ],
  },
  {
    title: "Publicación",
    desc: "Controla cómo se publican e implementan los proyectos en la web.",
    rows: [
      { t: "Acceso predeterminado al sitio web", tier: "Business", d: "Elige quién puede ver los sitios web recién publicados: cualquier persona con el enlace o solo los miembros del espacio de trabajo que hayan iniciado sesión. Quienes publican pueden elegir una audiencia diferente para cada proyecto.", control: "select", value: "Anyone" },
      { t: "Quién puede publicar externamente", tier: "Enterprise", d: "Controla quién puede publicar e implementar proyectos en la web.", control: "select", value: "Editores y superiores" },
      { t: "Invitaciones externas", tier: "Business", d: "Los miembros pueden invitar por correo electrónico a personas ajenas al espacio de trabajo para que vean los proyectos publicados. Cuando se desactiva, los usuarios externos ya invitados conservan su acceso.", on: true },
      { t: "Bloquear la publicación con problemas críticos", d: "Impide que los proyectos con problemas de seguridad críticos se publiquen o actualicen.", on: false },
      { t: "Exigir análisis de seguridad básico antes de la primera publicación", d: "Exige que se complete el análisis de seguridad básico antes de que un proyecto pueda publicarse por primera vez.", on: false },
      { t: "Métodos de inicio de sesión de la app", tier: "Business", d: "Controla qué métodos de inicio de sesión pueden usar los proyectos de este espacio de trabajo para las apps generadas. Esto no afecta la forma en que los miembros del espacio de trabajo inician sesión en Xframe.", control: "button", value: "Configurar" },
    ],
  },
  {
    title: "Automatización de seguridad",
    desc: "Controla la corrección automática de seguridad para los proyectos del espacio de trabajo.",
    rows: [
      { t: "Corregir automáticamente problemas de seguridad", d: "Habilita la corrección automática de problemas básicos detectados en el análisis que sean de bajo riesgo a nivel del espacio de trabajo. Para el proyecto seleccionado, ajústalo en la configuración del proyecto.", control: "select", value: "Proyecto seleccionado" },
    ],
  },
  {
    title: "Abandoned projects",
    desc: "Automatically identify projects with no recent activity, both published and unpublished, and optionally delete them after a grace period.",
    rows: [
      { t: "Mark as abandoned after", tier: "Enterprise", d: "Projects with no activity for this period are marked abandoned.", control: "select", value: "60 days" },
      { t: "Delete abandoned projects after", d: "Abandoned projects stay recoverable during this grace period. Editing a project, sending a message, or clicking Keep it cancels deletion.", control: "select", value: "Never" },
    ],
  },
  {
    title: "Uso compartido",
    desc: "Controla cómo los miembros comparten los archivos del proyecto y los enlaces de vista previa.",
    rows: [
      { t: "Compartir enlace de vista previa", tier: "Enterprise", d: "Cuando está habilitado, los usuarios pueden crear enlaces de vista previa públicos y temporales para sus aplicaciones. Cuando está deshabilitado, se bloquea la creación de enlaces de vista previa.", on: true },
      { t: "Descargas de código", tier: "Enterprise", d: "Cuando está deshabilitado, solo los administradores y propietarios del espacio de trabajo pueden descargar el código fuente del proyecto.", on: true },
      { t: "Uso compartido entre proyectos", d: "Permite que los proyectos de este espacio de trabajo lean archivos de otros proyectos.", on: true },
    ],
  },
  {
    title: "Conectores MCP",
    desc: "Controla los servidores MCP que Xframe puede usar desde el chat.",
    rows: [
      { t: "Conectores MCP remotos", tier: "Business", d: "Permite que los miembros del espacio de trabajo conecten servidores MCP que Xframe puede invocar desde el chat. Al desactivarlo se eliminan las conexiones MCP existentes.", on: true },
      { t: "Servidores MCP locales de escritorio", tier: "Business", d: "Permite que los miembros del espacio de trabajo usen servidores MCP de sesiones conectadas de Xframe Desktop. Requiere que los conectores MCP remotos permanezcan habilitados.", on: true },
    ],
  },
  {
    title: "Protección de datos",
    desc: "Controla cómo se recopilan y exponen los datos de este espacio de trabajo.",
    rows: [
      { t: "Exclusión de la recopilación de datos", tier: "Business", d: "Excluye este espacio de trabajo de la recopilación de datos.", on: false },
      { t: "Análisis de datos confidenciales", tier: "Enterprise", d: "Activa la detección de PII para este espacio de trabajo. Incluye análisis bajo demanda del historial de chat, Xframe Cloud Database y Xframe Cloud Storage, y activa la protección de envío en el chat para mensajes nuevos y archivos adjuntos.", on: false },
      { t: "Bloquear buckets de almacenamiento públicos", d: "Impide que los usuarios creen buckets de almacenamiento de acceso público en Xframe Cloud.", on: true },
      { t: "Región de alojamiento predeterminada", tier: "Business", d: "Elige dónde se alojan los nuevos proyectos de este espacio de trabajo. Requiere una instancia de base de datos micro o superior y puede consumir más créditos.", control: "select", value: "Sin definir" },
    ],
  },
];
function PrivacySettings() {
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Privacidad y seguridad
          </h1>
          <p className="mt-1 text-muted-foreground">
            Gestiona la configuración de privacidad y seguridad de tu espacio de
            trabajo.
          </p>
        </div>
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Abrir docs <ExternalLink />
        </UIButton>
      </div>
      {privacySections.map((sec) => (
        <section key={sec.title} className="mt-8">
          <h2 className="text-lg font-semibold">{sec.title}</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{sec.desc}</p>
          <Card className="mt-3 divide-y p-0">
            {sec.rows.map((row) => (
              <div
                key={row.t}
                className="flex items-start justify-between gap-6 px-5 py-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{row.t}</p>
                    {row.tier && <TierBadge tier={row.tier} />}
                  </div>
                  <p className="mt-0.5 text-sm text-muted-foreground">{row.d}</p>
                </div>
                <div className="shrink-0 pt-0.5">
                  {row.control === "select" ? (
                    <SelectPill className="min-w-[160px]">
                      {row.value}
                    </SelectPill>
                  ) : row.control === "button" ? (
                    <UIButton variant="outline">{row.value}</UIButton>
                  ) : (
                    <Switch defaultChecked={row.on} />
                  )}
                </div>
              </div>
            ))}
          </Card>
        </section>
      ))}
    </div>
  );
}

function SettingsPage({ page }) {
  const [sideW, resizeSide] = useResizableWidth("xf-settings-sidebar", 264, 220, 420);
  return (
    <div className="min-h-screen bg-background">
      <SettingsSide page={page} width={sideW} onResize={resizeSide} />
      <main style={{ marginLeft: sideW }}>
        {page === "account" ? (
          <AccountSettings />
        ) : page === "apps" ? (
          <AppsSettings />
        ) : page === "workspace" ? (
          <WorkspaceSettings />
        ) : page === "billing" ? (
          <BillingSettings />
        ) : page === "people" ? (
          <PeopleSettings />
        ) : page === "knowledge" ? (
          <KnowledgeSettings />
        ) : page === "skills" ? (
          <SkillsSettings />
        ) : page === "git" ? (
          <GitSettings />
        ) : page === "mcp-server" ? (
          <McpServerSettings />
        ) : page === "privacy-security" ? (
          <PrivacySettings />
        ) : (
          <GenericSettings page={page} />
        )}
      </main>
    </div>
  );
}

function App() {
  const [, rerender] = useState(0);
  const { ready, profile, isRemote } = useStudio();
  React.useEffect(() => {
    const f = () => rerender((x) => x + 1);
    addEventListener("popstate", f);
    return () => removeEventListener("popstate", f);
  }, []);
  const p = location.pathname;
  const params = new URLSearchParams(location.search);
  const showConnectors = params.has("connectors");
  const showSearch = params.has("search");

  // Rutas privadas: sin sesión se muestra la landing con el modal de acceso.
  const isPrivate =
    p.startsWith("/dashboard") ||
    p.startsWith("/projects/") ||
    p.startsWith("/settings/");

  if (isRemote && isPrivate && !profile) {
    if (!ready) {
      return (
        <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
          Cargando…
        </div>
      );
    }
    return (
      <>
        <Landing />
        <AuthModal />
      </>
    );
  }

  const projectMatch = p.match(/^\/projects\/([^/]+)$/);
  const settingsMatch = p.match(/^\/settings\/([^/]+)$/);

  let page;
  if (p === "/es/pricing") page = <Pricing />;
  else if (p === "/es" || p === "/") page = <Landing />;
  else if (p === "/dashboard/resources") page = <Dashboard kind="resources" />;
  else if (p === "/dashboard") page = <Dashboard kind="home" />;
  else if (settingsMatch) page = <SettingsPage page={settingsMatch[1]} />;
  else if (projectMatch) page = <Editor projectId={projectMatch[1]} />;
  else page = <Landing />;

  const closeOverlay = () => go(p);
  return (
    <>
      {page}
      {showConnectors && <ConnectorsDialog onClose={closeOverlay} />}
      {showSearch && <CommandPalette close={closeOverlay} />}
    </>
  );
}
// Reutiliza la raíz entre hot-reloads: createRoot() en cada recarga apila
// raíces sobre el mismo contenedor y deja la UI en un estado inconsistente.
const container = document.getElementById("root");
const root = (window.__xframeRoot ??= createRoot(container));
root.render(
  <StudioProvider>
    <App />
  </StudioProvider>,
);
