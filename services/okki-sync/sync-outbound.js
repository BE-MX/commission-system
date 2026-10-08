/**
 * sync-outbound.js
 * 同步 Okki 销售出库单到 okki_outbound_records / okki_outbound_record_items
 *
 * 接口：GET /v1/invoices/outbound/list
 *      GET /v1/invoices/outbound/info?outbound_invoice_id={id}
 *
 * 用法：
 *   node sync-outbound.js                           # 增量（窗口=昨天00:00起，跳过未变更单）
 *   node sync-outbound.js full                      # 全量（2020-01-01至今）
 *   node sync-outbound.js 2026-01-01 2026-04-25     # 指定日期范围（两个日期参数）
 *   node sync-outbound.js range 2026-01-01 2026-04-25  # 等效写法
 *   node sync-outbound.js incremental --force        # 强制重拉所有单（忽略跳过逻辑）
 *
 * 优化：列表返回的 update_time 与库内一致且已有明细时，跳过详情拉取与写库；
 *       某单详情拉取失败（库内无明细）即使 update_time 未变也会重拉，保证自愈。
 */

import 'dotenv/config';
import { OkkiAuth, OKKI_CONFIG } from './auth.js';
import pool, { closePool, withDbRetry } from './db.js';
import { saveOutboundSnapshot } from './outbound-store.mjs';

const auth = new OkkiAuth();
const PAGE_SIZE = 100;
const CONCURRENCY = 8;          // 并发处理单据数
const REQ_TIMEOUT_MS = 20000;   // 单请求超时，防止挂死（见教训16）
const SKIP_UNCHANGED = process.env.OUTBOUND_SKIP_UNCHANGED !== '0'; // 跳过未变更单（默认开）
const FORCE = process.argv.includes('--force');                     // 强制全量重拉

function parseTs(val) {
  if (!val) return null;
  // OKKI DATETIME strings are already Beijing time; do not reinterpret them in the host timezone.
  if (/^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?$/.test(String(val))) return val;
  const d = new Date(val);
  return isNaN(d) ? null : d;
}

function num(val) {
  if (val === null || val === undefined || val === '') return null;
  const n = Number(val);
  return isNaN(n) ? null : n;
}

// -------------------------------------------------------
// API 层
// -------------------------------------------------------

// 并发受限的 map
async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const idx = cursor++;
      results[idx] = await fn(items[idx], idx);
    }
  });
  await Promise.all(runners);
  return results;
}

