import { env } from 'cloudflare:workers';
import { authErrorResponse, requireApiUser } from '@/lib/server/auth';
import {
  mayReadSourceAsset,
  readSourceVersion,
  sourceObjectKey,
  templateSourceErrorResponse,
} from '@/lib/server/template-sources';

export async function GET(
  _request: Request,
  context: { params: Promise<{ versionId: string; path: string[] }> },
) {
  try {
    const user = await requireApiUser();
    const { versionId, path } = await context.params;
    const row = await env.DB.prepare(`
      SELECT template_id AS templateId FROM template_source_versions WHERE id = ?
    `).bind(versionId).first<{ templateId: string }>();
    if (!row) return Response.json({ error: '源文件素材不存在。' }, { status: 404 });
    const source = await readSourceVersion(row.templateId, versionId);
    const assetName = path.map(decodeURIComponent).join('/');
    const businessAsset = assetName === 'base.png' || assetName === 'hot.png' || /^colors\/[a-z0-9][a-z0-9_-]{0,80}\.png$/.test(assetName);
    if (!source || !(await mayReadSourceAsset(source, user)) || (user.role !== 'admin' && !businessAsset)) {
      return Response.json({ error: '没有权限读取这个源文件素材。' }, { status: 403 });
    }
    const object = await env.FILES.get(sourceObjectKey(source, assetName));
    if (!object) return Response.json({ error: '源文件素材不存在。' }, { status: 404 });
    return new Response(object.body, {
      headers: {
        'content-type': object.httpMetadata?.contentType || (assetName.endsWith('.jpg') ? 'image/jpeg' : 'image/png'),
        'content-length': String(object.size),
        'cache-control': 'private, max-age=31536000, immutable',
        'x-content-type-options': 'nosniff',
      },
    });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
