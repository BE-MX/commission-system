import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { readSourceVersion, templateSourceErrorResponse } from '@/lib/server/template-sources';
import { normalizedParts, psdDimensions, PSD_LIMIT } from '@/lib/server/uploads';

export async function POST(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string; uploadId: string }> },
) {
  try {
    await requireView('master');
    const { templateId, versionId, uploadId } = await context.params;
    const row = await readSourceVersion(templateId, versionId);
    if (!row) return Response.json({ error: '没有找到这个源文件版本。' }, { status: 404 });
    if (row.status !== 'uploading') return Response.json({ error: '这个源文件版本已经结束上传。' }, { status: 409 });
    const input = await request.json<{ parts?: unknown }>().catch(() => null);
    const parts = normalizedParts(input?.parts);
    if (!parts) return Response.json({ error: 'PSD 上传分片不完整。' }, { status: 400 });
    const reference = await env.FILES.head(row.referenceJpgKey);
    if (!reference) return Response.json({ error: '请先上传对应 JPG。' }, { status: 409 });
    const upload = env.FILES.resumeMultipartUpload(row.sourcePsdKey, uploadId);
    const completed = await upload.complete(parts);
    const prefixObject = await env.FILES.get(row.sourcePsdKey, { range: { offset: 0, length: 26 } });
    const prefix = prefixObject ? new Uint8Array(await prefixObject.arrayBuffer()) : new Uint8Array();
    const psd = psdDimensions(prefix);
    const jpgWidth = Number(reference.customMetadata?.width);
    const jpgHeight = Number(reference.customMetadata?.height);
    if (
      completed.size > PSD_LIMIT || completed.size !== row.sourcePsdSize || !psd ||
      reference.size !== row.referenceJpgSize || psd.width !== jpgWidth || psd.height !== jpgHeight
    ) {
      await env.FILES.delete([row.sourcePsdKey, row.referenceJpgKey]);
      await env.DB.prepare(`
        UPDATE template_source_versions SET status = 'failed', failure_reason = ?, updated_at = ?
        WHERE id = ? AND template_id = ?
      `).bind('PSD/JPG 上传不完整、文件签名无效、画布尺寸不一致或与开始上传时选择的文件不一致。', new Date().toISOString(), row.id, row.templateId).run();
      return Response.json({ error: 'PSD/JPG 上传不完整、文件内容或画布尺寸不一致，请重新开始更新。' }, { status: 422 });
    }
    const updated = await env.DB.prepare(`
      UPDATE template_source_versions
      SET status = 'parsing', source_psd_size = ?, reference_jpg_size = ?, updated_at = ?
      WHERE id = ? AND template_id = ? AND status = 'uploading'
    `).bind(completed.size, reference.size, new Date().toISOString(), row.id, row.templateId).run();
    if (!updated.meta.changes) return Response.json({ error: '源文件版本已被其他操作更新，请刷新。' }, { status: 409 });
    return Response.json({ ok: true, sourceVersion: { id: row.id, number: row.versionNumber, status: 'parsing' }, size: completed.size });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
