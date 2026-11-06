import { findActiveTryonGrant, readTryonToken } from "../../../lib/retail-tryon-grant";
import { requireRetailTryonService } from "../../../lib/retail-tryon-service";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (!requireRetailTryonService(request)) return Response.json({ active: false }, { status: 401 });
  const token = readTryonToken(request);
  if (!token) return Response.json({ active: false }, { status: 401 });
  const grant = await findActiveTryonGrant(token);
  if (!grant) return Response.json({ active: false }, { status: 401 });
  return Response.json({
    active: true,
    subject: `retail:${grant.phone}`,
    expiresAt: grant.expires_at,
    claimId: grant.claim_id,
  }, { headers: { "Cache-Control": "no-store" } });
}
