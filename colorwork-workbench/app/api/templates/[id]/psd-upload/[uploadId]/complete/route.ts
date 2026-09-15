import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { SERVER_TEMPLATES } from '@/lib/server/catalog';
import { ensureSourceHistory } from '@/lib/server/template-sources';
import { normalizedParts, PSD_LIMIT } from '@/lib/server/uploads';

type CompleteInput = {
  parts?: Array<{ partNumber?: unknown; etag?: unknown }>;
  sourcePsdName?: unknown;
  referenceJpgName?: unknown;
  versionId?: unknown;
};

export async function POST(request: Request, context: { params: Promise<{ id: string; uploadId: string }> }) {
  try {
    const admin = await requireView('master');
    const { id, uploadId } = await context.params;
    const template = SERVER_TEMPLATES.find((item) => item.id === id);
    if (!template) return Response.json({ error: '模板编号无效。' }, { status: 400 });
    const input = await request.json<CompleteInput>().catch(() => null);
    if (!input) return Response.json({ error: '请求格式无效。' }, { status: 400 });
    const versionId = typeof input.versionId === 'string' ? input.versionId : '';
    if (!/^[0-9a-f-]{36}$/i.test(versionId)) return Response.json({ error: '模板版本无效。' }, { status: 400 });
    const parts = normalizedParts(input.parts);
    if (!parts) {
      return Response.json({ error: '上传分片不完整。' }, { status: 400 });
    }
    const sourcePsdName = typeof input.sourcePsdName === 'string' ? input.sourcePsdName.slice(0, 220) : `${id}.psd`;
    const referenceJpgName = typeof input.referenceJpgName === 'string' ? input.referenceJpgName.slice(0, 220) : `${id}.jpg`;
    if (sourcePsdName !== template.sourcePsdName || referenceJpgName !== template.referenceJpgName) {
      return Response.json({ error: '源文件名与这个模板不匹配。' }, { status: 400 });
    }
    const sourcePsdKey = `templates/${id}/versions/${versionId}/source.psd`;
    const referenceJpgKey = `templates/${id}/versions/${versionId}/reference.jpg`;
    const reference = await env.FILES.head(referenceJpgKey);
    if (!reference) return Response.json({ error: '请先上传对应 JPG。' }, { status: 409 });
    const upload = env.FILES.resumeMultipartUpload(sourcePsdKey, uploadId);
    const completed = await upload.complete(parts);
    if (completed.size > PSD_LIMIT) {
      await env.FILES.delete([sourcePsdKey, referenceJpgKey]);
      return Response.json({ error: 'PSD 文件不得超过 256 MB。' }, { status: 400 });
    }
    const now = new Date().toISOString();
    const inserted = await env.DB.prepare(`
      INSERT INTO template_files
        (template_id, source_psd_key, reference_jpg_key, source_psd_name,
         reference_jpg_name, imported_by, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(template_id) DO NOTHING
    `).bind(id, sourcePsdKey, referenceJpgKey, sourcePsdName, referenceJpgName, admin.email, now, now).run();
    if (!inserted.meta.changes) {
      await env.FILES.delete([sourcePsdKey, referenceJpgKey]);
      return Response.json({
        error: '这个产品与 Radio 已有源文件，请使用“更新现有模板源文件”，避免生成重复模板。',
        code: 'TEMPLATE_ALREADY_IMPORTED',
      }, { status: 409 });
    }
    await ensureSourceHistory(id);
    return Response.json({ ok: true, templateId: id, size: completed.size });
  } catch (error) {
    return authErrorResponse(error);
  }
}
