import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const sourcePath = new URL('./sync-outbound.js', import.meta.url);
const itemFields = ['outbound_record_id', 'outbound_invoice_id', 'sku_id', 'product_id', 'sku_code', 'product_no', 'product_name', 'product_cn_name', 'product_model', 'product_unit', 'outbound_count', 'sale_count', 'sale_price', 'product_amount', 'cost_unit_price_rmb', 'moment_enable_count', 'order_id', 'order_no', 'order_record_id', 'product_type', 'product_disable_flag'];

// Execute the actual persistence entry, injecting only network/pool dependencies.
async function saver(db) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const section = source.slice(source.indexOf('async function saveOutbound('), source.indexOf('// 主流程'));
  const helpers = source.slice(source.indexOf('function parseTs('), source.indexOf('// API 层'));
  const storePath = new URL('./outbound-store.mjs', import.meta.url);
  const store = fs.existsSync(storePath) ? (await import(storePath.href)).saveOutboundSnapshot : undefined;
  const save = new Function('pool', 'withDbRetry', 'saveOutboundSnapshot', helpers + section + ';return saveOutbound;')(
    { getConnection: async () => db }, fn => fn(), store,
  );
  return (invoice, detail) => save(invoice, detail && { outbound_invoice_id: invoice.outbound_invoice_id, update_time: invoice.update_time, ...detail });
}

class MemoryConnection {
  rows = [];
  header = null;
  nextId = 100;
  snapshot = null;
  released = 0;
  failAt = null;
  writes = 0;
  inspection = null;
  event = null;
  photos = [];
  audits = [];
  async beginTransaction() { this.snapshot = structuredClone({ rows: this.rows, header: this.header, inspection: this.inspection, event: this.event, audits: this.audits, photos: this.photos }); }
  async commit() { this.snapshot = null; }
  async rollback() { if (this.snapshot) Object.assign(this, this.snapshot); this.snapshot = null; }
  release() { this.released++; }
  async query(sql, params = []) {
    const q = sql.replace(/\s+/g, ' ').trim();
    if (q.startsWith('SET time_zone')) return [[]];
    if (q.startsWith('SELECT') && q.includes('.ark_shipping_operation_events')) return [this.event ? [structuredClone(this.event)] : []];
    if (q.startsWith('SELECT') && q.includes('.ark_shipping_inspections')) return [this.inspection ? [structuredClone(this.inspection)] : []];
    if (q.startsWith('SELECT') && q.includes('.ark_shipping_inspection_photos')) return [structuredClone(this.photos)];
    if (/^SELECT .*FROM okki_outbound_records/.test(q)) return [this.header ? [structuredClone(this.header)] : []];
    if (/^SELECT .*FROM okki_outbound_record_items/.test(q)) return [structuredClone(this.rows.filter(row => String(row.outbound_invoice_id) === String(params[0])))];
    this.writes++;
    if (this.failAt === this.writes) throw new Error('Injected database failure');
    if (q.startsWith('UPDATE') && q.includes('.ark_shipping_inspections')) {
      assert.ok(q.indexOf('recalled_at=') < q.indexOf("status='draft'"), 'Recall audit must evaluate the original submitted status');
      if (this.inspection.status === 'submitted') { this.inspection.recalled_at = 'BEIJING_NOW'; this.inspection.recalled_by = 0; }
      this.inspection.status = 'draft'; this.inspection.edit_version++; return [{ affectedRows: 1 }];
    }
    if (q.startsWith('UPDATE') && q.includes('.ark_shipping_inspection_photos')) { const row = this.photos.find(photo => photo.id === params[1]); assert.ok(row); row.item_id = params[0]; return [{ affectedRows: 1 }]; }
    if (q.startsWith('UPDATE') && q.includes('.ark_shipping_operation_events')) { this.event.action = 'sync_done'; this.event.result = JSON.parse(params[0]); return [{ affectedRows: 1 }]; }
    if (q.startsWith('INSERT') && q.includes('.ark_shipping_operation_events')) { this.audits.push(params); return [{ affectedRows: 1 }]; }
    if (q.startsWith('INSERT INTO okki_outbound_records')) { this.header = { id: 42, outbound_invoice_id: params[0], update_time: params[22], serial_id: params[1], remark: params[8] }; return [{ affectedRows: 1 }]; }
    if (q.startsWith('DELETE FROM okki_outbound_record_items')) {
      const ids = params[1];
      const count = this.rows.length;
      this.rows = this.rows.filter(row => String(row.outbound_invoice_id) !== String(params[0]) || (ids && !ids.map(String).includes(String(row.id))));
      return [{ affectedRows: count - this.rows.length }];
    }
    if (q.startsWith('INSERT INTO okki_outbound_record_items')) {
      const row = Object.fromEntries(itemFields.map((field, i) => [field, params[i]]));
      row.id = this.nextId++; this.rows.push(row); return [{ insertId: row.id, affectedRows: 1 }];
    }
    if (q.startsWith('UPDATE okki_outbound_record_items')) {
      const id = params.at(-2), invoice = params.at(-1);
      const row = this.rows.find(row => String(row.id) === String(id) && String(row.outbound_invoice_id) === String(invoice));
      assert.ok(row, 'UPDATE must target existing local ID in the same outbound');
      itemFields.forEach((field, i) => { row[field] = params[i]; });
      return [{ affectedRows: 1 }];
    }
    throw new Error('Unexpected SQL: ' + q);
  }
}

