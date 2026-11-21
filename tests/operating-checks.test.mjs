import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
import * as options from '../app/lib/product-options.ts';

async function setup(denied = false) {
  const sql = new DatabaseSync(':memory:');
  sql.exec(`CREATE TABLE orders (id INTEGER PRIMARY KEY, order_no TEXT, customer_phone TEXT, channel TEXT,
    sales_person TEXT, payment_status TEXT, status TEXT, amount REAL, commission_amount REAL, item_count INTEGER, created_at TEXT);
    CREATE TABLE products (stock INTEGER, status TEXT);
    CREATE TABLE customer_profiles (id INTEGER PRIMARY KEY, sales_person TEXT, status TEXT, channel TEXT);
    CREATE TABLE referrals (id INTEGER, code TEXT, owner_name TEXT, visitor_phone TEXT, order_no TEXT, amount REAL, commission REAL, status TEXT, created_at TEXT);
    CREATE TABLE sales_people (id INTEGER, name TEXT, phone TEXT, role TEXT, promo_code TEXT, store_code TEXT, customer_service TEXT, status TEXT);
    INSERT INTO sales_people VALUES (1,'销售甲','','','','','','active');
    INSERT INTO customer_profiles VALUES (1,'销售甲','active','retail'),(2,'销售甲','active','wholesale');
    INSERT INTO orders VALUES
      (1,'LS1','13900000000','retail','销售甲','已支付','已发货',100,3,1,'2026-11-21'),
      (2,'LS2','13900000000','retail','销售甲','待确认付款','待发货',900,27,1,'2026-11-21'),
      (3,'LS3','13900000000','retail','销售甲','已支付','已取消',200,6,1,'2026-11-21'),
      (4,'LS4','13900000000','retail','销售甲','已退款','已退款',300,9,1,'2026-11-21');
    INSERT INTO referrals VALUES
      (1,'A','','','LS1',100,3,'待结算','2026-11-21'),
      (2,'A','','','LS2',900,27,'待结算','2026-11-21'),
      (3,'A','','','LS3',200,6,'待结算','2026-11-21');`);
  const db = { prepare(query) { const args = []; const p = {
    bind(...values) { args.push(...values); return p; },
    async first() { return sql.prepare(query).get(...args) ?? null; },
    async all() { return { results: sql.prepare(query).all(...args) }; },
  }; return p; } };
  const context = vm.createContext({ Response, Number, String, Boolean, Array, Set });
  const stub = (values) => new vm.SyntheticModule(Object.keys(values), function () {
    for (const [key, value] of Object.entries(values)) this.setExport(key, value);
  }, { context });
  const checks = new vm.SourceTextModule(stripTypeScriptTypes(readFileSync(new URL('../app/lib/operating-checks.ts', import.meta.url), 'utf8')), { context });
  await checks.link(() => stub({ sellable: options.sellable })); await checks.evaluate();
  async function route(path) {
    const mod = new vm.SourceTextModule(stripTypeScriptTypes(readFileSync(new URL(path, import.meta.url), 'utf8')), { context });
    await mod.link((name) => {
      if (name.endsWith('db/runtime')) return stub({ getD1: () => db, ensureDatabase: async () => {} });
      if (name.endsWith('admin-auth')) return stub({ requireAdminApi: async () => denied ? new Response('', { status: 401 }) : null });
      if (name.endsWith('operating-checks')) return checks;
      throw new Error(name);
    });
    await mod.evaluate(); return mod.namespace;
  }
  return { sql, lib: checks.namespace, route };
}

test('finance and daily revenue exclude unpaid, cancelled and refunded orders', async () => {
  const s = await setup();
  const response = await (await s.route('../app/api/dashboard/route.ts')).GET();
  const body = await response.json();
  assert.equal(body.summary.orders.revenue, 100);
  assert.equal(body.summary.orders.paidCount, 1);
  assert.equal(body.summary.orders.pendingAmount, 900);
  assert.equal(body.summary.orders.commission, 3);
  assert.equal(body.summary.referrals.commission, 3);
  assert.equal(body.daily[0].revenue, 100);
});

test('sales revenue is not multiplied when a salesperson has multiple customers', async () => {
  const s = await setup();
  const body = await (await (await s.route('../app/api/sales-team/route.ts')).GET()).json();
  assert.equal(body.sales[0].customerCount, 2);
  assert.equal(body.sales[0].orderAmount, 100);
  assert.equal(body.sales[0].commission, 3);
});

test('finance totals include all paid orders beyond the 200-row detail limit', async () => {
  const s = await setup();
  const insert = s.sql.prepare("INSERT INTO orders(order_no,payment_status,status,amount,commission_amount,item_count,created_at) VALUES(?,'已支付','待发货',10,0.3,1,'2026-11-21')");
  for (let i = 0; i < 250; i++) insert.run(`extra-${i}`);
  const body = await (await (await s.route('../app/api/dashboard/route.ts')).GET()).json();
  assert.equal(body.summary.orders.revenue, 2600);
  assert.equal(body.summary.orders.paidCount, 251);
});

test('finance and sales endpoints still deny unauthenticated requests', async () => {
  const s = await setup(true);
  for (const path of ['../app/api/dashboard/route.ts', '../app/api/sales-team/route.ts']) {
    assert.equal((await (await s.route(path)).GET()).status, 401);
  }
});

test('product review identifies missing prices and stock without making up replacements', async () => {
  const { lib } = await setup();
  const product = { variants: options.initialVariants('45厘米'), stock: 0, images: [], status: 'active' };
  assert.equal(lib.productChecks(product).join('；'), '3个规格待定价；暂无库存；缺少产品图片');
  assert.equal(product.variants[0].price, null);
  assert.equal(lib.productChecks({ ...product, variants: options.initialVariants('20厘米'), stock: 1, images: ['/image.jpg'] }).length, 0);
});

test('product edits reject negative or fractional stock and invalid visibility levels', async () => {
  const { lib } = await setup();
  for (const stock of [-1, 1.5, NaN, Infinity]) assert.throws(() => lib.validateProductAvailability(stock, 'active', 'retail'));
  assert.throws(() => lib.validateProductAvailability(1, 'active', 'invalid'));
  assert.throws(() => lib.validateProductAvailability(1, 'invalid', 'b'));
  assert.doesNotThrow(() => lib.validateProductAvailability(0, 'draft', 'b'));
});
