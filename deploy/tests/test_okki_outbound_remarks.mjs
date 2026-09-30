import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {buildPayload, createOne} from '../okki_outbound_creator.mjs';

const order = {order_id: 123, create_time: '2026-09-30 08:44:32', handler: [9], company_id: 2,
  currency: 'USD', product_list: [{product_id: 4, sku_id: 5, unique_id: 6, count: 10, unit_price: 29.55}]};

function fixture(t, invoiceRemark, remoteRemark, {recover = false, rowChange = {}} = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ark-outbound-remarks-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const payload = buildPayload(order, 'INV123', invoiceRemark);
  const intent = path.join(directory, 'logs', 'ark-outbound-intents', '123.json');
  const saved = JSON.stringify({order_id: '123', payload});
  if (recover) {
    fs.mkdirSync(path.dirname(intent), {recursive: true});
    fs.writeFileSync(intent, saved);
  }
  let posts = 0;
  const api = async (route, body) => {
    if (body) {
      posts++;
      assert.equal(body.remark, invoiceRemark ?? '');
      return {outbound_invoice_id: 88, serial_id: 'INV123'};
    }
    if (route.includes('/order/info')) return order;
    if (route.includes('/outbound/list')) return {count: recover ? 1 : 0,
      list: recover ? [{outbound_invoice_id: 88, serial_id: 'INV123'}] : []};
    if (route.includes('serial_id=')) return null;
    return {outbound_invoice_id: 88, serial_id: 'INV123', status: 1, company_info: {id: 2},
      remark: remoteRemark, record_list: payload.record_list.map(row => ({...row, ...rowChange}))};
  };
  return {options: {directory, invoiceNo: 'INV123', invoiceRemark, api}, intent, saved,
    posts: () => posts, ledger: path.join(directory, 'logs', 'created-outbound.jsonl')};
}

for (const recover of [false, true]) {
  const phase = recover ? 'recovery' : 'creation';
  for (const [label, original, remote] of [
    ['trailing space from invoice 836', '公司黑色logo 5条一包 ', '公司黑色logo 5条一包'],
    ['edge whitespace with internal formatting intact', ' \t第一行  标签\n第二行\r\n', '第一行  标签\n第二行'],
    ['blank remark normalized to null', ' \t\n', null],
  ]) {
    test(`${phase} accepts ${label} without changing submitted text`, async t => {
      const f = fixture(t, original, remote, {recover});
      // Recovery must use the persisted intent, not a later invoice edit.
      const options = recover ? {...f.options, invoiceRemark: 'later edited invoice'} : f.options;
      const result = await createOne('123', options);
      assert.equal(result.outcome, recover ? 'existing' : 'created');
      assert.equal(f.posts(), recover ? 0 : 1);
      if (recover) assert.equal(fs.readFileSync(f.intent, 'utf8'), f.saved);
      else assert.match(fs.readFileSync(f.ledger, 'utf8'), /"outbound_invoice_id":88/);
    });
  }
  for (const [label, original, remote] of [
    ['missing text', '公司黑色logo 5条一包 ', ''],
    ['changed packaging quantity', '公司黑色logo 5条一包 ', '公司黑色logo 6条一包'],
    ['collapsed internal spaces', '第一行  标签\n第二行 ', '第一行 标签\n第二行'],
    ['removed internal line break', '第一行\n第二行 ', '第一行第二行'],
    ['invalid remote type', '123 ', 123],
  ]) {
    test(`${phase} quarantines ${label} and never repeats a POST`, async t => {
      const f = fixture(t, original, remote, {recover});
      await assert.rejects(createOne('123', f.options), e => e.uncertain === true && /remark differs/.test(e.message));
      await assert.rejects(createOne('123', f.options), e => e.uncertain === true);
      assert.equal(f.posts(), recover ? 0 : 1);
      assert.equal(fs.existsSync(f.ledger), false);
      if (recover) assert.equal(fs.readFileSync(f.intent, 'utf8'), f.saved);
    });
  }
  for (const rowChange of [{outbound_count: 9}, {sale_price: 28}, {sku_id: 99}]) {
    test(`${phase} still rejects changed item ${JSON.stringify(rowChange)} with trimmed remark`, async t => {
      const f = fixture(t, '公司黑色logo 5条一包 ', '公司黑色logo 5条一包', {recover, rowChange});
      await assert.rejects(createOne('123', f.options), e => e.uncertain === true && /items differ/.test(e.message));
      assert.equal(f.posts(), recover ? 0 : 1);
      assert.equal(fs.existsSync(f.ledger), false);
    });
  }
}
