import { ensureDatabase, getD1 } from "../../../../db/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const authorization = request.headers.get("authorization") ?? "";
  const match = authorization.match(/^TryOn\s+([0-9a-f-]{36})$/i);
  if (!match) return Response.json({ active: false }, { status: 401 });

  await ensureDatabase();
  const row = await getD1().prepare(`SELECT phone, grant_expires_at
    FROM retail_tryon_entitlements WHERE grant_token = ? LIMIT 1`)
    .bind(match[1]).first<{ phone: string; grant_expires_at: string }>();
  if (!row || Date.parse(row.grant_expires_at) <= Date.now()) {
    return Response.json({ active: false }, { status: 401 });
  }
  return Response.json({ active: true, subject: `retail:${row.phone}`, expiresAt: row.grant_expires_at }, {
    headers: { "Cache-Control": "no-store" },
  });
}
