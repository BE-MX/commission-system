import { ensureDatabase, getD1 } from "../../../db/runtime";
import { requireAdminApi } from "../../lib/admin-auth";

export const dynamic = "force-dynamic";

export async function GET() {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  await ensureDatabase();
  const rows = await getD1().prepare(`SELECT s.id, s.name, s.phone, s.role, s.promo_code AS promoCode,
    s.store_code AS storeCode, s.customer_service AS customerService, s.status,
    COUNT(DISTINCT c.id) AS customerCount, COALESCE(SUM(o.amount),0) AS orderAmount,
    COALESCE(SUM(o.commission_amount),0) AS commission
    FROM sales_people s
    LEFT JOIN customer_profiles c ON c.sales_person=s.name
    LEFT JOIN orders o ON o.sales_person=s.name
    GROUP BY s.id ORDER BY orderAmount DESC`).all();
  const referrals = await getD1().prepare(`SELECT id, code, owner_name AS ownerName, visitor_phone AS visitorPhone,
    order_no AS orderNo, amount, commission, status, created_at AS createdAt FROM referrals ORDER BY created_at DESC LIMIT 100`).all();
  return Response.json({ sales: rows.results, referrals: referrals.results });
}

export async function POST(request: Request) {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  await ensureDatabase();
  const body = await request.json() as Record<string, unknown>;
  const name = String(body.name ?? "").trim();
  const phone = String(body.phone ?? "").replace(/\D/g, "");
  if (!name || !/^1\d{10}$/.test(phone)) return Response.json({ error: "请填写销售姓名和正确手机号" }, { status: 400 });
  const token = `${name.slice(0, 1).toUpperCase()}${phone.slice(-4)}`;
  try {
    await getD1().prepare("INSERT INTO sales_people (name, phone, role, promo_code, store_code, customer_service, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)")
      .bind(name, phone, String(body.role ?? "销售顾问"), `SALE-${token}`, `STORE-${token}`, String(body.customerService ?? "小莱客服"), new Date().toISOString()).run();
    return Response.json({ ok: true }, { status: 201 });
  } catch {
    return Response.json({ error: "推广码重复，请更换手机号" }, { status: 409 });
  }
}
