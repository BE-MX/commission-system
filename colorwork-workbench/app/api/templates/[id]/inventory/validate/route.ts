import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  masterInventoryErrorResponse,
  validateInventoryForGeneration,
} from '@/lib/server/master-inventory';

const privateHeaders = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const user = await requireView('library');
    const { id } = await context.params;
    let input: unknown;
    try {
      input = await request.json();
    } catch {
      return Response.json(
        { error: '请求格式无效。', code: 'INVALID_JSON' },
        { status: 400, headers: privateHeaders },
      );
    }
    return Response.json(await validateInventoryForGeneration(id, user, input), {
      headers: privateHeaders,
    });
  } catch (error) {
    return masterInventoryErrorResponse(error) ?? authErrorResponse(error);
  }
}
