import { authErrorResponse, requireView } from '@/lib/server/auth';
import { runtimeAssetRows, runtimeAssetsComplete } from '@/lib/server/runtime-assets';

export async function GET() {
  try {
    await requireView('master');
    const assets = await runtimeAssetRows();
    return Response.json(
      { ready: runtimeAssetsComplete(assets), assets },
      { headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' } },
    );
  } catch (error) {
    return authErrorResponse(error);
  }
}
