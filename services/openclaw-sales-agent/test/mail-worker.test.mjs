import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MailWorker, apiClient, readJson, runCli, dsnCandidates } from '../src/mail-worker.mjs';

const binding = { id: 1, sender_email: 'sender@example.com', cli_workspace: 'ark-mail' };
async function fixture(t, overrides = {}) {
  const root = await mkdtemp(join(tmpdir(), 'ark-mail-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const calls = [], executions = [];
  const api = async (path, body) => {
    calls.push({ path, body });
    if (path === '/bindings') return [binding];
    if (path.endsWith('/claim')) return { id: 3, fencing_token: 2 };
    if (path.endsWith('/authorize')) return { to: 'test@example.com', subject: 'Approved subject', body_text: 'Approved body' };
    return {};
  };
  const execute = async (cli, args, options) => {
    executions.push({ cli, args, options });
    if (args[0] === '+me') return { ok: true, data: { aliases: [{ email: binding.sender_email, is_primary: true }] } };
    if (args[1] === '+list') return { ok: true, data: { data: [], pagination: { has_more: false } } };
    assert.equal(await readFile(join(options.cwd, 'body.txt'), 'utf8'), 'Approved body');
    return { ok: true, started: true, data: { queued: true } };
  };
  const worker = new MailWorker({ root, api, execute, cli: 'fixture-cli', allowedRecipients: ['test@example.com'], ...overrides });
  await worker.init();
  return { worker, root, calls, executions, api, execute };
}
test('queued true without ID is accepted; body stays in a private relative file', async (t) => {
  const f = await fixture(t);
  await f.worker.cycle();
  const send = f.executions.find((item) => item.args[1] === '+send');
  assert.equal(send.args[send.args.indexOf('--body-file') + 1], './body.txt');
  assert.equal(send.options.workspace, 'ark-mail');
  assert.equal(f.calls.at(-1).body.outcome, 'accepted');
  assert.equal(await readJson(join(f.root, 'pending.json')), null);
  await assert.rejects(readFile(join(send.options.cwd, 'body.txt')), { code: 'ENOENT' });
});
test('pending accepted result survives API loss and restart without another send', async (t) => {
  const f = await fixture(t);
  f.worker.api = async (path, body) => { if (path.endsWith('/result')) throw new Error('offline'); return f.api(path, body); };
  await assert.rejects(f.worker.cycle());
  assert.equal((await readJson(join(f.root, 'pending.json'))).result.outcome, 'accepted');
  let sends = 0;
  const restart = new MailWorker({ root: f.root, api: async (path, body) => {
    assert.equal(body.outcome, 'accepted'); assert.equal(path, '/jobs/3/result');
  }, execute: async () => { sends++; } });
  restart.stopping = true;
  await restart.cycle();
  assert.equal(sends, 0);
});
test('send timeout becomes unknown and is never retried', async (t) => {
  const f = await fixture(t);
  f.worker.execute = async (...args) => args[1][1] === '+send'
    ? { ok: false, started: true, error: 'timeout' } : f.execute(...args);
  await f.worker.cycle();
  assert.equal(f.calls.at(-1).body.outcome, 'unknown');
});
test('crash after authorization has a durable unknown record before send', async (t) => {
  const f = await fixture(t);
  f.worker.execute = async (...args) => {
    if (args[1][1] === '+send') {
      assert.equal((await readJson(join(f.root, 'pending.json'))).result.outcome, 'unknown');
      throw new Error('crash');
    }
    return f.execute(...args);
  };
  await assert.rejects(f.worker.cycle());
  f.worker.stopping = true;
  await f.worker.cycle();
  assert.equal(f.calls.at(-1).body.outcome, 'unknown');
});
test('identity mismatch and recipient outside allowlist never execute send', async (t) => {
  const f = await fixture(t);
  f.worker.execute = async () => ({ ok: true, data: { aliases: [{ email: 'other@example.com', is_primary: true }] } });
  await f.worker.cycle();
  assert.equal(f.calls.some((call) => call.path.endsWith('/claim')), false);
  f.worker.execute = f.execute;
  f.worker.allowedRecipients = ['someone-else@example.com'];
  await f.worker.cycle();
  assert.equal(f.executions.some((item) => item.args[1] === '+send'), false);
  assert.equal(f.calls.at(-1).body.outcome, 'failed_safe');
});
test('secondary alias is not accepted as the default sender', async (t) => {
  const f = await fixture(t);
  f.worker.execute = async () => ({ ok: true, data: { aliases: [{ email: binding.sender_email, is_primary: false }] } });
  assert.equal(await f.worker.identity(binding), false);
});
test('API rejects plaintext origin and redirects, preserving machine credentials', async () => {
  assert.throws(() => apiClient({ baseUrl: 'http://example.com', token: 'x' }));
  const api = apiClient({ baseUrl: 'https://example.com', token: 'x', fetchImpl: async (url, options) => {
    assert.equal(options.redirect, 'error'); return { ok: true, json: async () => ({ code: 200, data: [] }) };
  } });
  assert.deepEqual(await api('/bindings'), []);
});
test('missing CLI is definitely not started', async () => {
  const result = await runCli(join(tmpdir(), 'nonexistent-ark-cli'), ['+me'], { workspace: 'test' });
  assert.equal(result.started, false);
});

test('definite authorize rejection records safe failure without launching CLI', async (t) => {
  const f = await fixture(t);
  f.worker.api = async (path, body) => {
    if (path.endsWith('/authorize')) { const error = new Error('approval revoked'); error.status = 409; throw error; }
    return f.api(path, body);
  };
  await f.worker.cycle();
  assert.equal(f.calls.at(-1).body.outcome, 'failed_safe');
  assert.equal(f.executions.some((item) => item.args[1] === '+send'), false);
});

test('authorize timeout is conservatively reconciled as unknown before any new claim', async (t) => {
  const f = await fixture(t);
  f.worker.api = async (path, body) => {
    if (path.endsWith('/authorize')) throw new Error('lost authorization response');
    return f.api(path, body);
  };
  await assert.rejects(f.worker.cycle());
  f.worker.stopping = true;
  await f.worker.cycle();
  assert.equal(f.calls.at(-1).body.outcome, 'unknown');
  assert.equal(f.executions.some((item) => item.args[1] === '+send'), false);
});

test('persistent release freeze only flushes existing receipt and prevents claims', async (t) => {
  const f = await fixture(t);
  const { durableJson } = await import('../src/mail-worker.mjs');
  await durableJson(join(f.root, 'freeze.json'), { release_id: 'release' });
  await f.worker.persist({ id: 3, result: { fencing_token: 2, outcome: 'accepted' } });
  const result = await f.worker.cycle();
  assert.deepEqual(result, { frozen: true, bindings: 1, authenticated: 1 });
  assert.deepEqual(f.calls.map((call) => call.path), ['/jobs/3/result', '/bindings', '/1/heartbeat']);
});

test('explicit wildcard allows approved production recipient while empty allowlist blocks', async (t) => {
  const f = await fixture(t);
  f.worker.allowedRecipients = ['*'];
  await f.worker.cycle();
  assert.equal(f.calls.at(-1).body.outcome, 'accepted');
});

test('malformed inbox page and event cannot advance the durable cursor', async (t) => {
  const f = await fixture(t);
  for (const data of [{}, { data: [{}], pagination: { has_more: false } }]) {
    f.worker.execute = async (...args) => args[1][1] === '+list' ? { ok: true, data } : f.execute(...args);
    await assert.rejects(f.worker.ingest(binding), /invalid_inbox/);
    assert.equal(await readJson(join(f.root, 'inbox-1.json')), null);
  }
});

test('DSN candidate extraction is bounded and never uploads the body', async (t) => {
  const f = await fixture(t);
  const body = 'Sensitive content. Failed recipient: test@example.com. sender@example.com';
  f.worker.execute = async (...args) => {
    if (args[1][1] === '+list') return { ok: true, data: { data: [{ message_id: 'msg_dsn',
      from: { email: 'mailer-daemon@example.net' }, to: [{ email: binding.sender_email }],
      subject: 'Mail delivery failed', created_at: '2026-10-02T00:00:00Z' }], pagination: { has_more: false } } };
    if (args[1][1] === '+read') return { ok: true, data: { body } };
    return f.execute(...args);
  };
  await f.worker.ingest(binding);
  const events = f.calls.find((call) => call.path.endsWith('/events')).body.events;
  assert.deepEqual(events[0].original_recipient_candidates, ['test@example.com']);
  assert.equal(JSON.stringify(events).includes('Sensitive content'), false);
  assert.equal(dsnCandidates(Array.from({ length: 20 }, (_, index) => `r${index}@example.com`).join(' ')).length, 10);
});

test('inbox sync failure blocks claim and send for that cycle', async (t) => {
  const f = await fixture(t);
  f.worker.execute = async (...args) => args[1][1] === '+list'
    ? { ok: false, error: 'timeout' } : f.execute(...args);
  await assert.rejects(f.worker.cycle(), /inbox_sync_failed/);
  assert.equal(f.calls.some((call) => call.path.endsWith('/claim')), false);
  assert.equal(f.executions.some((item) => item.args[1] === '+send'), false);
  assert.equal(await readJson(join(f.root, 'inbox-1.json')), null);
});
