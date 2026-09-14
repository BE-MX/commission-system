import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { SERVER_TEMPLATES } from '@/lib/server/catalog';
import { PSD_PART_SIZE } from '@/lib/server/uploads';

export async function POST(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    await requireView('master');
    const { id } = await context.params;
    if (!SERVER_TEMPLATES.some((item) => item.id === id)) return Response.json({ error: '模板编号无效。' }, { status: 400 });
    const existing = await env.DB.prepare('SELECT 1 AS found FROM template_files WHERE template_id = ?')
      .bind(id).first<{ found: number }>();
    if (existing) {
      return Response.json({
        error: '这个产品与 Radio 已有源文件，请使用“更新现有模板源文件”，避免生成重复模板。',
        code: 'TEMPLATE_ALREADY_IMPORTED',
      }, { status: 409 });
    }
    const versionId = crypto.randomUUID();
    const key = `templates/${id}/versions/${versionId}/source.psd`;
    const upload = await env.FILES.createMultipartUpload(key, {
      httpMetadata: { contentType: 'image/vnd.adobe.photoshop' },
    });
    return Response.json({ uploadId: upload.uploadId, versionId, partSize: PSD_PART_SIZE });
  } catch (error) {
    return authErrorResponse(error);
  }
}
