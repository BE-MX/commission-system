#!/usr/bin/env node
/**
 * okki_outbound_poller.js — 消费方舟 ark_okki_outbound_tasks，自动生成 OKKI 销售出库单。
 *
 * 部署位置：singapore 主机 /root/.openclaw/workspace/okki-sync/（与 create-outbound.js 同目录）。
 * 运行方式：单次处理一批后退出（推荐，由 systemd timer 每分钟触发）；OUTBOUND_LOOP=1 时常驻轮询。
 *
 * 任务状态机（后端 ark_okki_outbound_tasks 表是唯一事实来源）：
 *   pending → running → done / failed
 *   failed 且 attempts < OUTBOUND_MAX_ATTEMPTS 按 (attempts+1)*5 分钟退避后重试
 *   running 且超过 OUTBOUND_TIMEOUT_MS + 5 分钟未回写 = 认领进程已死，回收重试
 *   （attempts 用尽的 running/failed 行不再自动动，人工核对后重置 status='pending'）
 *   skipped（含非标合并行的发票）永不消费，由人工在 OKKI 处理
 *
 * 时间口径：后端写北京时间（naive）。本脚本所有 SQL 时间戳一律用北京墙钟字符串，
 * 不依赖 singapore 主机的系统时区，SQL 里禁止 NOW()。
 *
 * 环境变量（写在 okki-sync/.env 或进程环境）：
 *   ARK_DB_HOST / ARK_DB_PORT(3306) / ARK_DB_USER / ARK_DB_PASSWORD / ARK_DB_NAME
 *     —— 方舟业务库（ark_invoices 所在 schema）；账号只需该表的 SELECT/UPDATE 权限
 *   OUTBOUND_SCRIPT_DIR   —— create-outbound.js 所在目录（默认本脚本所在目录）
 *   OUTBOUND_BATCH        —— 单轮最多处理任务数（默认 5）
 *   OUTBOUND_MAX_ATTEMPTS —— 单任务最大认领次数（默认 5，超过后保持原状待人工）
 *   OUTBOUND_TIMEOUT_MS   —— 单订单脚本超时（默认 120000）
 *   OUTBOUND_LOOP         —— 1=常驻循环（默认 0，跑一批即退出）
 *   OUTBOUND_INTERVAL_MS  —— 常驻模式轮询间隔（默认 30000）
 *
 * 退出码：0=本轮全部成功或无任务；1=有失败或自身异常；2=配置缺失。
 * 注意：create-outbound.js 退出码 2=参数错误。所有非零退出都按 failed 退避重试，
 * 达 OUTBOUND_MAX_ATTEMPTS 后不再自动重试，避免参数类错误无限刷接口。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import mysql from 'mysql2/promise';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));

// 轻量 .env 兜底（不覆盖已有进程环境变量），避免强依赖 dotenv
function loadDotenv(file) {
  try {
    const text = fs.readFileSync(file, 'utf8');
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith('#')) continue;
      const eq = line.indexOf('=');
      if (eq <= 0) continue;
      const key = line.slice(0, eq).trim();
      let value = line.slice(eq + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      if (!(key in process.env)) process.env[key] = value;
    }
  } catch { /* .env 不存在时全靠进程环境 */ }
}
loadDotenv(path.join(SCRIPT_DIR, '.env'));

