import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { isPsd, PSD_MAX_PARTS, PSD_PART_SIZE } from '@/lib/server/uploads';

export async function PUT(request: Request, context: { params: Promise<{ id: string; uploadId: string; part: string }> }) {
  try {
    const user = await requireView('master');
    const { id, uploadId, part } = await context.params;
    const partNumber = Number(part);
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > PSD_MAX_PARTS || declaredSize > PSD_PART_SIZE) {
      return Response.json({ error: '分片信息无效。' }, { status: 400 });
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
    const buffer = await request.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > PSD_PART_SIZE || (partNumber === 1 && !isPsd(new Uint8Array(buffer)))) {
      return Response.json({ error: partNumber === 1 ? 'PSD 文件头无效。' : '分片信息无效。' }, { status: 400 });
    }
    const upload = env.FILES.resumeMultipartUpload(artifact.psdKey, uploadId);
    const uploaded = await upload.uploadPart(partNumber, buffer);
    return Response.json({ partNumber: uploaded.partNumber, etag: uploaded.etag });
  } catch (error) {
    return authErrorResponse(error);
  }
}
