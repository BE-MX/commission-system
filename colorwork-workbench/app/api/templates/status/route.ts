import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';

export async function GET() {
  try {
    await requireView('master');
    const result = await env.DB.prepare(`
      SELECT template_id AS templateId, source_psd_name AS psdName,
        reference_jpg_name AS jpgName, updated_at AS updatedAt
      FROM template_files ORDER BY template_id
    `).all();
    return Response.json({ templates: result.results }, {
      headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' },
    });
  } catch (error) {
    return authErrorResponse(error);
  }
}
