import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  getInventorySnapshot,
  masterInventoryErrorResponse,
} from '@/lib/server/master-inventory';

const privateHeaders = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const user = await requireView('library');
    const { id } = await context.params;
    return Response.json(await getInventorySnapshot(id, user), { headers: privateHeaders });
  } catch (error) {
    return masterInventoryErrorResponse(error) ?? authErrorResponse(error);
  }
}
