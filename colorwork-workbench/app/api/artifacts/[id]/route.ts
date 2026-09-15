import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';

export async function DELETE(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    await requireView('library');
    const { id } = await context.params;
    const artifact = await env.DB.prepare(`
      SELECT id, jpg_key AS jpgKey, psd_key AS psdKey, status
      FROM artifacts WHERE id = ?
    `).bind(id).first<{ id: string; jpgKey: string; psdKey: string; status: string }>();
    if (!artifact) return Response.json({ error: '成品不存在。' }, { status: 404 });
    if (artifact.status === 'archived') return Response.json({ artifact: { id, status: 'archived' } });
    await env.DB.prepare(`UPDATE artifacts SET status = 'archived', updated_at = ? WHERE id = ?`)
      .bind(new Date().toISOString(), id).run();
    return Response.json({ artifact: { id, status: 'archived' } });
  } catch (error) {
    return authErrorResponse(error);
  }
}

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const user = await requireView('library');
    const { id } = await context.params;
    const artifact = await env.DB.prepare(`
      SELECT a.id, a.name, a.source_template_id AS templateId,
        a.source_artifact_id AS sourceArtifactId, a.config_json AS configJson,
        a.owner_user_id AS ownerUserId, u.role AS ownerRole, a.status
      FROM artifacts a JOIN users u ON u.id = a.owner_user_id
      WHERE a.id = ?
    `).bind(id).first<{
      id: string; name: string; templateId: string; sourceArtifactId: string | null;
      configJson: string; ownerUserId: string; ownerRole: string; status: string;
    }>();
    if (!artifact || artifact.status !== 'ready' || (
      artifact.ownerUserId !== user.id && artifact.ownerRole !== 'admin' && user.role !== 'admin'
    )) {
      return Response.json({ error: '没有权限读取这个源文件。' }, { status: 403 });
    }
    let config: unknown = null;
    try { config = JSON.parse(artifact.configJson); } catch { config = null; }
    return Response.json({
      artifact: {
        id: artifact.id,
        name: artifact.name,
        templateId: artifact.templateId,
        sourceArtifactId: artifact.sourceArtifactId,
        config,
      },
    }, { headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' } });
  } catch (error) {
    return authErrorResponse(error);
  }
}

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const user = await requireView('inventory');
    const { id } = await context.params;
    const input: { status?: unknown; jpgOnly?: unknown } = await request.json<{ status?: unknown; jpgOnly?: unknown }>().catch(() => ({}));
    const artifact = await env.DB.prepare(`
      SELECT owner_user_id AS ownerUserId, jpg_key AS jpgKey, psd_key AS psdKey, status
      FROM artifacts WHERE id = ?
    `).bind(id).first<{ ownerUserId: string; jpgKey: string; psdKey: string; status: string }>();
    if (!artifact || artifact.ownerUserId !== user.id) return Response.json({ error: '没有权限修改这个文件。' }, { status: 403 });
    if (input.status === 'failed') {
      if (artifact.status === 'failed') {
        return Response.json({ artifact: { id, status: 'failed' } });
      }
      if (artifact.status !== 'uploading' && artifact.status !== 'psd_uploading') {
        return Response.json({ error: '这个文件已经封存，不能再标记为失败。' }, { status: 409 });
      }
      const failed = await env.DB.prepare(`
        UPDATE artifacts SET status = 'failed', updated_at = ?
        WHERE id = ? AND owner_user_id = ? AND status IN ('uploading', 'psd_uploading')
      `).bind(new Date().toISOString(), id, user.id).run();
      if (!failed.meta.changes) {
        return Response.json({ error: '这个文件已被其他操作更新，请刷新。' }, { status: 409 });
      }
      await env.FILES.delete([artifact.jpgKey, artifact.psdKey]);
      return Response.json({ artifact: { id, status: 'failed' } });
    }
    if (input.jpgOnly === true) {
      if (artifact.status !== 'uploading') {
        return Response.json({ error: '这个文件已经结束上传。' }, { status: 409 });
      }
      const jpg = await env.FILES.head(artifact.jpgKey);
      if (!jpg) return Response.json({ error: 'JPG 尚未上传完成。' }, { status: 409 });
      const completed = await env.DB.prepare(`
        UPDATE artifacts SET status = 'ready', jpg_size = ?, psd_size = 0, updated_at = ?
        WHERE id = ? AND owner_user_id = ? AND status = 'uploading'
      `).bind(jpg.size, new Date().toISOString(), id, user.id).run();
      if (!completed.meta.changes) return Response.json({ error: '这个文件已被其他操作更新，请刷新。' }, { status: 409 });
      return Response.json({ artifact: { id, status: 'ready', jpgSize: jpg.size, psdSize: 0 } });
    }
    if (artifact.status !== 'psd_uploading') {
      return Response.json({ error: '这个文件已经结束上传。' }, { status: 409 });
    }
    const [jpg, psd] = await Promise.all([env.FILES.head(artifact.jpgKey), env.FILES.head(artifact.psdKey)]);
    if (!jpg || !psd) return Response.json({ error: 'JPG 或 PSD 尚未上传完成。' }, { status: 409 });
    const completed = await env.DB.prepare(`
      UPDATE artifacts SET status = 'ready', jpg_size = ?, psd_size = ?, updated_at = ?
      WHERE id = ? AND owner_user_id = ? AND status = 'psd_uploading'
    `).bind(jpg.size, psd.size, new Date().toISOString(), id, user.id).run();
    if (!completed.meta.changes) return Response.json({ error: '这个文件已被其他操作更新，请刷新。' }, { status: 409 });
    return Response.json({ artifact: { id, status: 'ready', jpgSize: jpg.size, psdSize: psd.size } });
  } catch (error) {
    return authErrorResponse(error);
  }
}
