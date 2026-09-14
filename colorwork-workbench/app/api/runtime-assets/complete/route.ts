import { authErrorResponse, requireView } from '@/lib/server/auth';
import { RUNTIME_ASSETS } from '@/lib/server/catalog';
import { runtimeAssetRows, runtimeAssetsComplete } from '@/lib/server/runtime-assets';

export async function POST() {
  try {
    await requireView('master');
    const assets = await runtimeAssetRows();
    if (!runtimeAssetsComplete(assets)) {
      return Response.json(
        { error: `工作台素材尚未完整上传，应为 ${RUNTIME_ASSETS.length} 个。` },
        { status: 409, headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' } },
      );
    }
    return Response.json(
      { ok: true, ready: true, count: RUNTIME_ASSETS.length },
      { headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' } },
    );
  } catch (error) {
    return authErrorResponse(error);
  }
}
