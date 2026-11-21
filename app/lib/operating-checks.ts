import type { Product } from "./types";
import { sellable } from "./product-options";

// These internal aliases are chosen by callers, never taken from requests.
export function paidOrderSql(alias = "") {
  const prefix = alias ? `${alias}.` : "";
  return `${prefix}payment_status='已支付' AND ${prefix}status NOT IN ('已取消','已关闭','已退款','退款中')`;
}

export function productChecks(product: Pick<Product, "variants" | "stock" | "images" | "status">) {
  const issues: string[] = [];
  const active = (product.variants ?? []).filter((item) => item.enabled);
  if (!active.length) issues.push("未开放网底和长度");
  else {
    const unpriced = active.filter((item) => !sellable(item)).length;
    if (unpriced) issues.push(`${unpriced}个规格待定价`);
  }
  if (!Number.isSafeInteger(product.stock) || product.stock < 0) issues.push("库存数量无效");
  else if (!product.stock) issues.push("暂无库存");
  if (!product.images.length) issues.push("缺少产品图片");
  if (product.status !== "active") issues.push("尚未上架");
  return issues;
}

export function validateProductAvailability(stock: unknown, status: unknown, minLevel: unknown) {
  if (!Number.isSafeInteger(stock) || Number(stock) < 0) throw new Error("库存必须是大于或等于零的整数");
  if (status !== "active" && status !== "draft") throw new Error("请选择有效的上架状态");
  if (!["retail", "a", "b"].includes(String(minLevel))) throw new Error("请选择有效的客户查看等级");
}
