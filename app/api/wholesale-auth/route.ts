import { ensureDatabase, getD1 } from "../../../db/runtime";
import { clearSessionCookie, getWholesaleAccount, readSessionToken, sessionCookie } from "../../lib/wholesale-session";
import type { WholesaleAccount } from "../../lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const account = await getWholesaleAccount(request.headers.get("cookie"));
  return account ? Response.json({ authenticated: true, account }) : Response.json({ authenticated: false }, { status: 401 });
}

export async function POST(request: Request) {
  await ensureDatabase();
  const body = await request.json() as { phone?: string; code?: string };
  const phone = String(body.phone ?? "").replace(/\D/g, "");
  const code = String(body.code ?? "").trim();
  const db = getD1();
  const now = new Date().toISOString();
  const account = /^1\d{10}$/.test(phone) ? await db.prepare(`SELECT id, company_name AS companyName, phone, level,
    sales_person AS salesPerson, note FROM wholesale_accounts WHERE phone = ? AND status = 'active' LIMIT 1`)
    .bind(phone).first<WholesaleAccount>() : null;

  if (code !== "6688") {
    await db.prepare("INSERT INTO wholesale_access_logs (account_id, phone, level, sales_person, result, access_at) VALUES (?, ?, ?, ?, ?, ?)")
      .bind(account?.id ?? null, phone || "未填写", account?.level ?? null, account?.salesPerson ?? null, "failed", now).run();
    return Response.json({ error: "验证码不正确，请重新输入" }, { status: 401 });
  }
  if (!account) {
    await db.prepare("INSERT INTO wholesale_access_logs (account_id, phone, level, sales_person, result, access_at) VALUES (?, ?, ?, ?, ?, ?)")
      .bind(null, phone || "未填写", null, null, "unknown", now).run();
    return Response.json({ error: "该手机号还不是已审核的批发商账户，请联系业务员开通" }, { status: 403 });
  }

  const token = crypto.randomUUID();
  const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
  await db.batch([
    db.prepare("INSERT INTO wholesale_sessions (token, account_id, expires_at, created_at) VALUES (?, ?, ?, ?)").bind(token, account.id, expiresAt, now),
    db.prepare("INSERT INTO wholesale_access_logs (account_id, phone, level, sales_person, result, access_at) VALUES (?, ?, ?, ?, ?, ?)").bind(account.id, account.phone, account.level, account.salesPerson, "success", now),
  ]);
  const secure = new URL(request.url).protocol === "https:";
  return Response.json({ authenticated: true, account }, { headers: { "Set-Cookie": sessionCookie(token, secure) } });
}

export async function DELETE(request: Request) {
  await ensureDatabase();
  const token = readSessionToken(request.headers.get("cookie"));
  if (token) await getD1().prepare("DELETE FROM wholesale_sessions WHERE token = ?").bind(token).run();
  const secure = new URL(request.url).protocol === "https:";
  return Response.json({ ok: true }, { headers: { "Set-Cookie": clearSessionCookie(secure) } });
}
