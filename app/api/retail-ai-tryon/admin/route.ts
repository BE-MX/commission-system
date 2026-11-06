import { ensureDatabase, getD1 } from "../../../../db/runtime";
import { requireAdminApi } from "../../../lib/admin-auth";

export const dynamic = "force-dynamic";

export async function DELETE(request: Request) {
  const denied = await requireAdminApi();
  if (denied) return denied;
  const body = await request.json().catch(() => ({})) as { phone?: string };
  const phone = String(body.phone ?? "").replace(/\D/g, "");
  if (!/^1\d{10}$/.test(phone)) return Response.json({ error: "手机号格式不正确" }, { status: 400 });
  await ensureDatabase();
  const db = getD1();
  const results = await db.batch([
    db.prepare("DELETE FROM retail_ai_tryon_grants WHERE phone = ?").bind(phone),
    db.prepare("DELETE FROM retail_tryon_entitlements WHERE phone = ?").bind(phone),
  ]);
  return Response.json({ reset: true, existed: results.some((result) => Number(result.meta.changes ?? 0) > 0) });
}
