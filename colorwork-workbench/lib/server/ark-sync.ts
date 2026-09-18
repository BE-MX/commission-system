import { env } from 'cloudflare:workers';
import { colorsForTemplate, type StockColor, type TemplateSummary } from '@/lib/catalog';
import type { InventoryStatus, InventorySpec } from '@/lib/inventory';

/**
 * 方舟 okki 实时库存覆盖层。
 *
 * 工作台规格的共享状态原本完全由站内手动维护（inventory_states 表）。接入方舟后，
 * 「实时库存图修改」页读到的状态以 lsordertest.okki_inventory.enable_count 为准：
 * 方舟后端 /api/colorwork/inventory-status 按模板返回「{颜色}|{尺寸} → normal|low_stock|restocking」，
 * 这里在快照返回前逐规格覆盖；手动保存在站内的状态仍保留，仅作为 okki 未覆盖规格
 * （映射未配置/接口不可达）的兜底显示。
 */

type StatusResponse = {
  statuses?: Record<string, string>;
  unmapped?: boolean;
};

const FETCH_TIMEOUT_MS = 3500;

async function fetchArkStatuses(templateId: string): Promise<StatusResponse | null> {
  const endpoint = typeof env.ARK_STATUS_ENDPOINT === 'string' ? env.ARK_STATUS_ENDPOINT.trim() : '';
  const syncKey = typeof env.ARK_SYNC_KEY === 'string' ? env.ARK_SYNC_KEY.trim() : '';
  if (!endpoint || !syncKey) return null;
  try {
    const response = await fetch(`${endpoint}?template_id=${encodeURIComponent(templateId)}`, {
      headers: { 'x-colorwork-sync-key': syncKey, accept: 'application/json' },
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    if (!response.ok) return null;
    return await response.json() as StatusResponse;
  } catch {
    // 方舟不可达时静默退回站内已保存状态（导出与展示不中断）
    return null;
  }
}

function isOkkiStatus(value: string): value is InventoryStatus {
  return value === 'normal' || value === 'low_stock' || value === 'restocking';
}

/** 就地把 okki 状态覆盖到快照 specs 上，返回覆盖条数（供日志/调试）。 */
export async function applyArkInventoryOverlay(
  templateId: string,
  colors: StockColor[],
  template: TemplateSummary,
  specs: InventorySpec[],
): Promise<number> {
  const data = await fetchArkStatuses(templateId);
  if (!data?.statuses) return 0;
  const codeById = new Map(colorsForTemplate(colors, template).map((color) => [color.id, color.code]));
  let overlaid = 0;
  for (const spec of specs) {
    const code = codeById.get(spec.colorId);
    if (!code) continue;
    const status = data.statuses[`${code}|${spec.length}`];
    if (status && isOkkiStatus(status) && spec.status !== status) {
      spec.status = status;
      overlaid += 1;
    }
  }
  return overlaid;
}
