import React, { useState } from "react";
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
  Command,
  Mic,
  ArrowUp,
  MoreHorizontal,
  ExternalLink,
  Check,
  Grid2X2,
  PanelLeft,
  Monitor,
  Share2,
  Eye,
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
  Bookmark,
  LineChart,
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
import "./index.css";
import "./styles.css";

const PROJECT = "/projects/77199122-f79d-49b5-b6b4-c3d86b6565da";
const go = (p) => {
  history.pushState({}, "", p);
  dispatchEvent(new PopStateEvent("popstate"));
};
const LovableHeart = ({ size = 24, className = "" }) => (
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
    <LovableHeart size={22} />
    Lovable
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
  ["Maison", "Editorial home goods storefront", "/assets/maison.webp"],
  [
    "Inspo Canvas",
    "Spatial canvas for collecting, arranging, and sharing ideas",
    "/assets/inspo.jpg",
  ],
  ["Personal blog", "Muted, intimate design", "/assets/personal-blog.png"],
  ["Fashion blog", "Minimal, playful design", "/assets/vesper.webp"],
  [
    "Continuum",
    "A calm, distraction-free habit tracker with streak cues",
    "/assets/continuum.jpg",
  ],
  [
    "Lovable slides",
    "Code-powered presentation builder",
    "/assets/lovable-slides.webp",
  ],
  [
    "Prompt Frame Creative Portfolio",
    "Dark-first premium aesthetic",
    "/assets/prompt-frame.webp",
  ],
  [
    "Ecommerce Store Website Template",
    "Premium design for webstore",
    "/assets/ecommerce.webp",
  ],
];
function PromptBox() {
  const [t, setT] = useState("");
  return (
    <Card className="w-full max-w-2xl p-2 text-left shadow-lg">
      <Textarea
        value={t}
        onChange={(e) => setT(e.target.value)}
        placeholder="Pídele a Lovable que cree una página de destino para mi…"
        className="min-h-[76px] resize-none border-0 text-base shadow-none focus-visible:ring-0"
      />
      <div className="flex items-center gap-1 px-1 pb-1">
        <UIButton variant="ghost" size="icon" aria-label="Añadir">
          <Plus />
        </UIButton>
        <div className="flex-1" />
        <UIButton variant="outline" size="sm">
          Crear <ChevronDown />
        </UIButton>
        <UIButton variant="ghost" size="icon" aria-label="Grabar voz">
          <Mic />
        </UIButton>
        <UIButton size="icon" aria-label="Enviar" onClick={() => go("/dashboard")}>
          <ArrowUp />
        </UIButton>
      </div>
    </Card>
  );
}
const authProviders = [
  ["Continuar con Google", "google"],
  ["Continuar con GitHub", "github"],
  ["Continuar con Apple", "apple"],
];
function AuthModal() {
  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o) go("/es");
      }}
    >
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader className="items-center">
          <LovableHeart size={36} />
          <DialogTitle className="text-2xl">Empieza a crear.</DialogTitle>
          <DialogDescription>Inicia sesión en tu cuenta</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          {authProviders.map(([label, slug]) => (
            <UIButton
              key={label}
              variant="outline"
              className="w-full"
              onClick={() => go("/dashboard")}
            >
              <img
                src={`https://cdn.simpleicons.org/${slug}`}
                alt=""
                className="size-4"
              />
              {label}
            </UIButton>
          ))}
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Separator className="flex-1" />O<Separator className="flex-1" />
          </div>
          <Input type="email" placeholder="Correo electrónico" />
          <UIButton className="w-full" onClick={() => go("/dashboard")}>
            Continuar
          </UIButton>
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
    "Contrata a un experto de Lovable",
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
    "Describe la aplicación o el sitio web que quieres crear, o adjunta capturas de pantalla y documentos.",
  ],
  [
    "Velo cobrar vida",
    "Mira cómo tu visión se transforma en una aplicación funcional en tiempo real.",
  ],
  [
    "Perfecciona y publica",
    "Personaliza tu creación con comentarios sencillos y publícala con un solo clic.",
  ],
];
const stats = [
  ["50M", "proyectos creados en Lovable"],
  ["1M", "nuevos proyectos creados por semana en Lovable"],
  ["100M", "visitas al mes a proyectos creados con Lovable"],
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
          Construye con IA
        </Badge>
        <h1 className="max-w-3xl text-4xl font-bold tracking-tight sm:text-6xl">
          Construye algo con Lovable
        </h1>
        <p className="max-w-xl text-lg text-muted-foreground">
          Crea apps y sitios web conversando con la IA
        </p>
        <PromptBox />
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16 text-center">
        <p className="text-sm text-muted-foreground">
          Equipos de empresas líderes crean con Lovable
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
        <h2 className="text-3xl font-bold tracking-tight">Lovable</h2>
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
    desc: "Descubre lo que Lovable puede hacer por ti",
    price: "€0",
    cadence: "al mes",
    leads: [
      ["No se necesita tarjeta de crédito", CreditCard],
      ["Créditos gratuitos", Grid2X2, true],
    ],
    features: [
      "Proyectos privados del espacio de trabajo",
      "Colaboradores ilimitados",
      "5 dominios lovable.app",
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
      "Dominios lovable.app ilimitados",
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
  "¿Qué es Lovable y cómo funciona?",
  "¿Qué es un crédito?",
  "¿Cómo uso los créditos en Lovable?",
  "¿Caducan los créditos?",
  "¿Qué pasa con mis créditos si finaliza mi suscripción?",
  "¿Son reembolsables los créditos?",
  "¿Qué incluyen los planes gratuitos y de pago?",
  "How do I buy credits for a team, class, or community?",
  "Do you charge per seat or per user?",
  "How much does it cost to run my app on Lovable?",
  "Why is the Business plan more expensive?",
  "¿Quién es propietario de los proyectos y el código?",
  "¿Ofrecen un descuento para estudiantes?",
  "¿Dónde puedo obtener más información?",
];
function PricingCard({ p, i }) {
  const isPro = p.name === "Pro";
  const isEnterprise = p.name === "Enterprise";
  const hasSelect = i === 1 || i === 2;
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
          {p.price}
        </span>
      </div>
      <p className="mt-1 min-h-[20px] text-sm text-muted-foreground">
        {isEnterprise ? "Precios por volumen" : p.cadence}
      </p>
      {hasSelect ? (
        <button className="mt-4 flex h-9 w-full items-center justify-between rounded-md border bg-background px-3 text-sm">
          100 créditos mensuales
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </button>
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
    "Lovable para estudiantes",
    "Verifica tu condición de estudiante y obtén hasta un 50 % de descuento en Lovable Pro.",
    "Empezar",
  ],
  [
    "Lovable para campus",
    "Controles de facturación y administración para universidades y centros de educación superior.",
    "Contactar con ventas",
  ],
  [
    "Lovable para niños",
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
          <LovableHeart size={32} />
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
          <PricingCard key={p.name} p={p} i={i} />
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
              onClick={() => go(`${PROJECT}/settings/privacy-security`)}
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
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex size-8 items-center justify-center rounded-full bg-green-600 text-sm font-semibold text-white outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Cuenta"
        >
          H
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-64">
        <div className="flex items-center gap-2.5 p-2">
          <span className="flex size-9 items-center justify-center rounded-full bg-green-600 text-sm font-semibold text-white">
            H
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">Héctor Vidal Sánchez</p>
            <p className="truncate text-xs text-muted-foreground">
              hectorvidal0411@gmail.com
            </p>
          </div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem>
          <User /> Perfil
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => go(`${PROJECT}/settings/account`)}>
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
        <DropdownMenuItem onClick={() => go("/es")}>
          <LogOut /> Cerrar sesión
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
function DashboardSide() {
  const openOverlay = (name) => go(`${location.pathname}?${name}=1`);
  return (
    <aside className="fixed inset-y-0 left-0 flex w-60 flex-col gap-1 border-r bg-muted/30 p-3">
      <div className="px-2 py-1">
        <Logo />
      </div>
      <button className="mt-2 flex items-center gap-2 rounded-md p-2 text-sm transition-colors hover:bg-accent">
        <span className="flex size-6 items-center justify-center rounded-md bg-primary text-xs font-semibold text-primary-foreground">
          H
        </span>
        <span className="flex-1 text-left font-medium">Héctor's Lovable</span>
        <ChevronDown className="size-4 text-muted-foreground" />
      </button>
      <nav className="mt-2 flex flex-col gap-1">
        {navItems.map(([id, I, l]) => {
          if (id === "search") {
            return (
              <button
                key={id}
                className={sideNavClass(false)}
                onClick={() => openOverlay("search")}
              >
                <I />
                {l}
                <kbd className="ml-auto rounded border bg-background px-1.5 text-xs text-muted-foreground">
                  Ctrl K
                </kbd>
              </button>
            );
          }
          if (id === "connectors") {
            return (
              <button
                key={id}
                className={sideNavClass(location.search.includes("connectors"))}
                onClick={() => openOverlay("connectors")}
              >
                <I />
                {l}
              </button>
            );
          }
          const selected = location.pathname === id && !location.search;
          return (
            <button key={id} className={sideNavClass(selected)} onClick={() => go(id)}>
              <I />
              {l}
            </button>
          );
        })}
      </nav>
      <p className="mt-4 px-3 text-xs font-medium text-muted-foreground">
        PROYECTOS
      </p>
      {[
        [FolderKanban, "Todos los proyectos"],
        [Users, "Creados por mí"],
        [Share2, "Compartido conmigo"],
      ].map(([I, l]) => (
        <button key={l} className={sideNavClass(false)}>
          <I />
          {l}
        </button>
      ))}
      <p className="mt-4 px-3 text-xs font-medium text-muted-foreground">
        RECIENTES
      </p>
      <button className={sideNavClass(false)} onClick={() => go(PROJECT)}>
        <span className="size-2 rounded-full bg-green-500" />
        Telemetry Landing Pages
      </button>
      <div className="mt-auto flex flex-col gap-2 pt-2">
        <Card className="p-3">
          <div className="flex items-center gap-2.5">
            <Gift className="size-5 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <p className="text-sm font-medium">Compartir Lovable</p>
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
            <p className="text-sm font-medium">Cambia a Pro</p>
            <p className="truncate text-xs text-muted-foreground">
              Desbloquear más funciones
            </p>
          </div>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary">
            <Zap className="size-4" />
          </span>
        </button>
        <div className="flex items-center justify-between px-1 pt-1">
          <UserMenu />
          <button className="relative rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
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
  "Telemetry Landing Pages",
  "E-commerce Studio",
  "Portfolio Minimal",
  "Analytics Dashboard",
];
const cmdItemClass =
  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors [&_svg]:size-4 [&_svg]:text-muted-foreground";
const cmdRecent = [
  "Remix of Prompt Frame Creative Portfolio",
  "Telemetry Landing Pages",
];
const cmdNavigate = [
  [LayoutDashboard, "Dashboard", "/dashboard"],
  [Plus, "Create new project", PROJECT],
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
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[14vh]"
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
        <div className="overflow-y-auto p-2">
          <p className="px-3 py-1.5 text-xs font-medium text-muted-foreground">
            Recent projects
          </p>
          {cmdRecent.map((x) => (
            <button
              key={x}
              onClick={() => go(PROJECT)}
              className={cn(cmdItemClass, "hover:bg-accent")}
            >
              <FolderKanban />
              {x}
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
              onClick={() => go(`${PROJECT}/settings/${pg}`)}
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
  "Actualizaste la landing de Telemetry",
  "Lovable publicó una nueva versión",
  "Conectaste el proyecto con GitHub",
  "Se guardaron los últimos cambios",
];
const projectTabs = [
  ["mine", "Mis proyectos"],
  ["recent", "Vistos recientemente"],
  ["shared", "Compartidos conmigo"],
  ["templates", "Plantillas de Lovable"],
];
function Dashboard({ kind = "home" }) {
  const [projectView, setProjectView] = useState("mine");
  return (
    <div className="min-h-screen bg-background">
      <DashboardSide />
      <main className="relative isolate ml-60 min-h-screen">
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
                Las apps de Lovable ahora funcionan en ChatGPT y Claude
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
                <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-6 md:grid-cols-4">
                  {projects.map((p, i) => (
                    <div
                      key={p}
                      className="group cursor-pointer"
                      onClick={() => go(PROJECT)}
                    >
                      <div
                        className="aspect-video overflow-hidden rounded-xl border bg-muted bg-cover bg-center transition-shadow group-hover:shadow-md"
                        style={{ backgroundImage: `url(${projectThumbs[i]})` }}
                      />
                      <div className="mt-3 flex items-center gap-2">
                        <span className="flex size-7 items-center justify-center rounded-full bg-green-100 text-xs font-semibold text-green-700">
                          H
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{p}</p>
                          <p className="text-xs text-muted-foreground">
                            Editado {i + 1} días atrás
                          </p>
                        </div>
                        <MoreHorizontal className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                      </div>
                    </div>
                  ))}
                </div>
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
                          Telemetry Landing Pages
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
      <h1 className="text-2xl font-bold tracking-tight">Resources</h1>
      <p className="mt-1 text-muted-foreground">
        Start from a template to build your next project
      </p>
      <div className="mt-6 grid grid-cols-2 gap-6 md:grid-cols-3 lg:grid-cols-4">
        {items.map((x, i) => (
          <div
            key={`${x[0]}-${i}`}
            className="group cursor-pointer"
            onClick={() => go(PROJECT)}
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
// [name, slug, description, category, { enabled, badge, kind }]
const connectors = [
  ["Cloud", null, "Built-in backend, ready to use", "Productivity", { enabled: true, kind: "connections" }],
  ["AI", null, "Unlock powerful AI features", "Productivity", { enabled: true }],
  ["Stripe", "stripe", "Set up payments", "Ecommerce", { enabled: true }],
  ["Paddle", "paddle", "Set up payments with tax handled for you", "Ecommerce", {}],
  ["Shopify", "shopify", "Build an eCommerce store", "Ecommerce", {}],
  ["Apollo.io", null, "Search, enrich, and engage B2B contacts and companies", "Sales", { badge: "New" }],
  ["ClickHouse", "clickhouse", "Query ClickHouse databases over the HTTP interface", "Productivity", { badge: "New", kind: "connections" }],
  ["dbt Semantic Layer", null, "Query governed metrics from your dbt Semantic Layer", "Productivity", { badge: "New", kind: "connections" }],
  ["Google Search Console", "googlesearchconsole", "Read Search Console analytics and manage sites", "Google", {}],
  ["Firecrawl", null, "AI-powered scraper, search and retrieval tool", "Productivity", {}],
  ["Google Sheets", "googlesheets", "Read and update spreadsheet data", "Google", {}],
  ["Google Maps Platform", "googlemaps", "Maps, geocoding, directions, and places APIs", "Google", { kind: "connections" }],
  ["Resend", "resend", "Email API for developers", "Marketing", {}],
  ["Gmail", "gmail", "Read, send, and manage your emails", "Google", {}],
  ["Google Drive", "googledrive", "Upload and download files to and from Google Drive", "Google", {}],
  ["Google Calendar", "googlecalendar", "Create and manage Google Calendar events", "Google", {}],
  ["Telegram", "telegram", "Messaging platform with Bot API for automated interactions", "Messaging", {}],
  ["Twilio", "twilio", "Cloud communications platform for SMS, voice, and messaging", "Messaging", {}],
  ["ElevenLabs", "elevenlabs", "AI voice generation, text-to-speech, and speech-to-text", "Productivity", {}],
  ["Notion", "notion", "Add Notion pages and databases to your app", "Productivity", {}],
  ["Google Docs", "googledocs", "Create and edit Google Docs documents", "Google", {}],
  ["Brevo", "brevo", "Email, SMS, CRM, and marketing automation API", "Marketing", {}],
  ["Airtable", "airtable", "Spreadsheet-database hybrid and automation platform", "Productivity", {}],
  ["Slack", "slack", "Send messages and interact with Slack workspaces", "Messaging", {}],
  ["Microsoft Outlook", "microsoftoutlook", "Read, send, and manage Outlook email", "Microsoft", {}],
  ["HubSpot", "hubspot", "CRM, marketing, and sales platform", "Sales", {}],
  ["GitHub", "github", "Sync code and manage repositories", "Productivity", { enabled: true }],
  ["Supabase", "supabase", "Postgres database, auth, and storage", "Productivity", { enabled: true, kind: "connections" }],
].map(([name, slug, desc, category, meta]) => ({
  name,
  slug,
  desc,
  category,
  kind: meta.kind || "permissions",
  ...meta,
}));

function ConnectorIcon({ c, className = "size-6" }) {
  if (c.slug) {
    return (
      <img
        src={`https://cdn.simpleicons.org/${c.slug}`}
        alt=""
        className={className}
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
  const list = connectors.filter((c) =>
    category === "All"
      ? true
      : category === "Enabled"
        ? c.enabled
        : c.category === category,
  );
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[85vh] w-full max-w-5xl overflow-hidden rounded-xl border bg-background shadow-2xl"
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
          <div className="flex-1 overflow-y-auto p-5">
            {selected ? (
              <ConnectorDetail c={selected} />
            ) : (
              <>
                <div className="py-4 text-center">
                  <h2 className="text-xl font-bold">
                    Build from what you already use
                  </h2>
                  <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                    Connectors let your Lovable app talk to external tools like
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
  ["preview", Globe, "Vista previa"],
  ["files", FileText, "Archivos"],
  ["code", Code2, "Código"],
  ["more", Layers, "Más"],
];
const editorChips = [
  "Configurar analítica",
  "Añadir formulario demo",
  "Mejorar SEO técnico",
  "Crear…",
];
const codeTree = [
  ["folder", ".lovable", 0],
  ["file", "project.json", 1],
  ["folder", "public", 0],
  ["file", "favicon.ico", 1],
  ["file", "robots.txt", 1],
  ["folder", "src", 0],
  ["folder", "assets", 1],
  ["folder", "components / ui", 1],
  ["folder", "hooks", 1],
  ["folder", "lib", 1],
  ["folder", "routes", 1],
  ["file", "router.tsx", 1],
  ["file", "routeTree.gen.ts", 1],
  ["file", "server.ts", 1],
  ["file", "start.ts", 1],
  ["file", "styles.css", 1],
  ["file", ".gitignore", 0],
  ["file", ".prettierignore", 0],
  ["file", ".prettierrc", 0],
  ["file", "AGENTS.md", 0],
  ["file", "bun.lock", 0],
  ["file", "bunfig.toml", 0],
  ["file", "components.json", 0],
  ["file", "eslint.config.js", 0],
  ["file", "package.json", 0],
  ["file", "tsconfig.json", 0],
  ["file", "vite.config.ts", 0],
];
const moreMenu = [
  [LineChart, "Analíticas"],
  [Cloud, "Cloud"],
  [Layers, "Integraciones de agentes"],
  [CreditCard, "Pagos"],
  [Plug, "Conectores"],
  [Shield, "Seguridad"],
  [Search, "SEO y búsqueda con IA"],
];
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

function EditorChat() {
  return (
    <aside className="flex w-[380px] shrink-0 flex-col border-r bg-background">
      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
        <div className="ml-8 rounded-2xl bg-muted p-3">
          Hazme una landing web para mi empresa de saas de txlemetry
        </div>
        <p className="text-muted-foreground">Thought for 12s</p>
        <p className="leading-relaxed">
          Voy a preparar 3 propuestas visuales para tu landing de SaaS de
          telemetría para que elijas la dirección antes de construirla.
        </p>
        <Card className="p-3">
          <div className="flex items-center justify-between">
            <p className="font-medium">Preparó propuestas de estilo</p>
            <Bookmark className="size-4 text-muted-foreground" />
          </div>
          <div
            className="mt-3 aspect-[16/10] rounded-lg border bg-neutral-900 bg-cover bg-center"
            style={{ backgroundImage: "url(/assets/prompt-frame.webp)" }}
          />
          <div className="mt-3 grid grid-cols-2 gap-2">
            <UIButton variant="outline" size="sm">
              Detalles
            </UIButton>
            <UIButton variant="secondary" size="sm">
              Preview
            </UIButton>
          </div>
        </Card>
        <p className="leading-relaxed">
          Tu landing de Txlemetry ya está lista con la dirección{" "}
          <b>Engineering noir</b>: tema oscuro, acento cian, tipografía Space
          Grotesk + Inter, hero con imagen generada del dashboard, grid de
          características, CTA de demo y footer. El build y la vista previa se ven
          correctos.
        </p>
        <div className="flex items-center gap-1 text-muted-foreground">
          {[Undo2, ThumbsUp, ThumbsDown, Copy, MoreHorizontal].map((I, i) => (
            <EditorIconBtn key={i}>
              <I />
            </EditorIconBtn>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {editorChips.map((c) => (
            <button
              key={c}
              className="rounded-full border px-3 py-1.5 text-xs transition-colors hover:bg-accent"
            >
              {c}
            </button>
          ))}
        </div>
      </div>
      <div className="p-3">
        <Card className="p-2">
          <Textarea
            placeholder="Pregúntale a Lovable…"
            className="min-h-[52px] resize-none border-0 text-sm shadow-none focus-visible:ring-0"
          />
          <div className="flex items-center gap-1 px-1 pb-1">
            <EditorIconBtn>
              <Plus />
            </EditorIconBtn>
            <div className="flex-1" />
            <UIButton variant="ghost" size="sm">
              Crear <ChevronDown />
            </UIButton>
            <EditorIconBtn>
              <Mic />
            </EditorIconBtn>
            <UIButton size="icon" className="size-8">
              <ArrowUp />
            </UIButton>
          </div>
        </Card>
      </div>
    </aside>
  );
}

function EditorPreview() {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border bg-[#070707] font-grotesk text-white">
      <div className="flex h-14 shrink-0 items-center gap-8 border-b border-white/10 px-6">
        <span className="flex items-center gap-2 font-semibold">
          <span className="flex size-6 items-center justify-center rounded bg-cyan-400 text-xs text-black">
            ◆
          </span>
          TXLEMETRY
        </span>
        <span className="flex-1 text-sm text-white/60">
          Platform　Integrations　Pricing
        </span>
        <button className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-black">
          Request Demo
        </button>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <p className="text-xs tracking-widest text-cyan-400">
          ● REAL-TIME TRANSMISSION MONITORING
        </p>
        <h1 className="mt-4 text-5xl font-medium leading-tight">
          Observe every <span className="text-cyan-400">TX</span>
          <br />
          in high definition.
        </h1>
        <p className="mt-4 max-w-md text-white/60">
          Stop guessing. Txlemetry provides millisecond-level visibility into
          distributed transactions and data streams for engineering teams that
          ship fast.
        </p>
        <div className="mt-6 flex gap-3">
          <button className="rounded-md bg-cyan-400 px-5 py-2.5 font-medium text-black">
            Get Started for Free
          </button>
          <button className="rounded-md border border-white/20 px-5 py-2.5 font-medium">
            View Documentation
          </button>
        </div>
      </div>
    </div>
  );
}

function EditorFiles() {
  return (
    <div className="grid h-full grid-cols-2 overflow-hidden rounded-xl border bg-background">
      <div className="flex flex-col items-center justify-center gap-2 border-r px-6 text-center">
        <FileText className="size-8 text-muted-foreground" />
        <p className="font-semibold">You haven't generated any files yet.</p>
        <p className="text-sm text-muted-foreground">
          Once you create one, it will appear here.
        </p>
      </div>
      <div className="flex items-center justify-center px-6 text-center text-sm text-muted-foreground">
        File preview unavailable.
      </div>
    </div>
  );
}

function EditorCode() {
  return (
    <div className="grid h-full grid-cols-[minmax(280px,340px)_1fr] overflow-hidden rounded-xl border bg-background">
      <div className="flex flex-col overflow-hidden border-r">
        <div className="flex items-center gap-2 p-3">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <input
              placeholder="Search code"
              className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          <EditorIconBtn>
            <ChevronsUpDown />
          </EditorIconBtn>
        </div>
        <div className="overflow-y-auto px-2 pb-3 text-sm">
          {codeTree.map(([type, name, depth]) => (
            <button
              key={name}
              style={{ paddingLeft: `${8 + depth * 16}px` }}
              className="flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left transition-colors hover:bg-accent"
            >
              {type === "folder" ? (
                <>
                  <ChevronRight className="size-3.5 text-muted-foreground" />
                  {name}
                </>
              ) : (
                <>
                  <FileText className="size-3.5 text-muted-foreground" />
                  {name}
                </>
              )}
            </button>
          ))}
        </div>
      </div>
      <div />
    </div>
  );
}

function EditorMore() {
  return (
    <div className="grid h-full grid-cols-[minmax(240px,280px)_1fr] overflow-hidden rounded-xl border bg-background">
      <div className="flex flex-col gap-1 border-r p-2">
        {moreMenu.map(([I, l], i) => (
          <button
            key={l}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors [&_svg]:size-4 [&_svg]:text-muted-foreground",
              i === 0 ? "bg-accent font-medium" : "hover:bg-accent",
            )}
          >
            <I />
            {l}
          </button>
        ))}
      </div>
      <div className="flex flex-col items-center justify-center gap-2 px-6 text-center">
        <LineChart className="size-7 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          To view analytics, you first need to publish your project.
        </p>
      </div>
    </div>
  );
}

function Editor() {
  const [tab, setTab] = useState("preview");
  const title = { files: "Files", code: "Code", more: "Más" }[tab];
  return (
    <div className="flex h-screen flex-col bg-muted/30">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3">
        <button
          className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm font-medium transition-colors hover:bg-accent"
          onClick={() => go("/dashboard")}
        >
          <img src="/lovable-logo.svg" alt="" className="size-6" />
          Telemetry Landing Pages
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

        {tab === "preview" ? (
          <>
            <div className="ml-auto flex items-center gap-0.5">
              <EditorIconBtn>
                <Monitor />
              </EditorIconBtn>
              <EditorIconBtn>
                <RefreshCw />
              </EditorIconBtn>
            </div>
            <button className="flex h-8 items-center gap-2 rounded-md border px-3 text-sm">
              Homepage <ChevronDown className="size-3.5 text-muted-foreground" />
            </button>
            <EditorIconBtn>
              <ExternalLink />
            </EditorIconBtn>
            <UIButton variant="outline" size="sm">
              <Share2 /> Share
            </UIButton>
            <UIButton
              size="sm"
              className="bg-violet-600 text-white hover:bg-violet-700"
            >
              <Zap /> Mejorar plan
            </UIButton>
            <UIButton
              size="sm"
              className="bg-blue-600 text-white hover:bg-blue-700"
            >
              Publish
            </UIButton>
          </>
        ) : (
          <>
            <span className="absolute left-1/2 -translate-x-1/2 text-sm font-medium">
              {title}
            </span>
            {tab === "code" && (
              <div className="ml-auto flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Read only</span>
                <UIButton
                  size="sm"
                  className="bg-violet-600 text-white hover:bg-violet-700"
                >
                  Upgrade
                </UIButton>
              </div>
            )}
            <EditorIconBtn
              className={tab === "code" ? "" : "ml-auto"}
              onClick={() => setTab("preview")}
            >
              <X />
            </EditorIconBtn>
          </>
        )}
      </header>

      <div className="flex flex-1 overflow-hidden">
        <EditorChat />
        <main className="flex-1 overflow-hidden p-2">
          {tab === "preview" && <EditorPreview />}
          {tab === "files" && <EditorFiles />}
          {tab === "code" && <EditorCode />}
          {tab === "more" && <EditorMore />}
        </main>
      </div>
    </div>
  );
}

const settingsGroups = [
  {
    title: "CUENTA",
    items: [
      ["account", "Héctor Vidal Sánchez", User],
      ["apps", "Dispositivos y apps", Monitor],
    ],
  },
  {
    title: "ESPACIO DE TRABAJO",
    items: [
      ["workspace", "Héctor's Lovable", "H"],
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
function SettingsSide({ page }) {
  return (
    <aside className="fixed inset-y-0 left-0 flex w-[264px] flex-col overflow-y-auto border-r bg-muted/30 p-3">
      <button
        onClick={() => go(PROJECT)}
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
          {group.items.map(([id, label, Icon, badge, external]) => (
            <button
              key={id}
              onClick={() => go(`${PROJECT}/settings/${id}`)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors [&>svg]:size-4 [&>svg]:text-muted-foreground",
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
                    "rounded px-1.5 py-0 text-[10px] font-normal",
                    badge === "Enterprise" &&
                      "bg-purple-100 text-purple-700 hover:bg-purple-100",
                  )}
                >
                  {badge}
                </Badge>
              )}
              {external && (
                <ExternalLink className="size-3.5 text-muted-foreground" />
              )}
            </button>
          ))}
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
        "Lovable Desktop",
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
    "Configura Telemetry Landing Pages",
    [
      ["Nombre del proyecto", "Telemetry Landing Pages"],
      ["Visibilidad", "Privado"],
      ["Dominio de Lovable", "telemetry-landing-pages.lovable.app"],
      ["Eliminar proyecto", "Esta acción no se puede deshacer."],
    ],
  ],
  workspace: [
    "Espacio de trabajo",
    "Gestiona Héctor's Lovable",
    [
      ["Nombre del espacio de trabajo", "Héctor's Lovable"],
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
        "Lovable usará estas instrucciones en nuevas conversaciones.",
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
        "Enseña a Lovable un flujo de trabajo repetible.",
      ],
    ],
  ],
  "mcp-server": [
    "Conectores MCP",
    "Controla los servidores MCP que Lovable puede usar desde el chat.",
    [
      [
        "Conectores MCP remotos",
        "Permite que los miembros del espacio de trabajo conecten servidores MCP que Lovable puede invocar desde el chat. Al desactivarlo se eliminan las conexiones MCP existentes.",
      ],
      [
        "Servidores MCP locales de escritorio",
        "Permite que los miembros usen servidores MCP de sesiones conectadas de Lovable Desktop. Requiere que los conectores MCP remotos permanezcan habilitados.",
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
        "Activa la detección de información personal en el historial de chat, la base de datos y el almacenamiento de Lovable Cloud.",
      ],
      [
        "Bloquear buckets de almacenamiento públicos",
        "Impide que los usuarios creen buckets de almacenamiento de acceso público en Lovable Cloud.",
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
function AccountSettings() {
  const [chatSug, setChatSug] = useState(true);
  const [autoInvite, setAutoInvite] = useState(true);
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Cuenta</h1>
      <p className="mt-1 text-muted-foreground">
        Personaliza cómo te ven los demás e interactúan contigo en Lovable.
      </p>

      <Card className="mt-6 p-5">
        <div className="flex items-center gap-2">
          <p className="font-medium">Showcase skills</p>
          <Badge variant="secondary" className="rounded">
            Beta
          </Badge>
        </div>
        <p className="mt-1.5 text-sm text-muted-foreground">
          No skills yet. Build apps that get real usage to unlock skills to
          showcase on your LinkedIn profile.{" "}
          <a href="#" className="text-foreground underline">
            Learn how to unlock skills
          </a>
        </p>
      </Card>

      <SettingsSection title="Perfil" desc="Controla cómo apareces en Lovable.">
        <SettingsRow
          title="Perfil"
          desc="Cambia el nombre, la ubicación, el avatar y el banner de tu perfil."
        >
          <UIButton variant="ghost" className="text-muted-foreground">
            Abrir perfil <ExternalLink />
          </UIButton>
        </SettingsRow>
        <SettingsRow
          title="Nombre de usuario"
          desc="Tu identificador público y la URL de tu perfil."
        >
          <button className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">
            e60r71rqUdTmME4wb4oYLy4G9vE3
            <Pencil className="size-3.5" />
          </button>
        </SettingsRow>
        <SettingsRow
          title="Correo electrónico"
          desc="Tu dirección de correo electrónico asociada a tu cuenta."
        >
          <span className="text-sm text-muted-foreground">
            hectorvidal0411@gmail.com
          </span>
        </SettingsRow>
        <SettingsRow
          title="Visibilidad del perfil"
          desc="Controla quién puede ver tu perfil público."
        >
          <FauxSelect>Público</FauxSelect>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Preferencias"
        desc="Personaliza cómo funciona Lovable para ti."
      >
        <SettingsRow
          title="Idioma (Language)"
          desc="Elige el idioma que Lovable usará para tu cuenta."
        >
          <FauxSelect>Español</FauxSelect>
        </SettingsRow>
        <SettingsRow
          title="Sugerencias de chat"
          desc="Muestra sugerencias útiles en la interfaz de chat para mejorar tu experiencia."
        >
          <Switch checked={chatSug} onCheckedChange={setChatSug} />
        </SettingsRow>
        <SettingsRow
          title="Sonido de generación completada"
          desc="Reproduce un sonido de notificación agradable cuando finaliza una generación."
        >
          <FauxSelect>Primera generación</FauxSelect>
        </SettingsRow>
        <SettingsRow
          title="Aceptar invitaciones automáticamente"
          desc="Únete automáticamente a espacios de trabajo y proyectos cuando te inviten, sin tener que aceptarlos manualmente."
        >
          <Switch checked={autoInvite} onCheckedChange={setAutoInvite} />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Cuentas vinculadas"
        desc="Gestiona las cuentas vinculadas para el inicio de sesión."
      >
        <div className="flex items-center gap-3 px-5 py-4">
          <img
            src="https://cdn.simpleicons.org/google"
            alt=""
            className="size-6"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium">Google</p>
              <Badge variant="secondary" className="rounded">
                Principal
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              hectorvidal0411@gmail.com
            </p>
          </div>
        </div>
        <SettingsRow
          title="Vincular cuenta de empresa"
          desc="Usa el inicio de sesión único de tu organización."
        >
          <UIButton variant="outline">Vincular</UIButton>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Seguridad" desc="Protege el acceso a tu cuenta.">
        <SettingsRow
          title="Se requiere reautenticación"
          desc="Por seguridad, por favor vuelve a autenticarte para gestionar los ajustes de la autenticación."
        >
          <UIButton variant="outline">Volver a autenticarte</UIButton>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Zona de peligro">
        <SettingsRow
          title="Eliminar cuenta"
          desc="Elimina permanentemente tu cuenta de Lovable. Esta acción no se puede deshacer."
        >
          <UIButton
            variant="ghost"
            className="text-destructive hover:text-destructive"
          >
            Eliminar cuenta
          </UIButton>
        </SettingsRow>
      </SettingsSection>
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
function WorkspaceSettings() {
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
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Abrir docs <ExternalLink />
        </UIButton>
      </div>

      <SettingsSection
        title="Perfil del espacio de trabajo"
        desc="Controla cómo aparece este espacio de trabajo en Lovable."
      >
        <SettingsRow
          title="Avatar"
          desc="Configura un avatar para tu espacio de trabajo."
        >
          <span className="flex size-9 items-center justify-center rounded-lg bg-pink-600 text-sm font-semibold text-white">
            H
          </span>
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
            <Input defaultValue="Héctor's Lovable" />
            <p className="mt-1 text-right text-xs text-muted-foreground">
              16 / 50 caracteres
            </p>
          </div>
        </div>
        <SettingsRow
          title="ID del espacio de trabajo"
          desc="Identificador único del espacio de trabajo"
        >
          <button className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">
            PeTnE2Zn3qNK0h5TGLod
            <Copy className="size-3.5" />
          </button>
        </SettingsRow>
        <SettingsRow
          title="Identificador del espacio de trabajo"
          desc="Configura un identificador para la página de perfil del espacio de trabajo."
        >
          <UIButton variant="outline">Establecer identificador</UIButton>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Valores predeterminados de los miembros"
        desc="Establece límites predeterminados para los miembros del espacio de trabajo."
      >
        <div className="flex items-start justify-between gap-4 px-5 py-4">
          <div className="min-w-0">
            <p className="text-sm font-medium">
              Límite de créditos mensual predeterminado por miembro
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              El límite de créditos mensual predeterminado para los miembros de
              este espacio de trabajo. Déjalo vacío para no aplicar ningún
              límite.
            </p>
          </div>
          <Input
            placeholder="Introduce el límite de créditos mensual por miembro"
            className="w-64 shrink-0"
          />
        </div>
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
          desc="Elimina permanentemente este espacio de trabajo y todos los proyectos que contiene. Los miembros pierden el acceso de inmediato."
        >
          <UIButton
            variant="ghost"
            className="text-destructive hover:text-destructive"
          >
            Eliminar espacio de trabajo
          </UIButton>
        </SettingsRow>
      </SettingsSection>
    </div>
  );
}

function BillingPlanCard({ p }) {
  const isPro = p.name === "Pro";
  const isEnterprise = p.name === "Enterprise";
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
          {p.price}
        </span>
      </div>
      <p className="mt-1 min-h-[20px] text-sm text-muted-foreground">
        {isEnterprise ? "" : p.cadence}
      </p>
      {!isEnterprise && (
        <button className="mt-4 flex h-9 w-full items-center justify-between rounded-md border bg-background px-3 text-sm">
          100 créditos mensuales
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </button>
      )}
      <UIButton
        variant={isPro ? "default" : "outline"}
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
    "Lovable para estudiantes",
    "Verifica tu condición de estudiante y obtén hasta un 50 % de descuento en Lovable Pro.",
    "Empezar",
  ],
  [
    "Lovable para campus",
    "Controles de facturación y administración para universidades y centros de educación superior.",
    "Contactar con ventas",
  ],
  [
    "Lovable para niños",
    "Acceso conforme a la normativa y plan de estudios para colegios, en colaboración con imagi.",
    "Más información",
  ],
];
function BillingSettings() {
  const [billing, setBilling] = useState("monthly");
  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Planes y uso de créditos
          </h1>
          <p className="mt-1 text-muted-foreground">
            Manage your subscription plan and credit balance.
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
              <span className="font-semibold">Lovable Free</span>
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
          <svg viewBox="0 0 320 60" className="mt-4 h-14 w-full text-muted-foreground/50">
            <path
              d="M0 45 L 210 45 L 240 12 L 265 45 L 320 45"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Jun 20</span>
            <span>Jul 19</span>
          </div>
          <div className="mt-4 flex items-center justify-between border-t pt-4 text-sm">
            <span className="text-muted-foreground">Last 30 days</span>
            <span className="font-medium">2.40 credits</span>
          </div>
          <div className="mt-2 flex items-center justify-between text-sm">
            <span>Telemetry Landing Pages</span>
            <span className="text-muted-foreground">2.40 credits</span>
          </div>
          <UIButton variant="outline" className="mt-4">
            More usage details
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
          <BillingPlanCard key={p.name} p={p} />
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

const peopleTabs = ["All", "Invitations", "Collaborators", "Requests"];
function PeopleSettings() {
  const [tab, setTab] = useState("All");
  return (
    <div className="mx-auto max-w-6xl px-8 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">People</h1>
          <p className="mt-1 max-w-2xl text-muted-foreground">
            Inviting people to <b className="text-foreground">Héctor's Lovable</b>{" "}
            gives access to workspace shared projects and credits. You have 1
            builder in this workspace.
          </p>
        </div>
        <UIButton variant="ghost" className="shrink-0 text-muted-foreground">
          Abrir docs <ExternalLink />
        </UIButton>
      </div>

      <div className="mt-6 inline-flex rounded-full border bg-muted p-1 text-sm">
        {peopleTabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "rounded-full px-4 py-1.5 transition-colors",
              tab === t
                ? "bg-background shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 md:max-w-xs">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <input
            placeholder="Search..."
            className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <button className="flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm">
          All roles <ChevronDown className="size-3.5 text-muted-foreground" />
        </button>
        <div className="ml-auto flex items-center gap-2">
          <UIButton variant="outline" size="icon">
            <Grid2X2 />
          </UIButton>
          <UIButton variant="outline">
            <Download /> Export
          </UIButton>
          <UIButton variant="outline">
            <Link /> Invite link
          </UIButton>
          <UIButton>
            <UserPlus /> Invite members
          </UIButton>
        </div>
      </div>

      {tab === "All" ? (
        <Card className="mt-4 overflow-hidden p-0">
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr_auto] items-center gap-4 border-b px-5 py-3 text-xs font-medium text-muted-foreground">
            {[
              "Name",
              "Role",
              "Joined/Invited",
              "July usage",
              "Total usage",
              "Credit limit",
            ].map((h) => (
              <span key={h} className="flex items-center gap-1">
                {h}
                <ChevronsUpDown className="size-3" />
              </span>
            ))}
            <span />
          </div>
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr_auto] items-center gap-4 px-5 py-4 text-sm">
            <div className="flex items-center gap-3">
              <span className="flex size-9 items-center justify-center rounded-full bg-green-600 text-xs font-semibold text-white">
                H
              </span>
              <div className="min-w-0">
                <p className="truncate font-medium">
                  Héctor Vidal Sánchez (you)
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  hectorvidal0411@gmail.com
                </p>
              </div>
            </div>
            <button className="flex items-center gap-1 text-muted-foreground">
              Owner <ChevronDown className="size-3.5" />
            </button>
            <span className="text-muted-foreground">Jul 24, 2025</span>
            <span className="text-muted-foreground">2 credits</span>
            <span className="text-muted-foreground">10 credits</span>
            <span />
            <button className="text-muted-foreground hover:text-foreground">
              <MoreHorizontal className="size-4" />
            </button>
          </div>
        </Card>
      ) : (
        <div className="mt-4 flex flex-col items-center justify-center gap-3 py-24 text-center">
          <img
            src="/lovable-logo.svg"
            alt=""
            className="size-10 opacity-30 grayscale"
          />
          <p className="text-muted-foreground">No {tab.toLowerCase()} found</p>
          <UIButton variant="outline">
            <UserPlus /> Invite members
          </UIButton>
        </div>
      )}

      <p className="mt-4 text-xs text-muted-foreground">
        {tab === "All" ? "Showing 1-1 of 1" : "No results"}
      </p>
    </div>
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
    'Trigger a skill with "/" or let Lovable activate it automatically when it matches your task.',
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
            <h2 className="text-lg font-semibold">Teach Lovable how you work</h2>
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
        <h2 className="text-lg font-semibold">Skills built by Lovable</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Maintained by Lovable and ready to use when your team needs proven
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
        Lovable are committed to the repo, and pushed commits flow back into the
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
              <img
                src={`https://cdn.simpleicons.org/${slug}`}
                alt=""
                className="size-5"
              />
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
      <h1 className="text-2xl font-bold tracking-tight">Lovable MCP server</h1>
      <p className="mt-1 text-muted-foreground">
        Connect supported AI clients and developer tools to Lovable.
      </p>

      <div className="mt-6 flex items-start gap-3 rounded-lg border bg-muted/40 p-4">
        <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="flex-1">
          <p className="text-sm font-medium">
            What is Model Context Protocol (MCP)?
          </p>
          <p className="mt-0.5 text-sm text-muted-foreground">
            The Lovable MCP server allows AI agents, such as Claude, Codex, and
            Cursor, to connect to Lovable and build, manage and deploy apps.
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
          Use this URL when adding Lovable as an MCP server in a supported
          client.
        </p>
        <div className="mt-3 flex items-center justify-between gap-2 rounded-md border px-3 py-2 font-mono text-sm">
          <span>https://mcp.lovable.dev/?src=settings</span>
          <Copy className="size-4 shrink-0 cursor-pointer text-muted-foreground hover:text-foreground" />
        </div>
        <Separator className="my-5" />
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Workspace access</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Connected clients use the signed-in user's Lovable access. Tool
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
                Add Lovable through Claude's connector settings. Works in Claude
                Desktop and on claude.ai.
              </p>
              <ol className="mt-4 space-y-3">
                {[
                  "In Claude, click the plus sign in the composer.",
                  "Open Connectors, browse connectors, then search for Lovable.",
                  "Click Connect, then sign in to Lovable when Claude prompts you.",
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
                The Lovable tools appear in the composer's tool menu once
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
      "url": "https://mcp.lovable.dev/?src=settings"
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
                {`claude mcp add --transport http lovable "https://mcp.lovable.dev/?src=settings"`}
              </CodeBlock>
              <p className="mt-3 text-muted-foreground">
                Claude Code opens a browser window for OAuth. Sign in to Lovable
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
      "url": "https://mcp.lovable.dev/?src=settings"
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
      "url": "https://mcp.lovable.dev/?src=settings"
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
      { t: "Perfiles públicos de miembros", tier: "Enterprise", d: "Los espacios de trabajo empresariales ocultan los perfiles de los miembros de forma predeterminada. Activa esta opción para que los perfiles públicos de Lovable de los miembros (lovable.dev/@username) sean visibles fuera del espacio de trabajo.", on: false },
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
      { t: "Métodos de inicio de sesión de la app", tier: "Business", d: "Controla qué métodos de inicio de sesión pueden usar los proyectos de este espacio de trabajo para las apps generadas. Esto no afecta la forma en que los miembros del espacio de trabajo inician sesión en Lovable.", control: "button", value: "Configurar" },
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
    desc: "Controla los servidores MCP que Lovable puede usar desde el chat.",
    rows: [
      { t: "Conectores MCP remotos", tier: "Business", d: "Permite que los miembros del espacio de trabajo conecten servidores MCP que Lovable puede invocar desde el chat. Al desactivarlo se eliminan las conexiones MCP existentes.", on: true },
      { t: "Servidores MCP locales de escritorio", tier: "Business", d: "Permite que los miembros del espacio de trabajo usen servidores MCP de sesiones conectadas de Lovable Desktop. Requiere que los conectores MCP remotos permanezcan habilitados.", on: true },
    ],
  },
  {
    title: "Protección de datos",
    desc: "Controla cómo se recopilan y exponen los datos de este espacio de trabajo.",
    rows: [
      { t: "Exclusión de la recopilación de datos", tier: "Business", d: "Excluye este espacio de trabajo de la recopilación de datos.", on: false },
      { t: "Análisis de datos confidenciales", tier: "Enterprise", d: "Activa la detección de PII para este espacio de trabajo. Incluye análisis bajo demanda del historial de chat, Lovable Cloud Database y Lovable Cloud Storage, y activa la protección de envío en el chat para mensajes nuevos y archivos adjuntos.", on: false },
      { t: "Bloquear buckets de almacenamiento públicos", d: "Impide que los usuarios creen buckets de almacenamiento de acceso público en Lovable Cloud.", on: true },
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
  return (
    <div className="min-h-screen bg-background">
      <SettingsSide page={page} />
      <main className="ml-[264px]">
        {page === "account" ? (
          <AccountSettings />
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
  React.useEffect(() => {
    const f = () => rerender((x) => x + 1);
    addEventListener("popstate", f);
    return () => removeEventListener("popstate", f);
  }, []);
  const p = location.pathname;
  const params = new URLSearchParams(location.search);
  const showConnectors = params.has("connectors");
  const showSearch = params.has("search");

  let page;
  if (p === "/es/pricing") page = <Pricing />;
  else if (p === "/es" || p === "/") page = <Landing />;
  else if (p === "/dashboard/resources") page = <Dashboard kind="resources" />;
  else if (p === "/dashboard") page = <Dashboard kind="home" />;
  else if (p === PROJECT) page = <Editor />;
  else if (p.startsWith(PROJECT + "/settings/"))
    page = <SettingsPage page={p.split("/").pop()} />;
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
createRoot(document.getElementById("root")).render(<App />);
