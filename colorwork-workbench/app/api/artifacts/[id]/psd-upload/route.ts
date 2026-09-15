import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { PSD_PART_SIZE } from '@/lib/server/uploads';

export async function POST(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const user = await requireView('master');
    const { id } = await context.params;
    const artifact = await env.DB.prepare(`
      SELECT owner_user_id AS ownerUserId, psd_key AS psdKey, status
      FROM artifacts WHERE id = ?
    `).bind(id).first<{ ownerUserId: string; psdKey: string; status: string }>();
    if (!artifact || artifact.ownerUserId !== user.id) {
      return Response.json({ error: '没有权限写入这个文件。' }, { status: 403 });
    }
    if (artifact.status !== 'uploading') {
      return Response.json({ error: '这个文件已经结束上传。' }, { status: 409 });
    }
    const lock = await env.DB.prepare(`
      UPDATE artifacts SET status = 'psd_uploading', updated_at = ?
      WHERE id = ? AND owner_user_id = ? AND status = 'uploading'
    `).bind(new Date().toISOString(), id, user.id).run();
    if (!lock.meta.changes) return Response.json({ error: '这个文件已有 PSD 上传任务。' }, { status: 409 });
    try {
      const upload = await env.FILES.createMultipartUpload(artifact.psdKey, {
        httpMetadata: { contentType: 'image/vnd.adobe.photoshop' },
      });
      return Response.json({ uploadId: upload.uploadId, partSize: PSD_PART_SIZE });
    } catch (error) {
      await env.DB.prepare(`
        UPDATE artifacts SET status = 'uploading', updated_at = ?
        WHERE id = ? AND owner_user_id = ? AND status = 'psd_uploading'
      `).bind(new Date().toISOString(), id, user.id).run();
      throw error;
    }
  } catch (error) {
    return authErrorResponse(error);
  }
}
