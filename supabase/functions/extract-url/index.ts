// Ingesta segura y acotada de una fuente web para el conocimiento del workspace.
// No sigue redirecciones: evita convertir la Edge Function en un proxy hacia red
// privada. Los redireccionamientos se muestran al usuario para que confirme la URL.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

function safeUrl(value: unknown): URL {
  const parsed = new URL(String(value));
  if (!/^https?:$/.test(parsed.protocol)) throw new Error("Sólo se admiten URLs HTTP(S)");
  const host = parsed.hostname.toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost") || /^(127\.|0\.|10\.|192\.168\.|169\.254\.|::1$|fc|fd)/.test(host)) {
    throw new Error("La URL no puede apuntar a una red privada");
  }
  return parsed;
}

function textFromHtml(input: string): string {
  return input
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const auth = request.headers.get("Authorization");
    if (!auth) throw new Error("No autenticado");
    const url = Deno.env.get("SUPABASE_URL")!;
    const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
    const client = createClient(url, anon, { global: { headers: { Authorization: auth } } });
    const { data: { user }, error: userError } = await client.auth.getUser();
    if (userError || !user) throw new Error("No autenticado");
    const { workspace_id, source_url, title } = await request.json();
    const target = safeUrl(source_url);
    const { data: workspace } = await client.from("workspaces").select("id").eq("id", workspace_id).eq("owner_id", user.id).maybeSingle();
    if (!workspace) return Response.json({ error: "Espacio no encontrado" }, { status: 404, headers: cors });

    const pending = await client.from("knowledge_sources").insert({ workspace_id, kind: "url", title: String(title || target.hostname).slice(0, 300), url: target.toString(), status: "pending" }).select("id").single();
    if (pending.error) throw pending.error;
    const response = await fetch(target, { redirect: "manual", signal: AbortSignal.timeout(10_000) });
    if (response.status >= 300 && response.status < 400) throw new Error("La URL redirige; confirma la URL de destino antes de importarla");
    if (!response.ok) throw new Error(`La web respondió ${response.status}`);
    const type = response.headers.get("content-type") || "";
    if (!/(text\/html|text\/plain|application\/json|application\/pdf)/i.test(type)) throw new Error("El recurso no es texto o HTML legible");
    const raw = (await response.text()).slice(0, 1_500_000);
    const content = type.includes("html") ? textFromHtml(raw) : raw.replace(/\s+/g, " ").trim();
    if (!content) throw new Error("No se pudo extraer texto de la URL");
    const { error: updateError } = await client.from("knowledge_sources").update({ content: content.slice(0, 200_000), excerpt: content.slice(0, 800), status: "ready", error: null }).eq("id", pending.data.id);
    if (updateError) throw updateError;
    return Response.json({ source: { id: pending.data.id, title: title || target.hostname, excerpt: content.slice(0, 800), status: "ready" } }, { headers: cors });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Error" }, { status: 400, headers: cors });
  }
});
