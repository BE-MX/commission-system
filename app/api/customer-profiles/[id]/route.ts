import { ensureDatabase, getD1 } from "../../../../db/runtime";
import { requireAdminApi } from "../../../lib/admin-auth";

export async function PUT(request: Request, context: { params: Promise<{ id: string }> }) {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  await ensureDatabase();
  const { id } = await context.params;
  const body = await request.json() as Record<string, unknown>;
  const db = getD1();
  const current = await db.prepare("SELECT phone, channel FROM customer_profiles WHERE id=?").bind(Number(id)).first<{ phone: string; channel: string }>();
  if (!current) return Response.json({ error: "客户不存在" }, { status: 404 });
  const values = {
    displayName: String(body.displayName ?? "莱莎会员").trim(), storeName: String(body.storeName ?? "").trim(),
    level: ["retail", "a", "b"].includes(String(body.level)) ? String(body.level) : "retail",
    salesPerson: String(body.salesPerson ?? "未分配").trim(), customerService: String(body.customerService ?? "小莱客服").trim(),
    note: String(body.note ?? "").trim(), status: body.status === "disabled" ? "disabled" : "active",
  };
  await db.prepare("UPDATE customer_profiles SET display_name=?, store_name=?, level=?, sales_person=?, customer_service=?, note=?, status=? WHERE id=?")
    .bind(values.displayName, values.storeName, values.level, values.salesPerson, values.customerService, values.note, values.status, Number(id)).run();
  if (current.channel === "wholesale") {
    await db.prepare("UPDATE wholesale_accounts SET company_name=?, level=?, sales_person=?, note=?, status=? WHERE phone=?")
      .bind(values.storeName || values.displayName, values.level === "b" ? "b" : "a", values.salesPerson, values.note, values.status, current.phone).run();
  }
  return Response.json({ ok: true });
}
