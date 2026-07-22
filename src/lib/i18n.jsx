import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Check, Languages } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const LANGUAGE_KEY = "xframe.language";
const LANGUAGES = [
  { code: "es", label: "Español", short: "ES" },
  { code: "en", label: "English", short: "EN" },
];

const EXACT_EN = new Map(
  Object.entries({
    "Soluciones": "Solutions",
    "Recursos": "Resources",
    "Comunidad": "Community",
    "Precios": "Pricing",
    "Seguridad": "Security",
    "Iniciar sesión": "Sign in",
    "Empezar": "Get started",
    "Volver": "Back",
    "Buscar": "Search",
    "Buscar ajustes": "Search settings",
    "Cuenta": "Account",
    "Dispositivos y apps": "Devices and apps",
    "Espacio de trabajo": "Workspace",
    "Planes y uso de créditos": "Plans and credit usage",
    "Personas": "People",
    "Grupos": "Groups",
    "Conocimiento": "Knowledge",
    "Habilidades": "Skills",
    "Plantillas": "Templates",
    "Sistemas de diseño": "Design systems",
    "Conectores": "Connectors",
    "Git": "Git",
    "Servidor MCP": "MCP server",
    "Dominios del espacio de trabajo": "Workspace domains",
    "Privacidad y seguridad": "Privacy and security",
    "Centro de seguridad": "Security center",
    "Registros de auditoría": "Audit logs",
    "Dashboard": "Dashboard",
    "Proyectos": "Projects",
    "Todos los proyectos": "All projects",
    "Volver al dashboard": "Back to dashboard",
    "Nuevo proyecto": "New project",
    "Crear proyecto": "Create project",
    "Crear": "Create",
    "Guardar": "Save",
    "Cancelar": "Cancel",
    "Eliminar": "Delete",
    "Revocar": "Revoke",
    "Enviar": "Send",
    "Copiar": "Copy",
    "Copiado": "Copied",
    "Cerrar sesión": "Sign out",
    "Abrir docs": "Open docs",
    "Documentación": "Documentation",
    "Gestionar": "Manage",
    "Uso": "Usage",
    "Últimos 30 días": "Last 30 days",
    "Últimos 90 días": "Last 90 days",
    "Últimos 7 días": "Last 7 days",
    "Todos": "All",
    "Mensual": "Monthly",
    "Anual": "Annual",
    "Mejorar plan": "Upgrade plan",
    "Reservar una demo": "Book a demo",
    "Más información": "Learn more",
    "Más detalles de uso": "More usage details",
    "Créditos disponibles": "Available credits",
    "¿Necesitas más créditos?": "Need more credits?",
    "Todavía no has gastado créditos": "You have not spent credits yet",
    "Todavía no hay tokens MCP.": "There are no MCP tokens yet.",
    "Servidor": "Server",
    "Operativo": "Operational",
    "Sin conexión": "Disconnected",
    "Comprobando": "Checking",
    "Crear token": "Create token",
    "Conecta tu cliente": "Connect your client",
    "Lectura": "Read",
    "Lectura y edición": "Read and edit",
    "Lectura, edición y generación": "Read, edit, and generate",
    "Acceso completo y generaciones": "Full access and generations",
    "Solo lectura": "Read only",
    "Permitir acceso": "Allow access",
    "Conectar aplicación": "Connect application",
    "Datos usados para iniciar sesión": "Data used to sign in",
    "Acceso de este cliente": "Client access",
    "Proyectos autorizados": "Authorized projects",
    "Aplicación": "Application",
    "Identificador de tu cuenta": "Your account identifier",
    "Nombre y datos básicos del perfil": "Name and basic profile data",
    "Correo electrónico": "Email address",
    "Capacidades de Xframe": "Xframe capabilities",
    "Generar": "Generate",
    "Assets": "Assets",
    "Brief": "Brief",
    "Canvas": "Canvas",
    "Chat": "Chat",
    "Equipo": "Team",
    "Compartir": "Share",
    "Vista previa": "Preview",
    "Modelo": "Model",
    "Modo": "Mode",
    "Vídeo": "Video",
    "Imagen": "Image",
    "Duración": "Duration",
    "Resolución": "Resolution",
    "Aspecto": "Aspect",
    "Sonido": "Sound",
    "Género": "Genre",
    "Estilo": "Style",
    "Cámara": "Camera",
    "Lente": "Lens",
    "Iluminación": "Lighting",
    "Movimiento de cámara": "Camera movement",
    "Paleta de color": "Color palette",
    "Arrastra para redimensionar": "Drag to resize",
    "Cargando…": "Loading...",
    "Guardando": "Saving",
    "Cambios guardados": "Changes saved",
    "No hay coincidencias": "No matches",
    "Sin preview": "No preview",
    "Usar": "Use",
    "Asignar": "Assign",
    "Estado": "Status",
    "Idioma": "Language",
    "Nueva escena": "New scene",
    "Nueva voz": "New voice",
    "Diálogo": "Dialogue",
    "Voz en off": "Voiceover",
    "Acción": "Action",
    "Rótulo": "Caption",
    "Música": "Music",
    "Efectos": "Effects",
    "Ambiente": "Ambience",
    "Audio nativo": "Native audio",
    "Referencia visual": "Visual reference",
    "Fuente obligatoria": "Required source",
    "Personaje": "Character",
    "Producto": "Product",
    "Fondo / localización": "Background / location",
    "Primer fotograma": "First frame",
    "Último fotograma": "Last frame",
    "Diseño de audio": "Audio design",
    "Biblioteca": "Library",
    "Voces": "Voices",
    "Timeline de mezcla": "Mix timeline",
    "Mezcla reproducible": "Reproducible mix",
    "Diseñar con el agente": "Design with the agent",
    "Dirección de audio": "Audio direction",
    "Brief sonoro": "Sound brief",
    "Llevar al chat": "Send to chat",
    "Diseñar plan": "Design plan",
    "Guardar en Voces": "Save to Voices",
    "Guardar en Plantillas": "Save to Templates",
    "Editar o variar": "Edit or vary",
    "Biblioteca vacía": "Empty library",
    "Guion": "Screenplay",
    "Escenas": "Scenes",
    "Plano": "Shot",
    "Planos": "Shots",
    "Fuente": "Source",
    "Hasta": "To",
    "Desde": "From",
    "Función en la generación": "Role in generation",
    "Instrucción precisa": "Precise instruction",
    "Referencia obligatoria": "Required reference",
    "Usuario": "User",
    "Correo": "Email",
    "Nombre": "Name",
    "Rol": "Role",
    "Alta": "Joined",
    "Límite de créditos": "Credit limit",
    "Sin límite": "No limit",
    "Enlace de invitación": "Invitation link",
    "Invitación enviada": "Invitation sent",
    "Invitación revocada": "Invitation revoked",
    "Página web": "Website",
    "Página releída": "Page reread",
    "Volver a leer": "Read again",
    "Añadir una página web": "Add a website",
    "Añadir una nota": "Add a note",
    "Leer página": "Read page",
    "Añadir": "Add",
    "Nota añadida": "Note added",
    "De fábrica": "Built in",
    "Proyecto seleccionado": "Selected project",
    "Sin definir": "Not set",
    "Permitir todos": "Allow all",
    "Editores y superiores": "Editors and above",
    "Crea algo con Xframe": "Create something with Xframe",
    "Crea vídeos y películas conversando con la IA": "Create videos and films by chatting with AI",
    "Equipos de empresas líderes crean con Xframe": "Teams at leading companies create with Xframe",
    "Empieza con una idea": "Start with an idea",
    "Velo cobrar vida": "Watch it come to life",
    "Perfecciona y publica": "Refine and publish",
    "Descubre": "Discover",
    "Ver todo": "View all",
    "Tráiler cinematográfico": "Cinematic trailer",
    "Videoclip musical": "Music video",
    "Spot de producto": "Product spot",
    "Moda editorial": "Editorial fashion",
    "Documental": "Documentary",
    "Anuncio vertical": "Vertical ad",
    "Noir cinematográfico": "Cinematic noir",
    "Time-lapse aéreo": "Aerial time-lapse",
    "Millones de creadores ya están convirtiendo sus ideas en realidad": "Millions of creators are already turning their ideas into reality",
    "¿Listo para crear?": "Ready to create?",
    "Diseñadores": "Designers",
    "Creación de prototipos": "Prototyping",
    "Guías": "Guides",
    "Reseñas": "Reviews",
    "Política de privacidad": "Privacy policy",
    "Configuración de cookies": "Cookie settings",
    "Términos para empresas": "Terms for companies",
    "Términos generales": "General terms",
    "Conviértete en socio": "Become a partner",
    "Código de conducta": "Code of conduct",
    "Descuento para estudiantes": "Student discount",
    "Fundadores": "Founders",
    "Gerentes de producto": "Product managers",
    "Especialistas en marketing": "Marketing specialists",
    "Operaciones": "Operations",
    "Recursos humanos": "Human resources",
    "Herramientas internas": "Internal tools",
    "Descargar aplicaciones": "Download apps",
    "Conexiones": "Connections",
    "Registro de cambios": "Changelog",
    "Aprender": "Learn",
    "Soporte": "Support",
    "Mapa del sitio": "Sitemap",
    "No vender ni compartir mi información personal": "Do not sell or share my personal information",
    "Reglas de la plataforma": "Platform rules",
    "Denunciar abuso": "Report abuse",
    "Reportar problemas de seguridad": "Report security issues",
    "Acuerdo de tratamiento de datos": "Data processing agreement",
    "Contrata a un experto de Xframe": "Hire an Xframe expert",
    "Afiliados": "Affiliates",
    "La solicitud OAuth no es válida.": "The OAuth request is not valid.",
    "No se ha podido cargar la solicitud OAuth.": "The OAuth request could not be loaded.",
    "No se ha podido guardar la autorización.": "The authorization could not be saved.",
    "No se ha podido conectar con el servidor MCP. Comprueba que el backend está en marcha.": "Could not connect to the MCP server. Check that the backend is running.",
  }),
);

