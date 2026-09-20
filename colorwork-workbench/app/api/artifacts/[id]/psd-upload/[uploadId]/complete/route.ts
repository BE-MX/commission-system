import { getFiles } from '@/lib/server/storage';
import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { normalizedParts, PSD_LIMIT } from '@/lib/server/uploads';

type CompleteInput = { parts?: Array<{ partNumber?: unknown; etag?: unknown }> };

export async function POST(request: Request, context: { params: Promise<{ id: string; uploadId: string }> }) {
  try {
    const user = await requireView('master');
    const { id, uploadId } = await context.params;
    const input = await request.json<CompleteInput>().catch(() => null);
    const parts = normalizedParts(input?.parts);
    if (!parts) {
      return Response.json({ error: '上传分片不完整。' }, { status: 400 });
    }
    const artifact = await env.DB.prepare(`
      SELECT owner_user_id AS ownerUserId, psd_key AS psdKey, status
      FROM artifacts WHERE id = ?
    `).bind(id).first<{ ownerUserId: string; psdKey: string; status: string }>();
    if (!artifact || artifact.ownerUserId !== user.id) {
      return Response.json({ error: '没有权限写入这个文件。' }, { status: 403 });
    }
    if (artifact.status !== 'psd_uploading') {
      return Response.json({ error: '这个文件已经结束上传。' }, { status: 409 });
    }
    const upload = getFiles().resumeMultipartUpload(artifact.psdKey, uploadId);
    const completed = await upload.complete(parts);
    if (completed.size > PSD_LIMIT) {
      await getFiles().delete(artifact.psdKey);
      return Response.json({ error: 'PSD 文件不得超过 256 MB。' }, { status: 400 });
    }
    const updated = await env.DB.prepare(`
      UPDATE artifacts SET psd_size = ?, updated_at = ?
      WHERE id = ? AND owner_user_id = ? AND status = 'psd_uploading'
    `).bind(completed.size, new Date().toISOString(), id, user.id).run();
    if (!updated.meta.changes) {
      const current = await env.DB.prepare(`SELECT status FROM artifacts WHERE id = ? AND owner_user_id = ?`)
        .bind(id, user.id).first<{ status: string }>();
      if (current?.status === 'failed') await getFiles().delete(artifact.psdKey);
      return Response.json({ error: '这个文件已被其他操作封存，请刷新。' }, { status: 409 });
    }
    return Response.json({ ok: true, size: completed.size });
  } catch (error) {
    return authErrorResponse(error);
  }
}
