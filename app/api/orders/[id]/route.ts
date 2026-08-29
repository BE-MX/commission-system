import { ensureDatabase, getD1 } from "../../../../db/runtime";
import { requireAdminApi } from "../../../lib/admin-auth";

export async function PUT(request: Request, context: { params: Promise<{ id: string }> }) {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  await ensureDatabase();
  const { id } = await context.params;
  const body = await request.json() as Record<string, unknown>;
  const status = String(body.status ?? "待发货");
  const logisticsCompany = String(body.logisticsCompany ?? "").trim();
  const trackingNo = String(body.trackingNo ?? "").trim();
  const logisticsStatus = String(body.logisticsStatus ?? (trackingNo ? "快件已揽收" : "山东仓正在配货")).trim();
  const shippedAt = trackingNo ? new Date().toISOString() : null;
  await getD1().prepare(`UPDATE orders SET status=?, logistics_company=?, tracking_no=?, logistics_status=?, shipped_at=? WHERE id=?`)
    .bind(status, logisticsCompany, trackingNo, logisticsStatus, shippedAt, Number(id)).run();
  return Response.json({ ok: true });
}
