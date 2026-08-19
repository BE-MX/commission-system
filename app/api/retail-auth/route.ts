import { ensureDatabase, getD1 } from "../../../db/runtime";
import { clearRetailCookie, getRetailPhone, readRetailToken, retailCookie } from "../../lib/retail-session";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const phone = await getRetailPhone(request.headers.get("cookie"));
  return phone ? Response.json({ authenticated: true, phone }) : Response.json({ authenticated: false }, { status: 401 });
}

export async function POST(request: Request) {
  await ensureDatabase();
  const body = await request.json() as { phone?: string; code?: string };
  const phone = String(body.phone ?? "").replace(/\D/g, "");
  const code = String(body.code ?? "").trim();
  if (!/^1\d{10}$/.test(phone)) return Response.json({ error: "请输入正确的11位手机号码" }, { status: 400 });
  const now = new Date().toISOString();
  const db = getD1();
  if (code !== "6688") {
    await db.prepare("INSERT INTO retail_access_logs (phone, result, access_at) VALUES (?, ?, ?)").bind(phone, "failed", now).run();
    return Response.json({ error: "验证码不正确，请重新输入" }, { status: 401 });
  }
  const token = crypto.randomUUID();
  const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
  await db.batch([
    db.prepare("INSERT INTO retail_sessions (token, phone, expires_at, created_at) VALUES (?, ?, ?, ?)").bind(token, phone, expiresAt, now),
    db.prepare("INSERT INTO retail_access_logs (phone, result, access_at) VALUES (?, ?, ?)").bind(phone, "success", now),
  ]);
  const secure = new URL(request.url).protocol === "https:";
  return Response.json({ authenticated: true, phone }, { headers: { "Set-Cookie": retailCookie(token, secure) } });
}

export async function DELETE(request: Request) {
  await ensureDatabase();
  const token = readRetailToken(request.headers.get("cookie"));
  if (token) await getD1().prepare("DELETE FROM retail_sessions WHERE token = ?").bind(token).run();
  const secure = new URL(request.url).protocol === "https:";
  return Response.json({ ok: true }, { headers: { "Set-Cookie": clearRetailCookie(secure) } });
}
