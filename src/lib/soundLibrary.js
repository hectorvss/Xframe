/**
 * Catálogo integrado de la biblioteca de Audio: categorías de efectos, efectos de ejemplo
 * y un catálogo de voces. Son entradas para explorar y pedir al agente que las genere y
 * coloque en la mezcla — no traen audio real (eso lo produce el proveedor conectado).
 * Separado por categoría, al estilo de una librería de SFX/voces.
 */

export const SFX_CATEGORIES = [
  { id: "animales", name: "Animales", emoji: "🐾", from: "#fb923c", to: "#b91c1c" },
  { id: "armas", name: "Armas", emoji: "🔫", from: "#f59e0b", to: "#7c2d12" },
  { id: "ascensos", name: "Ascensos", emoji: "📈", from: "#f472b6", to: "#831843" },
  { id: "bajo", name: "Bajo", emoji: "🔊", from: "#334155", to: "#0f172a" },
  { id: "braams", name: "Braams", emoji: "🎬", from: "#fb7185", to: "#881337" },
  { id: "ciencia-ficcion", name: "Ciencia ficción", emoji: "🚀", from: "#818cf8", to: "#312e81" },
  { id: "clima", name: "Clima", emoji: "⛈️", from: "#60a5fa", to: "#1e3a8a" },
  { id: "cuerdas", name: "Cuerdas", emoji: "🎻", from: "#fbbf24", to: "#92400e" },
  { id: "deportes", name: "Deportes", emoji: "🏟️", from: "#38bdf8", to: "#0c4a6e" },
  { id: "dispositivos", name: "Dispositivos", emoji: "⚙️", from: "#94a3b8", to: "#1e293b" },
  { id: "drones", name: "Drones", emoji: "🛰️", from: "#a78bfa", to: "#4c1d95" },
  { id: "ui", name: "Elementos de UI", emoji: "🔘", from: "#2dd4bf", to: "#134e4a" },
  { id: "escuela", name: "Escuela", emoji: "🏫", from: "#60a5fa", to: "#1e3a8a" },
  { id: "explosiones", name: "Explosiones", emoji: "💥", from: "#fb923c", to: "#7c2d12" },
  { id: "magia", name: "Magia", emoji: "✨", from: "#c084fc", to: "#581c87" },
  { id: "humano", name: "Humano", emoji: "🫧", from: "#f472b6", to: "#831843" },
  { id: "naturaleza", name: "Naturaleza", emoji: "🌿", from: "#4ade80", to: "#14532d" },
  { id: "ambiente", name: "Ambiente", emoji: "🌆", from: "#22d3ee", to: "#0e7490" },
];

// track: a qué pista de la mezcla va por defecto cuando se añade (sfx | music | ambience).
export const SFX_LIBRARY = [
  { id: "sfx-hound", title: "SFX de anime para el ataque de rayo de un lobo corrupto: primeros 3 s de gruñido grave", category: "Magia", sub: "Malvado", duration: "8s", downloads: 405, track: "sfx" },
  { id: "sfx-breath", title: "Respiración controlada de una atleta parada antes de una prueba importante", category: "Humano", sub: "Aliento", duration: "10s", downloads: 609, track: "sfx" },
  { id: "sfx-arcade", title: "Sonido de recompensa estilo arcade, tipo premio de pachinko, con un remate de vídeo", category: "Interfaz", sub: "Alerta", duration: "2s", downloads: 105, track: "sfx" },
  { id: "sfx-star", title: "Pequeño impulso mágico de estrella: whoosh corto y brillante con campanillas de cristal", category: "Magia", sub: "Brillo", duration: "0.5s", downloads: 610, track: "sfx" },
  { id: "sfx-riser", title: "Riser tenso que crece hacia un impacto, ideal para transiciones de tráiler", category: "Ascensos", sub: "Tensión", duration: "4s", downloads: 512, track: "sfx" },
  { id: "sfx-braam", title: "Braam cinematográfico grave y potente para un momento de revelación", category: "Braams", sub: "Impacto", duration: "3s", downloads: 878, track: "sfx" },
  { id: "sfx-ui-click", title: "Clic de interfaz suave y confirmación tonal para una interacción de producto", category: "Elementos de UI", sub: "Clic", duration: "0.4s", downloads: 1204, track: "sfx" },
  { id: "sfx-rain", title: "Lluvia constante sobre asfalto con truenos lejanos, bucle imperceptible", category: "Clima", sub: "Lluvia", duration: "20s", downloads: 733, track: "ambience" },
  { id: "sfx-drone", title: "Zumbido de dron acercándose y alejándose, con paneo estéreo natural", category: "Drones", sub: "Vuelo", duration: "12s", downloads: 289, track: "sfx" },
  { id: "sfx-explosion", title: "Explosión seca y grave con cola de escombros, sin distorsión épica excesiva", category: "Explosiones", sub: "Detonación", duration: "3s", downloads: 640, track: "sfx" },
  { id: "sfx-forest", title: "Ambiente de bosque al amanecer con pájaros lejanos y brisa entre las hojas", category: "Naturaleza", sub: "Bosque", duration: "24s", downloads: 421, track: "ambience" },
  { id: "sfx-sword", title: "Desenvaine metálico de espada con resonancia limpia y ataque afilado", category: "Armas", sub: "Metal", duration: "1s", downloads: 356, track: "sfx" },
  { id: "sfx-room", title: "Room tone de estudio moderno y silencioso, ventilación muy distante, sin voces", category: "Ambiente", sub: "Room tone", duration: "30s", downloads: 198, track: "ambience" },
  { id: "sfx-whoosh", title: "Whoosh corto y aireado para una transición de interfaz: ataque suave, final sin resonancia", category: "Elementos de UI", sub: "Transición", duration: "0.6s", downloads: 902, track: "sfx" },
];

