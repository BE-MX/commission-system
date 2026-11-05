import { ensureDatabase, getD1 } from "../../../db/runtime";
import { getRetailPhone } from "../../lib/retail-session";

export const dynamic = "force-dynamic";

const GRANT_LIFETIME_MS = 4 * 60 * 60 * 1000;

type EntitlementRow = {
  phone: string;
  grant_token: string;
  grant_expires_at: string;
  used_at: string;
};

async function authenticatedPhone(request: Request) {
  const phone = await getRetailPhone(request.headers.get("cookie"));
  if (!phone) return null;
  await ensureDatabase();
  return phone;
}

function entitlementResponse(row: EntitlementRow | null) {
  if (!row) return Response.json({ status: "available", available: true });
  const active = Date.parse(row.grant_expires_at) > Date.now();
  return Response.json({
    status: active ? "active" : "used",
    available: false,
    usedAt: row.used_at,
    expiresAt: row.grant_expires_at,
    ...(active ? { grantToken: row.grant_token } : {}),
  });
}

export async function GET(request: Request) {
  const phone = await authenticatedPhone(request);
  if (!phone) return Response.json({ error: "请先登录零售商城" }, { status: 401 });
  const row = await getD1().prepare(`SELECT phone, grant_token, grant_expires_at, used_at
    FROM retail_tryon_entitlements WHERE phone = ? LIMIT 1`).bind(phone).first<EntitlementRow>();
  return entitlementResponse(row ?? null);
}

export async function POST(request: Request) {
  const phone = await authenticatedPhone(request);
  if (!phone) return Response.json({ error: "请先登录零售商城" }, { status: 401 });

  const now = new Date();
  const grantToken = crypto.randomUUID();
  const expiresAt = new Date(now.getTime() + GRANT_LIFETIME_MS).toISOString();
  await getD1().prepare(`INSERT OR IGNORE INTO retail_tryon_entitlements
    (phone, grant_token, grant_expires_at, used_at, updated_at) VALUES (?, ?, ?, ?, ?)`)
    .bind(phone, grantToken, expiresAt, now.toISOString(), now.toISOString()).run();

  const row = await getD1().prepare(`SELECT phone, grant_token, grant_expires_at, used_at
    FROM retail_tryon_entitlements WHERE phone = ? LIMIT 1`).bind(phone).first<EntitlementRow>();
  if (!row) return Response.json({ error: "免费资格领取失败，请联系专属客服" }, { status: 500 });
  return entitlementResponse(row);
}
