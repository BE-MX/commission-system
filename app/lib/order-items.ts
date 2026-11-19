import { getD1 } from "../../db/runtime";
export async function withOrderItems<T extends { id: number }>(orders: T[]) {
  if (!orders.length) return [];
  const result = await getD1().prepare(`SELECT order_id AS orderId, product_name AS productName,
    variant_label AS variantLabel, unit_price AS unitPrice, quantity FROM order_items
    WHERE order_id IN (${orders.map(() => "?").join(",")}) ORDER BY id`).bind(...orders.map((item) => item.id)).all<{ orderId: number; productName: string; variantLabel: string; unitPrice: number; quantity: number }>();
  return orders.map((order) => ({ ...order, items: result.results.filter((item) => item.orderId === order.id) }));
}