const PHRASE_EN = [
  ["Gestiona tu plan y el saldo de créditos.", "Manage your plan and credit balance."],
  ["Uso incluido en tu plan", "Usage included in your plan"],
  ["Cada generación descuenta créditos según el modelo y la duración.", "Each generation uses credits based on the model and duration."],
  ["Mejora tu plan para tener más créditos cada mes.", "Upgrade your plan to get more credits every month."],
  ["Aún no hay consumo en este periodo.", "There is no usage in this period yet."],
  ["Genera material y aquí verás el consumo día a día.", "Generate material and you will see daily usage here."],
  ["Ningún proyecto ha consumido créditos en este periodo.", "No project has used credits in this period."],
  ["Conecta agentes a tus proyectos, assets, contexto creativo y generación.", "Connect agents to your projects, assets, creative context, and generation."],
  ["Es una conexión estándar para que Claude Code, Codex, Cursor u otros agentes trabajen con las herramientas de Xframe.", "It is a standard connection that lets Claude Code, Codex, Cursor, and other agents work with Xframe tools."],
  ["Elige tu cliente y pega el token creado arriba en su configuración. Nunca lo incluyas en un repositorio.", "Choose your client and paste the token created above into its configuration. Never commit it to a repository."],
  ["Las herramientas aparecerán cuando el cliente complete initialize.", "The tools will appear once the client completes initialize."],
  ["Reinicia Claude Code tras exportar XFRAME_MCP_TOKEN. La credencial se puede revocar arriba.", "Restart Claude Code after exporting XFRAME_MCP_TOKEN. You can revoke the credential above."],
  ["Revisa lo que podrá consultar antes de aprobar.", "Review what it can access before approving."],
  ["Todo lo anterior, incluida la ejecución del agente y las generaciones.", "Everything above, including agent execution and generations."],
  ["Sin selección equivale a todos los proyectos a los que tienes acceso.", "No selection means every project you can access."],
  ["Estos datos solo verifican tu identidad. El acceso real a proyectos y herramientas lo eliges abajo.", "This data only verifies your identity. You choose the real project and tool access below."],
  ["Gestiona la configuración de privacidad y seguridad de tu espacio de trabajo.", "Manage privacy and security settings for your workspace."],
  ["Quién puede unirse al espacio de trabajo y mover proyectos.", "Who can join the workspace and move projects."],
  ["Controla cómo se publican e implementan los proyectos en la web.", "Control how projects are published and deployed to the web."],
  ["Controla cómo los miembros comparten los archivos del proyecto y los enlaces de vista previa.", "Control how members share project files and preview links."],
  ["Controla los servidores MCP que Xframe puede usar desde el chat.", "Control the MCP servers Xframe can use from chat."],
  ["Controla cómo se recopilan y exponen los datos de este espacio de trabajo.", "Control how this workspace collects and exposes data."],
  ["Indica qué modelos, resoluciones o formatos prefieres por defecto.", "Set the models, resolutions, and formats you prefer by default."],
  ["Añade reglas que el agente deba respetar siempre: idioma, ritmo, cosas que evitar.", "Add rules the agent should always follow: language, pacing, and things to avoid."],
  ["Documentos y páginas de los que el agente puede tirar.", "Documents and pages the agent can use."],
  ["Añade la web de tu marca, un documento de estilo o una nota suelta y el agente los tendrá en cuenta al generar.", "Add your brand website, a style document, or a note and the agent will use them during generation."],
  ["Xframe leerá la página y guardará su texto como contexto.", "Xframe will read the page and save its text as context."],
  ["Un apunte que el agente tendrá siempre a mano.", "A note the agent can always keep at hand."],
  ["El agente la aplicará cuando el contexto encaje con sus disparadores.", "The agent will apply it when the context matches its triggers."],
  ["Frases que activan la habilidad. Déjalo vacío para que decida el agente.", "Phrases that trigger the skill. Leave empty to let the agent decide."],
  ["Biblioteca, voces y mezcla multipista determinista.", "Library, voices, and deterministic multitrack mixing."],
  ["Selecciona un clip para ajustar sus parámetros exactos.", "Select a clip to tune its exact parameters."],
  ["Los tiempos, fades, ganancias, paneo y ducking se guardan como parámetros exactos para FFmpeg.", "Timing, fades, gain, pan, and ducking are saved as exact FFmpeg parameters."],
  ["Describe el arco musical, silencios, intensidad y referencias.", "Describe the musical arc, silences, intensity, and references."],
  ["Puedes pedir una o varias piezas según el contexto de cada escena.", "You can request one or several pieces based on each scene's context."],
  ["Genera o sube voces, música y efectos desde Assets. Cuando estén listos aparecerán aquí.", "Generate or upload voices, music, and effects from Assets. They will appear here when ready."],
  ["Sin referencias: el agente decidirá la imagen únicamente desde el texto.", "No references: the agent will decide the image only from the text."],
  ["El agente los tratará como contexto explícito de esta escena.", "The agent will treat them as explicit context for this scene."],
  ["El agente los tratará como contexto explícito de esta línea.", "The agent will treat them as explicit context for this line."],
  ["Elige una imagen o vídeo ya aprobado. Después podrás indicar su función exacta y el tramo donde debe utilizarse.", "Choose an approved image or video. Then you can define its exact role and where it should be used."],
  ["Genera o sube el asset en la sección Assets y después asígnalo aquí.", "Generate or upload the asset in Assets, then assign it here."],
  ["Impide sustituciones silenciosas", "Prevents silent substitutions"],
  ["Nadie coincide con la búsqueda.", "No one matches the search."],
  ["Todavía no hay colaboradores", "There are no collaborators yet"],
  ["Cuando alguien pida entrar en el espacio, lo verás aquí.", "When someone asks to join the workspace, you will see it here."],
  ["Separa varios correos con comas. Recibirán un enlace para unirse.", "Separate multiple emails with commas. They will receive a link to join."],
  ["Describe la escena o el vídeo que quieres rodar, o adjunta guiones e imágenes de referencia.", "Describe the scene or video you want to shoot, or attach scripts and reference images."],
  ["Mira cómo tu visión se transforma en planos de vídeo en tiempo real.", "Watch your vision become video shots in real time."],
  ["Ajusta la dirección con comentarios sencillos y exporta tu vídeo con un solo clic.", "Adjust direction with simple comments and export your video in one click."],
  ["Empieza tu próximo proyecto con una plantilla", "Start your next project with a template"],
  ["Ritmo alto, cortes secos y música épica", "High pace, hard cuts, and epic music"],
  ["Planos sincronizados al beat con color intenso", "Shots synced to the beat with intense color"],
  ["Producto en primer plano con luz de estudio", "Close-up product shots with studio lighting"],
  ["Cámara lenta, texturas y luz natural", "Slow motion, textures, and natural light"],
  ["Tono sobrio, planos largos y voz en off", "Restrained tone, long shots, and voiceover"],
  ["Formato 9:16 para redes, impacto en los primeros segundos", "9:16 social format, impact in the first seconds"],
  ["Alto contraste, sombras duras y ambiente nocturno", "High contrast, hard shadows, and night mood"],
  ["Planos de dron y paisajes en movimiento", "Drone shots and moving landscapes"],
  ["vídeos generados en Xframe", "videos generated in Xframe"],
  ["planos nuevos generados cada semana", "new shots generated every week"],
  ["reproducciones al mes de vídeos creados con Xframe", "monthly views of videos created with Xframe"],
  ["reproducciones al mes de videos creados con Xframe", "monthly views of videos created with Xframe"],
];

