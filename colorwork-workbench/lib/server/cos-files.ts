/** Private loopback COS bridge; R2 retains only resumable staging and completion receipts. */
import { createHmac, timingSafeEqual } from 'node:crypto';
import { Buffer } from 'node:buffer';

const MAX_BYTES = 256 * 1024 * 1024;
type Info = { key: string; size: number; etag: string; httpMetadata: R2HTTPMetadata; customMetadata: Record<string, string> };
type Config = { endpoint: string; secret: string; staging: R2Bucket; fetcher?: typeof fetch };
const b64 = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');

function object(info: Info): R2Object {
  return { ...info, version: info.etag, httpEtag: `"${info.etag}"`, uploaded: new Date(0), checksums: {},
    storageClass: 'Standard', writeHttpMetadata(headers: Headers) {
      if (info.httpMetadata.contentType) headers.set('content-type', info.httpMetadata.contentType);
    } } as R2Object;
}

export function createCosFiles(config: Config) {
  const endpoint = new URL(config.endpoint);
  if (endpoint.origin !== 'http://127.0.0.1:8001' || endpoint.pathname !== '/api/colorwork/storage' || endpoint.search || endpoint.hash) {
    throw new Error('Storage gateway must use the fixed loopback endpoint');
  }
  const fetcher = config.fetcher ?? fetch;
  async function call(kind: string, key: string, init: RequestInit = {}, range?: { offset?: number; length?: number }) {
    const url = new URL(endpoint + '/' + kind);
    url.searchParams.set('key', key);
    if (range?.offset !== undefined) url.searchParams.set('offset', String(range.offset));
    if (range?.length !== undefined) url.searchParams.set('length', String(range.length));
    const headers = new Headers(init.headers);
    headers.set('x-ark-storage-key', config.secret);
    return fetcher(url, { ...init, headers, redirect: 'manual' });
  }
  async function infoResponse(response: Response): Promise<R2Object | null> {
    if (response.status === 404 || response.status === 412) return null;
    if (!response.ok) throw new Error(`Cloud storage unavailable (${response.status})`);
    return object(await response.json() as Info);
  }
  async function putStream(key: string, body: BodyInit | null, size: number, options?: R2PutOptions, operationId?: string) {
    if (size > MAX_BYTES) throw new Error('File exceeds 256MiB');
    const onlyIf = options?.onlyIf;
    if (onlyIf && (onlyIf instanceof Headers || onlyIf.etagDoesNotMatch !== '*')) throw new Error('Unsupported storage condition');
    const headers = new Headers({ 'content-length': String(size), 'x-ark-content-length': String(size),
      'content-type': options?.httpMetadata instanceof Headers ? (options.httpMetadata.get('content-type') || 'application/octet-stream') : (options?.httpMetadata?.contentType || 'application/octet-stream'),
      'x-ark-metadata': Buffer.from(JSON.stringify(options?.customMetadata || {})).toString('base64') });
    if (operationId) headers.set('x-ark-upload-id', operationId);
    if (onlyIf) headers.set('if-none-match', '*');
    return infoResponse(await call('object', key, { method: 'PUT', headers, body }));
  }
  function token(logical: string, key: string, id: string) {
    const payload = b64({ logical, key, id });
    return 'cwcos1.' + payload + '.' + createHmac('sha256', config.secret).update(payload).digest('base64url');
  }
  function unpack(logical: string, id: string) {
    if (!id.startsWith('cwcos1.')) return { key: logical, id, receipt: '__cos-receipts/' + createHmac('sha256', config.secret).update(logical + '\0' + id).digest('hex') };
    const [, payload, signature, extra] = id.split('.');
    const expected = createHmac('sha256', config.secret).update(payload || '').digest();
    const supplied = Buffer.from(signature || '', 'base64url');
    if (extra || supplied.length !== expected.length || !timingSafeEqual(expected, supplied)) throw new Error('Invalid upload token');
    const data = JSON.parse(Buffer.from(payload, 'base64url').toString());
    if (data.logical !== logical || typeof data.id !== 'string' || !/^__cos-staging\/[0-9a-f-]{36}$/.test(data.key)) throw new Error('Upload token does not match object');
    return { key: data.key as string, id: data.id as string, receipt: data.key.replace('__cos-staging/', '__cos-receipts/') };
  }
  function resume(key: string, uploadId: string): R2MultipartUpload {
    const stage = unpack(key, uploadId);
    const upload = config.staging.resumeMultipartUpload(stage.key, stage.id);
    return { key, uploadId,
      uploadPart: (part, value, options) => upload.uploadPart(part, value, options),
      async abort() {
        try { await upload.abort(); }
        finally {
          if (stage.key.startsWith('__cos-staging/')) await config.staging.delete(stage.key);
        }
      },
      async complete(parts) {
        const prior = await config.staging.get(stage.receipt);
        if (prior) return object(await prior.json() as Info);
        let pending = await config.staging.get(stage.key);
        if (!pending) {
          await upload.complete(parts);
          pending = await config.staging.get(stage.key);
        }
        if (!pending) throw new Error('Completed upload is missing');
        const result = await putStream(key, pending.body, pending.size, {
          httpMetadata: pending.httpMetadata, customMetadata: pending.customMetadata,
        }, createHmac('sha256', config.secret).update(key + '\0' + uploadId).digest('hex'));
        if (!result) throw new Error('Cloud publication was not confirmed');
        // Persist completion before deleting staging; retries never read an unrelated key.
        await config.staging.put(stage.receipt, JSON.stringify(result));
        await config.staging.delete(stage.key);
        return result;
      },
    };
  }
  return {
    async head(key: string) { return infoResponse(await call('metadata', key)); },
    async get(key: string, options?: R2GetOptions) {
      if (options?.onlyIf || options?.range instanceof Headers || (options?.range && 'suffix' in options.range)) throw new Error('Unsupported storage read options');
      const response = await call('object', key, {}, options?.range as { offset?: number; length?: number } | undefined);
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`Cloud storage unavailable (${response.status})`);
      const metadata = JSON.parse(Buffer.from(response.headers.get('x-ark-object') || '', 'base64').toString()) as Info;
      return { ...object(metadata), body: response.body!, get bodyUsed() { return response.bodyUsed; },
        arrayBuffer: () => response.arrayBuffer(), text: () => response.text(), json: <T>() => response.json() as Promise<T>, blob: () => response.blob() } as R2ObjectBody;
    },
    async put(key: string, value: ReadableStream | ArrayBuffer | ArrayBufferView | string | null | Blob, options?: R2PutOptions) {
      if (value instanceof ReadableStream) throw new Error('Use resumable upload for stream bodies');
      const body = typeof value === 'string' ? new TextEncoder().encode(value) : value;
      const size = body === null ? 0 : body instanceof Blob ? body.size : body.byteLength;
      return putStream(key, body as BodyInit, size, options);
    },
    async delete(keys: string | string[]) {
      for (const key of typeof keys === 'string' ? [keys] : keys) {
        const response = await call('object', key, { method: 'DELETE' });
        if (!response.ok) throw new Error(`Cloud storage delete failed (${response.status})`);
      }
    },
    async createMultipartUpload(key: string, options?: R2MultipartOptions) {
      const stage = '__cos-staging/' + crypto.randomUUID();
      const upload = await config.staging.createMultipartUpload(stage, options);
      return resume(key, token(key, stage, upload.uploadId));
    },
    resumeMultipartUpload: resume,
  };
}
