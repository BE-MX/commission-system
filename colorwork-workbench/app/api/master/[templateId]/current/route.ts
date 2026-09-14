import { authErrorResponse, requireView } from '@/lib/server/auth';
import { getCurrentSnapshot, masterInventoryErrorResponse } from '@/lib/server/master-inventory';

export async function GET(_request: Request, context: { params: Promise<{ templateId: string }> }) {
  try {
    const user = await requireView('master');
    const { templateId } = await context.params;
    return Response.json(await getCurrentSnapshot(templateId, user), {
      headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' },
    });
  } catch (error) {
    return masterInventoryErrorResponse(error) ?? authErrorResponse(error);
  }
}
