import { ensureDatabase, getD1 } from "../../../../db/runtime";

const serializeList = (value: unknown) => JSON.stringify(Array.isArray(value)
  ? value.map(String).filter(Boolean)
  : String(value ?? "").split(/[\n；;]+/).map((item) => item.trim()).filter(Boolean));

export async function PUT(request: Request, context: { params: Promise<{ id: string }> }) {
  await ensureDatabase();
  const { id } = await context.params;
  const body = await request.json() as Record<string, unknown>;
  const values = [
    String(body.name ?? "").trim(), String(body.material ?? "真人发"), String(body.length ?? "45cm"),
    String(body.color ?? "自然黑"), Number(body.retailPrice ?? 0), Number(body.priceA ?? 0),
    Number(body.priceB ?? 0), String(body.minLevel ?? "retail"), Number(body.stock ?? 0),
    String(body.status ?? "active"), String(body.tone ?? "espresso"), String(body.category ?? "短发系列"),
    String(body.sku ?? "").trim(), String(body.construction ?? ""), String(body.hairVolume ?? ""),
    String(body.parting ?? ""), String(body.craft ?? ""), String(body.description ?? ""),
    serializeList(body.highlights), serializeList(body.audience), serializeList(body.scenarios),
    serializeList(body.images), String(body.videoUrl ?? "").trim(), Number(id),
  ];
  if (!values[0]) return Response.json({ error: "请填写款式名称" }, { status: 400 });
  await getD1().prepare(`UPDATE products SET name=?, material=?, length=?, color=?, retail_price=?,
    price_a=?, price_b=?, min_level=?, stock=?, status=?, tone=?, category=?, sku=?, construction=?,
    hair_volume=?, parting=?, craft=?, description=?, highlights=?, audience=?, scenarios=?, images=?,
    video_url=? WHERE id=?`).bind(...values).run();
  return Response.json({ ok: true });
}

export async function DELETE(_request: Request, context: { params: Promise<{ id: string }> }) {
  await ensureDatabase();
  const { id } = await context.params;
  await getD1().prepare("DELETE FROM products WHERE id=?").bind(Number(id)).run();
  return Response.json({ ok: true });
}
