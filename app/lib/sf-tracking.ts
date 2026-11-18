export type TrackingEvent = { time: string; location: string; description: string; status: string };
export type SfConfig = { partnerId: string; checkword: string; sandbox: boolean };
export class SfError extends Error {
  code: string;
  constructor(code: string, message: string) { super(message); this.code = code; }
}

const labels: Record<string, string> = {
  pending: "待揽收", picked_up: "已揽收", in_transit: "运输中", out_for_delivery: "派送中",
  delivered: "已签收", returned: "已退回", exception: "物流异常", customs_hold: "清关中",
};
export function statusLabel(state: string) { return labels[state] ?? "等待轨迹更新"; }
export function sfState(route: Record<string, unknown>) {
  const text = `${route.firstStatusName ?? ""} ${route.secondaryStatusName ?? ""}`;
  if (text.includes("退回")) return "returned";
  if (["70", "934"].includes(String(route.opCode)) || String(route.remark).includes("遗失")) return "exception";
  if (String(route.secondaryStatusCode) === "204") return "customs_hold";
  if (String(route.secondaryStatusCode) === "205") return "in_transit";
  const state = String(route.firstStatusCode);
  const map: Record<string, string> = { "1": "picked_up", "2": "in_transit", "3": "out_for_delivery", "4": "delivered", "5": "exception", "6": "exception", "7": "pending", "10": "pending", "11": "out_for_delivery", "13": "in_transit" };
  if (map[state]) return map[state];
  if (String(route.opCode) === "80") return "delivered";
  if (String(route.opCode) === "44") return "out_for_delivery";
  if (String(route.opCode) === "50") return "picked_up";
  return "in_transit";
}

// SF timestamps are Beijing wall time. Never parse them using the server's timezone.
export function sfTime(value: unknown) {
  const match = String(value ?? "").match(/^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{2}):(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, year, month, day, hour, minute, second] = match;
  const iso = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}T${hour}:${minute}:${second}+08:00`;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return null;
  const check = new Date(parsed.getTime() + 8 * 3600000).toISOString().slice(0, 19);
  return check === iso.slice(0, 19) ? iso : null;
}

export function parseSfRoutes(payload: unknown, trackingNo: string) {
  if (!payload || typeof payload !== "object") throw new SfError("FORMAT", "顺丰返回的数据暂时无法解析");
  const outer = payload as Record<string, unknown>;
  if (outer.apiResultCode !== "A1000") {
    const code = /^[A-Z0-9]{1,16}$/.test(String(outer.apiResultCode)) ? String(outer.apiResultCode) : "API";
    throw new SfError(code, code === "A1004" ? "顺丰生产路由查询权限尚未开通" : "顺丰查询暂时不可用，请稍后再试");
  }
  let data: Record<string, unknown>;
  try { data = typeof outer.apiResultData === "string" ? JSON.parse(outer.apiResultData) : outer.apiResultData; }
  catch { throw new SfError("FORMAT", "顺丰返回的数据暂时无法解析"); }
  if (!data || data.success !== true || data.errorCode !== "S0000") throw new SfError("BUSINESS", "顺丰未接受本次轨迹查询，请核对单号及查询权限");
  const responses = (data.msgData as { routeResps?: Array<{ mailNo?: string; routes?: Record<string, unknown>[] }> })?.routeResps;
  const routes = (Array.isArray(responses) ? responses.find((item) => item.mailNo === trackingNo)?.routes : []) ?? [];
  const unique = new Map<string, TrackingEvent & { state: string }>();
  for (const route of Array.isArray(routes) ? routes : []) {
    const time = sfTime(route.acceptTime);
    if (!time || !String(route.remark ?? "").trim()) continue;
    const state = sfState(route);
    const description = String(route.remark).slice(0, 2000);
    unique.set(`${time}:${description}`, { time, location: String(route.acceptAddress ?? "").slice(0, 200), description, state, status: statusLabel(state) });
  }
  const events = [...unique.values()].sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
  return { state: events[0]?.state ?? "pending", events: events.map(({ time, location, description, status }) => ({ time, location, description, status })) };
}

const tokenCache = new Map<string, { token: string; until: number }>();
const tokenRequests = new Map<string, Promise<string>>();
export async function querySf(config: SfConfig, trackingNo: string, phoneLast4: string, reserve: () => Promise<void>, fetcher: typeof fetch = fetch) {
  const base = config.sandbox ? "https://sfapi-sbox.sf-express.com" : "https://bspgw.sf-express.com";
  const cacheKey = `${base}:${config.partnerId}:${config.checkword}`;
  async function post(path: string, form: Record<string, string>) {
    try {
      const response = await fetcher(base + path, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }, body: new URLSearchParams(form), signal: AbortSignal.timeout(12000) });
      if (!response.ok) throw new Error("http");
      return await response.json() as Record<string, unknown>;
    } catch { throw new SfError("NETWORK", "顺丰暂时未响应，已保留上次查询结果"); }
  }
  async function getToken(force = false): Promise<string> {
    const cached = tokenCache.get(cacheKey);
    if (!force && cached && cached.until > Date.now()) return cached.token;
    const pending = tokenRequests.get(cacheKey);
    if (pending) return pending;
    const request = (async () => {
      const body = await post("/oauth2/accessToken", { partnerID: config.partnerId, secret: config.checkword, grantType: "password" });
      if (body.apiResultCode !== "A1000" || typeof body.accessToken !== "string") throw new SfError("TOKEN", "顺丰接口身份校验失败，请联系管理员检查配置");
      const seconds = Number(body.expiresIn);
      if (!Number.isFinite(seconds) || seconds <= 0) throw new SfError("TOKEN", "顺丰令牌有效期异常");
      if (tokenCache.size > 4) tokenCache.clear();
      tokenCache.set(cacheKey, { token: body.accessToken, until: Date.now() + Math.max(0, seconds - 60) * 1000 });
      return body.accessToken;
    })();
    tokenRequests.set(cacheKey, request);
    try { return await request; } finally { tokenRequests.delete(cacheKey); }
  }
  const msg = { language: "zh-CN", trackingType: "1", trackingNumber: [trackingNo], methodType: "1", ...(phoneLast4 ? { checkPhoneNo: phoneLast4 } : {}) };
  async function call(token: string) {
    await reserve();
    return post("/std/service", { partnerID: config.partnerId, requestID: crypto.randomUUID(), serviceCode: "EXP_RECE_SEARCH_ROUTES", timestamp: String(Date.now()), accessToken: token, msgData: JSON.stringify(msg) });
  }
  let response = await call(await getToken());
  if (response.apiResultCode === "A1011") response = await call(await getToken(true));
  return parseSfRoutes(response, trackingNo);
}
