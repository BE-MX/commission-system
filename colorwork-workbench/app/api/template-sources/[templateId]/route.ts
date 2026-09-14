import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  createSourceUpload,
  listSourceVersions,
  templateSourceErrorResponse,
} from '@/lib/server/template-sources';

const privateHeaders = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };

export async function GET(_request: Request, context: { params: Promise<{ templateId: string }> }) {
  try {
    const admin = await requireView('master');
    const { templateId } = await context.params;
    return Response.json(await listSourceVersions(templateId, admin), { headers: privateHeaders });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}

export async function POST(request: Request, context: { params: Promise<{ templateId: string }> }) {
  try {
    const admin = await requireView('master');
    const { templateId } = await context.params;
    const input = await request.json().catch(() => null);
    return Response.json(await createSourceUpload(templateId, admin, input), {
      status: 201,
      headers: privateHeaders,
    });
  } catch (error) {
    return templateSourceErrorResponse(error) ?? authErrorResponse(error);
  }
}

