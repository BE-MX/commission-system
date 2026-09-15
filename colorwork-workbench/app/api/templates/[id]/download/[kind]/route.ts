import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { SERVER_TEMPLATES } from '@/lib/server/catalog';
import { ensureSourceHistory } from '@/lib/server/template-sources';

export async function GET(request: Request, context: { params: Promise<{ id: string; kind: string }> }) {
  try {
    const { id, kind } = await context.params;
    if ((kind !== 'jpg' && kind !== 'psd') || !SERVER_TEMPLATES.some((item) => item.id === id)) {
      return Response.json({ error: '文件请求无效。' }, { status: 400 });
    }
    if (kind === 'psd') await requireView('master');
    else await requireView('library');
    const initialRow = await env.DB.prepare(`
      SELECT source_psd_key AS psdKey, reference_jpg_key AS jpgKey,
        source_psd_name AS psdName, reference_jpg_name AS jpgName
      FROM template_files WHERE template_id = ?
    `).bind(id).first<{ psdKey: string; jpgKey: string; psdName: string; jpgName: string }>();
    const currentSource = (await ensureSourceHistory(id)).current;
    const row = currentSource ? {
      psdKey: currentSource.sourcePsdKey,
      jpgKey: currentSource.referenceJpgKey,
      psdName: currentSource.sourcePsdName,
      jpgName: currentSource.referenceJpgName,
    } : initialRow;
    if (!row) return Response.json({ error: '模板文件尚未导入。' }, { status: 404 });
    const object = await env.FILES.get(kind === 'jpg' ? row.jpgKey : row.psdKey);
    if (!object) return Response.json({ error: '文件不存在。' }, { status: 404 });
    const name = kind === 'jpg' ? row.jpgName : row.psdName;
    const inline = new URL(request.url).searchParams.get('inline') === '1';
    return new Response(object.body, {
      headers: {
        'content-type': kind === 'jpg' ? 'image/jpeg' : 'image/vnd.adobe.photoshop',
        'content-disposition': `${inline ? 'inline' : 'attachment'}; filename*=UTF-8''${encodeURIComponent(name)}`,
        'content-length': String(object.size),
        'cache-control': 'private, no-store',
        'x-content-type-options': 'nosniff',
      },
    });
  } catch (error) {
    return authErrorResponse(error);
  }
}
