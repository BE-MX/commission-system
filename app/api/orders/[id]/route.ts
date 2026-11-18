import { requireAdminApi } from "../../../lib/admin-auth";
import { readLogisticsOrder, saveShipment } from "../../../lib/order-logistics";

export async function PUT(request: Request, context: { params: Promise<{ id: string }> }) {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  const { id } = await context.params;
  if (!/^\d+$/.test(id) || !Number.isSafeInteger(Number(id))) return Response.json({ error: "订单不存在" }, { status: 404 });
  const order = await readLogisticsOrder(Number(id));
  if (!order) return Response.json({ error: "订单不存在" }, { status: 404 });
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) return Response.json({ error: "请填写物流信息" }, { status: 400 });
  const result = await saveShipment(order, body as Record<string, unknown>);
  if (result.error) return Response.json({ error: result.error }, { status: result.status });
  return Response.json({ ok: true });
}
