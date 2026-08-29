import { ensureDatabase, getD1 } from "../../../db/runtime";

export const dynamic = "force-dynamic";

export async function GET() {
  await ensureDatabase();
  const rows = await getD1().prepare(`SELECT id, company_name AS companyName, phone, level,
    sales_person AS salesPerson, note FROM wholesale_accounts WHERE status = 'active' ORDER BY id DESC`).all();
  return Response.json({ accounts: rows.results });
}

export async function POST(request: Request) {
  await ensureDatabase();
  const body = await request.json() as Record<string, unknown>;
  const companyName = String(body.companyName ?? "").trim();
  const phone = String(body.phone ?? "").replace(/\D/g, "");
  const level = body.level === "b" ? "b" : "a";
  const salesPerson = String(body.salesPerson ?? "未分配").trim() || "未分配";
  const note = String(body.note ?? "").trim();
  if (!companyName) return Response.json({ error: "请填写批发商或门店名称" }, { status: 400 });
  if (!/^1\d{10}$/.test(phone)) return Response.json({ error: "请填写正确的11位手机号" }, { status: 400 });
  try {
    const db = getD1();
    const now = new Date().toISOString();
    const row = await db.prepare(`INSERT INTO wholesale_accounts
      (company_name, phone, level, sales_person, note, status, created_at)
      VALUES (?, ?, ?, ?, ?, 'active', ?) RETURNING id`)
      .bind(companyName, phone, level, salesPerson, note, now).first<{ id: number }>();
    await db.prepare(`INSERT INTO customer_profiles
      (phone, channel, display_name, store_name, level, sales_person, customer_service, note, referral_code, status, created_at)
      VALUES (?, 'wholesale', ?, ?, ?, ?, '小莱客服', ?, ?, 'active', ?)
      ON CONFLICT(phone) DO UPDATE SET display_name=excluded.display_name, store_name=excluded.store_name,
        level=excluded.level, sales_person=excluded.sales_person, note=excluded.note, status='active'`)
      .bind(phone, companyName, companyName, level, salesPerson, note, `D-${phone.slice(-4)}`, now).run();
    return Response.json({ id: row?.id }, { status: 201 });
  } catch {
    return Response.json({ error: "该手机号已经建立过批发商账户" }, { status: 409 });
  }
}
