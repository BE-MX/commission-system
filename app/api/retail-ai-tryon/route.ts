import { getRetailPhone } from "../../lib/retail-session";
import { issueTryonGrant } from "../../lib/retail-tryon-grant";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const phone = await getRetailPhone(request.headers.get("cookie"));
  if (!phone) return Response.json({ error: "请先登录零售商城" }, { status: 401 });

  const grant = await issueTryonGrant(phone);
  if (grant.claim_id) {
    if (grant.expires_at <= new Date().toISOString()) {
      return Response.json({
        error: "该账号的一次 AI 试戴机会已使用，如需再次体验请联系客服",
        code: "trial_used",
        usedAt: grant.claimed_at,
      }, { status: 409, headers: { "Cache-Control": "no-store" } });
    }
    return Response.json({
      status: "claimed",
      available: false,
      grantToken: grant.token,
      claimId: grant.claim_id,
      usedAt: grant.claimed_at,
      expiresAt: grant.expires_at,
    }, { headers: { "Cache-Control": "no-store" } });
  }
  return Response.json({
    status: "active",
    available: true,
    grantToken: grant.token,
    expiresAt: grant.expires_at,
  }, { headers: { "Cache-Control": "no-store" } });
}
