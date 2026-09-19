import { getFiles } from '@/lib/server/storage';
import { env } from 'cloudflare:workers';

/** Readiness only: no accounts or assets are exposed, no data is written. */
export async function GET() {
  try {
    await env.DB.prepare('SELECT views_json FROM local_sessions LIMIT 0').all();
    await env.DB.prepare('SELECT asset_key FROM runtime_assets LIMIT 0').all();
    await getFiles().head('__ark_readiness__');
    return Response.json({ status: 'ok', module: 'colorwork' }, {
      headers: { 'cache-control': 'no-store' },
    });
  } catch {
    return Response.json({ status: 'unavailable', module: 'colorwork' }, { status: 503 });
  }
}
