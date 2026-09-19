import { getFiles } from '@/lib/server/storage';
import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { serverTemplateById } from '@/lib/server/catalog';
import { isJpeg, jpegDimensions, JPG_LIMIT } from '@/lib/server/uploads';

function hex(bytes: ArrayBuffer) {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

export async function PUT(request: Request, context: { params: Promise<{ id: string; kind: string }> }) {
  try {
    const user = await requireView('inventory');
    const { id, kind } = await context.params;
    if (kind !== 'jpg') return Response.json({ error: 'PSD 必须使用分片上传。' }, { status: 400 });
    const artifact = await env.DB.prepare(`
      SELECT owner_user_id AS ownerUserId, source_template_id AS templateId,
        jpg_key AS jpgKey, psd_key AS psdKey, config_json AS configJson, status
      FROM artifacts WHERE id = ?
    `).bind(id).first<{ ownerUserId: string; templateId: string; jpgKey: string; psdKey: string; configJson: string; status: string }>();
    if (!artifact || artifact.ownerUserId !== user.id) return Response.json({ error: '没有权限写入这个文件。' }, { status: 403 });
    if (artifact.status !== 'uploading') return Response.json({ error: '这个文件已经结束上传。' }, { status: 409 });
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (declaredSize > JPG_LIMIT) {
      return Response.json({ error: 'JPG 文件不能为空，且不得超过 25 MB。' }, { status: 400 });
    }
    const buffer = await request.arrayBuffer();
    const size = buffer.byteLength;
    if (!size || size > JPG_LIMIT || !isJpeg(new Uint8Array(buffer))) {
      return Response.json({ error: 'JPG 文件格式无效，或文件超过 25 MB。' }, { status: 400 });
    }
    let expected: { width?: number; height?: number } | null = null;
    try {
      const config = JSON.parse(artifact.configJson) as { schemaVersion?: number; template?: { width?: number; height?: number } };
      expected = config.schemaVersion === 3 ? config.template ?? null : serverTemplateById(artifact.templateId) ?? null;
    } catch {
      expected = null;
    }
    const dimensions = jpegDimensions(new Uint8Array(buffer));
    if (!expected || !dimensions || dimensions.width !== expected.width || dimensions.height !== expected.height) {
      return Response.json({ error: 'JPG 图片尺寸与当前模板不一致。' }, { status: 422 });
    }
    const sha256 = hex(await crypto.subtle.digest('SHA-256', buffer));
    const existing = await getFiles().head(artifact.jpgKey);
    if (existing) {
      if (existing.size !== size || existing.customMetadata?.sha256 !== sha256) {
        return Response.json({
          error: '这个历史成品的 JPG 已经封存，不能覆盖。',
          code: 'ARTIFACT_IMMUTABLE',
        }, { status: 409 });
      }
      return Response.json({ ok: true, kind: 'jpg', size, sha256, idempotent: true });
    }
    const stored = await getFiles().put(artifact.jpgKey, buffer, {
      onlyIf: { etagDoesNotMatch: '*' },
      httpMetadata: { contentType: 'image/jpeg' },
      customMetadata: { sha256, size: String(size) },
    });
    if (!stored) {
      const concurrent = await getFiles().head(artifact.jpgKey);
      if (concurrent?.size !== size || concurrent.customMetadata?.sha256 !== sha256) {
        return Response.json({
          error: '这个历史成品的 JPG 已被另一上传封存，不能覆盖。',
          code: 'ARTIFACT_IMMUTABLE',
        }, { status: 409 });
      }
    }
    const updated = await env.DB.prepare(`
      UPDATE artifacts SET jpg_size = ?, updated_at = ?
      WHERE id = ? AND owner_user_id = ? AND status = 'uploading'
    `).bind(size, new Date().toISOString(), id, user.id).run();
    if (!updated.meta.changes) {
      const current = await env.DB.prepare(`SELECT status FROM artifacts WHERE id = ? AND owner_user_id = ?`)
        .bind(id, user.id).first<{ status: string }>();
      if (current?.status === 'failed') await getFiles().delete(artifact.jpgKey);
      return Response.json({ error: '这个文件已被其他操作封存，请刷新。' }, { status: 409 });
    }
    return Response.json({ ok: true, kind: 'jpg', size, sha256 });
  } catch (error) {
    return authErrorResponse(error);
  }
}
