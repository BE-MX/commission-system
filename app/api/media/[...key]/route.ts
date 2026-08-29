import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ key: string[] }> }) {
  const { key } = await context.params;
  const bucket = (env as unknown as { MEDIA: R2Bucket }).MEDIA;
  if (!bucket) return new Response("素材存储尚未连接", { status: 503 });
  const object = await bucket.get(key.join("/"));
  if (!object) return new Response("素材不存在", { status: 404 });
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "public, max-age=31536000, immutable");
  return new Response(object.body, { headers });
}
