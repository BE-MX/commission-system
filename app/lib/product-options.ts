export const CAP_TYPES = ["递针旋", "递针前顶", "递针分界"] as const;
export type ProductVariant = { key: string; cap: string; length: number; price: number | null; enabled: boolean };
const PRICES: Record<string, Record<number, number>> = {
  递针旋: { 15: 1198, 20: 1498, 25: 1798, 30: 1998, 35: 2050, 40: 2700 },
  递针前顶: { 20: 1798, 25: 2198, 30: 2498, 35: 2650, 40: 3300 },
  递针分界: { 20: 1598, 25: 1898, 30: 2198, 35: 2298, 40: 2900 },
};
export const lengthCm = (value: string) => Number(value.match(/\d+/)?.[0] ?? 0);
export function allowedLengths(referenceLength: string) {
  const length = lengthCm(referenceLength);
  if (!length) return [];
  return length <= 20 ? [15, 20] : length < 35 ? [25, 30] : [35, 40, 45];
}
export function option(cap: string, length: number): ProductVariant {
  return { key: `cap${CAP_TYPES.indexOf(cap as typeof CAP_TYPES[number])}-${length}`, cap, length, price: PRICES[cap]?.[length] ?? null, enabled: true };
}
// Initially expose only the length already documented for this specific hairstyle.
// Other same-group lengths require an explicit choice in the product editor.
export function initialVariants(referenceLength: string) {
  const length = lengthCm(referenceLength);
  return allowedLengths(referenceLength).includes(length) ? CAP_TYPES.map((cap) => option(cap, length)) : [];
}
export function validateVariants(input: unknown, referenceLength: string): ProductVariant[] {
  const values = typeof input === "string" ? JSON.parse(input) : input;
  if (!Array.isArray(values) || values.length > 30) throw new Error("请填写有效的网底与长度规格");
  const seen = new Set<string>();
  return values.map((value) => {
    if (!value || !CAP_TYPES.includes(value.cap) || !allowedLengths(referenceLength).includes(value.length)) throw new Error("规格长度与当前发型不符：短发、中长发和长发的长度不能混用");
    const expected = option(value.cap, value.length).key;
    if (value.key !== expected || seen.has(expected)) throw new Error("网底与长度组合重复或无效");
    seen.add(expected);
    if (typeof value.enabled !== "boolean") throw new Error("请选择规格是否开放");
    const price = value.price;
    if (price !== null && (typeof price !== "number" || !Number.isFinite(price) || price <= 0 || Math.abs(Math.round(price * 100) - price * 100) > 0.000001)) throw new Error("规格价格必须大于零，最多两位小数；未定价请留空");
    return { key: expected, cap: value.cap, length: value.length, price, enabled: value.enabled };
  });
}
export function readVariants(input: unknown, referenceLength: string): ProductVariant[] {
  try { return validateVariants(input ?? [], referenceLength); } catch { return []; }
}
export const sellable = (variant: ProductVariant) => variant.enabled && variant.price !== null && variant.price > 0;
export function minimumPrice(variants: ProductVariant[] = []) {
  const prices = variants.filter(sellable).map((item) => item.price!);
  return prices.length ? Math.min(...prices) : null;
}
export type CartLine = { id: number; variantKey: string; quantity: number };
export const cartKey = (line: Pick<CartLine, "id" | "variantKey">) => `${line.id}:${line.variantKey}`;
export function normalizeCart(input: unknown): CartLine[] {
  if (!Array.isArray(input) || input.length > 100) throw new Error("购物车数据无效，请重新选择规格");
  const result = new Map<string, CartLine>();
  for (const line of input) {
    if (!line || !Number.isSafeInteger(line.id) || line.id <= 0 || typeof line.variantKey !== "string" || line.variantKey.length > 40 || !Number.isInteger(line.quantity) || line.quantity <= 0 || line.quantity > 100) throw new Error("请重新选择有效的网底、长度和购买数量");
    const key = cartKey(line), quantity = (result.get(key)?.quantity ?? 0) + line.quantity;
    if (quantity > 100) throw new Error("同一规格最多购买100件");
    result.set(key, { id: line.id, variantKey: line.variantKey, quantity });
  }
  return [...result.values()];
}

export type OptionProduct = { id: number; name: string; length: string; variants: unknown; stock: number; status: string; minLevel: string };
export function priceCart(products: OptionProduct[], lines: CartLine[], level: string) {
  const ranks: Record<string, number> = { retail: 0, a: 1, b: 2 };
  const totals = new Map<number, number>();
  return lines.map((line) => {
    const product = products.find((item) => item.id === line.id);
    if (!product || product.status !== "active" || !Object.hasOwn(ranks, product.minLevel) || !Object.hasOwn(ranks, level) || ranks[level] < ranks[product.minLevel]) throw new Error("商品已下架或当前账号无购买权限");
    const variant = readVariants(product.variants, product.length).find((item) => item.key === line.variantKey);
    if (!variant || !sellable(variant)) throw new Error("所选网底或长度不可购买，请重新选择规格");
    const count = (totals.get(product.id) ?? 0) + line.quantity;
    totals.set(product.id, count);
    if (count > product.stock) throw new Error(`${product.name}库存不足`);
    return { ...line, product, variant, price: variant.price!, label: `${variant.cap} · ${variant.length}厘米` };
  });
}
