import { ensureDatabase, getD1 } from "../../../db/runtime";
import { getRetailPhone } from "../../lib/retail-session";
import { getWholesaleAccount } from "../../lib/wholesale-session";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  await ensureDatabase();
  const mode = new URL(request.url).searchParams.get("mode") === "wholesale" ? "wholesale" : "retail";
  const cookie = request.headers.get("cookie");
  const wholesale = mode === "wholesale" ? await getWholesaleAccount(cookie) : null;
  const retailPhone = mode === "retail" ? await getRetailPhone(cookie) : null;
  if ((mode === "wholesale" && !wholesale) || (mode === "retail" && !retailPhone)) {
    return Response.json({ error: "未登录" }, { status: 401 });
  }
  const db = getD1();
  const phone = wholesale?.phone ?? retailPhone!;
  const now = new Date().toISOString();
  const referralCode = `D-${phone.slice(-4)}`;
  await db.prepare(`INSERT INTO customer_profiles
    (phone, channel, display_name, store_name, level, sales_person, customer_service, note, referral_code, status, created_at, last_login_at)
    VALUES (?, ?, ?, ?, ?, ?, '小莱客服', '', ?, 'active', ?, ?)
    ON CONFLICT(phone) DO UPDATE SET last_login_at=excluded.last_login_at`)
    .bind(phone, mode, wholesale?.companyName ?? "莱莎会员", wholesale?.companyName ?? "", wholesale?.level ?? "retail", wholesale?.salesPerson ?? "林青", referralCode, now, now).run();

  const profile = await db.prepare(`SELECT id, phone, channel, display_name AS displayName, store_name AS storeName,
    level, sales_person AS salesPerson, customer_service AS customerService, note, referral_code AS referralCode,
    status, created_at AS createdAt, last_login_at AS lastLoginAt FROM customer_profiles WHERE phone=? LIMIT 1`).bind(phone).first();
  const orders = await db.prepare(`SELECT id, order_no AS orderNo, status, payment_status AS paymentStatus,
    logistics_company AS logisticsCompany, tracking_no AS trackingNo, logistics_status AS logisticsStatus,
    item_count AS itemCount, amount, created_at AS createdAt FROM orders WHERE customer_phone=? ORDER BY created_at DESC LIMIT 20`).bind(phone).all();
  const promotions = await db.prepare(`SELECT id, title, audience, benefit_type AS benefitType, benefit_value AS benefitValue,
    description, status, ends_at AS endsAt FROM promotions WHERE status='active' ORDER BY id`).all();
  const salespersonName = wholesale?.salesPerson ?? (profile as { salesPerson?: string } | null)?.salesPerson ?? "林青";
  const salesperson = await db.prepare(`SELECT id, name, phone, role, promo_code AS promoCode,
    store_code AS storeCode, customer_service AS customerService FROM sales_people WHERE name=? AND status='active' LIMIT 1`).bind(salespersonName).first();
  return Response.json({
    profile,
    orders: orders.results,
    promotions: promotions.results,
    salesperson,
    distributor: { eligible: orders.results.length > 0, referralCode, commissionRate: 3 },
  });
}