const inv = { outbound_invoice_id: '500', serial_id: 'TEST', update_time: '2026-10-08 10:00:00' };
const item = (id, extra = {}) => ({ outbound_record_id: id, product_id: '700', sku_id: '800', sku_code: 'S1', order_record_id: '900', outbound_count: 2, ...extra });
async function seeded() { const db = new MemoryConnection(); const save = await saver(db); await save(inv, { record_list: [item('600'), item('601')] }); return { db, save }; }

test('same remote detail preserves local ID and photo link across repeated sync and reorder', async () => {
  const { db, save } = await seeded(); const ids = db.rows.map(row => row.id);
  const photo = { item_id: String(ids[0]) };
  await save(inv, { record_list: [item('601'), item('600', { outbound_count: 5 })] });
  await save(inv, { record_list: [item('600', { outbound_count: 5 }), item('601')] });
  assert.equal(String(db.rows.find(row => row.outbound_record_id === '600').id), photo.item_id);
  assert.deepEqual(db.rows.map(row => row.id).sort(), ids.sort());
  assert.equal(db.rows.find(row => row.outbound_record_id === '600').outbound_count, 5);
});

test('new and removed details change only their own rows', async () => {
  const { db, save } = await seeded(); const kept = db.rows[1].id, removed = db.rows[0].id;
  await save(inv, { record_list: [item('601'), item('602')] });
  assert.equal(db.rows.find(row => row.outbound_record_id === '601').id, kept);
  assert.ok(!db.rows.some(row => row.id === removed));
  assert.ok(db.rows.find(row => row.outbound_record_id === '602').id > kept);
});

function inspected(db) {
  db.inspection = { id: 5, status: 'submitted', edit_version: 0 };
  db.event = { id: 6, action: 'sync_idle', result: {} };
  db.photos = [{ id: 1, item_id: String(db.rows[0].id) }, { id: 2, item_id: null }];
}

test('changed product preserves photo history but requires fresh inspection', async () => {
  const { db, save } = await seeded(); inspected(db); const photoId = db.rows[0].id;
  await save(inv, { record_list: [item('600', { product_id: 'DIFFERENT' }), item('601')] });
  assert.equal(db.rows.find(row => row.outbound_record_id === '600').id, photoId);
  assert.equal(db.inspection.status, 'draft'); assert.equal(db.inspection.edit_version, 1);
  assert.deepEqual(db.event.result.stale_media_ids, [1, 2]);
  assert.deepEqual(db.event.result.required_recheck_ids, ['__all_items__']);
  assert.equal(db.audits.length, 1);
});

test('failed detail fetch cannot advance header and hide stale details behind skip-unchanged', async () => {
  const { db, save } = await seeded(); const before = structuredClone(db.header);
  await assert.rejects(save({ ...inv, update_time: '2026-10-08 11:00:00' }, null));
  assert.deepEqual(db.header, before);
});

