// Entrega una URL firmada sólo si el usuario autenticado puede acceder al proyecto.
// Se usa desde automatizaciones de Supabase; las llamadas MCP pasan por el backend,
// que aplica exactamente la misma frontera antes de firmar.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const auth = request.headers.get("Authorization");
    if (!auth) throw new Error("No autenticado");
    const url = Deno.env.get("SUPABASE_URL")!;
    const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
    const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const client = createClient(url, anon, { global: { headers: { Authorization: auth } } });
    const { data: { user }, error: userError } = await client.auth.getUser();
    if (userError || !user) throw new Error("No autenticado");
    const { asset_id, expires_in = 3600 } = await request.json();
    if (typeof asset_id !== "string") throw new Error("asset_id inválido");

    // Service role sólo después de comprobar pertenencia: la firma no puede
    // depender de una ruta que el navegador pueda inventar.
    const admin = createClient(url, service);
    const { data: asset } = await admin
      .from("assets")
      .select("id, url, project_id")
      .eq("id", asset_id)
      .maybeSingle();
    if (!asset?.url) return new Response(JSON.stringify({ error: "Asset no encontrado" }), { status: 404, headers: { ...cors, "Content-Type": "application/json" } });
    const { data: project } = await admin.from("projects").select("owner_id").eq("id", asset.project_id).maybeSingle();
    if (!project || project.owner_id !== user.id) return new Response(JSON.stringify({ error: "Asset no encontrado" }), { status: 404, headers: { ...cors, "Content-Type": "application/json" } });

    const path = String(asset.url).replace(/^.*\/storage\/v1\/object\/(?:public\/)?assets\//, "");
    if (!path || path.startsWith("/")) throw new Error("El asset no está en Storage");
    const { data, error } = await admin.storage.from("assets").createSignedUrl(path, Math.min(Math.max(Number(expires_in) || 3600, 60), 3600));
    if (error) throw error;
    return Response.json({ asset_id, signed_url: data.signedUrl }, { headers: cors });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Error" }, { status: 400, headers: cors });
  }
});
