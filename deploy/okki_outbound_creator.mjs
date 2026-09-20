/** Managed outbound creation: live association check + durable submission intent. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const now = () => new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 19).replace('T', ' ');

export function buildPayload(order, invoiceNo, invoiceRemark) {
  if (invoiceRemark != null && typeof invoiceRemark !== 'string') throw new Error('Invalid Ark invoice remark');
  if (typeof invoiceNo !== 'string' || !invoiceNo.trim()) throw new Error('Missing Ark invoice number');
  if (!Array.isArray(order.product_list) || !order.product_list.length) throw new Error('Order has no items');
  const handler = (order.handler || []).map(String).filter(Boolean);
  if (!handler.length) throw new Error('Order has no handler');
  const record_list = order.product_list.map(p => {
    if (!p.product_id || !p.sku_id || !p.unique_id || !(Number(p.count) > 0)) throw new Error('Invalid order item; refusing partial outbound');
    return { sku_id: p.sku_id, product_id: p.product_id, order_id: order.order_id,
      order_record_id: Number(p.unique_id), outbound_count: Number(p.count), sale_price: Number(p.unit_price || 0),
      product_unit: p.unit || 'Piece', product_name: p.product_name, product_model: p.product_model,
      product_cn_name: p.product_cn_name || undefined };
  });
  return { serial_id: invoiceNo, remark: invoiceRemark ?? '', status: 1, source_type: 2, currency: order.currency || 'USD',
    exchange_rate: Number(order.exchange_rate || 0), exchange_rate_usd: Number(order.exchange_rate_usd || 0),
    invoice_warehouse_id: 8193514242746, company_id: order.company_id, handler, record_list };
}

// No order_id filter exists on the OKKI list API. Scan all updates since the
// order was created, then inspect the actual record_list associations. An older
// outbound edited to link this order also has an update time inside this window.
export async function findExisting(order, api, knownIds = []) {
  for (const id of knownIds) {
    const detail = await api('/v1/invoices/outbound/info?outbound_invoice_id=' + id);
    if (!Array.isArray(detail.record_list)) throw new Error('Outbound detail missing record_list');
    if (detail.record_list.some(r => String(r.order_id) === String(order.order_id))) {
      assertSingleOrder(detail, order);
      return {outbound_invoice_id: id, serial_id: detail.serial_id};
    }
  }
  if (!/^\d{4}-\d{2}-\d{2}/.test(order.create_time || '')) throw new Error('Missing authoritative order creation time');
  const start = order.create_time.slice(0, 10) + ' 00:00:00';
  const seen = new Set();
  for (let page = 1; page <= 500; page++) {
    const qs = new URLSearchParams({count: '100', start_index: String(page), time_type: '1', start_time: start, removed: '0'});
    const data = await api('/v1/invoices/outbound/list?' + qs);
    if (!Array.isArray(data.list) || !Number.isFinite(Number(data.count))) throw new Error('Invalid outbound list response');
    if (data.list.length === 0) {
      if (seen.size < Number(data.count)) throw new Error('Incomplete outbound pagination');
      return null;
    }
    let fresh = 0;
    for (const row of data.list) {
      if (!row.outbound_invoice_id) throw new Error('Outbound list missing ID');
      const id = String(row.outbound_invoice_id);
      if (seen.has(id)) continue;
      seen.add(id); fresh++;
      const detail = await api('/v1/invoices/outbound/info?outbound_invoice_id=' + id);
      if (!Array.isArray(detail.record_list)) throw new Error('Outbound detail missing record_list');
      if (detail.record_list.some(r => String(r.order_id) === String(order.order_id))) {
        assertSingleOrder(detail, order);
        return { outbound_invoice_id: row.outbound_invoice_id, serial_id: row.serial_id };
      }
    }
    if (!fresh) throw new Error('Outbound pagination repeated');
    if (seen.size >= Number(data.count)) return null;
  }
  throw new Error('Outbound scan limit exceeded; no creation attempted');
}

// OKKI push upserts by serial_id even when outbound_invoice_id is omitted.
// Probe the global serial namespace, including documents older than this order.
function assertSingleOrder(detail, order) {
  if (!Array.isArray(detail.record_list) || !detail.record_list.length ||
      detail.record_list.some(r => String(r.order_id) !== String(order.order_id))) {
    throw Object.assign(new Error('Outbound contains unrelated order lines; manual reconciliation required'), {uncertain: true});
  }
}

export async function selectSerial(order, invoiceNo, api) {
  for (const serial of [invoiceNo, `${invoiceNo} [${order.order_id}]`]) {
    const detail = await api('/v1/invoices/outbound/info?' + new URLSearchParams({serial_id: serial}));
    if (detail === null) return {serial};
    if (!detail?.outbound_invoice_id || detail.serial_id !== serial || !Array.isArray(detail.record_list)) throw new Error('Invalid serial lookup response');
    if (detail.record_list.some(r => String(r.order_id) === String(order.order_id))) {
      assertSingleOrder(detail, order);
      return {existing: {outbound_invoice_id: detail.outbound_invoice_id, serial_id: serial}};
    }
  }
  throw new Error('Outbound serial collision; no submission attempted');
}

export function verifyCreated(detail, result, payload) {
  if (String(detail.outbound_invoice_id) !== String(result.outbound_invoice_id) ||
      detail.serial_id !== payload.serial_id || Number(detail.status) !== 1 ||
      String(detail.company_info?.id) !== String(payload.company_id)) throw new Error('Created outbound identity/customer/status differs');
  const signature = row => JSON.stringify([String(row.order_id), String(row.order_record_id),
    String(row.product_id), String(row.sku_id), Number(row.outbound_count), Number(row.sale_price)]);
  const actual = (detail.record_list || []).map(signature).sort();
  const expected = payload.record_list.map(signature).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error('Created outbound items differ from requested order');
}

// Inventory is checked against the exact destination warehouse, not order enable_count.
export async function stockShortages(payload, api) {
  const needs = new Map();
  for (const row of payload.record_list) needs.set(String(row.sku_id), (needs.get(String(row.sku_id)) || 0) + row.outbound_count);
  const shortages = [];
  for (const [sku, required] of needs) {
    const data = await api('/v1/product/inventory-list?' + new URLSearchParams({sku_id: sku, count: '100', start_index: '1'}));
    // Fail closed if a complete warehouse listing cannot be proved.
    if (!Array.isArray(data.list) || !Number.isInteger(Number(data.count)) || Number(data.count) !== data.list.length) throw new Error('Incomplete inventory response');
    const rows = data.list.filter(r => String(r.sku_id) === sku && String(r.warehouse_id) === String(payload.invoice_warehouse_id));
    if (rows.length > 1) throw new Error('Duplicate warehouse inventory rows');
    let available = 0;
    if (rows.length) {
      const row = rows[0];
      if (row.enable_count == null || String(row.enable_count).trim() === '' || !Number.isFinite(Number(row.enable_count)) || ![0, 1].includes(Number(row.disable_flag)) || row.disable_flag == null) throw new Error('Invalid warehouse inventory');
      available = Number(row.disable_flag) === 0 ? Number(row.enable_count) : 0;
    }
    if (available < required) shortages.push({sku_id: sku, required, available});
  }
  return shortages;
}

function nextSubmissionIntent(baseIntent, orderId) {
  let intent = baseIntent, retry = 0;
  while (fs.existsSync(intent)) {
    let previous;
    try { previous = JSON.parse(fs.readFileSync(intent, 'utf8')); }
    catch { throw Object.assign(new Error('Unreadable submission intent; manual review required'), {uncertain: true}); }
    if (previous.order_id !== orderId || previous.outcome !== 'stock_rejected') throw Object.assign(new Error('Prior submission intent exists; no automatic resubmission'), {uncertain: true});
    intent = baseIntent + '.retry-' + (++retry);
  }
  return {intent, retry};
}

async function recoverExisting(existing, order, {api, directory, invoiceNo, invoiceRemark}) {
  const intent = path.join(directory, 'logs', 'ark-outbound-intents', String(order.order_id) + '.json');
  // A previously submitted document cannot bypass strict verification on recovery.
  // Manual partial outbounds without our intent continue to prevent duplicate creation.
  if (fs.existsSync(intent)) {
    try {
      const detail = await api('/v1/invoices/outbound/info?outbound_invoice_id=' + existing.outbound_invoice_id);
      let latest = intent;
      for (let retry = 1; fs.existsSync(intent + '.retry-' + retry); retry++) latest = intent + '.retry-' + retry;
      const saved = JSON.parse(fs.readFileSync(latest, 'utf8'));
      if (saved.order_id !== String(order.order_id)) throw new Error('Submission intent order mismatch');
      const expected = saved.payload || {...buildPayload(order, invoiceNo, invoiceRemark), serial_id: existing.serial_id};
      verifyCreated(detail, existing, expected);
      if ((detail.remark ?? '') !== expected.remark) throw new Error('Recovered outbound remark differs');
    } catch (error) { error.uncertain = true; throw error; }
  }
  return {outcome: 'existing', order_id: String(order.order_id), ...existing};
}

export async function createOne(orderId, options) {
  try { return await createOneAttempt(orderId, options); }
  catch (error) {
    if (!error.uncertain && /^\d+$/.test(orderId)) {
      const base = path.join(options.directory, 'logs', 'ark-outbound-intents', orderId + '.json');
      // After worker recovery the queue may have lost its prior waiting state.
      // Only durable rejection evidence with no newer active intent permits waiting.
      try {
        if (nextSubmissionIntent(base, orderId).retry > 0) {
          console.warn('[outbound] stock retry deferred: ' + error.message);
          return {outcome: 'waiting_stock', order_id: orderId, reason: 'Stock retry deferred: ' + error.message};
        }
      } catch { error.uncertain = true; }
    }
    throw error;
  }
}

async function createOneAttempt(orderId, {api, directory, invoiceNo, invoiceRemark, dryRun = false, knownIds = []}) {
  if (!/^\d+$/.test(orderId)) throw new Error('Invalid order ID');
  const order = await api('/v1/invoices/order/info?order_id=' + orderId);
  if (String(order.order_id) !== orderId) throw new Error('Order ID mismatch');
  const existing = await findExisting(order, api, knownIds);
  if (existing) return recoverExisting(existing, order, {api, directory, invoiceNo, invoiceRemark});
  const ledger = path.join(directory, 'logs', 'created-outbound.jsonl');
  if (fs.existsSync(ledger)) {
    const records = fs.readFileSync(ledger, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
    if (records.some(r => String(r.order_id) === orderId)) throw Object.assign(new Error('Local ledger exists but no live association; manual review required'), {uncertain: true});
  }
  const payload = buildPayload(order, invoiceNo, invoiceRemark);
  const selection = await selectSerial(order, invoiceNo, api);
  if (selection.existing) return recoverExisting(selection.existing, order, {api, directory, invoiceNo, invoiceRemark});
  payload.serial_id = selection.serial;
  const intents = path.join(directory, 'logs', 'ark-outbound-intents');
  const baseIntent = path.join(intents, orderId + '.json');
  const {intent, retry} = nextSubmissionIntent(baseIntent, orderId);
  if (retry) {
    let shortages;
    try { shortages = await stockShortages(payload, api); }
    catch (error) {
      console.warn('[outbound] inventory check failed: ' + error.message);
      return {outcome: 'waiting_stock', order_id: orderId, reason: 'Inventory check failed: ' + error.message};
    }
    if (shortages.length) return {outcome: 'waiting_stock', order_id: orderId, reason: 'Insufficient warehouse stock', shortages};
  }
  if (dryRun) return { outcome: 'dry_run', order_id: orderId, serial_id: payload.serial_id, items: payload.record_list.length, quantity: payload.record_list.reduce((n, r) => n + r.outbound_count, 0) };
  fs.mkdirSync(intents, {recursive: true, mode: 0o700});
  let fd;
  try { fd = fs.openSync(intent, 'wx', 0o600); }
  catch (error) { if (error.code === 'EEXIST') error.uncertain = true; throw error; }
  try { fs.writeFileSync(fd, JSON.stringify({order_id: orderId, started_at: now(), payload})); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
  // Once intent is durable, every ambiguous failure is quarantined, never retried.
  try {
    const result = await api('/v1/invoices/outbound/push', payload);
    if (!result.outbound_invoice_id || !result.serial_id) throw new Error('Creation response missing outbound ID/number');
    if (result.serial_id !== payload.serial_id) throw new Error('Created outbound number differs from Ark invoice');
    const detail = await api('/v1/invoices/outbound/info?outbound_invoice_id=' + result.outbound_invoice_id);
    if (!Array.isArray(detail.record_list) || !detail.record_list.some(r => String(r.order_id) === orderId)) throw new Error('Created outbound association not verified');
    verifyCreated(detail, result, payload);
    if ((detail.remark ?? '') !== payload.remark) throw new Error('Created outbound remark differs from Ark invoice');
    const row = {order_id: orderId, outbound_invoice_id: result.outbound_invoice_id, serial_id: result.serial_id, at: now()};
    fs.appendFileSync(ledger, JSON.stringify(row) + '\n', {mode: 0o600});
    return {outcome: 'created', ...row};
  } catch (error) {
    if (error.stockRejected === true) {
      // Preserve rejection evidence. A crash during this write fails closed on next read.
      const fd = fs.openSync(intent, 'w', 0o600);
      try { fs.writeFileSync(fd, JSON.stringify({order_id: orderId, outcome: 'stock_rejected', rejected_at: now(), error: error.message, payload})); fs.fsyncSync(fd); }
      finally { fs.closeSync(fd); }
      return {outcome: 'waiting_stock', order_id: orderId, reason: error.message};
    }
    error.uncertain = true; throw error;
  }
}

export async function requestOkki(auth, base, route, payload, fetchImpl = fetch) {
  // Read failures may be transient. Never retry a POST whose acceptance is unknown.
  for (let attempt = 0; attempt < (payload ? 1 : 2); attempt++) {
    try {
      const token = await auth.getAccessToken();
      const response = await fetchImpl(base + route, {method: payload ? 'POST' : 'GET',
        headers: {Authorization: token, ...(payload ? {'Content-Type': 'application/json'} : {})},
        body: payload ? JSON.stringify(payload) : undefined, signal: AbortSignal.timeout(20000)});
      if (response.status === 401 && !payload && attempt === 0) {
        auth.accessToken = null;
        continue;
      }
      const data = await response.json();
      if (!payload && route.startsWith('/v1/invoices/outbound/info?serial_id=') &&
          response.status === 200 && data.code === 404 && data.message === 'Not Found Resource' && !data.data) return null;
      if (!response.ok || data.code !== 200 || !data.data) {
        const message = typeof data.message === 'string' ? data.message.trim() : '';
        const error = new Error('OKKI ' + route.split('?')[0] + ' HTTP=' + response.status + ' code=' + data.code + ' ' + message.slice(0, 500));
        // Narrow, observed business rejection only; unrelated 404s remain uncertain.
        error.stockRejected = !!payload && route === '/v1/invoices/outbound/push' && response.status === 200 && data.code === 404
          && /^Operation Failed\. 序号为\[\d+\]可用库存数量不足$/.test(message) && !data.data?.outbound_invoice_id;
        throw error;
      }
      return data.data;
    } catch (error) {
      if (payload || attempt === 1) throw error;
    }
  }
  throw new Error('OKKI read retry exhausted');
}

export async function loadInvoiceForOrder(conn, orderId) {
  const [invoices] = await conn.query('SELECT i.invoice_no, i.remark FROM ark_invoices i JOIN ark_okki_outbound_tasks t ON t.invoice_id=i.id WHERE t.order_id=?', [orderId]);
  if (invoices.length !== 1) throw new Error('Expected one Ark invoice for outbound task');
  return {invoiceNo: invoices[0].invoice_no, invoiceRemark: invoices[0].remark};
}

async function main() {
  const directory = process.env.OUTBOUND_SCRIPT_DIR || path.dirname(fileURLToPath(import.meta.url));
  const {OkkiAuth, OKKI_CONFIG} = await import('./auth.js');
  const auth = new OkkiAuth();
  const api = (route, payload) => requestOkki(auth, OKKI_CONFIG.baseUrl, route, payload);
  const mysql = await import('mysql2/promise');
  const conn = await mysql.createConnection({host: process.env.ARK_DB_HOST, port: Number(process.env.ARK_DB_PORT || 3306),
    user: process.env.ARK_DB_USER, password: process.env.ARK_DB_PASSWORD, database: process.env.ARK_DB_NAME});
  let knownIds, invoice;
  try {
    const schema = process.env.ARK_BUSINESS_DB_NAME;
    if (!/^[A-Za-z0-9_]+$/.test(schema || '')) throw new Error('Invalid business schema');
    const [rows] = await conn.query(`SELECT DISTINCT outbound_invoice_id FROM \`${schema}\`.okki_outbound_record_items WHERE order_id=?`, [process.argv[2]]);
    knownIds = rows.map(row => String(row.outbound_invoice_id));
    invoice = await loadInvoiceForOrder(conn, process.argv[2]);
  } finally { await conn.end(); }
  const result = await createOne(process.argv[2], {api, directory, ...invoice, knownIds, dryRun: !process.argv.includes('--run')});
  console.log('ARK_OUTBOUND_RESULT=' + JSON.stringify(result));
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.message); process.exitCode = error.uncertain ? 3 : 1; });
}
