/**
 * Construcción del XframeUIContext que viaja en cada turno.
 *
 * Contraparte exacta de `backend/app/context/types.py`. La decisión que hay que
 * respetar al tocar este fichero está escrita allí y es la misma que en PostHog:
 *
 *   > El contexto no es un puntero (id), es el objeto semiserializado.
 *
 * O sea: se manda el plano entero con su spec, no `shot_id`; el element entero,
 * no su id. El backend lo enriquece con lo que solo él sabe (estado de render,
 * fichas de continuidad, coste), pero la forma la fija el frontend porque es
 * quien sabe qué está mirando el usuario.
 *
 * Nada de esto se guarda: se reconstruye en cada turno desde el estado del
 * editor. Es barato y evita que el agente razone sobre una foto vieja.
 */

/** Pestañas del editor, tal cual las declara `OpenTab` en el backend. */
const OPEN_TABS = ["brief", "canvas", "assets", "elements", "preview", "chat"];

/** Ventana de assets recientes. El censo real va en `total_assets`. */
const RECENT_ASSETS_LIMIT = 40;

/**
 * Orden narrativo de la timeline.
 *
 * Primero `position` — el orden que el usuario ha fijado explícitamente — y
 * para los planos que aún no lo tienen (uno recién soltado en el lienzo), el
 * orden de lectura del canvas `(y, x)`. Es `narrative_sort_key` del backend
 * portado: si los dos lados ordenan distinto, el agente habla de "el plano
 * siguiente" refiriéndose a otro que el que ve el usuario.
 */
function narrativeSortKey(node) {
  if (node.position !== null && node.position !== undefined) {
    return [0, Number(node.position), 0, 0];
  }
  return [1, 0, Number(node.y) || 0, Number(node.x) || 0];
}

const byNarrativeOrder = (a, b) => {
  const ka = narrativeSortKey(a);
  const kb = narrativeSortKey(b);
  for (let i = 0; i < ka.length; i += 1) {
    if (ka[i] !== kb[i]) return ka[i] - kb[i];
  }
  return 0;
};

/** Un asset del proyecto en la forma que espera `AssetContext`. */
function toAssetContext(asset) {
  if (!asset) return null;
  return {
    id: String(asset.id),
    name: asset.name ?? "",
    kind: asset.type ?? "",
    status: asset.status ?? "ready",
    meta: asset.meta ?? "",
    role: asset.role ?? null,
    shot_id: asset.shot_id ?? null,
    model_id: asset.model_id ?? null,
    prompt: asset.prompt ?? null,
    params: asset.params ?? {},
    credits_spent: asset.credits_spent ?? 0,
    parent_id: asset.parent_id ?? null,
    created_at: asset.created_at ?? null,
  };
}

/**
 * Un element: el asset que tiene rol.
 *
 * `sheet` lo rellena el backend desde `project_memory`; aquí va null a
 * propósito. El frontend no tiene la ficha destilada y mandar una versión
 * pobre haría que el backend la prefiriese a la buena.
 */
function toElementContext(asset) {
  return {
    id: String(asset.id),
    name: asset.name ?? "",
    role: asset.role ?? "",
    meta: asset.meta ?? "",
    sheet: null,
    // La RUTA, no la URL firmada. Esto viaja al backend y acaba en el contexto
    // del LLM: una URL firmada ahí queda escrita en logs y en transcripciones
    // que sobreviven al TTL, y además el backend ya sabe firmar por su cuenta
    // desde la ruta. `path` lo añade `db.listAssets()`.
    thumb_url: asset.path ?? asset.url ?? null,
  };
}

/** Un nodo del canvas en la forma que espera `ShotContext`. */
function toShotContext(node, assetsByShot) {
  const spec = node.spec ?? {};
  const camera = spec.camera ?? {};

  return {
    id: String(node.id),
    position: node.position ?? null,
    type: node.type ?? "shot",
    title: node.title ?? "",
    text: node.text ?? "",
    status: node.shot_status ?? "pending",
    spec,
    camera: {
      motion: camera.motion ?? null,
      strength: camera.strength ?? null,
      lens: camera.lens ?? null,
      aperture: camera.aperture ?? null,
    },
    element_names: node.element_names ?? [],
    asset: toAssetContext(assetsByShot.get(String(node.id))),
    x: Number(node.x) || 0,
    y: Number(node.y) || 0,
  };
}

/**
 * Ajustes de generación por defecto.
 *
 * Los del editor están en castellano y anidados (`style`, `camera`); el
 * backend los quiere planos y con nombres de `GenSettings`. Lo que no encaja
 * en un campo con nombre se conserva en `extra` en vez de perderse: el agente
 * lee `extra` y así un ajuste nuevo del editor no necesita tocar el backend.
 */
function toGenSettings(genSettings = {}) {
  const { mode, model, aspect, res, dur, count, sound, genre, style, camera } =
    genSettings;

  const duration = parseFloat(dur);

  return {
    model: model ?? null,
    aspect: aspect ?? null,
    resolution: res ?? null,
    duration_s: Number.isFinite(duration) ? duration : null,
    style: style ? Object.values(style).filter((v) => v && v !== "Auto").join(", ") || null : null,
    camera: camera?.["Cámara"] && camera["Cámara"] !== "Auto" ? camera["Cámara"] : null,
    extra: { mode, count, sound, genre, style, camera },
  };
}

/**
 * Arma el contexto completo de un turno.
 *
 * Se le pasa el estado del editor tal cual lo tiene `Editor`; este módulo no
 * lee de `db` para que el contexto sea siempre lo que el usuario está viendo,
 * no lo que hay persistido (que puede ir un guardado por detrás).
 */
export function buildUIContext({
  project,
  tab,
  brief,
  canvas,
  assets = [],
  selectedIds = [],
  genSettings,
  credits = 0,
}) {
  const nodes = (canvas?.nodes ?? []).slice();

  // Índice plano → asset, para colgar el render de cada plano sin recorrer la
  // lista entera por nodo.
  const assetsByShot = new Map();
  for (const asset of assets) {
    if (asset.shot_id) assetsByShot.set(String(asset.shot_id), asset);
  }

  const selected = new Set(selectedIds.map(String));
  const sortedAssets = assets
    .slice()
    .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));

  return {
    project_id: String(project?.id ?? ""),
    project_title: project?.title ?? "",
    open_tab: OPEN_TABS.includes(tab) ? tab : "assets",

    brief: (brief ?? []).map((block, position) => ({
      id: String(block.id ?? position),
      position: block.position ?? position,
      type: block.type ?? "text",
      text: block.text ?? "",
      checked: Boolean(block.checked),
      src: block.src ?? null,
    })),

    timeline: nodes.sort(byNarrativeOrder).map((node) => toShotContext(node, assetsByShot)),

    elements: assets.filter((a) => a.role).map(toElementContext),

    recent_assets: sortedAssets.slice(0, RECENT_ASSETS_LIMIT).map(toAssetContext),
    selected_assets: assets
      .filter((a) => selected.has(String(a.id)))
      .map(toAssetContext),

    gen_settings: toGenSettings(genSettings),
    credits,

    // El censo real. `recent_assets` es solo una ventana, y el backend necesita
    // saber cuánto se está dejando fuera para poder declararlo al modelo.
    total_assets: assets.length,
  };
}
