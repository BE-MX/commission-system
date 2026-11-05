import { ensureDatabase, getD1 } from "../../../../db/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const authorization = request.headers.get("authorization") ?? "";
  const match = authorization.match(/^TryOn\s+([0-9a-f-]{36})$/i);
  if (!match) return Response.json({ claimed: false }, { status: 401 });
  const body = await request.json().catch(() => ({})) as { claimId?: string };
  const claimId = String(body.claimId ?? "").trim();
  if (!/^expo-session:\d{1,20}$/.test(claimId)) {
    return Response.json({ claimed: false }, { status: 400 });
  }

  await ensureDatabase();
  const now = new Date().toISOString();
  const db = getD1();
  await db.prepare(`UPDATE retail_tryon_entitlements SET generation_claim = ?, updated_at = ?
    WHERE grant_token = ? AND grant_expires_at > ? AND generation_claim IS NULL`)
    .bind(claimId, now, match[1], now).run();
  const row = await db.prepare(`SELECT generation_claim FROM retail_tryon_entitlements
    WHERE grant_token = ? AND grant_expires_at > ? LIMIT 1`)
    .bind(match[1], now).first<{ generation_claim: string | null }>();
  if (!row) return Response.json({ claimed: false }, { status: 401 });
  if (row.generation_claim !== claimId) {
    return Response.json({ claimed: false }, { status: 409 });
  }
  return Response.json({ claimed: true }, { headers: { "Cache-Control": "no-store" } });
}
