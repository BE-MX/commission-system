import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { readSourceVersion, templateSourceErrorResponse } from '@/lib/server/template-sources';

export async function GET(
  _request: Request,
  context: { params: Promise<{ templateId: string; versionId: string; kind: string }> },
) {
  try {
    await requireView('master');
    const { templateId, versionId, kind } = await context.params;
    if (kind !== 'jpg' && kind !== 'psd') {
      return Response.json({ error: '文件请求无效。' }, { status: 400 });
    }
    const row = await readSourceVersion(templateId, versionId);
    if (!row) return Response.json({ error: '没有找到这个源文件版本。' }, { status: 404 });
    const key = kind === 'jpg' ? row.referenceJpgKey : row.sourcePsdKey;
    const object = await env.FILES.get(key);
    if (!object) return Response.json({ error: '源文件不存在。' }, { status: 404 });
    const name = kind === 'jpg' ? row.referenceJpgName : row.sourcePsdName;
    return new Response(object.body, {
      headers: {
        'content-type': kind === 'jpg' ? 'image/jpeg' : 'image/vnd.adobe.photoshop',
        'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(name)}`,
        'content-length': String(object.size),
        'cache-control': 'private, no-store',
        'x-content-type-options': 'nosniff',
      },
    });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
