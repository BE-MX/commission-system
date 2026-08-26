import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
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
  assert.doesNotMatch(client, /external_order_id\s*=/)
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
  assert.doesNotMatch(apiDoc, /token=.*ark_live_/i)
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
