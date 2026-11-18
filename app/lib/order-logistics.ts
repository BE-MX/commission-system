import { env } from "cloudflare:workers";
import { ensureDatabase, getD1 } from "../../db/runtime";
import { querySf, SfError, statusLabel, type TrackingEvent } from "./sf-tracking";

export type LogisticsRow = { order_id: number; tracking_no: string; phone_last4: string; revision: string; events: string; state: string; checked_at: string | null; next_check_at: string | null; lease_token: string | null; last_error: string; failures: number; sandbox: number };
export type LogisticsOrder = { id: number; orderNo: string; channel: string; customerPhone: string; trackingNo: string; logisticsCompany: string; logisticsStatus: string; status: string; shippedAt: string | null };
type Settings = { SF_PARTNER_ID?: string; SF_CHECKWORD?: string; SF_SANDBOX?: string; SF_DAILY_QUERY_LIMIT?: string };
const settings = () => env as unknown as Settings;
export const sfConfigured = () => Boolean(settings().SF_PARTNER_ID?.trim() && settings().SF_CHECKWORD?.trim());

export async function readLogisticsOrder(id: number) {
  await ensureDatabase();
  return getD1().prepare(`SELECT id, order_no AS orderNo, channel, customer_phone AS customerPhone,
    tracking_no AS trackingNo, logistics_company AS logisticsCompany, logistics_status AS logisticsStatus,
    status, shipped_at AS shippedAt FROM orders WHERE id=?`).bind(id).first<LogisticsOrder>();
}

export async function readSnapshot(order: LogisticsOrder) {
  const db = getD1();
  await db.prepare(`INSERT OR IGNORE INTO order_logistics
    (order_id, tracking_no, phone_last4, revision, events, state, last_error, failures, sandbox)
    VALUES (?, ?, '', ?, '[]', 'pending', '', 0, 0)`).bind(order.id, order.trackingNo, crypto.randomUUID()).run();
  return (await db.prepare("SELECT * FROM order_logistics WHERE order_id=?").bind(order.id).first<LogisticsRow>())!;
}

export function publicLogistics(order: LogisticsOrder, row: LogisticsRow, admin: boolean) {
  let events: TrackingEvent[] = [];
  try { const stored = JSON.parse(row.events); if (Array.isArray(stored)) events = stored; } catch { /* A broken cache is not a fabricated event. */ }
  const matches = row.tracking_no === order.trackingNo && (!sfConfigured() || Boolean(row.sandbox) === (settings().SF_SANDBOX !== "false"));
  return {
    orderNo: order.orderNo, trackingNo: order.trackingNo, company: order.logisticsCompany,
    state: matches ? row.state : "pending", status: matches && events.length ? statusLabel(row.state) : (order.trackingNo ? "等待顺丰轨迹" : "等待发货"),
    events: matches ? events : [], checkedAt: matches ? row.checked_at : null,
    nextCheckAt: matches ? row.next_check_at : null, sandbox: Boolean(row.sandbox), configured: sfConfigured(),
    message: !order.trackingNo ? "仓库发货后会在这里显示顺丰运单和轨迹。" : !sfConfigured() ? "顺丰自动查询尚未配置，请联系销售员了解配送进度。" : matches ? row.last_error : "运单已变更，正在等待新轨迹。",
    ...(admin ? { revision: row.revision, phoneLast4: row.phone_last4 } : {}),
  };
}

async function reserveQuery() {
  const db = getD1();
  const now = Date.now();
  const day = new Date(now + 8 * 3600000).toISOString().slice(0, 10);
  const input = Number(settings().SF_DAILY_QUERY_LIMIT ?? 500);
  const limit = Number.isInteger(input) && input > 0 ? Math.min(input, 2000) : 500;
  for (const [name, window, cap] of [["sf-day", day, limit], ["sf-second", String(Math.floor(now / 1000)), 5]] as const) {
    const result = await db.prepare(`INSERT INTO logistics_query_budget (name, window_key, used) VALUES (?, ?, 1)
      ON CONFLICT(name) DO UPDATE SET window_key=excluded.window_key,
      used=CASE WHEN window_key=excluded.window_key THEN used+1 ELSE 1 END
      WHERE window_key<>excluded.window_key OR used<? RETURNING used`).bind(name, window, cap).first();
    if (!result) throw new SfError("LIMIT", "查询较多，稍后再试；上次轨迹仍可查看");
  }
}

