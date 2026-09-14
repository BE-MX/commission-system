import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  getSourceVersionDetail,
  markSourceFailed,
  templateSourceErrorResponse,
} from '@/lib/server/template-sources';

const privateHeaders = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };

export async function GET(
  _request: Request,
  context: { params: Promise<{ templateId: string; versionId: string }> },
) {
  try {
    const admin = await requireView('master');
    const { templateId, versionId } = await context.params;
    return Response.json(await getSourceVersionDetail(templateId, versionId, admin), { headers: privateHeaders });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string }> },
) {
  try {
    const admin = await requireView('master');
    const { templateId, versionId } = await context.params;
    const input: { failureReason?: unknown } = await request.json<{ failureReason?: unknown }>().catch(() => ({}));
    return Response.json(await markSourceFailed(templateId, versionId, admin, input.failureReason), { headers: privateHeaders });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
