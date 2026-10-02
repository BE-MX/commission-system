import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, open, readFile, rename, unlink, mkdtemp, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

// UTC here is a machine protocol timestamp, never a business display date.
export async function durableJson(path, value) {
  const temp = `${path}.${randomUUID()}.tmp`;
  const file = await open(temp, 'wx', 0o600);
  try { await file.writeFile(JSON.stringify(value)); await file.sync(); } finally { await file.close(); }
  await rename(temp, path);
  if (process.platform !== 'win32') {
    const directory = await open(resolve(path, '..'), 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  }
}

export async function readJson(path, fallback = null) {
  try { return JSON.parse(await readFile(path, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return fallback; throw error; }
}

export function dsnCandidates(body, excluded = []) {
  const text = typeof body === 'string' ? body : typeof body?.text === 'string' ? body.text : '';
  const matches = text.slice(0, 1_000_000).match(/[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}/g) || [];
  return [...new Set(matches.map((value) => value.toLowerCase()))].filter((value) => !excluded.includes(value)).slice(0, 10);
}

export function runCli(executable, args, options = {}) {
  return new Promise((done) => {
    let stdout = '', spawned = false, timedOut = false, finished = false;
    const child = spawn(executable, args, { shell: false, windowsHide: true, cwd: options.cwd,
      env: { ...process.env, AGENTLY_WORKSPACE: options.workspace }, stdio: ['ignore', 'pipe', 'pipe'] });
    const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL'); }, options.timeoutMs || 120_000);
    const finish = (result) => { if (!finished) { finished = true; clearTimeout(timer); done(result); } };
    child.on('spawn', () => { spawned = true; });
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
      if (stdout.length > 2_000_000) { timedOut = true; child.kill('SIGKILL'); }
    });
    // Provider diagnostics may contain addresses/content; never log them.
    child.stderr.on('data', () => {});
    child.on('error', (error) => finish({ started: spawned, error: error.code, ok: false }));
    child.on('close', (code) => {
      let json; try { json = JSON.parse(stdout); } catch { /* handled as an unknown result */ }
      finish({ started: spawned, ok: !timedOut && code === 0 && json?.ok === true,
        data: json?.data, error: timedOut ? 'timeout' : `exit_${code}` });
    });
  });
}

export function apiClient({ baseUrl, token, fetchImpl = fetch }) {
  const base = new URL(baseUrl);
  if (base.protocol !== 'https:' || base.username || base.password || base.pathname !== '/' || base.search || base.hash) {
    throw new Error('Worker requires an HTTPS origin');
  }
  return async (path, body) => {
    const response = await fetchImpl(`${base.origin}/api/mail-outreach/worker${path}`, {
      method: body === undefined ? 'GET' : 'POST', redirect: 'error',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok) {
      const error = new Error(`worker_api_${response.status}`);
      error.status = response.status;
      throw error;
    }
    const envelope = await response.json();
    if (envelope.code !== 0 && envelope.code !== 200) throw new Error('worker_api_envelope');
    return envelope.data;
  };
}

export class MailWorker {
  constructor({ root, api, cli, execute = runCli, allowedRecipients = [] }) {
    Object.assign(this, { root, api, cli, execute, allowedRecipients });
    this.stopping = false;
    this.lastCliAt = 0;
  }
  async init() { await mkdir(this.root, { recursive: true, mode: 0o700 }); }
  async persist(record) { await durableJson(join(this.root, 'pending.json'), record); }
  async flush() {
    const pending = await readJson(join(this.root, 'pending.json'));
    if (!pending) return;
    await this.api(`/jobs/${pending.id}/result`, pending.result);
    // Null is durable too: a crash cannot resurrect a successfully acknowledged send.
    await this.persist(null);
  }
  async cliRead(args, binding) {
    let result;
    for (let attempt = 0; attempt < 2; attempt++) {
      await this.paceCli();
      result = await this.execute(this.cli, args, { workspace: binding.cli_workspace, timeoutMs: 30_000 });
      if (result.ok) return result;
    }
    return result;
  }
  async paceCli() {
    // Provider's 10 requests/minute quota applies to reads too. Tests inject a
    // fake CLI; real subprocesses are spaced and never burst on retries.
    if (this.execute === runCli) {
      await delay(Math.max(0, 6_700 - (Date.now() - this.lastCliAt)));
      this.lastCliAt = Date.now();
    }
  }
  async identity(binding) {
    const me = await this.cliRead(['+me'], binding);
    // +send uses primary identity; matching a secondary alias is insufficient.
    const valid = me.ok && me.data?.aliases?.some((alias) => alias.is_primary === true
      && alias.email?.toLowerCase() === binding.sender_email?.toLowerCase());
    await this.api(`/${binding.id}/heartbeat`, { sender_email: binding.sender_email,
      auth_status: valid ? 'active' : me.ok ? 'unbound' : me.error === 'exit_3' ? 'expired' : 'unknown' });
    return valid;
  }
  async ingest(binding) {
    // One bounded page per cycle. Replayed pages are deduplicated by the backend.
    const path = join(this.root, `inbox-${binding.id}.json`);
    const state = await readJson(path, {});
    const args = ['message', '+list', '--dir', 'inbox', '--limit', '50'];
    if (state.cursor) args.push('--cursor', state.cursor);
    if (state.after) args.push('--after', state.after);
    const scanStarted = state.scanStarted || new Date().toISOString();
    const result = await this.cliRead(args, binding);
    if (!result.ok) throw new Error('inbox_sync_failed');
    const page = result.data?.pagination;
    if (!Array.isArray(result.data?.data) || typeof page?.has_more !== 'boolean'
        || (page.has_more && (typeof page.next_cursor !== 'string' || !page.next_cursor || page.next_cursor === state.cursor))) {
      throw new Error('invalid_inbox_page');
    }
    const events = [];
    for (const message of result.data.data) {
      if (typeof message.message_id !== 'string' || !message.message_id || typeof message.from?.email !== 'string'
          || !Array.isArray(message.to) || !message.to.every((entry) => typeof entry.email === 'string')
          || typeof message.created_at !== 'string' || !Number.isFinite(Date.parse(message.created_at))) {
        throw new Error('invalid_inbox_event');
      }
      const recipient = message.to.find((item) => item.email.toLowerCase() === binding.sender_email.toLowerCase());
      if (!recipient) continue; // Explicitly unrelated alias/recipient; no event belongs to this binding.
      events.push({ provider_message_id: message.message_id, from_address: message.from.email,
        to_address: recipient.email, subject: String(message.subject || '').slice(0, 500), received_at_utc: message.created_at });
    }
    for (const event of events) {
      if (this.stopping) throw new Error('inbox_scan_draining');
      const local = event.from_address.toLowerCase().split('@')[0];
      if (['mailer-daemon', 'postmaster'].includes(local)
          && /delivery.{0,30}(fail|status)|undeliver|returned mail|failure notice|退信|投递失败/i.test(event.subject)) {
        const detail = await this.cliRead(['message', '+read', '--id', event.provider_message_id], binding);
        if (!detail.ok) throw new Error('dsn_read_failed');
        if (detail.ok) {
          const candidates = dsnCandidates(detail.data?.body, [binding.sender_email.toLowerCase(), event.from_address.toLowerCase()]);
          if (candidates.length) event.original_recipient_candidates = candidates;
        }
      }
    }
    if (events.length) await this.api(`/${binding.id}/events`, { events });
    await durableJson(path, page?.has_more
      ? { ...state, scanStarted, cursor: page.next_cursor }
      : { after: new Date(Date.parse(scanStarted) - 300_000).toISOString() });
  }
  async send(binding, job) {
    if (!Number.isSafeInteger(job.id) || !job.fencing_token) throw new Error('invalid_claim');
    // Record unknown before authorize: a crash/timeout cannot authorize a second send.
    const record = { id: job.id, result: { fencing_token: job.fencing_token, outcome: 'unknown', error_kind: 'interrupted' } };
    await this.persist(record);
    if (this.stopping || !(await this.identity(binding))) {
      record.result.outcome = 'failed_safe'; record.result.error_kind = 'identity_or_shutdown';
      await this.persist(record); await this.flush(); return;
    }
    let payload;
    try { payload = await this.api(`/jobs/${job.id}/authorize`, { fencing_token: job.fencing_token }); }
    catch (error) {
      if (error.status >= 400 && error.status < 500) {
        record.result.outcome = 'failed_safe'; record.result.error_kind = 'authorization_denied';
        await this.persist(record); await this.flush(); return;
      }
      throw error;
    }
    const to = typeof payload.to === 'string' ? payload.to : '';
    if (!to || !(this.allowedRecipients.includes('*') || this.allowedRecipients.includes(to.toLowerCase())) || typeof payload.subject !== 'string'
        || typeof payload.body_text !== 'string' || /[\r\n]/.test(to + payload.subject)) {
      record.result.outcome = 'failed_safe'; record.result.error_kind = 'invalid_or_disallowed_payload';
      await this.persist(record); await this.flush(); return;
    }
    const directory = await mkdtemp(join(this.root, 'body-'));
    try {
      const file = await open(join(directory, 'body.txt'), 'wx', 0o600);
      try { await file.writeFile(payload.body_text); await file.sync(); } finally { await file.close(); }
      // SIGTERM drains an authorized send and its durable result; no new claim follows.
      await this.paceCli();
      const result = await this.execute(this.cli, ['message', '+send', '--to', to, '--subject', payload.subject,
        '--body-file', './body.txt', '--confirmed'], { cwd: directory, workspace: binding.cli_workspace });
      record.result = { fencing_token: job.fencing_token,
        outcome: result.ok && (result.data?.queued === true || result.data?.message_id) ? 'accepted'
          : result.started === false ? 'failed_safe' : 'unknown' };
      if (record.result.outcome === 'accepted' && result.data?.message_id) record.result.provider_message_id = result.data.message_id;
      if (record.result.outcome !== 'accepted') record.result.error_kind = (result.error || 'invalid_send_result').toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 64);
      await this.persist(record);
    } finally { await rm(directory, { recursive: true, force: true }); }
    await this.flush();
  }
  async cycle() {
    await this.flush();
    if (this.stopping) return { frozen: true };
    const frozen = Boolean(await readJson(join(this.root, 'freeze.json')));
    const bindings = await this.api('/bindings');
    let authenticated = 0;
    for (const binding of bindings) {
      if (!Number.isSafeInteger(binding.id) || !/^[A-Za-z0-9_-]{1,64}$/.test(binding.cli_workspace || '')) {
        throw new Error('invalid_binding');
      }
      if (this.stopping) break;
      if (!(await this.identity(binding))) continue;
      authenticated++;
      if (frozen) continue;
      await this.ingest(binding);
      if (this.stopping || await readJson(join(this.root, 'freeze.json'))) break;
      const job = await this.api(`/${binding.id}/claim`, {});
      if (job) { await this.send(binding, job); break; }
    }
    return { bindings: bindings.length, authenticated, frozen };
  }
}
