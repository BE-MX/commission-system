import { adminAuthResult } from "../../lib/admin-auth";

export async function GET() {
  const result = await adminAuthResult();
  if (!result.ok) return Response.json({ error: result.error }, { status: result.status });
  return Response.json({ authenticated: true, name: result.user.displayName, email: result.user.email });
}
