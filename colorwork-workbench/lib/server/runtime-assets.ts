import { env } from 'cloudflare:workers';
import { RUNTIME_ASSETS } from '@/lib/server/catalog';

type RuntimeAssetRow = { assetKey: string; sha256: string; size: number };

export async function runtimeAssetRows() {
  const result = await env.DB.prepare(`
    SELECT asset_key AS assetKey, sha256, size
    FROM runtime_assets
    ORDER BY asset_key
  `).all<RuntimeAssetRow>();
  return result.results ?? [];
}

export function runtimeAssetsComplete(rows: RuntimeAssetRow[]) {
  const uploaded = new Map(rows.map((row) => [row.assetKey, row]));
  return RUNTIME_ASSETS.every((expected) => {
    const current = uploaded.get(expected.key);
    return current?.sha256 === expected.sha256 && current.size === expected.size;
  });
}

export async function runtimeAssetsReady() {
  return runtimeAssetsComplete(await runtimeAssetRows());
}
