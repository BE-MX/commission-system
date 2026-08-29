import { ensureDatabase, getD1 } from "../../../db/runtime";
import { getRetailPhone } from "../../lib/retail-session";
import { getWholesaleAccount } from "../../lib/wholesale-session";
import type { Product } from "../../lib/types";

export const dynamic = "force-dynamic";

const orderSelect = `SELECT id, order_no AS orderNo, channel, customer_phone AS customerPhone,
  customer_name AS customerName, level, sales_person AS salesPerson, status,
  payment_status AS paymentStatus, logistics_company AS logisticsCompany, tracking_no AS trackingNo,
  logistics_status AS logisticsStatus, item_count AS itemCount, amount,
  commission_amount AS commissionAmount, created_at AS createdAt, shipped_at AS shippedAt FROM orders`;

export async function GET() {
  await ensureDatabase();
  const rows = await getD1().prepare(`${orderSelect} ORDER BY created_at DESC LIMIT 200`).all();
  return Response.json({ orders: rows.results });
}

export async function POST(request: Request) {
  await ensureDatabase();
  const body = await request.json() as { mode?: "retail" | "wholesale"; lines?: Array<{ id: number; quantity: number }>; promoCode?: string };
  const mode = body.mode === "wholesale" ? "wholesale" : "retail";
  const cookie = request.headers.get("cookie");
  const wholesale = mode === "wholesale" ? await getWholesaleAccount(cookie) : null;
  const retailPhone = mode === "retail" ? await getRetailPhone(cookie) : null;
  if ((mode === "wholesale" && !wholesale) || (mode === "retail" && !retailPhone)) {
    return Response.json({ error: "登录已失效，请重新登录" }, { status: 401 });
  }
  const lines = (body.lines ?? []).filter((line) => Number.isInteger(line.id) && line.quantity > 0 && line.quantity <= 100);
  if (!lines.length) return Response.json({ error: "购物车中没有商品" }, { status: 400 });

  const db = getD1();
  const ids = [...new Set(lines.map((line) => line.id))];
  const placeholders = ids.map(() => "?").join(",");
  const result = await db.prepare(`SELECT id, name, retail_price AS retailPrice, price_a AS priceA,
    price_b AS priceB, stock, status FROM products WHERE id IN (${placeholders})`).bind(...ids).all<Product>();
  const productMap = new Map(result.results.map((product) => [product.id, product]));
  let amount = 0;
  let itemCount = 0;
  const pricedLines = lines.map((line) => {
    const product = productMap.get(line.id);
    if (!product || product.status !== "active") throw new Error("商品已下架或不存在");
    if (product.stock < line.quantity) throw new Error(`${product.name}库存不足`);
    const price = mode === "retail" ? product.retailPrice : wholesale?.level === "b" ? product.priceB : product.priceA;
    amount += price * line.quantity;
    itemCount += line.quantity;
    return { ...line, product, price };
  });

  const phone = wholesale?.phone ?? retailPhone!;
  const profile = await db.prepare(`SELECT display_name AS displayName, store_name AS storeName,
    sales_person AS salesPerson, referral_code AS referralCode FROM customer_profiles WHERE phone=? LIMIT 1`).bind(phone).first<{
      displayName: string; storeName: string; salesPerson: string; referralCode: string;
    }>();
  const customerName = wholesale?.companyName ?? (profile?.storeName || profile?.displayName || "莱莎零售会员");
  const salesPerson = wholesale?.salesPerson ?? profile?.salesPerson ?? "林青";
  const level = wholesale?.level ?? "retail";
  const now = new Date();
  const orderNo = `LS${now.toISOString().slice(0, 10).replaceAll("-", "")}${String(now.getTime()).slice(-6)}`;
  const commissionAmount = Math.round(amount * 0.03 * 100) / 100;
  const order = await db.prepare(`INSERT INTO orders
    (order_no, channel, customer_phone, customer_name, level, sales_person, status, payment_status,
      logistics_company, tracking_no, logistics_status, item_count, amount, commission_amount, created_at)
    VALUES (?, ?, ?, ?, ?, ?, '待发货', '已支付', '', '', '山东仓正在配货', ?, ?, ?, ?) RETURNING id`)
    .bind(orderNo, mode, phone, customerName, level, salesPerson, itemCount, amount, commissionAmount, now.toISOString())
    .first<{ id: number }>();
  if (!order?.id) return Response.json({ error: "订单创建失败" }, { status: 500 });

  await db.batch([
    ...pricedLines.map((line) => db.prepare("INSERT INTO order_items (order_id, product_id, product_name, unit_price, quantity) VALUES (?, ?, ?, ?, ?)")
      .bind(order.id, line.product.id, line.product.name, line.price, line.quantity)),
    ...pricedLines.map((line) => db.prepare("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?")
      .bind(line.quantity, line.product.id, line.quantity)),
  ]);

  const promoCode = String(body.promoCode ?? "").trim().toUpperCase();
  if (promoCode) {
    const owner = await db.prepare("SELECT name FROM sales_people WHERE promo_code=? OR store_code=? LIMIT 1").bind(promoCode, promoCode).first<{ name: string }>();
    await db.prepare("INSERT INTO referrals (code, owner_name, visitor_phone, order_no, amount, commission, status, created_at) VALUES (?, ?, ?, ?, ?, ?, '待结算', ?)")
      .bind(promoCode, owner?.name ?? "客户分销", phone, orderNo, amount, commissionAmount, now.toISOString()).run();
  }
  return Response.json({ ok: true, orderNo, amount, status: "待发货" }, { status: 201 });
}
