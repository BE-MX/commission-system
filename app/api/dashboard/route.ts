import { ensureDatabase, getD1 } from "../../../db/runtime";

export const dynamic = "force-dynamic";

export async function GET() {
  await ensureDatabase();
  const db = getD1();
  const [orders, products, customers, referrals, daily] = await Promise.all([
    db.prepare("SELECT COUNT(*) AS count, COALESCE(SUM(amount),0) AS revenue, COALESCE(SUM(commission_amount),0) AS commission, COALESCE(SUM(item_count),0) AS items FROM orders").first(),
    db.prepare("SELECT COUNT(*) AS count, COALESCE(SUM(stock),0) AS stock, SUM(CASE WHEN stock<25 THEN 1 ELSE 0 END) AS lowStock, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active FROM products").first(),
    db.prepare("SELECT COUNT(*) AS count, SUM(CASE WHEN channel='wholesale' THEN 1 ELSE 0 END) AS wholesale FROM customer_profiles WHERE status='active'").first(),
    db.prepare("SELECT COUNT(*) AS count, COALESCE(SUM(commission),0) AS commission FROM referrals").first(),
    db.prepare(`SELECT substr(created_at,1,10) AS day, COUNT(*) AS orders, COALESCE(SUM(amount),0) AS revenue
      FROM orders GROUP BY substr(created_at,1,10) ORDER BY day DESC LIMIT 7`).all(),
  ]);
  return Response.json({ summary: { orders, products, customers, referrals }, daily: daily.results.reverse() });
}
