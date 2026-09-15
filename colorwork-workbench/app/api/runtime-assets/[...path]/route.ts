import { env } from 'cloudflare:workers';
import { authErrorResponse, requireApiUser, requireView } from '@/lib/server/auth';
import { RUNTIME_ASSET_BY_KEY } from '@/lib/server/catalog';

const R2_PREFIX = 'runtime-assets/';

function responseHeaders() {
  return { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };
}

function assetKey(path: string[]) {
  return path.map((part) => decodeURIComponent(part)).join('/');
}

function hasExpectedSignature(bytes: Uint8Array, contentType: string) {
  if (contentType === 'image/jpeg') return bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
  return bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 && bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a;
}

function hex(bytes: ArrayBuffer) {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

export async function GET(_request: Request, context: { params: Promise<{ path: string[] }> }) {
  try {
    await requireApiUser();
    const key = assetKey((await context.params).path);
    const expected = RUNTIME_ASSET_BY_KEY.get(key);
    if (!expected) return Response.json({ error: '素材编号无效。' }, { status: 404, headers: responseHeaders() });
    const object = await env.FILES.get(`${R2_PREFIX}${key}`);
    if (!object) return Response.json({ error: '工作台素材尚未完成导入。' }, { status: 404, headers: responseHeaders() });
    return new Response(object.body, {
      headers: {
        ...responseHeaders(),
        'content-type': expected.contentType,
        'content-length': String(object.size),
      },
    });
  } catch (error) {
    return authErrorResponse(error);
  }
}

export async function PUT(request: Request, context: { params: Promise<{ path: string[] }> }) {
  try {
    const admin = await requireView('master');
    const key = assetKey((await context.params).path);
    const expected = RUNTIME_ASSET_BY_KEY.get(key);
    if (!expected) return Response.json({ error: '素材编号无效。' }, { status: 404, headers: responseHeaders() });
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (declaredSize && declaredSize !== expected.size) {
      return Response.json({ error: '素材大小与已核对版本不一致。' }, { status: 400, headers: responseHeaders() });
    }
    const buffer = await request.arrayBuffer();
    if (buffer.byteLength !== expected.size || !hasExpectedSignature(new Uint8Array(buffer), expected.contentType)) {
      return Response.json({ error: '素材格式或大小不正确。' }, { status: 400, headers: responseHeaders() });
    }
    const sha256 = hex(await crypto.subtle.digest('SHA-256', buffer));
    if (sha256 !== expected.sha256) {
      return Response.json({ error: '素材内容与已核对版本不一致。' }, { status: 400, headers: responseHeaders() });
    }
    const now = new Date().toISOString();
    await env.FILES.put(`${R2_PREFIX}${key}`, buffer, { httpMetadata: { contentType: expected.contentType } });
    await env.DB.prepare(`
      INSERT INTO runtime_assets (asset_key, sha256, size, uploaded_by, updated_at)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(asset_key) DO UPDATE SET
        sha256 = excluded.sha256,
        size = excluded.size,
        uploaded_by = excluded.uploaded_by,
        updated_at = excluded.updated_at
    `).bind(key, sha256, buffer.byteLength, admin.email, now).run();
    return Response.json({ ok: true, key, size: buffer.byteLength }, { headers: responseHeaders() });
  } catch (error) {
    return authErrorResponse(error);
  }
}