const WORD_EN = [
  ["créditos mensuales", "monthly credits"],
  ["créditos", "credits"],
  ["crédito", "credit"],
  ["proyectos", "projects"],
  ["proyecto", "project"],
  ["ajustes", "settings"],
  ["espacio de trabajo", "workspace"],
  ["espacio", "space"],
  ["cuenta", "account"],
  ["personas", "people"],
  ["persona", "person"],
  ["miembros", "members"],
  ["miembro", "member"],
  ["invitación", "invitation"],
  ["invitaciones", "invitations"],
  ["búsqueda", "search"],
  ["buscar", "search"],
  ["guardar", "save"],
  ["guardado", "saved"],
  ["cancelar", "cancel"],
  ["eliminar", "delete"],
  ["crear", "create"],
  ["añadir", "add"],
  ["leer", "read"],
  ["generación", "generation"],
  ["generaciones", "generations"],
  ["generar", "generate"],
  ["editar", "edit"],
  ["edición", "editing"],
  ["lectura", "read"],
  ["acceso", "access"],
  ["seguridad", "security"],
  ["privacidad", "privacy"],
  ["servidor", "server"],
  ["conector", "connector"],
  ["conectores", "connectors"],
  ["herramientas", "tools"],
  ["herramienta", "tool"],
  ["contexto", "context"],
  ["assets", "assets"],
  ["planos", "shots"],
  ["plano", "shot"],
  ["escenas", "scenes"],
  ["escena", "scene"],
  ["guion", "screenplay"],
  ["audio", "audio"],
  ["sonido", "sound"],
  ["voz", "voice"],
  ["voces", "voices"],
  ["música", "music"],
  ["efectos", "effects"],
  ["biblioteca", "library"],
  ["plantillas", "templates"],
  ["cámara", "camera"],
  ["vídeo", "video"],
  ["imagen", "image"],
  ["página", "page"],
  ["páginas", "pages"],
  ["documentos", "documents"],
  ["nota", "note"],
  ["notas", "notes"],
  ["correo", "email"],
  ["nombre", "name"],
  ["rol", "role"],
  ["límite", "limit"],
  ["sin", "without"],
  ["con", "with"],
  ["todos", "all"],
  ["todas", "all"],
  ["últimos", "last"],
  ["días", "days"],
  ["día", "day"],
  ["mensual", "monthly"],
  ["anual", "annual"],
  ["disponibles", "available"],
  ["disponible", "available"],
  ["operativo", "operational"],
  ["comprobando", "checking"],
  ["cargando", "loading"],
  ["todavía", "yet"],
  ["vacía", "empty"],
  ["vacío", "empty"],
  ["nuevo", "new"],
  ["nueva", "new"],
  ["aprobados", "approved"],
  ["aprobado", "approved"],
  ["pendiente", "pending"],
  ["pendientes", "pending"],
  ["público", "public"],
  ["públicos", "public"],
  ["privado", "private"],
  ["localización", "location"],
  ["fondo", "background"],
  ["personaje", "character"],
  ["producto", "product"],
  ["referencia", "reference"],
  ["obligatoria", "required"],
  ["fuente", "source"],
  ["usar", "use"],
  ["asignar", "assign"],
  ["desde", "from"],
  ["hasta", "to"],
  ["estado", "status"],
  ["configurar", "configure"],
  ["mejorar", "upgrade"],
  ["demo", "demo"],
  ["más", "more"],
  ["información", "information"],
  ["detalles", "details"],
  ["crea", "create"],
  ["crear", "create"],
  ["algo", "something"],
  ["vídeos", "videos"],
  ["video", "video"],
  ["películas", "films"],
  ["conversando", "chatting"],
  ["ia", "AI"],
  ["empresas", "companies"],
  ["líderes", "leading"],
  ["idea", "idea"],
  ["describe", "describe"],
  ["rodar", "shoot"],
  ["adjunta", "attach"],
  ["guiones", "scripts"],
  ["imágenes", "images"],
  ["mira", "watch"],
  ["cómo", "how"],
  ["visión", "vision"],
  ["transforma", "becomes"],
  ["tiempo real", "real time"],
  ["ajusta", "adjust"],
  ["dirección", "direction"],
  ["comentarios", "comments"],
  ["sencillos", "simple"],
  ["exporta", "export"],
  ["clic", "click"],
  ["descubre", "discover"],
  ["próximo", "next"],
  ["plantilla", "template"],
  ["tráiler", "trailer"],
  ["cinematográfico", "cinematic"],
  ["musical", "music"],
  ["ritmo", "pace"],
  ["alto", "high"],
  ["cortes", "cuts"],
  ["secos", "hard"],
  ["épica", "epic"],
  ["sincronizados", "synced"],
  ["color", "color"],
  ["intenso", "intense"],
  ["primer", "first"],
  ["luz", "light"],
  ["estudio", "studio"],
  ["lenta", "slow"],
  ["natural", "natural"],
  ["sobrio", "restrained"],
  ["largos", "long"],
  ["redes", "social"],
  ["impacto", "impact"],
  ["primeros", "first"],
  ["segundos", "seconds"],
  ["contraste", "contrast"],
  ["sombras", "shadows"],
  ["duras", "hard"],
  ["nocturno", "night"],
  ["dron", "drone"],
  ["paisajes", "landscapes"],
  ["movimiento", "movement"],
  ["vida", "life"],
  ["perfecciona", "refine"],
  ["publica", "publish"],
  ["creadores", "creators"],
  ["están", "are"],
  ["convirtiendo", "turning"],
  ["realidad", "reality"],
  ["listo", "ready"],
  ["diseñadores", "designers"],
  ["prototipos", "prototypes"],
  ["guías", "guides"],
  ["reseñas", "reviews"],
  ["política", "policy"],
  ["configuración", "settings"],
  ["cookies", "cookies"],
  ["términos", "terms"],
  ["generales", "general"],
  ["conviértete", "become"],
  ["socio", "partner"],
  ["código", "code"],
  ["conducta", "conduct"],
  ["generados", "generated"],
  ["generado", "generated"],
  ["nuevos", "new"],
  ["semana", "week"],
  ["reproducciones", "views"],
  ["creados", "created"],
  ["creado", "created"],
  ["estudiantes", "students"],
  ["fundadores", "founders"],
  ["gerentes", "managers"],
  ["especialistas", "specialists"],
  ["operaciones", "operations"],
  ["humanos", "human"],
  ["internas", "internal"],
  ["descargar", "download"],
  ["aplicaciones", "apps"],
  ["conexiones", "connections"],
  ["registro", "log"],
  ["cambios", "changes"],
  ["aprender", "learn"],
  ["soporte", "support"],
  ["mapa del sitio", "sitemap"],
  ["vender", "sell"],
  ["compartir", "share"],
  ["personal", "personal"],
  ["reglas", "rules"],
  ["plataforma", "platform"],
  ["denunciar", "report"],
  ["abuso", "abuse"],
  ["reportar", "report"],
  ["problemas", "issues"],
  ["acuerdo", "agreement"],
  ["tratamiento", "processing"],
  ["datos", "data"],
  ["contrata", "hire"],
  ["experto", "expert"],
  ["afiliados", "affiliates"],
];

