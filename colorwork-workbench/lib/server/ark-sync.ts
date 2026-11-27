import { env } from 'cloudflare:workers';
import { colorsForTemplate, type StockColor, type TemplateSummary } from '@/lib/catalog';
import type { InventoryStatus, InventorySpec } from '@/lib/inventory';

/**
 * 方舟 okki 实时库存覆盖层。
 *
 * 工作台规格的共享状态原本完全由站内手动维护（inventory_states 表）。接入方舟后，
 * 「实时库存图修改」页读到的状态以 lsordertest.okki_inventory.enable_count 为准：
 * 方舟后端 /api/colorwork/inventory-status 按模板返回「{颜色}|{尺寸} → normal|low_stock|restocking」，
 * 这里在快照返回前逐规格覆盖。业务口径（2026-09-21）：映射不到 okki 的规格直接显示
 * Restocking（正在补货），不再保留站内手动状态；接口不可达时才回退站内已保存状态。
 * 同时透传库存表 source_synced_at（非产品表时间），供页面标注「数据截至」。
 */

type StatusResponse = {
  statuses?: Record<string, string>;
  unmapped?: boolean;
  source_synced_at?: string | null;
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

function statusForSpec(statuses: Record<string, string>, code: string | undefined, length: number): InventoryStatus {
  if (!code) return 'restocking';
  const alternate = code.startsWith('#') ? code.slice(1) : `#${code}`;
  const status = statuses[`${code}|${length}`] ?? statuses[`${alternate}|${length}`];
  return status === 'normal' || status === 'low_stock' ? status : 'restocking';
}

export type ArkInventoryOverlayResult = {
  overlaid: number;
  sourceSyncedAt: string | null;
  /** 方舟是否成功返回（含 unmapped）；false = 接口不可达，保留站内状态 */
  applied: boolean;
};

/** 就地把 okki 状态覆盖到快照 specs 上。映射不到的规格显示 Restocking。 */
export async function applyArkInventoryOverlay(
  templateId: string,
  colors: StockColor[],
  template: TemplateSummary,
  specs: InventorySpec[],
): Promise<ArkInventoryOverlayResult> {
  const data = await fetchArkStatuses(templateId);
  if (!data || !data.statuses) {
    return { overlaid: 0, sourceSyncedAt: null, applied: false };
  }
  const codeById = new Map(colorsForTemplate(colors, template).map((color) => [color.id, color.code]));
  let overlaid = 0;
  for (const spec of specs) {
    const next = statusForSpec(data.statuses, codeById.get(spec.colorId), spec.length);
    if (spec.status !== next) {
      spec.status = next;
      overlaid += 1;
    }
  }
  const sourceSyncedAt = typeof data.source_synced_at === 'string' && data.source_synced_at
    ? data.source_synced_at
    : null;
  return { overlaid, sourceSyncedAt, applied: true };
}
