#!/usr/bin/env node
/**
 * Consume Ark outbound tasks on Singapore; run the managed creator with --run.
 * pending / waiting_stock -> running -> done / skipped / waiting_stock / failed / uncertain.
 * A confirmed existing live outbound (including partial/manual) is skipped.
 * Pre-submit failures retry with backoff, up to five attempts. Ambiguous writes,
 * killed children, or invalid success envelopes are uncertain and never retried.
 * A MySQL named lock serializes pollers; each task is claimed just before use,
 * and final writes require the same running attempt version.
 * Configuration: .ark-outbound.env (mode 600), ARK_DB_* / ARK_BUSINESS_DB_NAME,
 * OUTBOUND_SCRIPT_DIR, OUTBOUND_BATCH (5), OUTBOUND_MAX_ATTEMPTS (5),
 * OUTBOUND_TIMEOUT_MS (120000), OUTBOUND_LOOP (0), OUTBOUND_INTERVAL_MS (30000).
 * SQL timestamps are Beijing wall time. systemd triggers once per minute.
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
loadDotenv(path.join(SCRIPT_DIR, '.ark-outbound.env'));

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
//   待执行 / 等待库存满15分钟（不限次数） / 失败未超限且退避到期 / running 卡死（由持久意图保护提交）
export const CLAIMABLE = `(
     status = 'pending'
  OR (status = 'waiting_stock' AND updated_at <= DATE_SUB(?, INTERVAL 15 MINUTE))
  OR (status = 'failed' AND attempts < ? AND updated_at <= DATE_SUB(?, INTERVAL (attempts + 1) * 5 MINUTE))
  OR (status = 'running' AND updated_at <= DATE_SUB(?, INTERVAL ? MINUTE))
)`;

export async function claimBatch(conn) {
  const now = beijingNow();
  const [rows] = await conn.query(
    `SELECT id, order_id, attempts, status
       FROM ark_okki_outbound_tasks
      WHERE ${CLAIMABLE}
      ORDER BY updated_at, id
      LIMIT ?`,
    [now, config.maxAttempts, now, now, STALE_RUNNING_MINUTES, 1],
  );
  const claimed = [];
  for (const row of rows) {
    // 乐观认领：谓词完整复核，只有一处能把行翻成 running（attempts 记认领次数）
    const [result] = await conn.query(
      `UPDATE ark_okki_outbound_tasks
          SET status = 'running', attempts = attempts + 1, updated_at = ?
        WHERE id = ? AND ${CLAIMABLE}`,
      [now, row.id, now, config.maxAttempts, now, now, STALE_RUNNING_MINUTES],
    );
    if (result.affectedRows === 1) claimed.push({...row, priorStatus: row.status, attempts: Number(row.attempts) + 1});
  }
  return claimed;
}

function runCreateOutbound(orderId) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      [path.join(config.scriptDir, 'okki_outbound_creator.mjs'), String(orderId), '--run'],
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
      // Wait for close: never release claim while the killed child might still run.
      output += '\n[outbound-poller] timeout; manual review required';
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

export function resultFromOutput(code, output, orderId) {
  if (code !== 0) return null;
  const lines = output.split(/\r?\n/).filter(line => line.startsWith('ARK_OUTBOUND_RESULT='));
  if (lines.length !== 1) return null;
  try {
    const result = JSON.parse(lines[0].slice('ARK_OUTBOUND_RESULT='.length));
    if (result.outcome === 'waiting_stock') return String(result.order_id) === String(orderId) && typeof result.reason === 'string' && result.reason.length > 0 && !result.outbound_invoice_id ? result : null;
    return ['created', 'existing'].includes(result.outcome) && String(result.order_id) === String(orderId)
      && result.outbound_invoice_id ? result : null;
  } catch { return null; }
}

export async function finishTask(conn, task, status, reason, error = null) {
  const [result] = await conn.query(
    `UPDATE ark_okki_outbound_tasks SET status=?, reason=?, last_error=?, processed_at=?, updated_at=?
     WHERE id=? AND status='running' AND attempts=?`,
    [status, reason, error, beijingNow(), beijingNow(), task.id, task.attempts]);
  if (result.affectedRows !== 1) throw new Error('Task ownership changed: ' + task.id);
}

async function runOnce(conn) {
  let ok = 0, failed = 0;
  for (let n = 0; n < config.batch; n++) {
    // Claim immediately before execution; never lease a waiting batch.
    const [task] = await claimBatch(conn);
    if (!task) break;
    log(`start task#${task.id} order=${task.order_id} attempt=${task.attempts}`);
    const {code, output} = await runCreateOutbound(task.order_id);
    const result = resultFromOutput(code, output, task.order_id);
    if (result) {
      const status = result.outcome === 'waiting_stock' ? 'waiting_stock' : result.outcome === 'existing' ? 'skipped' : 'done';
      const reason = status === 'waiting_stock' ? result.reason : `${result.outcome}: ${result.serial_id || result.outbound_invoice_id}`;
      await finishTask(conn, task, status, reason.slice(0, 255), status === 'waiting_stock' ? JSON.stringify(result).slice(-1500) : null);
      ok++;
      log(`task#${task.id} ${status}`, result);
    } else {
      // code 1 is a definite pre-submit failure. Kill/unknown/intent failures
      // are quarantined instead of risking a duplicate after a lost response.
      const status = code === 1 ? (task.priorStatus === 'waiting_stock' ? 'waiting_stock' : 'failed') : 'uncertain';
      await finishTask(conn, task, status, 'See last_error', `exit=${code}\n${output}`.slice(-1500));
      failed++;
      log(`task#${task.id} ${status}`, output.slice(-500));
    }
  }
  return {ok, failed};
}

async function main() {
  if (!config.db.user || !config.db.database) {
    console.error('[outbound-poller] ARK_DB_USER / ARK_DB_NAME 未配置，退出');
    process.exit(2);
  }
  log(`config: db=${config.db.host}:${config.db.port}/${config.db.database} scriptDir=${config.scriptDir} `
    + `batch=${config.batch} maxAttempts=${config.maxAttempts} timeoutMs=${config.timeoutMs} loop=${config.loop}`);
  const mysql = await import('mysql2/promise');
  const conn = await mysql.createConnection(config.db);
  const [[lock]] = await conn.query("SELECT GET_LOCK('ark-okki-outbound-poller', 0) AS acquired");
  if (Number(lock.acquired) !== 1) { await conn.end(); log('another poller owns the lock'); return; }
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

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch((err) => {
  console.error(`[outbound-poller] fatal: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
