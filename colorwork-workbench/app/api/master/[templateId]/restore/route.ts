import { authErrorResponse, requireView } from '@/lib/server/auth';
import { masterInventoryErrorResponse, restoreMasterVersion } from '@/lib/server/master-inventory';

const privateHeaders = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };

export async function POST(request: Request, context: { params: Promise<{ templateId: string }> }) {
  try {
    const admin = await requireView('master');
    const { templateId } = await context.params;
    let input: unknown;
    try {
      input = await request.json();
    } catch {
      return Response.json(
        { error: '请求格式无效。', code: 'INVALID_JSON' },
        { status: 400, headers: privateHeaders },
      );
    }
    return Response.json(await restoreMasterVersion(templateId, admin, input), {
      status: 201,
      headers: privateHeaders,
    });
  } catch (error) {
    return masterInventoryErrorResponse(error) ?? authErrorResponse(error);
  }
}