test('failure midway rolls back header and all details before retry', async () => {
  const { db, save } = await seeded(); const before = structuredClone({ rows: db.rows, header: db.header });
  db.failAt = db.writes + 3;
  await assert.rejects(save({ ...inv, update_time: '2026-10-08 11:00:00' }, { record_list: [item('600'), item('602')] }));
  assert.deepEqual({ rows: db.rows, header: db.header }, before);
  assert.equal(db.snapshot, null); assert.equal(db.released, 2);
});

test('duplicate or missing remote identity aborts before touching rows', async () => {
  const { db, save } = await seeded(); const before = structuredClone(db.rows);
  await assert.rejects(save(inv, { record_list: [item('600'), item('600')] }));
  await assert.rejects(save(inv, { record_list: [item(null)] }));
  assert.deepEqual(db.rows, before);
});

test('confirmed empty detail list removes old rows', async () => {
  const { db, save } = await seeded(); await save(inv, { record_list: [] });
  assert.equal(db.rows.length, 0);
});

test('quantity change invalidates submitted evidence without losing photos or their IDs', async () => {
  const { db, save } = await seeded(); inspected(db); const id = db.rows[0].id;
  await save(inv, { record_list: [item('600', { outbound_count: 5 }), item('601')] });
  assert.equal(db.rows[0].id, id); assert.equal(db.photos.length, 2);
  assert.equal(db.inspection.status, 'draft'); assert.equal(db.inspection.edit_version, 1);
  assert.deepEqual(db.event.result.required_recheck_ids, ['__all_items__']);
});

test('unchanged inspected details preserve submitted status and manual audit/grant', async () => {
  const { db, save } = await seeded(); inspected(db);
  db.event = { id: 6, action: 'sync_done', result: { stale_media_ids: [9], required_recheck_ids: ['__whole__'], print_before_recheck: { reason: 'existing' } } };
  const before = structuredClone({ inspection: db.inspection, event: db.event });
  await save(inv, { record_list: [item('601'), item('600')] });
  assert.deepEqual({ inspection: db.inspection, event: db.event }, before);
});

test('active manual outbound reconciliation blocks automatic mirror mutation', async () => {
  const { db, save } = await seeded(); inspected(db); db.event.action = 'sync_sending';
  const before = structuredClone(db.rows);
  await assert.rejects(save(inv, { record_list: [item('600')] }), /reconciliation is active/);
  assert.deepEqual(db.rows, before);
});

test('older concurrent snapshot cannot overwrite the newer mirror', async () => {
  const { db, save } = await seeded();
  await assert.rejects(save({ ...inv, update_time: '2026-10-08 09:00:00' }, { record_list: [item('600')] }), /Older outbound snapshot/);
  assert.equal(db.rows.length, 2);
});

test('recheck audit failure rolls back mirror and inspection together', async () => {
  const { db, save } = await seeded(); inspected(db);
  const before = structuredClone({ rows: db.rows, header: db.header, inspection: db.inspection, event: db.event });
  db.failAt = db.writes + 6;
  await assert.rejects(save(inv, { record_list: [item('600', { outbound_count: 5 }), item('601')] }));
  assert.deepEqual({ rows: db.rows, header: db.header, inspection: db.inspection, event: db.event }, before);
});

test('list/detail version mismatch or wrong invoice cannot advance the header', async () => {
  const { db, save } = await seeded(); const before = structuredClone(db.header);
  await assert.rejects(save(inv, { update_time: '2026-10-08 09:00:00', record_list: [item('600')] }), /versions differ/);
  await assert.rejects(save(inv, { outbound_invoice_id: 'OTHER', record_list: [item('600')] }), /another invoice/);
  assert.deepEqual(db.header, before);
});

test('verified overlay photos converge to local IDs while preserving the business snapshot and recheck grant', async () => {
  const { db, save } = await seeded(); inspected(db);
  db.photos[0].item_id = 'okki:600';
  db.event = { id: 6, action: 'sync_done', result: { verified: { update_time: inv.update_time, serial_id: inv.serial_id, remark: '', items: ['600','601'].map(id => ({ item_id: 'okki:' + id, product_id: '700', sku: 'S1', product_name: '', unit: '', spec: '', qty: 2 })) }, print_before_recheck: { reason: 'existing' } } };
  const eventBefore = structuredClone(db.event), inspectionBefore = structuredClone(db.inspection);
  await save(inv, { record_list: [item('600'), item('601')] });
  assert.equal(db.photos[0].item_id, String(db.rows[0].id));
  assert.deepEqual(db.event, eventBefore); assert.deepEqual(db.inspection, inspectionBefore);
  assert.equal(db.audits.length, 1);
});

