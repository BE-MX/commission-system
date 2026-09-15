import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import { SERVER_TEMPLATES } from '@/lib/server/catalog';
import { isJpeg, JPG_LIMIT } from '@/lib/server/uploads';

export async function PUT(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    await requireView('master');
    const { id } = await context.params;
    if (!SERVER_TEMPLATES.some((item) => item.id === id)) return Response.json({ error: '模板编号无效。' }, { status: 400 });
    const versionId = new URL(request.url).searchParams.get('version') || '';
    if (!/^[0-9a-f-]{36}$/i.test(versionId)) return Response.json({ error: '模板版本无效。' }, { status: 400 });
    const declaredSize = Number(request.headers.get('content-length') || 0);
    if (declaredSize > JPG_LIMIT) {
      return Response.json({ error: 'JPG 文件不能为空，且不得超过 25 MB。' }, { status: 400 });
    }
    const buffer = await request.arrayBuffer();
    const size = buffer.byteLength;
    if (!size || size > JPG_LIMIT || !isJpeg(new Uint8Array(buffer))) {
      return Response.json({ error: 'JPG 文件格式无效，或文件超过 25 MB。' }, { status: 400 });
    }
    const key = `templates/${id}/versions/${versionId}/reference.jpg`;
    await env.FILES.put(key, buffer, { httpMetadata: { contentType: 'image/jpeg' } });
    return Response.json({ ok: true, key, size });
  } catch (error) {
    return authErrorResponse(error);
  }
}
