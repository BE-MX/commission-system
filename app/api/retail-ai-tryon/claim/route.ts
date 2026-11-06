import { claimTryonGrant, readTryonToken } from "../../../lib/retail-tryon-grant";
import { requireRetailTryonService } from "../../../lib/retail-tryon-service";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  if (!requireRetailTryonService(request)) return Response.json({ error: "服务身份无效" }, { status: 401 });
  const token = readTryonToken(request);
  if (!token) return Response.json({ error: "试戴授权无效" }, { status: 401 });
  const body = await request.json().catch(() => ({})) as { claimId?: string };
  const claimId = String(body.claimId ?? "");
  if (!/^expo-session:\d{1,20}$/.test(claimId)) {
    return Response.json({ error: "试戴请求标识无效" }, { status: 400 });
  }

  const grant = await claimTryonGrant(token, claimId);
  if (!grant) return Response.json({ error: "试戴授权已过期" }, { status: 401 });
  if (grant.claim_id !== claimId) {
    return Response.json({ error: "本账号的一次 AI 试戴机会已使用" }, { status: 409 });
  }
  return Response.json({ claimed: true, claimId, claimedAt: grant.claimed_at });
}
