import { getFiles } from '@/lib/server/storage';
import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { SERVER_TEMPLATES } from '@/lib/server/catalog';
import { isPsd, PSD_MAX_PARTS, PSD_PART_SIZE } from '@/lib/server/uploads';

export async function PUT(request: Request, context: { params: Promise<{ id: string; uploadId: string; part: string }> }) {
  try {
    await requireView('master');
    const { id, uploadId, part } = await context.params;
    if (!SERVER_TEMPLATES.some((item) => item.id === id)) return Response.json({ error: '模板编号无效。' }, { status: 400 });
    const versionId = new URL(request.url).searchParams.get('version') || '';
    if (!/^[0-9a-f-]{36}$/i.test(versionId)) return Response.json({ error: '模板版本无效。' }, { status: 400 });
    const partNumber = Number(part);
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > PSD_MAX_PARTS || declaredSize > PSD_PART_SIZE) {
      return Response.json({ error: '分片信息无效。' }, { status: 400 });
    }
    const buffer = await request.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > PSD_PART_SIZE || (partNumber === 1 && !isPsd(new Uint8Array(buffer)))) {
      return Response.json({ error: partNumber === 1 ? 'PSD 文件头无效。' : '分片信息无效。' }, { status: 400 });
    }
    const key = `templates/${id}/versions/${versionId}/source.psd`;
    const upload = getFiles().resumeMultipartUpload(key, uploadId);
    const uploaded = await upload.uploadPart(partNumber, buffer);
    return Response.json({ partNumber: uploaded.partNumber, etag: uploaded.etag });
  } catch (error) {
    return authErrorResponse(error);
  }
}