const TRANSLATABLE_ATTRS = ["placeholder", "title", "aria-label", "alt"];
const originalText = new WeakMap();
const originalAttrs = new WeakMap();

const I18nContext = createContext({
  language: "es",
  setLanguage: () => {},
  t: (value) => value,
});

function clean(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function preserveCase(source, translated) {
  if (!source) return translated;
  if (source === source.toUpperCase()) return translated.toUpperCase();
  if (source[0] === source[0].toUpperCase()) {
    return translated.charAt(0).toUpperCase() + translated.slice(1);
  }
  return translated;
}

function translateDynamic(value) {
  return value
    .replace(/\b(\d+)\s+créditos?\b/gi, "$1 credits")
    .replace(/\b(\d+)\s+días?\b/gi, "$1 days")
    .replace(/\b(\d+)\s+aprobados?\b/gi, "$1 approved")
    .replace(/\b(\d+)\s+clips?\b/gi, "$1 clips")
    .replace(/\bal mes IVA incl\./gi, "per month VAT incl.")
    .replace(/\ben los (\d+) últimos días\b/gi, "in the last $1 days")
    .replace(/\bde (\d+)\b/gi, "of $1")
    .replace(/¿Necesitas más créditos\?/g, "Need more credits?");
}

export function translateToEnglish(value) {
  if (value == null || value === "") return value;
  const original = String(value);
  const trimmed = clean(original);
  if (!trimmed) return original;

  const exact = EXACT_EN.get(trimmed);
  if (exact) return original.replace(trimmed, exact);

  let next = translateDynamic(original);
  for (const [source, target] of PHRASE_EN) {
    next = next.replaceAll(source, target);
  }
  for (const [source, target] of WORD_EN) {
    const re = new RegExp(`\\b${escapeRegExp(source)}\\b`, "gi");
    next = next.replace(re, (match) => preserveCase(match, target));
  }
  return next;
}

function translateValue(value, language) {
  return language === "en" ? translateToEnglish(value) : value;
}

function shouldSkip(element) {
  if (!element) return true;
  return Boolean(
    element.closest(
      "[data-i18n-skip], code, pre, textarea, [contenteditable='true']",
    ),
  );
}

function applyTranslations(root, language) {
  if (!root || typeof document === "undefined") return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  for (const node of textNodes) {
    const parent = node.parentElement;
    if (!parent || shouldSkip(parent) || !clean(node.nodeValue)) continue;
    if (!originalText.has(node)) originalText.set(node, node.nodeValue);
    const base = originalText.get(node);
    const next = translateValue(base, language);
    if (node.nodeValue !== next) node.nodeValue = next;
  }

  const elements =
    root.nodeType === Node.ELEMENT_NODE
      ? [root, ...root.querySelectorAll("*")]
      : [...root.querySelectorAll("*")];
  for (const element of elements) {
    if (shouldSkip(element)) continue;
    for (const attr of TRANSLATABLE_ATTRS) {
      if (!element.hasAttribute(attr)) continue;
      let attrs = originalAttrs.get(element);
      if (!attrs) {
        attrs = {};
        originalAttrs.set(element, attrs);
      }
      if (!(attr in attrs)) attrs[attr] = element.getAttribute(attr);
      const next = translateValue(attrs[attr], language);
      if (element.getAttribute(attr) !== next) element.setAttribute(attr, next);
    }
  }
}

export function I18nProvider({ children }) {
  const [language, setLanguageState] = useState(() => {
    try {
      return localStorage.getItem(LANGUAGE_KEY) || "es";
    } catch {
      return "es";
    }
  });

  const setLanguage = (next) => {
    const safe = next === "en" ? "en" : "es";
    setLanguageState(safe);
    try {
      localStorage.setItem(LANGUAGE_KEY, safe);
    } catch {
      // The language preference is non-critical.
    }
  };

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dataset.language = language;
    applyTranslations(document.body, language);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          const node = mutation.target;
          originalText.set(node, node.nodeValue);
          applyTranslations(node.parentElement, language);
          continue;
        }
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.TEXT_NODE) {
            applyTranslations(node.parentElement, language);
          } else if (node.nodeType === Node.ELEMENT_NODE) {
            applyTranslations(node, language);
          }
        }
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => observer.disconnect();
  }, [language]);

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      t: (text) => translateValue(text, language),
    }),
    [language],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}

export function LanguageDock({ className = "" }) {
  const { language, setLanguage } = useI18n();
  const current = LANGUAGES.find((item) => item.code === language) ?? LANGUAGES[0];

  return (
    <div
      className={cn(
        "fixed bottom-4 right-4 z-[80] print:hidden",
        className,
      )}
      data-i18n-skip
    >
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-2 bg-background/95 shadow-sm backdrop-blur"
            aria-label="Language"
          >
            <Languages className="size-4" />
            {current.short}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-36">
          {LANGUAGES.map((item) => (
            <DropdownMenuItem
              key={item.code}
              onSelect={() => setLanguage(item.code)}
              className="justify-between"
            >
              {item.label}
              {item.code === language && <Check className="size-4" />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
