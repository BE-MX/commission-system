/** Managed outbound creation: live association check + durable submission intent. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const now = () => new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 19).replace('T', ' ');

export function buildPayload(order, invoiceNo) {
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
  return { serial_id: invoiceNo, status: 1, source_type: 2, currency: order.currency || 'USD',
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
        return { outbound_invoice_id: row.outbound_invoice_id, serial_id: row.serial_id };
      }
    }
    if (!fresh) throw new Error('Outbound pagination repeated');
    if (seen.size >= Number(data.count)) return null;
  }
  throw new Error('Outbound scan limit exceeded; no creation attempted');
}

export async function createOne(orderId, {api, directory, invoiceNo, dryRun = false, knownIds = []}) {
  if (!/^\d+$/.test(orderId)) throw new Error('Invalid order ID');
  const order = await api('/v1/invoices/order/info?order_id=' + orderId);
  if (String(order.order_id) !== orderId) throw new Error('Order ID mismatch');
  const existing = await findExisting(order, api, knownIds);
  if (existing) return { outcome: 'existing', order_id: orderId, ...existing };
  const ledger = path.join(directory, 'logs', 'created-outbound.jsonl');
  if (fs.existsSync(ledger)) {
    const records = fs.readFileSync(ledger, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
    if (records.some(r => String(r.order_id) === orderId)) throw Object.assign(new Error('Local ledger exists but no live association; manual review required'), {uncertain: true});
  }
  const payload = buildPayload(order, invoiceNo);
  const intents = path.join(directory, 'logs', 'ark-outbound-intents');
  const intent = path.join(intents, orderId + '.json');
  if (fs.existsSync(intent)) throw Object.assign(new Error('Prior submission intent exists; no automatic resubmission'), {uncertain: true});
  if (dryRun) return { outcome: 'dry_run', order_id: orderId, serial_id: payload.serial_id, items: payload.record_list.length, quantity: payload.record_list.reduce((n, r) => n + r.outbound_count, 0) };
  fs.mkdirSync(intents, {recursive: true, mode: 0o700});
  let fd;
  try { fd = fs.openSync(intent, 'wx', 0o600); }
  catch (error) { if (error.code === 'EEXIST') error.uncertain = true; throw error; }
  try { fs.writeFileSync(fd, JSON.stringify({order_id: orderId, started_at: now()})); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
  // Once intent is durable, every ambiguous failure is quarantined, never retried.
  try {
    const result = await api('/v1/invoices/outbound/push', payload);
    if (!result.outbound_invoice_id || !result.serial_id) throw new Error('Creation response missing outbound ID/number');
    if (result.serial_id !== invoiceNo) throw new Error('Created outbound number differs from Ark invoice');
    const detail = await api('/v1/invoices/outbound/info?outbound_invoice_id=' + result.outbound_invoice_id);
    if (!Array.isArray(detail.record_list) || !detail.record_list.some(r => String(r.order_id) === orderId)) throw new Error('Created outbound association not verified');
    const row = {order_id: orderId, outbound_invoice_id: result.outbound_invoice_id, serial_id: result.serial_id, at: now()};
    fs.appendFileSync(ledger, JSON.stringify(row) + '\n', {mode: 0o600});
    return {outcome: 'created', ...row};
  } catch (error) { error.uncertain = true; throw error; }
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
      if (!response.ok || data.code !== 200 || !data.data) throw new Error('OKKI ' + route.split('?')[0] + ' HTTP=' + response.status + ' code=' + data.code);
      return data.data;
    } catch (error) {
      if (payload || attempt === 1) throw error;
    }
  }
  throw new Error('OKKI read retry exhausted');
}

async function main() {
  const directory = process.env.OUTBOUND_SCRIPT_DIR || path.dirname(fileURLToPath(import.meta.url));
  const {OkkiAuth, OKKI_CONFIG} = await import('./auth.js');
  const auth = new OkkiAuth();
  const api = (route, payload) => requestOkki(auth, OKKI_CONFIG.baseUrl, route, payload);
  const mysql = await import('mysql2/promise');
  const conn = await mysql.createConnection({host: process.env.ARK_DB_HOST, port: Number(process.env.ARK_DB_PORT || 3306),
    user: process.env.ARK_DB_USER, password: process.env.ARK_DB_PASSWORD, database: process.env.ARK_DB_NAME});
  let knownIds, invoiceNo;
  try {
    const schema = process.env.ARK_BUSINESS_DB_NAME;
    if (!/^[A-Za-z0-9_]+$/.test(schema || '')) throw new Error('Invalid business schema');
    const [rows] = await conn.query(`SELECT DISTINCT outbound_invoice_id FROM \`${schema}\`.okki_outbound_record_items WHERE order_id=?`, [process.argv[2]]);
    knownIds = rows.map(row => String(row.outbound_invoice_id));
    const [invoices] = await conn.query('SELECT i.invoice_no FROM ark_invoices i JOIN ark_okki_outbound_tasks t ON t.invoice_id=i.id WHERE t.order_id=?', [process.argv[2]]);
    if (invoices.length !== 1) throw new Error('Expected one Ark invoice for outbound task');
    invoiceNo = invoices[0].invoice_no;
  } finally { await conn.end(); }
  const result = await createOne(process.argv[2], {api, directory, invoiceNo, knownIds, dryRun: !process.argv.includes('--run')});
  console.log('ARK_OUTBOUND_RESULT=' + JSON.stringify(result));
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.message); process.exitCode = error.uncertain ? 3 : 1; });
}
