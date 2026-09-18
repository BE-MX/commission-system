import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  replaceCandidateColorAsset,
  templateSourceErrorResponse,
} from '@/lib/server/template-sources';

const ASSET_LIMIT = 16 * 1024 * 1024;

function isPng(bytes: Uint8Array) {
  return bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
    bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a;
}

export async function PUT(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string; colorId: string }> },
) {
  try {
    const admin = await requireView('master');
    const { templateId, versionId, colorId } = await context.params;
    const contentLength = Number(request.headers.get('content-length') || 0);
    if (contentLength > ASSET_LIMIT) {
      return Response.json({ error: '单个新增色块图不得超过 16 MB。' }, { status: 400 });
    }
    const buffer = await request.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > ASSET_LIMIT || !isPng(new Uint8Array(buffer))) {
      return Response.json({ error: '新增色块图必须是有效的 PNG，且不得超过 16 MB。' }, { status: 400 });
    }
    return Response.json(
      await replaceCandidateColorAsset(templateId, versionId, decodeURIComponent(colorId), buffer, admin),
      { headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' } },
    );
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
