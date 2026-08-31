import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ key: string[] }> }) {
  const { key } = await context.params;
  const storage = env as unknown as { MEDIA?: R2Bucket; MEDIA_KV?: KVNamespace };
  if (storage.MEDIA) {
    const object = await storage.MEDIA.get(key.join("/"));
    if (!object) return new Response("素材不存在", { status: 404 });
    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("etag", object.httpEtag);
    headers.set("cache-control", "public, max-age=31536000, immutable");
    return new Response(object.body, { headers });
  }
  if (storage.MEDIA_KV) {
    const object = await storage.MEDIA_KV.getWithMetadata<{ contentType?: string }>(key.join("/"), { type: "stream" });
    if (!object.value) return new Response("素材不存在", { status: 404 });
    return new Response(object.value, { headers: { "content-type": object.metadata?.contentType ?? "application/octet-stream", "cache-control": "public, max-age=31536000, immutable" } });
  }
  return new Response("素材存储尚未连接", { status: 503 });
}