// 带超时 + 401 自动刷新重试的 GET
async function apiGet(pathAndQuery, { retryOn401 = true } = {}) {
  const token = await auth.getAccessToken();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), REQ_TIMEOUT_MS);
  try {
    const res = await fetch(`${OKKI_CONFIG.baseUrl}${pathAndQuery}`, {
      headers: { Authorization: token },
      signal: ctrl.signal,
    });
    if (res.status === 401 && retryOn401) {
      auth.accessToken = null;              // 强制刷新 token 后重试一次
      await auth.getAccessToken();
      return apiGet(pathAndQuery, { retryOn401: false });
    }
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function fetchListPage(page, startTime, endTime) {
  const qs = new URLSearchParams({
    count: PAGE_SIZE,
    start_index: page,
    time_type: 1, // 按 update_time 查
    ...(startTime ? { start_time: startTime } : {}),
    ...(endTime   ? { end_time:   endTime   } : {}),
  });
  const data = await apiGet(`/v1/invoices/outbound/list?${qs}`);
  if (data.code !== 200) throw new Error(`Okki API 错误: ${data.message}`);
  return data.data?.list || [];
}

async function fetchDetail(outboundInvoiceId) {
  try {
    const data = await apiGet(`/v1/invoices/outbound/info?outbound_invoice_id=${outboundInvoiceId}`);
    if (data.code !== 200) return null;
    return data.data;
  } catch (_) {
    return null;
  }
}

// 批量获取库内单据状态，用于“未变更则跳过”判断
// 返回 Map<outbound_invoice_id, { updateTime: 'YYYY-MM-DD HH:MM:SS', itemCount: n }>
async function getDbState(ids) {
  const map = new Map();
  if (!ids || !ids.length) return map;
  const conn = await pool.getConnection();
  try {
    const [rows] = await conn.query(
      `SELECT outbound_invoice_id,
              DATE_FORMAT(update_time, '%Y-%m-%d %H:%i:%s') AS update_time
         FROM okki_outbound_records
        WHERE outbound_invoice_id IN (?)`,
      [ids]
    );
    const [cntRows] = await conn.query(
      `SELECT outbound_invoice_id, COUNT(*) AS cnt
         FROM okki_outbound_record_items
        WHERE outbound_invoice_id IN (?)
        GROUP BY outbound_invoice_id`,
      [ids]
    );
    const cntMap = new Map(cntRows.map(r => [String(r.outbound_invoice_id), Number(r.cnt)]));
    for (const r of rows) {
      map.set(String(r.outbound_invoice_id), {
        updateTime: r.update_time || null,
        itemCount:  cntMap.get(String(r.outbound_invoice_id)) || 0,
      });
    }
    return map;
  } finally {
    conn.release();
  }
}

// -------------------------------------------------------
// DB 层
// -------------------------------------------------------

async function saveOutbound(inv, detail) {
  return withDbRetry(() => saveOutboundSnapshot(pool, inv, detail, {
    parseTs, num, inspectionSchema: process.env.ARK_INSPECTION_DB_NAME || 'commission_db',
  }), { label: `保存出库单 ${inv.outbound_invoice_id}` });
}

// -------------------------------------------------------
// 主流程
// -------------------------------------------------------

export async function syncOutbound(mode, startDate, endDate) {
  let startTime, endTime;

  if (mode === 'full') {
    startTime = '2020-01-01 00:00:00';
    endTime   = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
      .replace(/\//g, '-').replace(/上午|下午/g, '').trim();
    console.log(`🔄 全量同步销售出库单 ...`);
  } else if (startDate) {
    startTime = startDate + ' 00:00:00';
    endTime   = (endDate || startDate) + ' 23:59:59';
    console.log(`🔄 同步销售出库单 ${startTime} ~ ${endTime}`);
  } else {
    const pad = n => String(n).padStart(2, '0');
    const fmt = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    // 同步窗口：昨天 00:00:00 ~ 现在（北京时间）—— 覆盖跨午夜边界，避免漏单
    const nowSh = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }));
    const start = new Date(nowSh);
    start.setDate(start.getDate() - 1);
    startTime = `${start.getFullYear()}-${pad(start.getMonth()+1)}-${pad(start.getDate())} 00:00:00`;
    endTime   = fmt(nowSh);
    console.log(`🔄 增量同步销售出库单（昨天起）: ${startTime} ~ ${endTime}`);
  }

  let page = 1, totalSaved = 0, totalFailed = 0, totalSkipped = 0, samplePrinted = false;

  while (true) {
    const list = await fetchListPage(page, startTime, endTime);
    if (list.length === 0) break;

    // 本页所有单据的库内状态（仅当开启跳过时才查）
    const dbState = SKIP_UNCHANGED && !FORCE
      ? await getDbState(list.map(x => x.outbound_invoice_id))
      : new Map();

    await mapLimit(list, CONCURRENCY, async (inv) => {
      try {
        // 未变更且已有明细 → 跳过详情拉取与写库
        const st = dbState.get(String(inv.outbound_invoice_id));
        if (st && st.updateTime === inv.update_time && st.itemCount > 0) {
          totalSkipped++;
          return;
        }

        const detail = await fetchDetail(inv.outbound_invoice_id);
        if (detail === null) {
          console.warn(`  ⚠️  详情拉取失败 outbound_invoice_id=${inv.outbound_invoice_id}`);
        }
        await saveOutbound(inv, detail);
        totalSaved++;
        if (!samplePrinted && detail?.record_list?.length > 0) {
          samplePrinted = true;
          console.log('  📋 明细字段:', JSON.stringify(Object.keys(detail.record_list[0])));
        }
      } catch (e) {
        console.warn(`  ⚠️  保存失败 outbound_invoice_id=${inv.outbound_invoice_id}: ${e.message}`);
        totalFailed++;
      }
    });

    console.log(`  页 ${page}: ${list.length} 条（更新 ${totalSaved}，跳过 ${totalSkipped}，失败 ${totalFailed}）`);

    if (list.length < PAGE_SIZE) break;
    page++;
  }

  console.log(`✅ 销售出库单同步完成：更新 ${totalSaved} 条，跳过 ${totalSkipped} 条，失败 ${totalFailed} 条`);
  return { saved: totalSaved, skipped: totalSkipped, failed: totalFailed };
}

// -------------------------------------------------------
// CLI 直接运行
// ⚠️ 必须带守卫：resync-outbound-by-order.js 会 import 本模块，
//    无守卫时 import 就会触发一次全量增量同步（并调用 process.exit）
// -------------------------------------------------------

if (process.argv[1] && process.argv[1].endsWith('sync-outbound.js')) {
  const _args = process.argv.slice(2).filter(a => !a.startsWith('--'));
  let mode, startDate, endDate;
  // 兼容两种写法：
  //   node sync-outbound.js 2026-01-01 2026-09-25   (两个日期 = 范围)
  //   node sync-outbound.js full|incremental [起] [止]
  if (/^\d{4}-\d{2}-\d{2}$/.test(_args[0] || '')) {
    mode = 'range';
    [startDate, endDate] = _args;
  } else {
    [mode, startDate, endDate] = _args;
  }

  syncOutbound(mode || 'incremental', startDate, endDate)
    .catch(err => {
      console.error('❌ 同步失败:', err.message);
      process.exit(1);
    })
    .finally(() => closePool());
}
