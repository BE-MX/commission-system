import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
import { SfError, statusLabel } from '../app/lib/sf-tracking.ts';

async function setup(options = {}) {
  const sql = new DatabaseSync(':memory:');
  sql.exec(`CREATE TABLE orders (id INTEGER PRIMARY KEY, order_no TEXT, channel TEXT, customer_phone TEXT, tracking_no TEXT,
    logistics_company TEXT, logistics_status TEXT, status TEXT, shipped_at TEXT, payment_status TEXT);
    INSERT INTO orders VALUES (1,'LS-TEST','retail','13900000000','SF1000000000000','顺丰速运','等待轨迹','已发货',NULL,'待付款');`);
  const migration = readFileSync(new URL('../drizzle/0009_friendly_ikaris.sql', import.meta.url), 'utf8');
  sql.exec(migration);
  const db = {
    prepare(query) {
      const values = [];
      const prepared = { bind(...args) { values.push(...args); return prepared; },
        _run() { const result = sql.prepare(query).run(...values); return { meta: { changes: Number(result.changes) } }; },
        async run() { return prepared._run(); },
        async first() { return sql.prepare(query).get(...values) ?? null; },
      };
      return prepared;
    },
    async batch(statements) {
      sql.exec('BEGIN');
      try { const results = statements.map((s) => s._run()); sql.exec('COMMIT'); return results; }
      catch (error) { sql.exec('ROLLBACK'); throw error; }
    },
  };
  const env = { SF_PARTNER_ID: 'TEST', SF_CHECKWORD: 'test-only', SF_SANDBOX: 'false', ...options.env };
  const context = vm.createContext({ Date, JSON, Number, String, Boolean, Array, Math, crypto, Response, URL });
  const modules = new Map();
  function stub(name, values) {
    const m = new vm.SyntheticModule(Object.keys(values), function() { for (const [key, value] of Object.entries(values)) this.setExport(key, value); }, { context, identifier: name });
    modules.set(name, m); return m;
  }
  let queries = 0;
  stub('cloudflare:workers', { env });
  stub('../../db/runtime', { getD1: () => db, ensureDatabase: async () => {} });
  stub('./sf-tracking', { SfError, statusLabel, querySf: async (...args) => {
    queries++; if (options.query) return options.query(...args);
    return { state: 'delivered', events: [{ time: '2026-11-18T15:00:00+08:00', status: '已签收', location: '济南', description: '已签收' }] };
  } });
  const source = readFileSync(new URL('../app/lib/order-logistics.ts', import.meta.url), 'utf8');
  const service = new vm.SourceTextModule(stripTypeScriptTypes(source), { context, identifier: 'logistics' });
  await service.link((specifier) => { if (!modules.has(specifier)) throw new Error(specifier); return modules.get(specifier); });
  await service.evaluate();
  const lib = service.namespace;
  return { lib, sql, env, db, context, queries: () => queries };
}

