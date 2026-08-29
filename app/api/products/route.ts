import { ensureDatabase, getD1 } from "../../../db/runtime";
import { requireAdminApi } from "../../lib/admin-auth";

export const dynamic = "force-dynamic";

const selectSql = `SELECT id, name, material, length, color,
  retail_price AS retailPrice, price_a AS priceA, price_b AS priceB,
  min_level AS minLevel, stock, status, tone, category, sku, construction,
  hair_volume AS hairVolume, parting, craft, description, highlights, audience,
  scenarios, images, video_url AS videoUrl, created_at AS createdAt FROM products`;

const parseList = (value: unknown) => {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value !== "string" || !value.trim()) return [];
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : []; }
  catch { return value.split(/[\n；;]+/).map((item) => item.trim()).filter(Boolean); }
};

const serializeList = (value: unknown) => JSON.stringify(parseList(value));

export async function GET() {
  await ensureDatabase();
  const rows = await getD1().prepare(`${selectSql} ORDER BY id DESC`).all();
  return Response.json({ products: rows.results.map((row) => ({
    ...row,
    highlights: parseList((row as Record<string, unknown>).highlights),
    audience: parseList((row as Record<string, unknown>).audience),
    scenarios: parseList((row as Record<string, unknown>).scenarios),
    images: parseList((row as Record<string, unknown>).images),
  })) });
}

export async function POST(request: Request) {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  await ensureDatabase();
  const body = await request.json() as Record<string, unknown>;
  const name = String(body.name ?? "").trim();
  if (!name) return Response.json({ error: "请填写款式名称" }, { status: 400 });
  const values = {
    material: String(body.material ?? "真人发"), length: String(body.length ?? "45cm"),
    color: String(body.color ?? "自然黑"), retailPrice: Number(body.retailPrice ?? 0),
    priceA: Number(body.priceA ?? 0), priceB: Number(body.priceB ?? 0),
    minLevel: String(body.minLevel ?? "retail"), stock: Number(body.stock ?? 0),
    status: String(body.status ?? "active"), tone: String(body.tone ?? "espresso"),
    category: String(body.category ?? "短发系列"), sku: String(body.sku ?? "").trim(),
    construction: String(body.construction ?? ""), hairVolume: String(body.hairVolume ?? ""),
    parting: String(body.parting ?? ""), craft: String(body.craft ?? ""),
    description: String(body.description ?? ""), highlights: serializeList(body.highlights),
    audience: serializeList(body.audience), scenarios: serializeList(body.scenarios),
    images: serializeList(body.images), videoUrl: String(body.videoUrl ?? "").trim(),
  };
  if ([values.retailPrice, values.priceA, values.priceB, values.stock].some((value) => !Number.isFinite(value) || value < 0)) {
    return Response.json({ error: "价格和库存不能为负数" }, { status: 400 });
  }
  const result = await getD1().prepare(`INSERT INTO products
    (name, material, length, color, retail_price, price_a, price_b, min_level, stock, status,
     tone, category, sku, construction, hair_volume, parting, craft, description, highlights,
     audience, scenarios, images, video_url, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`)
    .bind(name, values.material, values.length, values.color, values.retailPrice, values.priceA,
      values.priceB, values.minLevel, values.stock, values.status, values.tone, values.category, values.sku,
      values.construction, values.hairVolume, values.parting, values.craft, values.description,
      values.highlights, values.audience, values.scenarios, values.images, values.videoUrl,
      new Date().toISOString()).first<{ id: number }>();
  return Response.json({ id: result?.id }, { status: 201 });
}
