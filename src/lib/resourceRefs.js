const TYPE_PREFIX = {
  asset: "asset",
  element: "element",
  scene: "scene",
  line: "line",
  shot: "shot",
  canvas: "canvas",
  voice: "voice",
  cue: "cue",
  sound_template: "sound",
  transition: "transition",
  manifest: "manifest",
  annotation: "annotation",
  operation: "operation",
  report: "report",
  brief: "brief",
};

export function mentionSlug(value) {
  return String(value || "resource")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 54) || "resource";
}

function resource(type, id, label, extra = {}) {
  const prefix = TYPE_PREFIX[type] || type;
  return {
    type,
    id: String(id),
    label: String(label || id),
    mention: `${prefix}-${mentionSlug(label || id)}`,
    ...extra,
  };
}

/** Catálogo único para el compositor @. Los objetos completos nunca viajan al LLM. */
export function buildResourceCatalog({ assets = [], brief = [], canvas, production = {} }) {
  // Los proyectos antiguos y los estados parciales de carga pueden devolver `null`
  // explícito. Los defaults de desestructuración solo cubren `undefined`, de modo que
  // llamar a `.entries()` sobre el brief tumbaba todo el editor antes de pintar Guion,
  // Audio o Assets. Cada colección se normaliza en la frontera del catálogo.
  const assetList = Array.isArray(assets) ? assets : [];
  const briefBlocks = Array.isArray(brief) ? brief.filter(Boolean) : [];
  const canvasNodes = Array.isArray(canvas?.nodes)
    ? canvas.nodes.filter(Boolean)
    : [];
  const productionState =
    production && typeof production === "object" ? production : {};
  const collection = (key) =>
    Array.isArray(productionState[key])
      ? productionState[key].filter(Boolean)
      : [];

  const refs = [];
  for (const [index, block] of briefBlocks.entries()) {
    const id = block.db_id || block.id;
    if (id) {
      refs.push(
        resource("brief", id, block.text || `Bloque ${index + 1}`, {
          position: block.position ?? index,
          kind: block.type || "text",
        }),
      );
    }
  }
  for (const asset of assetList.filter((item) => item && !item.ghost)) {
    refs.push(
      resource(asset.role ? "element" : "asset", asset.id, asset.name, {
        kind: asset.type || "asset",
        status: asset.status || "ready",
        url: asset.url || null,
      }),
    );
  }
  for (const [index, node] of canvasNodes.entries()) {
    refs.push(
      resource(node.type === "shot" ? "shot" : "canvas", node.db_id || node.id, node.title || `Plano ${index + 1}`, {
        node_key: node.node_key || node.id,
        kind: node.type || "canvas",
      }),
    );
  }
  for (const [index, scene] of collection("scenes").entries()) {
    refs.push(resource("scene", scene.id, scene.title || `Escena ${index + 1}`, { position: scene.position }));
  }
  for (const line of collection("lines")) {
    const label = `${line.line_type || "línea"}-${String(line.text || "").slice(0, 42)}`;
    refs.push(resource("line", line.id, label, { scene_id: line.scene_id }));
  }
  for (const voice of collection("voices")) {
    refs.push(resource("voice", voice.id, voice.name, { status: voice.status }));
  }
  for (const cue of collection("cues")) {
    refs.push(
      resource("cue", cue.id, `${cue.track_kind || "audio"}-${cue.start_ms || 0}ms`, {
        start_ms: cue.start_ms,
        end_ms: cue.end_ms,
        asset_id: cue.asset_id,
      }),
    );
  }
  for (const template of collection("audioTemplates")) {
    refs.push(resource("sound_template", template.id, template.name, { asset_id: template.asset_id }));
  }
  for (const annotation of collection("annotations")) {
    refs.push(
      resource(
        "annotation",
        annotation.id,
        annotation.body || `${annotation.kind || "anotación"}-${String(annotation.id).slice(0, 6)}`,
        { asset_id: annotation.asset_id, kind: annotation.kind, time_ms: annotation.time_ms },
      ),
    );
  }
  for (const operation of collection("operations")) {
    refs.push(
      resource(
        "operation",
        operation.id,
        `${operation.operation || "edición"}-${operation.status || "planned"}`,
        {
          status: operation.status,
          output_asset_id: operation.output_asset_id,
          job_id: operation.job_id,
        },
      ),
    );
  }
  for (const report of collection("qualityReports")) {
    refs.push(
      resource(
        "report",
        report.id,
        `${report.check_type || "qa"}-${report.status || "review"}`,
        {
          asset_id: report.asset_id,
          check_type: report.check_type,
          status: report.status,
          passed: report.passed,
        },
      ),
    );
  }
  for (const transition of collection("transitions")) {
    refs.push(resource("transition", transition.id, transition.signature || transition.kind || "transición"));
  }
  for (const manifest of collection("productionManifests")) {
    refs.push(
      resource(
        "manifest",
        manifest.id,
        manifest.title || `Manifiesto v${manifest.version || ""}`,
        { status: manifest.status, scene_id: manifest.scene_id },
      ),
    );
  }

  // Un mismo nombre puede repetirse entre recursos. El sufijo corto conserva una
  // mención estable y evita que el texto resuelva al objeto equivocado.
  const totals = refs.reduce((counts, ref) => {
    counts.set(ref.mention, (counts.get(ref.mention) || 0) + 1);
    return counts;
  }, new Map());
  return refs.map((ref) =>
    totals.get(ref.mention) > 1
      ? { ...ref, mention: `${ref.mention}-${ref.id.slice(0, 8)}` }
      : ref,
  );
}

export function resolveResourceMentions(text, catalog) {
  const found = [];
  for (const ref of catalog || []) {
    const pattern = new RegExp(
      `(^|[\\s([{])@${ref.mention.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=\\s|$|[.,;:!?\\])}])`,
      "i",
    );
    if (pattern.test(text)) {
      const { searchText: _searchText, ...clean } = ref;
      found.push(clean);
    }
  }
  return found;
}
