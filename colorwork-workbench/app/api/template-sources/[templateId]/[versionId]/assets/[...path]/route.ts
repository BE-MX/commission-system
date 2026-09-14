import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  readSourceVersion,
  sourceObjectKey,
  templateSourceErrorResponse,
} from '@/lib/server/template-sources';

const ASSET_LIMIT = 16 * 1024 * 1024;

function isPng(bytes: Uint8Array) {
  return bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
    bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a;
}

function hex(bytes: ArrayBuffer) {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

export async function PUT(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string; path: string[] }> },
) {
  try {
    await requireView('master');
    const { templateId, versionId, path } = await context.params;
    const row = await readSourceVersion(templateId, versionId);
    if (!row) return Response.json({ error: '没有找到这个源文件版本。' }, { status: 404 });
    if (row.status !== 'parsing') return Response.json({ error: '这个源文件版本不在解析素材上传阶段。' }, { status: 409 });
    const assetName = path.map(decodeURIComponent).join('/');
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (declaredSize > ASSET_LIMIT) return Response.json({ error: '单个解析素材不得超过 16 MB。' }, { status: 400 });
    const buffer = await request.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > ASSET_LIMIT || !isPng(new Uint8Array(buffer))) {
      return Response.json({ error: '解析素材必须是有效的 PNG，且不得超过 16 MB。' }, { status: 400 });
    }
    const key = sourceObjectKey(row, assetName);
    const sha256 = hex(await crypto.subtle.digest('SHA-256', buffer));
    const existing = await env.FILES.head(key);
    if (existing) {
      if (existing.size === buffer.byteLength && existing.customMetadata?.sha256 === sha256) {
        return Response.json({ ok: true, assetName, size: buffer.byteLength, sha256, idempotent: true });
      }
      return Response.json({
        error: '这个解析素材已经封存，不能用其他内容覆盖。请重新开始一个源文件版本。',
        code: 'SOURCE_ASSET_IMMUTABLE',
      }, { status: 409 });
    }
    const stored = await env.FILES.put(key, buffer, {
      onlyIf: { etagDoesNotMatch: '*' },
      httpMetadata: { contentType: 'image/png' },
      customMetadata: { sha256, size: String(buffer.byteLength) },
    });
    if (!stored) {
      const concurrent = await env.FILES.head(key);
      if (concurrent?.size === buffer.byteLength && concurrent.customMetadata?.sha256 === sha256) {
        return Response.json({ ok: true, assetName, size: buffer.byteLength, sha256, idempotent: true });
      }
      return Response.json({
        error: '这个解析素材已被另一上传封存，不能覆盖。请刷新候选版本。',
        code: 'SOURCE_ASSET_IMMUTABLE',
      }, { status: 409 });
    }
    return Response.json({ ok: true, assetName, size: buffer.byteLength, sha256 });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
