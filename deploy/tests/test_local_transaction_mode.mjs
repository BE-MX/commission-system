import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {assertLegacyTransactions, createOne, requestOkki} from '../okki_outbound_creator.mjs';
import {claimBatch} from '../okki_outbound_poller.js';

test('local mode rejects direct calls before database, filesystem or network access', async () => {
  const original = process.env.TRANSACTION_MODE;
  process.env.TRANSACTION_MODE = 'local';
  try {
    const forbidden = () => { assert.fail('external dependency accessed'); };
    await assert.rejects(claimBatch({query: forbidden}), /disabled/);
    await assert.rejects(createOne('123', {api: forbidden}), /disabled/);
    await assert.rejects(requestOkki({getAccessToken: forbidden}, '', '', null, forbidden), /disabled/);
    assert.throws(() => assertLegacyTransactions('unknown'), /disabled/);
    assert.throws(() => assertLegacyTransactions(''), /disabled/);
  } finally {
    if (original === undefined) delete process.env.TRANSACTION_MODE;
    else process.env.TRANSACTION_MODE = original;
  }
});

test('standalone local mode scripts reject before loading private auth or mysql', () => {
  for (const filename of ['okki_outbound_creator.mjs', 'okki_outbound_poller.js']) {
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('../' + filename, import.meta.url)), '123', '--run'],
      {env: {...process.env, TRANSACTION_MODE: 'local'}, encoding: 'utf8'});
    assert.equal(result.status, 1);
    assert.match(result.stderr, /External outbound writes disabled/);
    assert.doesNotMatch(result.stderr, /ERR_MODULE_NOT_FOUND/);
  }
});

test('protected local file blocks manual scripts even with inherited legacy mode', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ark-local-fence-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  fs.writeFileSync(path.join(directory, '.ark-outbound.env'), 'TRANSACTION_MODE = local\n');
  for (const filename of ['okki_outbound_creator.mjs', 'okki_outbound_poller.js']) {
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('../' + filename, import.meta.url)), '123', '--run'],
      {env: {...process.env, TRANSACTION_MODE: 'legacy', OUTBOUND_SCRIPT_DIR: directory}, encoding: 'utf8'});
    assert.equal(result.status, 1);
    assert.match(result.stderr, /External outbound writes disabled by/);
    assert.doesNotMatch(result.stderr, /ERR_MODULE_NOT_FOUND/);
  }
});
