import { env } from "cloudflare:workers";
import { requireAdminApi } from "../../lib/admin-auth";

export const dynamic = "force-dynamic";

const allowedTypes = new Set([
  "image/jpeg", "image/png", "image/webp", "video/mp4", "video/quicktime",
]);

export async function POST(request: Request) {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  const formData = await request.formData();
  const file = formData.get("file");
  if (!(file instanceof File)) return Response.json({ error: "请选择要上传的图片或视频" }, { status: 400 });
  if (!allowedTypes.has(file.type)) return Response.json({ error: "仅支持 JPG、PNG、WebP、MP4 或 MOV" }, { status: 400 });
  const extension = file.name.split(".").pop()?.toLowerCase().replace(/[^a-z0-9]/g, "") || (file.type.startsWith("image/") ? "jpg" : "mp4");
  const key = `products/${new Date().toISOString().slice(0, 10)}/${crypto.randomUUID()}.${extension}`;
  const storage = env as unknown as { MEDIA?: R2Bucket; MEDIA_KV?: KVNamespace };
  if (!storage.MEDIA && !storage.MEDIA_KV) return Response.json({ error: "素材存储尚未连接" }, { status: 503 });
  if (storage.MEDIA) {
    if (file.size > 100 * 1024 * 1024) return Response.json({ error: "单个文件不能超过100MB" }, { status: 400 });
    await storage.MEDIA.put(key, file.stream(), { httpMetadata: { contentType: file.type }, customMetadata: { originalName: file.name } });
  } else if (storage.MEDIA_KV) {
    if (file.size > 20 * 1024 * 1024) return Response.json({ error: "当前单个文件不能超过20MB，请先压缩视频后上传" }, { status: 400 });
    await storage.MEDIA_KV.put(key, await file.arrayBuffer(), { metadata: { contentType: file.type, originalName: file.name } });
  }
  return Response.json({ url: `/api/media/${key}`, name: file.name, size: file.size });
}
