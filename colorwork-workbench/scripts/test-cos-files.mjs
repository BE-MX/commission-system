import test from 'node:test';
import assert from 'node:assert/strict';
import { createCosFiles } from '../lib/server/cos-files.ts';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

test('business routes and services cannot bypass the COS storage adapter', () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  for (const directory of ['app', 'lib/server']) {
    for (const name of readdirSync(path.join(root, directory), { recursive: true })) {
      if (!/\.tsx?$/.test(name)) continue;
      const relative = path.join(directory, name).replaceAll('\\', '/');
      if (relative === 'lib/server/storage.ts') continue;
      assert.doesNotMatch(readFileSync(path.join(root, relative), 'utf8'), /\benv\.FILES\b/,
        `${relative} must use getFiles() for business object access`);
    }
  }
});

function fixture() {
  const entries = new Map(); const uploads = new Map(); const calls = [];
  let fail = false; let abortFails = false;
  const staging = {
    async createMultipartUpload(key) { const id = crypto.randomUUID(); uploads.set(id, { key }); return { uploadId: id }; },
    resumeMultipartUpload(key, id) { return {
      async uploadPart() { return { partNumber: 1, etag: 'part' }; },
      async complete() { assert.equal(uploads.get(id).key, key); entries.set(key, 'PSD'); },
      async abort() { if (abortFails) throw new Error('already complete'); uploads.delete(id); },
    }; },
    async get(key) { if (!entries.has(key)) return null; const text = entries.get(key); const response = new Response(text); return {
      size: Buffer.byteLength(text), body: response.body, httpMetadata: { contentType:'application/octet-stream' }, customMetadata: {},
      json: async () => JSON.parse(text),
    }; },
    async put(key, value) { entries.set(key, value); },
    async delete(key) { entries.delete(key); },
  };
  const store = createCosFiles({ endpoint:'http://127.0.0.1:8001/api/colorwork/storage', secret:'test-only-secret', staging,
    fetcher: async (url, init) => { calls.push({url:String(url), headers:new Headers(init.headers)}); if(fail) return new Response('', {status:503});
      if (init.body) await new Response(init.body).arrayBuffer();
      return Response.json({key:new URL(url).searchParams.get('key'), size:3,etag:'result',httpMetadata:{},customMetadata:{sha256:'a'.repeat(64)}});
    },
  });
  return { store, entries, calls, fail(value) { fail=value; }, abortFails() { abortFails=true; } };
}

test('failed publication retains staging, retry uses same operation identity and completion receipt', async () => {
  const f=fixture(); const upload=await f.store.createMultipartUpload('result.psd');
  f.fail(true); await assert.rejects(upload.complete([{partNumber:1,etag:'part'}]));
  assert.equal([...f.entries.keys()].filter(x=>x.startsWith('__cos-staging/')).length,1);
  f.fail(false); await upload.complete([{partNumber:1,etag:'part'}]);
  assert.equal(f.calls[0].headers.get('x-ark-upload-id'), f.calls[1].headers.get('x-ark-upload-id'));
  assert.match(f.calls[0].headers.get('x-ark-upload-id'), /^[a-f0-9]{64}$/);
  assert.equal([...f.entries.keys()].filter(x=>x.startsWith('__cos-staging/')).length,0);
  await upload.complete([{partNumber:1,etag:'part'}]); assert.equal(f.calls.length,2);
});

test('abort cleans only signed staging even after native completion', async () => {
  const f=fixture(); const upload=await f.store.createMultipartUpload('result.psd');
  f.fail(true); await assert.rejects(upload.complete([{partNumber:1,etag:'part'}]));
  f.entries.set('result.psd','keep legacy'); f.abortFails();
  await assert.rejects(upload.abort());
  assert.deepEqual([...f.entries.keys()], ['result.psd']);
});

test('multipart token cannot be reused for another object or altered', async () => {
  const f=fixture(); const upload=await f.store.createMultipartUpload('private.psd');
  assert.throws(()=>f.store.resumeMultipartUpload('other.psd',upload.uploadId));
  assert.throws(()=>f.store.resumeMultipartUpload('private.psd',upload.uploadId+'x'));
});
