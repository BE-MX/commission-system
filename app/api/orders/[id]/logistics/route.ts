import { requireAdminApi } from "../../../../lib/admin-auth";
import { getRetailPhone } from "../../../../lib/retail-session";
import { getWholesaleAccount } from "../../../../lib/wholesale-session";
import { publicLogistics, readLogisticsOrder, readSnapshot, refreshLogistics } from "../../../../lib/order-logistics";

export const dynamic = "force-dynamic";
export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const mode = new URL(request.url).searchParams.get("mode");
  if (!["retail", "wholesale", "admin"].includes(mode ?? "")) return Response.json({ error: "请选择正确的订单类型" }, { status: 400 });
  let phone: string | null = null;
  if (mode === "admin") {
    const denied = await requireAdminApi();
    if (denied) return denied;
  } else {
    const cookie = request.headers.get("cookie");
    phone = mode === "retail" ? await getRetailPhone(cookie) : (await getWholesaleAccount(cookie))?.phone ?? null;
    if (!phone) return Response.json({ error: "请先登录后查看自己的物流" }, { status: 401 });
  }
  const { id } = await context.params;
  if (!/^\d+$/.test(id) || !Number.isSafeInteger(Number(id))) return Response.json({ error: "订单不存在" }, { status: 404 });
  const order = await readLogisticsOrder(Number(id));
  if (!order || (mode !== "admin" && (order.customerPhone !== phone || order.channel !== mode))) return Response.json({ error: "订单不存在" }, { status: 404 });
  const snapshot = await refreshLogistics(order, await readSnapshot(order));
  // Read the order again: a warehouse edit may have changed the waybill while SF was responding.
  const latest = await readLogisticsOrder(order.id);
  return Response.json({ logistics: publicLogistics(latest!, snapshot, mode === "admin") }, { headers: { "Cache-Control": "private, no-store" } });
}
