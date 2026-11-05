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
  const result = await getD1().prepare("DELETE FROM retail_tryon_entitlements WHERE phone = ?").bind(phone).run();
  return Response.json({ reset: true, existed: Number(result.meta.changes ?? 0) > 0 });
}
