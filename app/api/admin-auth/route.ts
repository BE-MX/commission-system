import { adminAuthResult, adminSessionCookie, clearAdminSessionCookie, verifyAdminPassword } from "../../lib/admin-auth";

export async function GET() {
  const result = await adminAuthResult();
  if (!result.ok) return Response.json({ error: result.error }, { status: result.status });
  return Response.json({ authenticated: true, name: result.user.displayName, email: result.user.email });
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({})) as { password?: string };
  if (!await verifyAdminPassword(body.password ?? "")) {
    return Response.json({ error: "后台管理密码不正确" }, { status: 401 });
  }
  return Response.json({ authenticated: true, name: "管理员" }, { headers: { "Set-Cookie": await adminSessionCookie() } });
}

export async function DELETE() {
  return Response.json({ authenticated: false }, { headers: { "Set-Cookie": clearAdminSessionCookie() } });
}
