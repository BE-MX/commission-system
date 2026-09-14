import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  readSourceVersion,
  templateSourceErrorResponse,
} from '@/lib/server/template-sources';
import { isJpeg, jpegDimensions, JPG_LIMIT } from '@/lib/server/uploads';

function hex(bytes: ArrayBuffer) {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

export async function PUT(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string }> },
) {
  try {
    await requireView('master');
    const { templateId, versionId } = await context.params;
    const row = await readSourceVersion(templateId, versionId);
    if (!row) return Response.json({ error: '没有找到这个源文件版本。' }, { status: 404 });
    if (row.status !== 'uploading') return Response.json({ error: '这个源文件版本已经结束上传。' }, { status: 409 });
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (declaredSize > JPG_LIMIT) return Response.json({ error: 'JPG 文件不得超过 25 MB。' }, { status: 400 });
    const buffer = await request.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const dimensions = jpegDimensions(bytes);
    if (!buffer.byteLength || buffer.byteLength > JPG_LIMIT || !isJpeg(bytes) || !dimensions) {
      return Response.json({ error: 'JPG 文件格式或画布尺寸无效。' }, { status: 400 });
    }
    if (buffer.byteLength !== row.referenceJpgSize) {
      return Response.json({ error: 'JPG 上传内容与开始上传时选择的文件大小不一致，请重新开始更新。' }, { status: 422 });
    }
    const sha256 = hex(await crypto.subtle.digest('SHA-256', buffer));
    const existing = await env.FILES.head(row.referenceJpgKey);
    if (existing) {
      if (existing.size !== buffer.byteLength || existing.customMetadata?.sha256 !== sha256) {
        return Response.json({
          error: '这个版本的 JPG 已经上传，不能用其他内容覆盖。请重新开始更新。',
          code: 'SOURCE_JPG_IMMUTABLE',
        }, { status: 409 });
      }
      return Response.json({ ok: true, size: buffer.byteLength, sha256, idempotent: true, ...dimensions });
    }
    const stored = await env.FILES.put(row.referenceJpgKey, buffer, {
      onlyIf: { etagDoesNotMatch: '*' },
      httpMetadata: { contentType: 'image/jpeg' },
      customMetadata: {
        width: String(dimensions.width),
        height: String(dimensions.height),
        sha256,
        size: String(buffer.byteLength),
      },
    });
    if (!stored) {
      const concurrent = await env.FILES.head(row.referenceJpgKey);
      if (concurrent?.size !== buffer.byteLength || concurrent.customMetadata?.sha256 !== sha256) {
        return Response.json({
          error: '这个版本的 JPG 已被另一上传封存，不能覆盖。请重新开始更新。',
          code: 'SOURCE_JPG_IMMUTABLE',
        }, { status: 409 });
      }
    }
    const updated = await env.DB.prepare(`
      UPDATE template_source_versions SET updated_at = ?
      WHERE id = ? AND template_id = ? AND status = 'uploading'
    `).bind(new Date().toISOString(), row.id, row.templateId).run();
    if (!updated.meta.changes) {
      return Response.json({ error: '源文件版本已被其他操作更新，请重新开始。' }, { status: 409 });
    }
    return Response.json({ ok: true, size: buffer.byteLength, sha256, ...dimensions });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