test('same snapshot remains in Beijing DATETIME format with a non-Beijing server timezone', async () => {
  const { db } = await seeded();
  assert.equal(db.header.update_time, '2026-10-08 10:00:00');
});

function verifiedEvent(db) {
  db.event = { id: 6, action: 'sync_done', result: { verified: { update_time: inv.update_time, serial_id: inv.serial_id, remark: '', items: ['600','601'].map(id => ({ item_id: 'okki:' + id, product_id: '700', sku: 'S1', product_name: '', unit: '', spec: '', qty: 2 })) } } };
}

test('historical stale overlay photo for a removed row does not block verified mirror convergence', async () => {
  const { db, save } = await seeded(); inspected(db); verifiedEvent(db);
  db.photos[0].item_id = 'okki:REMOVED'; db.event.result.stale_media_ids = [1];
  await save(inv, { record_list: [item('600'), item('601')] });
  assert.equal(db.photos[0].item_id, 'okki:REMOVED'); assert.equal(db.rows.length, 2);
});

test('photo link update rolls back if its audit insert fails', async () => {
  const { db, save } = await seeded(); inspected(db); verifiedEvent(db); db.photos[0].item_id = 'okki:600';
  const before = structuredClone({ photos: db.photos, event: db.event, inspection: db.inspection, rows: db.rows, header: db.header, audits: db.audits }); db.failAt = db.writes + 5;
  await assert.rejects(save(inv, { record_list: [item('600'), item('601')] }));
  assert.deepEqual({ photos: db.photos, event: db.event, inspection: db.inspection, rows: db.rows, header: db.header, audits: db.audits }, before); assert.equal(db.audits.length, 0);
});

test('same-second external material change retires old overlay and retains it in audit', async () => {
  const { db, save } = await seeded(); inspected(db); verifiedEvent(db);
  const verified = structuredClone(db.event.result.verified);
  await save(inv, { record_list: [item('600', { outbound_count: 5 }), item('601')] });
  assert.equal(db.event.result.verified, undefined);
  assert.deepEqual(JSON.parse(db.audits[0][3]).previous_verified, verified);
});


test('Beijing midnight remains on the same business date across server timezones', async () => {
  const db = new MemoryConnection(), save = await saver(db);
  await save({ ...inv, update_time: '2026-10-08 00:00:00' }, { record_list: [item('600')] });
  assert.equal(db.header.update_time, '2026-10-08 00:00:00');
});


test('product metadata differences preserve the remote verified identity while photos converge', async () => {
  const { db, save } = await seeded(); inspected(db); verifiedEvent(db);
  db.photos[0].item_id = 'okki:600';
  db.event.result.verified.items[0].size = '22';
  db.event.result.verified.items[0].color = '#2';
  db.event.result.print_before_recheck = { reason: 'already approved' };
  await save(inv, { record_list: [item('600'), item('601')] });
  assert.equal(db.event.result.verified.items[0].item_id, 'okki:600');
  assert.equal(db.photos[0].item_id, String(db.rows[0].id));
  assert.equal(db.event.result.verified.items[0].size, '22');
  assert.equal(db.event.result.verified.items[0].color, '#2');
  assert.deepEqual(db.event.result.print_before_recheck, { reason: 'already approved' });
  assert.equal(db.inspection.status, 'submitted');
  await save(inv, { record_list: [item('600'), item('601')] });
  assert.equal(db.event.result.verified.items[0].item_id, 'okki:600');
  assert.equal(db.photos[0].item_id, String(db.rows[0].id));
});


test('same-second replacement of remote identity requires fresh evidence even with identical product fields', async () => {
  const { db, save } = await seeded(); inspected(db); verifiedEvent(db);
  await save(inv, { record_list: [item('999'), item('601')] });
  assert.equal(db.inspection.status, 'draft');
  assert.equal(db.inspection.edit_version, 1);
  assert.deepEqual(db.event.result.stale_media_ids, [1, 2]);
  assert.equal(db.event.result.verified, undefined);
  assert.equal(db.audits.length, 1);
});