export const VOICE_CATALOG = [
  { id: "vc-viraj", name: "Viraj", tagline: "Rich, Confident and Expressive", description: "Narrador expresivo y natural para historias.", from: "#6366f1", to: "#a855f7", language: "Inglés", accent: "Indio", gender: "Masculina", age: "Adulta", category: "Narración" },
  { id: "vc-samantha", name: "Samantha", tagline: "Emotional, Soft and Intimate", description: "Voz calmada y cercana, ideal para relatos íntimos.", from: "#f472b6", to: "#a855f7", language: "Inglés", accent: "Americano", gender: "Femenina", age: "Adulta", category: "Narración" },
  { id: "vc-maya", name: "Maya", tagline: "Friendly and Cheerful", description: "Voz amistosa y alegre para contenido cotidiano.", from: "#fbbf24", to: "#f97316", language: "Inglés", accent: "Americano", gender: "Femenina", age: "Joven", category: "Social" },
  { id: "vc-max", name: "Max", tagline: "Elearning and Documentary", description: "Voz clara y didáctica para e-learning y documental.", from: "#34d399", to: "#0891b2", language: "Inglés", accent: "Británico", gender: "Masculina", age: "Adulta", category: "Educación" },
  { id: "vc-jerry", name: "Jerry B", tagline: "Realistic and Conversational", description: "Hiperrealista y conversacional para diálogos.", from: "#f59e0b", to: "#b45309", language: "Inglés", accent: "Americano", gender: "Masculina", age: "Adulta", category: "Conversación" },
  { id: "vc-siren", name: "Siren", tagline: "Natural, realistic conversational voice", description: "Perfecta para podcasts y vídeos.", from: "#22d3ee", to: "#0e7490", language: "Español", accent: "Neutro", gender: "Femenina", age: "Adulta", category: "Podcast" },
  { id: "vc-david", name: "David", tagline: "Deep, Mature, and Smooth", description: "Voz grave, madura y envolvente.", from: "#a78bfa", to: "#4c1d95", language: "Español", accent: "Castellano", gender: "Masculina", age: "Adulta", category: "Narración" },
  { id: "vc-brian", name: "Brian", tagline: "Warm, Smooth, Confident", description: "Narrador cálido y seguro, muy convincente.", from: "#60a5fa", to: "#1e3a8a", language: "Inglés", accent: "Americano", gender: "Masculina", age: "Adulta", category: "Narración" },
  { id: "vc-jessica", name: "Jessica Gallagher", tagline: "Clear and Neutral", description: "Calidad de estudio, clara y neutra.", from: "#f9a8d4", to: "#be185d", language: "Inglés", accent: "Americano", gender: "Femenina", age: "Adulta", category: "Corporativo" },
  { id: "vc-tyler", name: "Tyler", tagline: "Clear US YouTube Creator Voice", description: "Voz de creador de YouTube, clara y directa.", from: "#f97316", to: "#7c2d12", language: "Inglés", accent: "Americano", gender: "Masculina", age: "Joven", category: "Social" },
  { id: "vc-monika", name: "Monika Sogam", tagline: "Lively E-Com Support", description: "Energía contagiosa para soporte y e-commerce.", from: "#2dd4bf", to: "#0f766e", language: "Español", accent: "Latino", gender: "Femenina", age: "Joven", category: "Comercial" },
  { id: "vc-adam", name: "Adam", tagline: "Serious, Rich, and Smoky", description: "Voz seria y con cuerpo, tono cálido.", from: "#64748b", to: "#1e293b", language: "Español", accent: "Castellano", gender: "Masculina", age: "Adulta", category: "Narración" },
];
