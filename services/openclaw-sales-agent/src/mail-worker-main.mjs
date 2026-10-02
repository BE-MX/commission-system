import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { MailWorker, apiClient, readJson } from './mail-worker.mjs';

const root = process.env.MAIL_WORKER_STATE || '/var/lib/ark-mail-outreach';
const token = (await readFile(process.env.MAIL_WORKER_TOKEN_FILE, 'utf8')).trim();
if (token.length < 32) throw new Error('worker_token_too_short');
const worker = new MailWorker({ root, cli: process.env.AGENTLY_CLI_BIN,
  api: apiClient({ baseUrl: process.env.ARK_BASE_URL, token }),
  allowedRecipients: (process.env.MAIL_OUTREACH_ALLOWED_RECIPIENTS || '').toLowerCase().split(',').map((s) => s.trim()).filter(Boolean) });
if (!worker.cli || !worker.allowedRecipients.length) throw new Error('worker_configuration_missing');
await worker.init();
// systemd is the single process owner; flock in its ExecStart protects manual duplicates.
let busy = false, lastOk = null, lastError = null, timer, summary = {};
const server = createServer(async (request, response) => {
  if (request.method !== 'GET' || request.url !== '/health') { response.writeHead(404); response.end(); return; }
  const pending = await readJson(join(root, 'pending.json')).catch(() => ({ corrupt: true }));
  response.writeHead(lastError ? 503 : 200, { 'content-type': 'application/json' });
  response.end(JSON.stringify({ service: 'ark-mail-outreach', revision: process.env.MAIL_WORKER_REVISION,
    draining: worker.stopping, busy, pending_receipt: Boolean(pending), last_ok: lastOk, error: lastError, ...summary }));
});
server.listen(7911, '127.0.0.1');
async function tick() {
  busy = true;
  try { summary = await worker.cycle(); lastOk = new Date().toISOString(); lastError = null; }
  catch (error) { lastError = 'cycle_failed'; console.error(JSON.stringify({ event: 'cycle_failed', kind: error.name })); }
  finally { busy = false; }
  if (worker.stopping) server.close();
  else timer = setTimeout(tick, 60_000);
}
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => {
  worker.stopping = true; clearTimeout(timer);
  if (!busy) server.close();
});
await tick();
