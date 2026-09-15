import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';

export async function GET(request: Request, context: { params: Promise<{ id: string; kind: string }> }) {
  try {
    const user = await requireView('library');
    const { id, kind } = await context.params;
    if (kind !== 'jpg' && kind !== 'psd') return Response.json({ error: '不支持的文件类型。' }, { status: 400 });
    if (kind === 'psd' && !user.views.includes('master')) {
      return Response.json({ error: '业务账号只能下载 JPG 成品。' }, { status: 403 });
    }
    const artifact = await env.DB.prepare(`
      SELECT a.owner_user_id AS ownerUserId, a.name, a.jpg_key AS jpgKey, a.psd_key AS psdKey,
        u.role AS ownerRole
      FROM artifacts a JOIN users u ON u.id = a.owner_user_id
      WHERE a.id = ? AND a.status = 'ready'
    `).bind(id).first<{ ownerUserId: string; ownerRole: string; name: string; jpgKey: string; psdKey: string }>();
    if (!artifact || (artifact.ownerUserId !== user.id && artifact.ownerRole !== 'admin' && user.role !== 'admin')) {
      return Response.json({ error: '没有权限下载这个文件。' }, { status: 403 });
    }
    const object = await env.FILES.get(kind === 'jpg' ? artifact.jpgKey : artifact.psdKey);
    if (!object) return Response.json({ error: '文件不存在。' }, { status: 404 });
    const safeName = artifact.name.replace(/[\\/:*?"<>|]/g, '-');
    const inline = new URL(request.url).searchParams.get('inline') === '1';
    return new Response(object.body, {
      headers: {
        'content-type': kind === 'jpg' ? 'image/jpeg' : 'image/vnd.adobe.photoshop',
        'content-disposition': `${inline ? 'inline' : 'attachment'}; filename*=UTF-8''${encodeURIComponent(`${safeName}.${kind}`)}`,
        'content-length': String(object.size),
        'cache-control': 'private, no-store',
        'x-content-type-options': 'nosniff',
      },
    });
  } catch (error) {
    return authErrorResponse(error);
  }
}
