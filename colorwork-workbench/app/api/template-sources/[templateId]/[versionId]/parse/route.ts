import { authErrorResponse, requireView } from '@/lib/server/auth';
import { recordParsedSource, templateSourceErrorResponse } from '@/lib/server/template-sources';

export async function POST(
  request: Request,
  context: { params: Promise<{ templateId: string; versionId: string }> },
) {
  try {
    const admin = await requireView('master');
    const { templateId, versionId } = await context.params;
    const input = await request.json().catch(() => null);
    return Response.json(await recordParsedSource(templateId, versionId, admin, input), {
      headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' },
    });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}

