import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  enableTemplateSourceVersion,
  masterInventoryErrorResponse,
} from '@/lib/server/master-inventory';
import { templateSourceErrorResponse } from '@/lib/server/template-sources';

const privateHeaders = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };

export async function POST(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string }> },
) {
  try {
    const admin = await requireView('master');
    const { templateId, versionId } = await context.params;
    const input = await request.json().catch(() => null);
    return Response.json(await enableTemplateSourceVersion(templateId, versionId, admin, input), {
      status: 201,
      headers: privateHeaders,
    });
  } catch (error) {
    return masterInventoryErrorResponse(error) ?? templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}