test('shipment saves are compare-and-swap, preserve payment, reject invalid waybills and stale forms', async () => {
  const s = await setup(); const order = await s.lib.readLogisticsOrder(1); const row = await s.lib.readSnapshot(order);
  assert.equal((await s.lib.saveShipment(order, { trackingNo: 'fake', revision: row.revision })).status, 400);
  assert.equal((await s.lib.saveShipment(order, { trackingNo: 'SF2000000000000', phoneLast4: '1234', revision: row.revision })).status, 200);
  assert.equal((await s.lib.saveShipment(order, { trackingNo: 'SF3000000000000', revision: row.revision })).status, 409);
  const saved = s.sql.prepare('SELECT * FROM orders WHERE id=1').get();
  assert.equal(saved.tracking_no, 'SF2000000000000'); assert.equal(saved.payment_status, '待付款');
});
test('concurrent refreshes share a DB lease, and subsequent reads reuse the one-hour cache', async () => {
  const s = await setup(); const order = await s.lib.readLogisticsOrder(1); const row = await s.lib.readSnapshot(order);
  await Promise.all([s.lib.refreshLogistics(order, row), s.lib.refreshLogistics(order, row)]);
  const current = await s.lib.readSnapshot(order);
  await s.lib.refreshLogistics(order, current);
  assert.equal(s.queries(), 1);
  assert.equal((await s.lib.readLogisticsOrder(1)).status, '已签收');
});
test('a late SF response cannot replace a corrected waybill or attach its events', async () => {
  let release;
  const response = new Promise((resolve) => { release = resolve; });
  const s = await setup({ query: () => response }); const order = await s.lib.readLogisticsOrder(1); const row = await s.lib.readSnapshot(order);
  const refreshing = s.lib.refreshLogistics(order, row);
  while (s.queries() === 0) await new Promise((resolve) => setImmediate(resolve));
  assert.equal((await s.lib.saveShipment(order, { trackingNo: 'SF4000000000000', revision: row.revision })).status, 200);
  release({ state: 'delivered', events: [{ time: '2026-11-18T15:00:00+08:00', description: 'OLD', status: '已签收', location: '济南' }] });
  await refreshing;
  const latest = await s.lib.readLogisticsOrder(1), snapshot = await s.lib.readSnapshot(latest);
  assert.equal(latest.trackingNo, 'SF4000000000000'); assert.equal(snapshot.events, '[]'); assert.equal(latest.status, '已发货');
});
test('errors preserve old events and impose backoff instead of inventing movement', async () => {
  const s = await setup({ query: async () => { throw new SfError('NETWORK', '网络暂时不可用'); } });
  const order = await s.lib.readLogisticsOrder(1); await s.lib.readSnapshot(order);
  s.sql.prepare("UPDATE order_logistics SET events=?, state='in_transit'").run(JSON.stringify([{ description: 'previous' }]));
  const row = await s.lib.readSnapshot(order); const updated = await s.lib.refreshLogistics(order, row);
  assert.equal(updated.events, row.events); assert.equal(updated.failures, 1); assert.ok(Date.parse(updated.next_check_at) > Date.now() + 3500000);
  assert.equal((await s.lib.readLogisticsOrder(1)).status, '已发货');
});
test('sandbox results are labelled and never mark a real order delivered', async () => {
  const s = await setup({ env: { SF_SANDBOX: 'true' } }); const order = await s.lib.readLogisticsOrder(1);
  const row = await s.lib.refreshLogistics(order, await s.lib.readSnapshot(order));
  assert.equal(s.lib.publicLogistics(order, row, false).sandbox, true);
  assert.equal((await s.lib.readLogisticsOrder(1)).status, '已发货');
});
test('switching from sandbox to production clears mock events even if production fails', async () => {
  const s = await setup({ query: async () => { throw new SfError('A1004', '生产权限未开通'); } }); const order = await s.lib.readLogisticsOrder(1);
  await s.lib.readSnapshot(order);
  s.sql.exec(`UPDATE order_logistics SET sandbox=1,events='[{"description":"MOCK"}]',state='delivered'`);
  const row = await s.lib.refreshLogistics(order, await s.lib.readSnapshot(order));
  assert.equal(row.events, '[]'); assert.equal(row.sandbox, 0); assert.equal(row.last_error, '生产权限未开通');
});
test('customer output does not expose validation phone or revision', async () => {
  const s = await setup(); const order = await s.lib.readLogisticsOrder(1); const row = await s.lib.readSnapshot(order);
  row.phone_last4 = '1234';
  const response = s.lib.publicLogistics(order, row, false);
  assert.equal('phoneLast4' in response, false); assert.equal('revision' in response, false);
  assert.equal(s.lib.publicLogistics(order, row, true).phoneLast4, '1234');
});
test('route enforces both order owner and retail/wholesale channel before querying SF', async () => {
  const s = await setup();
  let retailPhone = '13800000000';
  const exports = (values) => new vm.SyntheticModule(Object.keys(values), function() { for (const [key, value] of Object.entries(values)) this.setExport(key, value); }, { context: s.context });
  const dependencies = {
    '../../../../lib/admin-auth': exports({ requireAdminApi: async () => Response.json({ error: 'denied' }, { status: 401 }) }),
    '../../../../lib/retail-session': exports({ getRetailPhone: async () => retailPhone }),
    '../../../../lib/wholesale-session': exports({ getWholesaleAccount: async () => ({ phone: '13900000000' }) }),
    '../../../../lib/order-logistics': exports(Object.fromEntries(Object.keys(s.lib).map((k) => [k, s.lib[k]]))),
  };
  const route = new vm.SourceTextModule(stripTypeScriptTypes(readFileSync(new URL('../app/api/orders/[id]/logistics/route.ts', import.meta.url), 'utf8')), { context: s.context });
  await route.link((specifier) => dependencies[specifier]); await route.evaluate();
  for (const mode of ['retail', 'wholesale', 'admin']) {
    const response = await route.namespace.GET(new Request(`https://shop.test/api/orders/1/logistics?mode=${mode}`), { params: Promise.resolve({ id: '1' }) });
    assert.equal(response.status, mode === 'admin' ? 401 : 404);
  }
  assert.equal(s.queries(), 0);
  retailPhone = '13900000000';
  const allowed = await route.namespace.GET(new Request('https://shop.test/api/orders/1/logistics?mode=retail'), { params: Promise.resolve({ id: '1' }) });
  assert.equal(allowed.status, 200);
  assert.equal(allowed.headers.get('cache-control'), 'private, no-store');
  const body = await allowed.json();
  assert.equal('phoneLast4' in body.logistics, false);
  assert.equal('revision' in body.logistics, false);
});

test('shared daily budget limits calls across different orders', async () => {
  const s = await setup({ env: { SF_DAILY_QUERY_LIMIT: '1' }, query: async (_cfg, _no, _phone, reserve) => {
    await reserve();
    return { state: 'in_transit', events: [{ time: '2026-11-18T15:00:00+08:00', status: '运输中', location: '', description: '运输中' }] };
  } });
  const first = await s.lib.readLogisticsOrder(1);
  await s.lib.refreshLogistics(first, await s.lib.readSnapshot(first));
  s.sql.exec(`INSERT INTO orders SELECT 2,'LS-TEST-2',channel,customer_phone,'SF2000000000000',logistics_company,logistics_status,status,NULL,payment_status FROM orders WHERE id=1`);
  const second = await s.lib.readLogisticsOrder(2);
  const result = await s.lib.refreshLogistics(second, await s.lib.readSnapshot(second));
  assert.match(result.last_error, /查询较多/);
  assert.equal(s.sql.prepare("SELECT used FROM logistics_query_budget WHERE name='sf-day'").get().used, 1);
});
