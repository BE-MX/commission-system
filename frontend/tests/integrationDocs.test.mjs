import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'

const paths = {
  requirements: new URL('../../docs/requirements/2026-08-26-external-invoice-integration.md', import.meta.url),
  api: new URL('../../docs/integrations/invoice-api.md', import.meta.url),
  client: new URL('../../docs/integrations/ark-invoice-client.ts', import.meta.url),
  prompt: new URL('../../docs/integrations/codex-site-prompt.md', import.meta.url),
}

const endpointContract = [
  ['POST', '/customers/resolve', '/api/integrations/v1/customers/resolve'],
  ['POST', '/products/resolve', '/api/integrations/v1/products/resolve'],
  ['POST', '/invoices/validate', '/api/integrations/v1/invoices/validate'],
  ['POST', '/invoices', '/api/integrations/v1/invoices'],
  ['GET', '/invoices/by-external-id/{external_order_id}', '/api/integrations/v1/invoices/by-external-id/{external_order_id}'],
]

function readAsset(name) {
  assert.equal(existsSync(paths[name]), true, `missing integration asset: ${name}`)
  return readFileSync(paths[name], 'utf8')
}

const runtimePayload = {
  schema_version: '1.0',
  external_order_id: 'SITE:RECOVER-001',
  order_type: 'stock',
  invoice_date: '2026-08-26',
  currency: 'USD',
  customer: { ark_customer_id: '1001' },
  delivery: {},
  items: [],
}

