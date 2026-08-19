import { ensureDatabase, getD1 } from "../../../db/runtime";

export const dynamic = "force-dynamic";

export async function GET() {
  await ensureDatabase();
  const rows = await getD1().prepare("SELECT id, code, name, threshold, rank FROM wholesale_levels ORDER BY rank").all();
  return Response.json({ levels: rows.results });
}

export async function PUT(request: Request) {
  await ensureDatabase();
  const body = await request.json() as { levels?: Array<{ code: string; name: string; threshold: number }> };
  if (!body.levels?.length) return Response.json({ error: "等级数据不能为空" }, { status: 400 });
  const db = getD1();
  await db.batch(body.levels.map((level) => db.prepare("UPDATE wholesale_levels SET name=?, threshold=? WHERE code=?")
    .bind(level.name.trim(), Math.max(0, Number(level.threshold)), level.code)));
  return Response.json({ ok: true });
}
