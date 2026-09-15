import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { readSourceVersion, templateSourceErrorResponse } from '@/lib/server/template-sources';
import { isPsd, PSD_MAX_PARTS, PSD_PART_SIZE } from '@/lib/server/uploads';

export async function PUT(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string; uploadId: string; part: string }> },
) {
  try {
    await requireView('master');
    const { templateId, versionId, uploadId, part } = await context.params;
    const row = await readSourceVersion(templateId, versionId);
    if (!row) return Response.json({ error: '没有找到这个源文件版本。' }, { status: 404 });
    if (row.status !== 'uploading') return Response.json({ error: '这个源文件版本已经结束上传。' }, { status: 409 });
    const partNumber = Number(part);
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > PSD_MAX_PARTS || declaredSize > PSD_PART_SIZE) {
      return Response.json({ error: 'PSD 分片信息无效。' }, { status: 400 });
    }
    const buffer = await request.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > PSD_PART_SIZE || (partNumber === 1 && !isPsd(new Uint8Array(buffer)))) {
      return Response.json({ error: partNumber === 1 ? 'PSD 文件头无效。' : 'PSD 分片信息无效。' }, { status: 400 });
    }
    const upload = env.FILES.resumeMultipartUpload(row.sourcePsdKey, uploadId);
    const uploaded = await upload.uploadPart(partNumber, buffer);
    return Response.json({ partNumber: uploaded.partNumber, etag: uploaded.etag });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}

