import { authErrorResponse, requireView } from '@/lib/server/auth';
import { getMasterVersion, masterInventoryErrorResponse } from '@/lib/server/master-inventory';

export async function GET(
  _request: Request,
  context: { params: Promise<{ templateId: string; versionId: string }> },
) {
  try {
    const admin = await requireView('master');
    const { templateId, versionId } = await context.params;
    return Response.json(await getMasterVersion(templateId, versionId, admin), {
      headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' },
    });
  } catch (error) {
    return masterInventoryErrorResponse(error) ?? authErrorResponse(error);
  }
}