function num(value, fallback) {
  const n = Math.floor(Number(value));
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

const config = {
  db: {
    host: process.env.ARK_DB_HOST || '127.0.0.1',
    port: num(process.env.ARK_DB_PORT, 3306),
    user: process.env.ARK_DB_USER || '',
    password: process.env.ARK_DB_PASSWORD || '',
    database: process.env.ARK_DB_NAME || '',
    // 与后端一致：北京时间 naive 字符串，禁用驱动侧的时区换算
    dateStrings: true,
  },
  scriptDir: process.env.OUTBOUND_SCRIPT_DIR || SCRIPT_DIR,
  batch: num(process.env.OUTBOUND_BATCH, 5),
  maxAttempts: num(process.env.OUTBOUND_MAX_ATTEMPTS, 5),
  timeoutMs: num(process.env.OUTBOUND_TIMEOUT_MS, 120000),
  loop: process.env.OUTBOUND_LOOP === '1',
  intervalMs: num(process.env.OUTBOUND_INTERVAL_MS, 30000),
};
// running 卡死回收阈值：单订单脚本超时时长 + 5 分钟缓冲
const STALE_RUNNING_MINUTES = Math.ceil(config.timeoutMs / 60000) + 5;

function beijingNow() {
  // 北京墙钟（UTC+8），与后端 beijing_now() 的 naive 落库口径一致
  const d = new Date(Date.now() + 8 * 3600 * 1000);
  return d.toISOString().slice(0, 19).replace('T', ' ');
}

function log(message, extra) {
  const line = `[outbound-poller] ${beijingNow()} ${message}`;
  if (extra !== undefined) {
    console.log(line, typeof extra === 'string' ? extra : JSON.stringify(extra));
  } else {
    console.log(line);
  }
}

// 可认领口径（SELECT 与 UPDATE 共用同一谓词，多实例/回收场景下 UPDATE 复核防绕过）：
//   待执行 / 失败未超限且退避到期 / running 卡死未超限
const CLAIMABLE = `(
     status = 'pending'
  OR (status = 'failed' AND attempts < ? AND updated_at <= DATE_SUB(?, INTERVAL (attempts + 1) * 5 MINUTE))
  OR (status = 'running' AND attempts < ? AND updated_at <= DATE_SUB(?, INTERVAL ? MINUTE))
)`;

async function claimBatch(conn) {
  const now = beijingNow();
  const [rows] = await conn.query(
    `SELECT id, order_id, attempts
       FROM ark_okki_outbound_tasks
      WHERE ${CLAIMABLE}
      ORDER BY id
      LIMIT ?`,
    [config.maxAttempts, now, config.maxAttempts, now, STALE_RUNNING_MINUTES, config.batch],
  );
  const claimed = [];
  for (const row of rows) {
    // 乐观认领：谓词完整复核，只有一处能把行翻成 running（attempts 记认领次数）
    const [result] = await conn.query(
      `UPDATE ark_okki_outbound_tasks
          SET status = 'running', attempts = attempts + 1, updated_at = ?
        WHERE id = ? AND ${CLAIMABLE}`,
      [now, row.id, config.maxAttempts, now, config.maxAttempts, now, STALE_RUNNING_MINUTES],
    );
    if (result.affectedRows === 1) claimed.push(row);
  }
  return claimed;
}

function runCreateOutbound(orderId) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      [path.join(config.scriptDir, 'create-outbound.js'), String(orderId), '--run'],
      { cwd: config.scriptDir, env: process.env },
    );
    let output = '';
    const onData = (chunk) => {
      output += chunk.toString();
      if (output.length > 64000) output = output.slice(-64000); // 只留尾部，防内存膨胀
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      resolve({ code: -1, output: `${output}\n[outbound-poller] timeout after ${config.timeoutMs}ms, killed` });
    }, config.timeoutMs);
    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ code: -1, output: `${output}\n[outbound-poller] spawn error: ${err.message}` });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code, output });
    });
  });
}

async function markDone(conn, id) {
  await conn.query(
    `UPDATE ark_okki_outbound_tasks
        SET status = 'done', last_error = NULL, processed_at = ?, updated_at = ?
      WHERE id = ?`,
    [beijingNow(), beijingNow(), id],
  );
}

async function markFailed(conn, id, error) {
  await conn.query(
    `UPDATE ark_okki_outbound_tasks
        SET status = 'failed', last_error = ?, processed_at = ?, updated_at = ?
      WHERE id = ?`,
    [String(error).slice(-1500), beijingNow(), beijingNow(), id],
  );
}

async function runOnce(conn) {
  const tasks = await claimBatch(conn);
  if (tasks.length === 0) return { ok: 0, failed: 0 };
  let ok = 0;
  let failed = 0;
  for (const task of tasks) {
    log(`start task#${task.id} order=${task.order_id} attempt=${task.attempts + 1}`);
    const { code, output } = await runCreateOutbound(task.order_id);
    if (code === 0) {
      await markDone(conn, task.id);
      ok += 1;
      log(`done task#${task.id} order=${task.order_id}`);
    } else {
      await markFailed(conn, task.id, `exit=${code}\n${output}`);
      failed += 1;
      log(`failed task#${task.id} order=${task.order_id} exit=${code}`, output.slice(-500));
    }
  }
  return { ok, failed };
}

async function main() {
  if (!config.db.user || !config.db.database) {
    console.error('[outbound-poller] ARK_DB_USER / ARK_DB_NAME 未配置，退出');
    process.exit(2);
  }
  log(`config: db=${config.db.host}:${config.db.port}/${config.db.database} scriptDir=${config.scriptDir} `
    + `batch=${config.batch} maxAttempts=${config.maxAttempts} timeoutMs=${config.timeoutMs} loop=${config.loop}`);
  const conn = await mysql.createConnection(config.db);
  let totalFailed = 0;
  try {
    do {
      const { ok, failed } = await runOnce(conn);
      totalFailed = failed;
      if (!config.loop && ok === 0 && failed === 0) log('no claimable tasks');
      if (config.loop) await new Promise((r) => setTimeout(r, config.intervalMs));
    } while (config.loop);
  } finally {
    await conn.end();
  }
  process.exit(totalFailed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error(`[outbound-poller] fatal: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