const recoveredResult = {
  request_id: 'request-1',
  replayed: true,
  external_order_id: 'SITE:RECOVER-001',
  invoice_id: 123,
  invoice_no: 'ARK-123',
  status: 'ready',
  sync_status: 'not_synced',
  totals: { product_amount: '20.00', total_amount: '20.00' },
  review_url: 'https://leshine.work/invoice/manage',
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function withRuntimeClient(callback) {
  const buildDirectory = mkdtempSync(join(tmpdir(), 'ark-invoice-client-test-'))
  try {
    const { build } = await import('esbuild')
    const outputFile = join(buildDirectory, 'ark-invoice-client.mjs')
    await build({
      entryPoints: [fileURLToPath(paths.client)],
      outfile: outputFile,
      bundle: true,
      platform: 'node',
      format: 'esm',
    })
    const runtime = await import(pathToFileURL(outputFile).href)
    await callback(runtime)
  } finally {
    rmSync(buildDirectory, { recursive: true, force: true })
  }
}

test('published endpoint list matches the FastAPI OpenAPI paths', () => {
  const apiDoc = readAsset('api')
  const python = process.env.PYTHON || 'python'
  const script = [
    'import json',
    'from fastapi import FastAPI',
    'from app.integration.router import router',
    'app = FastAPI()',
    'app.include_router(router, prefix="/api/integrations")',
    'print(json.dumps(sorted(app.openapi()["paths"])))',
  ].join('; ')
  const result = spawnSync(python, ['-c', script], {
    cwd: new URL('../../backend/', import.meta.url),
    encoding: 'utf8',
  })

  assert.equal(result.status, 0, result.stderr)
  const openApiPaths = JSON.parse(result.stdout.trim())
  for (const [method, relativePath, openApiPath] of endpointContract) {
    assert.ok(apiDoc.includes(`${method} \`${relativePath}\``), `${method} ${relativePath} missing from documentation`)
    assert.ok(openApiPaths.includes(openApiPath), `${openApiPath} missing from FastAPI OpenAPI`)
  }
})

test('TypeScript client exposes the supported operations and server-only authentication', () => {
  const client = readAsset('client')

  assert.match(client, /export class ArkInvoiceClient/)
  assert.match(client, /validateInvoice\s*\(/)
  assert.match(client, /createInvoice\s*\(/)
  assert.match(client, /getInvoiceByExternalId\s*\(/)
  assert.match(client, /AbortController/)
  assert.match(client, /Authorization:\s*`Bearer \$\{this\.token\}`/)
  assert.doesNotMatch(client, /localStorage|sessionStorage|\bwindow\b|console\./)
  assert.doesNotMatch(client, /randomUUID|Math\.random|Date\.now\(\)/)
})

test('ambiguous create recovers and retries only with the original external order id', () => {
  const client = readAsset('client')

  assert.match(client, /getInvoiceByExternalId\(payload\.external_order_id\)/)
  assert.match(client, /createOnce\(payload\)/)
  assert.match(client, /kind:\s*'timeout'\s*\|\s*'network'/)
  assert.doesNotMatch(client, /external_order_id\s*=(?!=)/)
})

test('broken 201 create response recovers by querying the same external order id', async () => {
  await withRuntimeClient(async ({ ArkInvoiceClient }) => {
    const calls = []
    const fetchImpl = async (url, init) => {
      calls.push({ url: String(url), method: init.method, body: init.body })
      if (calls.length === 1) {
        return new Response('{broken-json', {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return jsonResponse({ code: 200, message: 'invoice replayed', data: recoveredResult })
    }
    const client = new ArkInvoiceClient({
      baseUrl: 'https://leshine.work/api/integrations/v1',
      token: 'ark_live_test',
      fetchImpl,
    })

    const result = await client.createInvoice(runtimePayload)

    assert.deepEqual(result, recoveredResult)
    assert.equal(calls.length, 2)
    assert.equal(calls[0].method, 'POST')
    assert.equal(JSON.parse(calls[0].body).external_order_id, 'SITE:RECOVER-001')
    assert.equal(calls[1].method, 'GET')
    assert.match(calls[1].url, /\/invoices\/by-external-id\/SITE%3ARECOVER-001$/)
  })
})

test('empty 201 create data recovers by querying the same external order id', async () => {
  await withRuntimeClient(async ({ ArkInvoiceClient }) => {
    const calls = []
    const client = new ArkInvoiceClient({
      baseUrl: 'https://leshine.work/api/integrations/v1',
      token: 'ark_live_test',
      fetchImpl: async (url, init) => {
        calls.push({ url: String(url), method: init.method })
        if (calls.length === 1) {
          return jsonResponse({ code: 201, message: 'invoice created', data: {} }, 201)
        }
        return jsonResponse({ code: 200, message: 'invoice replayed', data: recoveredResult })
      },
    })

    assert.deepEqual(await client.createInvoice(runtimePayload), recoveredResult)
    assert.equal(calls.length, 2)
    assert.match(calls[1].url, /\/invoices\/by-external-id\/SITE%3ARECOVER-001$/)
  })
})

test('mismatched create HTTP and envelope codes recover by external order id', async () => {
  await withRuntimeClient(async ({ ArkInvoiceClient }) => {
    const calls = []
    const client = new ArkInvoiceClient({
      baseUrl: 'https://leshine.work/api/integrations/v1',
      token: 'ark_live_test',
      fetchImpl: async (url, init) => {
        calls.push({ url: String(url), method: init.method })
        if (calls.length === 1) {
          return jsonResponse(
            { code: 200, message: 'wrong create code', data: recoveredResult },
            201,
          )
        }
        return jsonResponse({ code: 200, message: 'invoice replayed', data: recoveredResult })
      },
    })

    assert.deepEqual(await client.createInvoice(runtimePayload), recoveredResult)
    assert.equal(calls.length, 2)
    assert.match(calls[1].url, /\/invoices\/by-external-id\/SITE%3ARECOVER-001$/)
  })
})

test('malformed validate success throws once without create recovery', async () => {
  await withRuntimeClient(async ({ ArkInvoiceClient, ArkInvoiceSuccessfulResponseError }) => {
    let calls = 0
    const client = new ArkInvoiceClient({
      baseUrl: 'https://leshine.work/api/integrations/v1',
      token: 'ark_live_test',
      fetchImpl: async () => {
        calls += 1
        return jsonResponse({ code: 200, message: 'ok', data: {} })
      },
    })

    await assert.rejects(
      client.validateInvoice(runtimePayload),
      error => error instanceof ArkInvoiceSuccessfulResponseError,
    )
    assert.equal(calls, 1)
  })
})

test('malformed get success throws once without create recovery', async () => {
  await withRuntimeClient(async ({ ArkInvoiceClient, ArkInvoiceSuccessfulResponseError }) => {
    let calls = 0
    const client = new ArkInvoiceClient({
      baseUrl: 'https://leshine.work/api/integrations/v1',
      token: 'ark_live_test',
      fetchImpl: async () => {
        calls += 1
        return jsonResponse({ code: 200, message: 'invoice replayed', data: {} })
      },
    })

    await assert.rejects(
      client.getInvoiceByExternalId('SITE:RECOVER-001'),
      error => error instanceof ArkInvoiceSuccessfulResponseError,
    )
    assert.equal(calls, 1)
  })
})

test('documents keep money, idempotency, totals and OKKI boundaries explicit', () => {
  const requirements = readAsset('requirements')
  const apiDoc = readAsset('api')
  const combined = `${requirements}\n${apiDoc}`

  assert.match(combined, /JSON 十进制字符串/)
  assert.match(combined, /服务端重算/)
  assert.match(combined, /Integration App.*external_order_id|App.*external_order_id/)
  assert.match(combined, /相同 external_order_id.*不同.*409/s)
  assert.match(apiDoc, /首次.*201/)
  assert.match(apiDoc, /重放.*200/)
  assert.match(combined, /不.*同步 OKKI/)
  assert.match(apiDoc, /超时|网络/)
  assert.match(apiDoc, /相同 external_order_id/)
  assert.match(combined, /绝对差额 <= 0\.01.*通过/)
  assert.match(combined, /> 0\.01.*DECLARED_TOTAL_MISMATCH.*422/s)
  assert.doesNotMatch(apiDoc, /token=.*ark_live_/i)
})

test('customer resolution documents the authoritative id and fallback order', () => {
  const apiDoc = readAsset('api')

  assert.match(apiDoc, /ark_customer_id.*权威/)
  assert.match(apiDoc, /命中后.*不.*反向核对/)
  assert.match(apiDoc, /未提供.*ark_customer_id.*联系人.*公司名/s)
  assert.match(apiDoc, /当前尝试的条件.*多命中.*CUSTOMER_NOT_UNIQUE/)
})

test('Codex site prompt requires a server route, environment secret and source-order JSON', () => {
  const prompt = readAsset('prompt')

  assert.match(prompt, /只改.*服务端|仅.*服务端/)
  assert.match(prompt, /ARK_INVOICE_API_BASE_URL/)
  assert.match(prompt, /ARK_INVOICE_API_TOKEN/)
  assert.match(prompt, /customers\/resolve/)
  assert.match(prompt, /products\/resolve/)
  assert.match(prompt, /invoices\/validate/)
  assert.match(prompt, /站点订单/)
  assert.match(prompt, /方舟发票/)
  assert.match(prompt, /不上传 Excel/)
  assert.match(prompt, /公式缓存/)
  assert.match(prompt, /npm test|pnpm test|yarn test/)
  assert.match(prompt, /验收场景/)
  assert.match(prompt, /"unit_price"\s*:\s*"\d+\.\d{4}"/)
})
