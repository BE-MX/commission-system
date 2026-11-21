import { ensureDatabase, getD1 } from "../../../db/runtime";
import { requireAdminApi } from "../../lib/admin-auth";
import { paidOrderSql } from "../../lib/operating-checks";

export const dynamic = "force-dynamic";

export async function GET() {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  await ensureDatabase();
  const db = getD1();
  const [orders, products, customers, referrals, daily] = await Promise.all([
    db.prepare(`SELECT COUNT(*) AS count,
      SUM(CASE WHEN ${paidOrderSql()} THEN 1 ELSE 0 END) AS paidCount,
      COALESCE(SUM(CASE WHEN ${paidOrderSql()} THEN amount ELSE 0 END),0) AS revenue,
      COALESCE(SUM(CASE WHEN ${paidOrderSql()} THEN commission_amount ELSE 0 END),0) AS commission,
      COALESCE(SUM(CASE WHEN payment_status='待确认付款' AND status NOT IN ('已取消','已关闭') THEN amount ELSE 0 END),0) AS pendingAmount,
      COALESCE(SUM(item_count),0) AS items FROM orders`).first(),
    db.prepare("SELECT COUNT(*) AS count, COALESCE(SUM(stock),0) AS stock, SUM(CASE WHEN stock<25 THEN 1 ELSE 0 END) AS lowStock, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active FROM products").first(),
    db.prepare("SELECT COUNT(*) AS count, SUM(CASE WHEN channel='wholesale' THEN 1 ELSE 0 END) AS wholesale FROM customer_profiles WHERE status='active'").first(),
    db.prepare(`SELECT COUNT(*) AS count, COALESCE(SUM(r.commission),0) AS commission FROM referrals r
      WHERE r.status='待结算' AND EXISTS (SELECT 1 FROM orders o WHERE o.order_no=r.order_no AND ${paidOrderSql("o")})`).first(),
    db.prepare(`SELECT substr(created_at,1,10) AS day, COUNT(*) AS orders,
      COALESCE(SUM(CASE WHEN ${paidOrderSql()} THEN amount ELSE 0 END),0) AS revenue
      FROM orders GROUP BY substr(created_at,1,10) ORDER BY day DESC LIMIT 7`).all(),
  ]);
  return Response.json({ summary: { orders, products, customers, referrals }, daily: daily.results.reverse() });
}