export async function refreshLogistics(order: LogisticsOrder, row: LogisticsRow) {
  if (!sfConfigured() || !order.trackingNo || row.tracking_no !== order.trackingNo) return row;
  const sandbox = settings().SF_SANDBOX !== "false";
  if (Boolean(row.sandbox) !== sandbox) {
    await getD1().prepare(`UPDATE order_logistics SET events='[]', state='pending', checked_at=NULL,
      next_check_at=NULL, last_error='', failures=0, sandbox=?, revision=?, lease_token=NULL
      WHERE order_id=? AND revision=?`).bind(sandbox ? 1 : 0, crypto.randomUUID(), order.id, row.revision).run();
    row = (await getD1().prepare("SELECT * FROM order_logistics WHERE order_id=?").bind(order.id).first<LogisticsRow>())!;
  }
  const now = new Date().toISOString();
  if (["delivered", "returned"].includes(row.state)) return row;
  if (order.shippedAt && Date.now() - Date.parse(order.shippedAt) > 90 * 86400000) return row;
  if (row.next_check_at && row.next_check_at > now) return row;
  const lease = crypto.randomUUID();
  const db = getD1();
  const result = await db.prepare(`UPDATE order_logistics SET lease_token=?, next_check_at=?
    WHERE order_id=? AND revision=? AND (next_check_at IS NULL OR next_check_at<=?)`)
    .bind(lease, new Date(Date.now() + 60000).toISOString(), order.id, row.revision, now).run();
  if (!result.meta.changes) return (await db.prepare("SELECT * FROM order_logistics WHERE order_id=?").bind(order.id).first<LogisticsRow>())!;
  let events = row.events, state = row.state, error = "", failures = 0, checked = row.checked_at;
  let delay = 3600000;
  const config = settings();
  try {
    const fresh = await querySf({ partnerId: config.SF_PARTNER_ID!.trim(), checkword: config.SF_CHECKWORD!.trim(), sandbox }, order.trackingNo, row.phone_last4, reserveQuery);
    checked = new Date().toISOString();
    if (fresh.events.length) { events = JSON.stringify(fresh.events); state = fresh.state; }
    else { error = "顺丰暂未返回轨迹，可能尚未揽收、缺少查询权限或运单已超期，请联系销售员核实。"; delay = 2 * 3600000; }
  } catch (failure) {
    failures = row.failures + 1;
    error = failure instanceof SfError ? failure.message : "物流查询暂时失败，上次轨迹已保留。";
    delay = Math.min(24 * 3600000, 3600000 * 2 ** Math.min(failures - 1, 5));
  }
  const updates = [];
  if (!sandbox && !error && events !== "[]") {
    const latest = (JSON.parse(events) as TrackingEvent[])[0];
    updates.push(db.prepare(`UPDATE orders SET status=?, logistics_status=? WHERE id=? AND tracking_no=?
      AND EXISTS (SELECT 1 FROM order_logistics WHERE order_id=? AND revision=? AND lease_token=?)`)
      .bind(state === "pending" ? "已发货" : statusLabel(state), latest.description, order.id, order.trackingNo, order.id, row.revision, lease));
  }
  updates.push(db.prepare(`UPDATE order_logistics SET events=?, state=?, checked_at=?, next_check_at=?, last_error=?, failures=?, sandbox=?, lease_token=NULL
    WHERE order_id=? AND revision=? AND lease_token=?`)
    .bind(events, state, checked, new Date(Date.now() + delay).toISOString(), error, failures, sandbox ? 1 : 0, order.id, row.revision, lease));
  await db.batch(updates);
  return (await db.prepare("SELECT * FROM order_logistics WHERE order_id=?").bind(order.id).first<LogisticsRow>())!;
}

export async function saveShipment(order: LogisticsOrder, body: Record<string, unknown>) {
  const trackingNo = String(body.trackingNo ?? "").replace(/\s/g, "").toUpperCase();
  const phoneLast4 = String(body.phoneLast4 ?? "").trim();
  if (!/^(?:SF)?\d{10,20}$/.test(trackingNo)) return { error: "请输入正确的顺丰单号（数字或 SF 开头）", status: 400 };
  if (phoneLast4 && !/^\d{4}$/.test(phoneLast4)) return { error: "手机号后四位应为四个数字", status: 400 };
  const current = await readSnapshot(order);
  if (body.revision !== current.revision) return { error: "物流信息已被其他管理员更新，请重新打开后修改", status: 409 };
  const changed = current.tracking_no !== trackingNo || current.phone_last4 !== phoneLast4;
  const revision = crypto.randomUUID();
  const now = new Date().toISOString();
  const db = getD1();
  const results = await db.batch([
    db.prepare(`UPDATE order_logistics SET tracking_no=?, phone_last4=?, revision=?,
      events=?, state=?, checked_at=?, next_check_at=?, last_error=?, failures=?, lease_token=NULL, sandbox=?
      WHERE order_id=? AND revision=?`)
      .bind(trackingNo, phoneLast4, revision, changed ? "[]" : current.events, changed ? "pending" : current.state,
        changed ? null : current.checked_at, changed ? null : current.next_check_at, changed ? "" : current.last_error,
        changed ? 0 : current.failures, changed ? 0 : current.sandbox, order.id, current.revision),
    db.prepare(`UPDATE orders SET logistics_company='顺丰速运', tracking_no=?,
      logistics_status=?, status=?, shipped_at=? WHERE id=?
      AND EXISTS (SELECT 1 FROM order_logistics WHERE order_id=? AND revision=?)`)
      .bind(trackingNo, changed ? "发货信息已录入，等待顺丰轨迹" : order.logisticsStatus,
        changed ? "已发货" : order.status, order.trackingNo !== trackingNo ? now : order.shippedAt ?? now, order.id, order.id, revision),
  ]);
  if (!results[0].meta.changes) return { error: "物流信息已被更新，请刷新后再试", status: 409 };
  return { status: 200 };
}
